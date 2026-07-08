# HyperMCP prototype

Stdlib-only proof-of-concept for the paper's mechanism. No dependencies.

```
python3 hypermcp_poc.py
```

`hypermcp_poc.py` models a slice of the tau-bench retail domain (authenticate →
inspect → act) and exposes the same tools through two interfaces:

- **FlatServer** — vanilla MCP: static full menu; guards enforced only by post-hoc
  rejection (invalid calls are *admitted* and must be caught).
- **HyperServer** — HyperMCP: `list_tools(state)` returns only guard-satisfied
  affordances `A(s)`, and each `call` returns a next-step affordance envelope.
  Precondition-violating calls are *unreachable by construction*.

**Result (current):** flat admits 2 invalid calls, avg menu 4.0; hyper admits 0
(2 blocked), avg menu 1.6. This is the validity + context-cost claim in miniature.

This PoC predates (and motivated) the full harness in `../hypermcp/`, which adds the
retrieval baseline, agent-context sensitivity (SEM), real LLM agents, the WoT environment,
ablations, and the invariant suite. It is kept as the smallest self-contained demonstration
of the mechanism.
