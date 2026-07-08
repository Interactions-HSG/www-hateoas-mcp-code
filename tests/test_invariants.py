"""Invariants that back the paper's central claim, checked over random walks of state.

Run: python -m tests.test_invariants

  I1 (consistency): HyperMCP advertises an affordance instance iff its guard holds AND it
                    is relevant to the agent context.
  I2 (soundness):   every advertised instance is callable without an illegal-call error
                    -> HyperMCP admits no invalid calls, by construction.
  I3 (enum):        a HyperMCP tool schema's parameter enum == the eligible bindings.
  I4 (baseline):    the flat interface advertises instances whose guard is FALSE
                    -> baselines *can* admit invalid calls (the gap we close).
  I5 (envelope):    the envelope returned with a result advertises exactly the
                    affordances valid in the SUCCESSOR state (post-transition), and
                    every signifier in it carries only guard-satisfying bindings.
"""
from __future__ import annotations
import copy
import random
from hypermcp.core import AgentContext
from hypermcp.envs import retail, wot
from hypermcp.interfaces import HyperInterface, FlatInterface


def instances(env, s):
    for a in env.affordances:
        for c in (a.candidates(s) or [{}]):
            yield a, c


def check_env(env, ctx, trials=40, steps=12, seed=0) -> tuple[int, bool]:
    random.seed(seed)
    checks = 0
    saw_flat_illegal_offer = False
    hyper = HyperInterface(env)
    hyper.agent_ctx = ctx
    flat = FlatInterface(env)
    for t in range(trials):
        s = env.tasks[t % len(env.tasks)].init()
        for _ in range(steps):
            offered = []
            for a, c in instances(env, s):
                guard_ok = a.guard(s, c) and a.relevant(ctx)
                assert hyper.offers(s, a.name, c) == guard_ok, \
                    f"I1 violated: {a.name}{c}"                              # I1
                if hyper.offers(s, a.name, c):
                    offered.append((a.name, c))
                if flat.offers(s, a.name, c) and not a.guard(s, c):
                    saw_flat_illegal_offer = True                            # I4
                checks += 1
            for name, args in offered:
                obs = hyper.call(copy.deepcopy(s), name, args)
                assert obs.ok, f"I2 violated: advertised but illegal {name}{args}"  # I2
            for spec in hyper.tool_specs(s, ""):                             # I3
                aff = env.by_name()[spec["name"]]
                for key, p in spec["input_schema"].get("properties", {}).items():
                    want = sorted({c[key] for c in aff.eligible(s) if key in c})
                    if want:
                        assert p.get("enum") == want, f"I3 violated: {spec['name']}.{key}"
            if not offered:
                break
            name, args = random.choice(offered)
            obs = hyper.call(s, name, args)                                  # advance state
            want_next = sorted(a.name for a in env.affordances
                               if a.available(s) and a.relevant(ctx))        # I5
            assert sorted(obs.next_affordances) == want_next, \
                f"I5 violated: envelope is not the successor affordance set after {name}"
            for sig in obs.signifiers:
                aff = env.by_name()[sig["signifies"]["tool"]]
                for b in sig["context-conditions"]["eligible-bindings"]:
                    assert aff.guard(s, b), f"I5 violated: ineligible binding in signifier"
                checks += 1
    return checks, saw_flat_illegal_offer


def main() -> None:
    total = 0
    flat_gap_seen = False
    for env, ctx in [(retail.ENV, AgentContext(goal="cancel")),
                     (retail.ENV, None),
                     (wot.ENV, AgentContext(goal="run")),
                     (wot.ENV, None)]:
        c, gap = check_env(env, ctx)
        total += c
        flat_gap_seen = flat_gap_seen or gap
        print(f"  {env.name:<7} ctx={str(ctx):<28} checks={c}")
    assert flat_gap_seen, "I4 expected: flat should advertise a guard-false instance"
    print(f"OK  {total} instance-checks across retail+wot; "
          f"I1/I2/I3/I5 hold, I4 confirmed (flat advertises invalid instances).")


if __name__ == "__main__":
    main()
