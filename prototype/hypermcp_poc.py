"""
HyperMCP proof-of-concept (stdlib only, no external deps).

Purpose: demonstrate the *mechanism* end-to-end before scaling to the LLM eval.
We model a slice of the tau-bench retail domain (authenticate -> inspect -> act on
an order) and expose the SAME underlying tools through two interfaces:

  * FlatServer   -- vanilla MCP: tools/list returns every tool, always (static menu).
                    Guards are enforced only by rejecting the call after the fact.
  * HyperServer  -- HyperMCP: tools/list(state) returns ONLY affordances whose guard
                    holds in the current application state, and every tools/call result
                    carries a hypermedia 'affordances' envelope advertising the next
                    valid steps. Invalid calls are UNREACHABLE by construction.

The "agent" here is a deterministic, slightly greedy stand-in for an LLM: it pursues a
goal and, crucially, will attempt a tool if that tool is visible to it. This is exactly
where flat vs. hypermedia diverge: the flat menu makes precondition-violating tools
visible (and LLMs do call them -- cf. tau-bench: gpt-4o pass^8 < 25% in retail), while
HyperMCP never surfaces them.

Run:  python3 hypermcp_poc.py
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable


# --------------------------------------------------------------------------- #
# Application state (per session) -- the "engine of application state".
# --------------------------------------------------------------------------- #
@dataclass
class State:
    authenticated_user: str | None = None
    # order_id -> status in {"pending", "delivered", "cancelled", "locked"}
    orders: dict[str, str] = field(default_factory=dict)
    order_owner: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Affordance = tool + guard (precondition) + effect (state transition).
# Guards lift tau-bench retail policy rules into machine-checked preconditions.
# --------------------------------------------------------------------------- #
@dataclass
class Affordance:
    name: str
    guard: Callable[[State, dict], bool]
    effect: Callable[[State, dict], str]
    rel: str  # semantic link relation / affordance type
    description: str


def _find_user_by_email(s: State, args: dict) -> str:
    s.authenticated_user = args["email"]
    return f"authenticated as {args['email']}"


def _get_order_status(s: State, args: dict) -> str:
    return f"order {args['order_id']} is '{s.orders.get(args['order_id'])}'"


def _cancel_order(s: State, args: dict) -> str:
    s.orders[args["order_id"]] = "cancelled"
    return f"order {args['order_id']} cancelled"


def _return_order(s: State, args: dict) -> str:
    s.orders[args["order_id"]] = "return-requested"
    return f"return started for order {args['order_id']}"


def _owns(s: State, args: dict) -> bool:
    oid = args.get("order_id")
    return s.authenticated_user is not None and s.order_owner.get(oid) == s.authenticated_user


AFFORDANCES: list[Affordance] = [
    Affordance(
        "find_user_by_email",
        guard=lambda s, a: s.authenticated_user is None,      # authenticate FIRST
        effect=_find_user_by_email,
        rel="authenticate",
        description="Locate and authenticate the user by email.",
    ),
    Affordance(
        "get_order_status",
        guard=lambda s, a: _owns(s, a),                       # must be authenticated owner
        effect=_get_order_status,
        rel="inspect",
        description="Read the status of one of the authenticated user's orders.",
    ),
    Affordance(
        "cancel_order",
        guard=lambda s, a: _owns(s, a) and s.orders.get(a.get("order_id")) == "pending",
        effect=_cancel_order,
        rel="act",
        description="Cancel an order. Only allowed while status is 'pending'.",
    ),
    Affordance(
        "return_order",
        guard=lambda s, a: _owns(s, a) and s.orders.get(a.get("order_id")) == "delivered",
        effect=_return_order,
        rel="act",
        description="Return an order. Only allowed while status is 'delivered'.",
    ),
]
BY_NAME = {a.name: a for a in AFFORDANCES}


# --------------------------------------------------------------------------- #
# Two interfaces over the same affordances.
# --------------------------------------------------------------------------- #
class FlatServer:
    """Vanilla MCP: static menu; guards enforced only by post-hoc rejection."""

    def list_tools(self, state: State, args_hint: dict) -> list[str]:
        return [a.name for a in AFFORDANCES]           # everything, always

    def call(self, state: State, name: str, args: dict) -> tuple[bool, str, list[str]]:
        aff = BY_NAME[name]
        if not aff.guard(state, args):
            return False, f"ERROR: precondition violated for {name}", []   # invalid call ADMITTED
        return True, aff.effect(state, args), []       # no next-step affordances


class HyperServer:
    """HyperMCP: state-scoped tool surface + next-step affordance envelope."""

    def list_tools(self, state: State, args_hint: dict) -> list[str]:
        # A(s) = { a : guard_a(s) } -- only currently-valid affordances are advertised.
        return [a.name for a in AFFORDANCES if a.guard(state, args_hint)]

    def call(self, state: State, name: str, args: dict) -> tuple[bool, str, list[str]]:
        aff = BY_NAME[name]
        # A conformant client only ever selects from A(s); this check is a safety net.
        if not aff.guard(state, args):
            return False, f"ERROR: precondition violated for {name}", []
        result = aff.effect(state, args)
        next_affs = self.list_tools(state, args)       # envelope: what's valid *now*
        return True, result, next_affs


# --------------------------------------------------------------------------- #
# Deterministic stand-in agent. Pursues goals in order; will ATTEMPT a goal's
# tool iff that tool is currently visible to it (this is where interfaces differ).
# --------------------------------------------------------------------------- #
def run(server, label: str) -> dict:
    print(f"\n=== {label} ===")
    state = State(
        orders={"W001": "pending", "W002": "delivered"},
        order_owner={"W001": "a@shop.com", "W002": "a@shop.com"},
    )
    # Goal-directed plan the agent WANTS to execute, in this order.
    # Note W002 is 'delivered', so cancel_order(W002) is precondition-INVALID.
    plan = [
        ("cancel_order", {"order_id": "W002"}),          # premature + wrong-state (double invalid)
        ("find_user_by_email", {"email": "a@shop.com"}),  # authenticate
        ("cancel_order", {"order_id": "W002"}),          # still wrong-state (delivered != pending)
        ("cancel_order", {"order_id": "W001"}),          # valid: pending
        ("return_order", {"order_id": "W002"}),          # valid: delivered
    ]

    invalid_admitted = 0
    invalid_blocked = 0
    offered_sizes: list[int] = []
    for name, args in plan:
        visible = server.list_tools(state, args)
        offered_sizes.append(len(visible))
        if name not in visible:
            # HyperMCP: the tool isn't on the menu, so the agent cannot even attempt it.
            invalid_blocked += 1
            print(f"  [skip ] {name}({args.get('order_id','')}) not offered "
                  f"(menu={visible})")
            continue
        ok, msg, nxt = server.call(state, name, args)
        if not ok:
            invalid_admitted += 1
            print(f"  [CALL!] {name}({args.get('order_id','')}) -> {msg}")
        else:
            extra = f"  next={nxt}" if nxt else ""
            print(f"  [ok   ] {name}({args.get('order_id','')}) -> {msg}{extra}")

    avg_menu = sum(offered_sizes) / len(offered_sizes)
    print(f"  -- invalid calls admitted: {invalid_admitted} | "
          f"structurally blocked: {invalid_blocked} | "
          f"avg menu size (context proxy): {avg_menu:.2f}")
    return {"invalid_admitted": invalid_admitted,
            "invalid_blocked": invalid_blocked,
            "avg_menu": avg_menu}


if __name__ == "__main__":
    flat = run(FlatServer(), "FlatServer (vanilla MCP: static menu)")
    hyper = run(HyperServer(), "HyperServer (HyperMCP: state-scoped affordances)")

    print("\n=== Summary (the mechanism in one table) ===")
    print(f"{'interface':<12} {'invalid_admitted':>16} {'avg_menu(ctx)':>14}")
    print(f"{'flat':<12} {flat['invalid_admitted']:>16} {flat['avg_menu']:>14.2f}")
    print(f"{'hyper':<12} {hyper['invalid_admitted']:>16} {hyper['avg_menu']:>14.2f}")
    print("\nFlat admits precondition-violating calls and always shows the full menu.")
    print("HyperMCP structurally prevents invalid calls and shows a smaller, valid menu.")
