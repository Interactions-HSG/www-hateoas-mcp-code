"""End-to-end check of both realizations over a real MCP transport (Streamable HTTP).

Run: python -m tests.test_mcp_transport

  T1 (protocol):  the session realization negotiates 2025-11-25 and receives
                  notifications/tools/list_changed; the stateless realization speaks
                  2026-07-28 and its tools/list result carries ttlMs and cacheScope.
  T2 (parity):    for every environment and realization, the scripted agent obtains the
                  same success, illegal-call, blocked, and menu-size results over the
                  wire as in process -- the harness numbers do not depend on the
                  in-process shortcut.
"""
from __future__ import annotations
from hypermcp.envs import retail, wot, shop
from hypermcp.interfaces import HyperInterface
from hypermcp.stateless import StatelessHyperInterface
from hypermcp.mcp_transport import (MCPInterface, SESSION_PROTOCOL, STATELESS_PROTOCOL,
                                    CATALOG_TTL_MS)
from hypermcp.agents import run_scripted

REFERENCE = {
    "hyper": lambda env: HyperInterface(env),
    "hyper-stateless": lambda env: StatelessHyperInterface(env),
    "hyper-stateless-noenv": lambda env: StatelessHyperInterface(env, use_envelope=False),
}


def _summary(rs):
    return (sum(r.success for r in rs), sum(r.illegal_calls for r in rs),
            sum(r.blocked for r in rs), [round(r.avg_menu, 3) for r in rs])


def check_protocol() -> None:
    env = retail.ENV
    task = env.tasks[0]
    for variant, version in (("hyper", SESSION_PROTOCOL),
                             ("hyper-stateless", STATELESS_PROTOCOL)):
        iface = MCPInterface(env, variant)
        try:
            iface.agent_ctx = task.agent_ctx
            state = task.init()
            iface.tool_specs(state, "")

            async def probe(client):
                return client.protocol_version, await client.list_tools()
            negotiated, listing = iface.request(probe)
            assert negotiated == version, f"T1 violated: {variant} spoke {negotiated}"
            if version == STATELESS_PROTOCOL:
                assert listing.ttl_ms == CATALOG_TTL_MS and \
                    listing.cache_scope == "public", "T1 violated: no cache directives"
            auth = next(a for a in iface.list_tools(state, "") if a.rel == "authenticate")
            iface.call(state, auth.name, state.scratch.get("creds", {}))
            if variant == "hyper":
                assert iface.list_changed_seen, "T1 violated: no tools/list_changed after auth"
        finally:
            iface.close()
        print(f"  T1 {variant:<22} protocol={negotiated}")


def check_parity() -> None:
    for env in (retail.ENV, wot.ENV, shop.ENV):
        for variant, ref in REFERENCE.items():
            wire = MCPInterface(env, variant)
            try:
                got = _summary([run_scripted(wire, env, t, max_steps=14)
                                for t in env.tasks])
            finally:
                wire.close()
            want = _summary([run_scripted(ref(env), env, t, max_steps=14)
                             for t in env.tasks])
            assert got == want, f"T2 violated: {env.name}/{variant} {got} != {want}"
            print(f"  T2 {env.name:<7}{variant:<22} success={got[0]}/{len(env.tasks)} "
                  f"illegal={got[1]} blocked={got[2]}")


def main() -> None:
    check_protocol()
    check_parity()
    print("OK  both realizations run over MCP Streamable HTTP and match the in-process "
          "harness.")


if __name__ == "__main__":
    main()
