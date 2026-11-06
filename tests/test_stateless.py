"""Invariants of the stateless realization (MCP 2026-07-28), over random walks of state.

Run: python -m tests.test_stateless

  S1 (catalog):  tools/list is state-independent and deterministically ordered: the same
                 catalog before and after every transition. Entry affordances take an
                 optional handle; every other affordance requires one.
  S2 (parity):   the envelope returned with each result equals what the session
                 realization (HyperInterface) advertises in the successor state, with the
                 state handle bound -- the two realizations expose the same A(s', c).
  S3 (handles):  calls that need state but carry no handle, or carry an unknown one, are
                 rejected without any state change; handles are opaque, 128-bit, distinct.
  S4 (host):     the EnvelopeHost presents exactly the envelope's tools after a result,
                 and only the catalog's entry tools before the first one.
"""
from __future__ import annotations
import random
from hypermcp.core import AgentContext, clone
from hypermcp.envs import retail, wot, shop
from hypermcp.interfaces import HyperInterface
from hypermcp.stateless import (StatelessServer, EnvelopeHost, HANDLE, HANDLE_PREFIX,
                                requires_handle)


def _strip_handle(spec: dict) -> dict:
    spec = {**spec, "input_schema": dict(spec["input_schema"])}
    schema = spec["input_schema"]
    schema["properties"] = {k: v for k, v in schema.get("properties", {}).items()
                            if k != HANDLE}
    if "required" in schema:
        schema["required"] = [r for r in schema["required"] if r != HANDLE]
        if not schema["required"]:
            del schema["required"]                  # added only to carry the handle
    return spec


def _instances(iface, s):
    for a in iface.list_tools(s, ""):
        for c in (a.eligible(s) or [{}]):
            yield a.name, c


def check_env(env, ctx, trials=20, steps=10, seed=0) -> int:
    rng = random.Random(seed)
    checks = 0
    handles = set()
    for t in range(trials):
        task = env.tasks[t % len(env.tasks)]
        s_session = task.init()
        hyper = HyperInterface(env)
        hyper.agent_ctx = ctx
        server = StatelessServer(env, s_session)
        catalog = server.catalog()
        host = EnvelopeHost(catalog)

        # S1: entry tools are exactly the affordances applicable in the entry state.
        for spec in catalog:
            assert requires_handle(spec) == (spec["name"] not in server.entry_names), \
                f"S1 violated: handle requirement wrong for {spec['name']}"
        # S4: before any result the host presents the entry tools only.
        assert {x["name"] for x in host.presented} == server.entry_names, \
            "S4 violated: initial presentation is not the entry tools"
        # S3: a state-requiring tool without a handle, or with an unknown one, fails.
        for name in sorted({a.name for a in env.affordances} - server.entry_names)[:3]:
            before = clone(server.entry)
            assert not server.call(name, {}, ctx).ok, f"S3 violated: {name} w/o handle"
            assert not server.call(name, {HANDLE: "hdl_forged"}, ctx).ok, \
                f"S3 violated: {name} with forged handle"
            assert server.entry == before and not server.store, \
                "S3 violated: rejected call changed state"
            checks += 2

        handle = None
        for _ in range(steps):
            options = list(_instances(hyper, s_session))
            if not options:
                break
            name, args = rng.choice(options)
            hyper.call(s_session, name, dict(args))
            r = server.call(name, {**args, **({HANDLE: handle} if handle else {})}, ctx)
            assert r.ok, f"S2 violated: advertised instance {name}({args}) rejected"
            host.absorb(r.envelope)
            if r.minted:
                assert r.handle.startswith(HANDLE_PREFIX) and len(r.handle) >= 22 \
                    and r.handle not in handles, "S3 violated: weak or reused handle"
                handles.add(r.handle)
            handle = r.handle or handle

            # S1: catalog unchanged by the transition.
            assert server.catalog() == catalog, "S1 violated: catalog depends on state"
            # S2: envelope == session advertisement in the successor state, handle bound.
            want = hyper.tool_specs(s_session, "")
            got = r.envelope
            assert [_strip_handle(x) for x in got] == want, \
                f"S2 violated after {name}: envelope differs from session advertisement"
            if handle:
                for x in got:
                    prop = x["input_schema"]["properties"][HANDLE]
                    assert prop["enum"] == [handle] and requires_handle(x), \
                        "S2 violated: handle not bound in envelope"
            # S4: the host now presents exactly the envelope.
            assert host.presented == got, "S4 violated: host ignores the envelope"
            checks += len(got) + 2
    return checks


def main() -> None:
    total = 0
    for env, ctx, trials in [(retail.ENV, AgentContext(goal="cancel"), 30),
                             (retail.ENV, None, 30),
                             (wot.ENV, AgentContext(goal="run"), 30),
                             (wot.ENV, None, 30),
                             (shop.ENV, AgentContext(goal={"cancel", "return"}), 6),
                             (shop.ENV, None, 6)]:
        c = check_env(env, ctx, trials=trials)
        total += c
        print(f"  {env.name:<7} ctx={str(ctx):<28} checks={c}")
    print(f"OK  {total} checks across retail+wot+shop; S1-S4 hold "
          "(stateless realization exposes the same A(s, c) as the session one).")


if __name__ == "__main__":
    main()
