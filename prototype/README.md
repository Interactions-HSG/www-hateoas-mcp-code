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

## Next steps toward the real eval
1. Replace the deterministic stand-in agent with an LLM (≥2 models) via a tool-calling loop.
2. Encode the full tau-bench retail (then airline) policy as guards; keep the underlying
   tools identical across B0/B1/HyperMCP.
3. Add the B1 retrieval baseline (top-k over tool descriptions).
4. Wire real metrics: task success (goal DB state), illegal-call rate, tokens/step, steps.
5. Add the bespoke Web-of-Things smart-space scenario.
