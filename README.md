# HyperMCP

Reference implementation and evaluation harness for the short paper *Toward a
Hypermedia-Driven Model Context Protocol: Exposing Tools through Situated Signifiers*.

HyperMCP exposes MCP tools through a Signifier Exposure Mechanism: the advertised set is
`A(s, p_ag)`, the tools applicable in application state `s` and relevant to the agent
profile `p_ag`, with enumerable parameters narrowed to their eligible bindings. Flat and
retrieval-based exposure run over the same affordances, so the interfaces differ only in
what they advertise.

## Setup

```sh
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # set OPENAI_API_KEY for LLM runs (gpt-4o-mini)
```

Scripted runs and the tests need no key.

## Layout

| File | Paper |
|---|---|
| `hypermcp/core.py`: state, affordances (guard `g_a`, effect `δ_a`, purposes `P_a`), schema narrowing | Sect. 3.2 |
| `hypermcp/interfaces.py`: Flat, Retrieval (BM25, embeddings), HyperMCP on session-stateful MCP | Sect. 3.2–3.3, 4 |
| `hypermcp/stateless.py`: HyperMCP on stateless MCP (handles, envelope, cacheable catalog) | Sect. 3.3 |
| `hypermcp/signifiers.py`: signifiers in the hMAS Interaction ontology, guard as SHACL shape | Sect. 3.3 |
| `hypermcp/mcp_transport.py`: both mappings as MCP servers (official SDK, Streamable HTTP) | Sect. 4 |
| `hypermcp/envs/shop.py`: 24-tool e-commerce environment, 11-rule policy, 10 tasks | Sect. 4 |
| `hypermcp/distractors.py`: tools of other services for the scaling runs | Sect. 4 |
| `hypermcp/agents.py`: OpenAI tool-calling loop (serial for HyperMCP); scripted test oracle | Sect. 3.2, 4 |
| `hypermcp/report.py`: summary table from `results/*.jsonl` | Table 2 |

## Reproducing the paper

All LLM runs use `--agent openai` (default model `gpt-4o-mini`) and `--out results`.
`python -m hypermcp.report` summarizes all logs. It reports each campaign (the date in
the log file name) as its own row.

| Claim | Command (repetitions) |
|---|---|
| Table 2, upper block: Flat, Retrieval (BM25, emb.), HyperMCP; agent-context ablation (14.0 tools) | `run --interfaces flat,retrieval,retrieval-emb,hyper --ablations` (×4) |
| Table 2, lower block: HyperMCP session-stateful and stateless, catalog only | `scripts/run-stateless-campaign.sh` (in-process part) |
| Both mappings over MCP (20 episodes each) | `scripts/run-stateless-campaign.sh` (MCP part) |
| Purchase task without pending signifiers | `run --interfaces hyper --ablations --tasks buy_hoodie` (×4) |
| Scaling to 1,024 tools (3 tasks per point) | `run --interfaces flat,hyper --distractors N --tasks cancel_and_return,return_window_trap,buy_hoodie` for N = 100, 500, 1000 (flat only up to 100: the API rejects more than 128 tools) |
| Flat baseline of the scaling runs at 24 tools (5.9k tokens) | `report --tasks cancel_and_return,return_window_trap,buy_hoodie` |

(`run` = `.venv/bin/python -m hypermcp.run`, `report` = `.venv/bin/python -m
hypermcp.report`.) The July 2026 logs also contain two ablations that the paper does not
report (no schema narrowing, no envelope). The current code no longer runs them.

## Tests

```sh
.venv/bin/python -m tests.test_invariants     # I1–I6: validity by construction, SHACL guard, pending ablation
.venv/bin/python -m tests.test_stateless      # S1–S4: stateless mapping exposes the same A(s, p_ag)
.venv/bin/python -m tests.test_mcp_transport  # T1–T2: protocol revisions; wire results = in-process results
```
