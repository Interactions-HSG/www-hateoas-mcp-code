# HyperMCP

Reference implementation and evaluation harness for the short paper *Toward a
Hypermedia-Driven Model Context Protocol: Exposing Tools through Situated Signifiers*.

## The idea in brief

In the Model Context Protocol (MCP), a server lists all of its tools, and an LLM agent may
call any of them at any time. Whether a call is valid at the current point of an
interaction (e.g., "authenticate first", "cancel only pending orders") is left to
natural-language policy that the model has to read and obey.

HyperMCP applies the Web's hypermedia principle to tool exposure: at every step, the agent
sees only the tools that are valid *now* and relevant to its goal, and enumerable
parameters (e.g., `order_id`) are narrowed to the values that are valid now. In the paper's
notation, the advertised set is `A(s, p_ag)`: the tools applicable in the interaction
state `s` that serve the agent profile `p_ag`.

The harness compares three ways of exposing the *same* 24 tools of an e-commerce service:

| Interface | What the agent sees at each step |
|---|---|
| Flat | all 24 tools (plain MCP) |
| Retrieval | the 3 tools whose descriptions are most similar (embeddings) to the request plus the latest tool result |
| HyperMCP | the tools in `A(s, p_ag)`, with narrowed parameters |

HyperMCP is implemented for both MCP protocol versions: on session-stateful MCP (revision
2025-11-25), the server re-scopes `tools/list` per session; on stateless MCP (revision
2026-07-28), the server keeps state under an explicit handle and returns the next valid
tools with every result (the *envelope*).

## Quick start

```sh
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m hypermcp.run                  # scripted agent, no API key needed
.venv/bin/python -m tests.test_invariants         # checks that HyperMCP never advertises an invalid call
```

For LLM runs, copy `.env.example` to `.env` and set `OPENAI_API_KEY`:

```sh
.venv/bin/python -m hypermcp.run --agent openai --interfaces flat,retrieval-emb,hyper
.venv/bin/python -m hypermcp.report               # summary table of all logs in results/
```

## How an episode runs

1. A task (e.g., "return my black t-shirt order") starts from a fixed, seeded shop state.
2. At each step, the interface decides which tools the model sees (`tool_specs`).
3. The model calls one tool (HyperMCP) or a batch of tools (baselines, as plain MCP hosts
   allow). The tool's guard checks the call against the current state; a call that
   violates a precondition is rejected and counted as *illegal*.
4. The episode ends when the model answers without calling a tool. If it stops to ask a
   clarifying question and the task defines a `user_reply`, that reply is given once.
5. Success is checked on the final state (e.g., the order is `return_requested` with a
   refund to the original payment method).

Each episode is logged as one JSON line in `results/`, including every call and whether it
was accepted.

## From the paper to the code

| Paper | Code |
|---|---|
| Interaction state `s`; tool with guard `g_a`, effect `δ_a`, purposes `P_a` | `core.State`, `core.Affordance` |
| Agent profile `p_ag = (A_ag, goal_ag)` | `core.AgentContext` |
| Exposed set `A(s, p_ag)` and parameter narrowing (Sect. 3.2) | `interfaces.HyperInterface.list_tools`, `core.Affordance.tool_spec` |
| Session-stateful MCP: re-scoped `tools/list` (Sect. 3.3) | `interfaces.HyperInterface` |
| Stateless MCP: handles, envelope, cacheable catalog (Sect. 3.3) | `stateless.StatelessServer`, `stateless.EnvelopeHost` |
| Signifiers in the hMAS Interaction ontology, guard as SHACL shape (Sect. 3.3) | `signifiers.envelope` |
| Both mappings as real MCP servers (Sect. 4) | `mcp_transport.MCPInterface` |
| Shop environment: 24 tools, 11-rule policy, 10 tasks (Sect. 4) | `envs/shop.py` |

Other files: `agents.py` (scripted test oracle and the two OpenAI tool-calling loops),
`distractors.py` (tools of other services for the scaling runs), `metrics.py` and
`report.py` (per-episode records and the summary table), `run.py` (command line).
`prototype/` holds an early standalone proof of concept that the paper does not use.

## Reproducing the paper

`run` stands for `.venv/bin/python -m hypermcp.run`; add `--out results` to log. Each
command below was repeated four times (10 tasks each), unless stated otherwise.
`python -m hypermcp.report` lists every campaign (the date in the log file name) as its
own row, so reruns are never pooled with earlier results.

| Paper | Command |
|---|---|
| Table 2, `gpt-4o-mini`, first block; agent-profile ablation (14.0 tools) | `run --agent openai --interfaces flat,retrieval-emb,hyper --ablations` |
| Table 2, `gpt-4o-mini`, second block; both mappings over MCP (20 episodes each) | `scripts/run-stateless-campaign.sh` |
| Table 2, `gpt-6.1-sol` block | `scripts/run-frontier-campaign.sh` |
| Purchase task without pending signifiers | `run --agent openai --interfaces hyper --ablations --tasks buy_hoodie` |
| Scaling to 1,024 tools (3 tasks per point) | `run --agent openai --interfaces flat,hyper --distractors N --tasks cancel_and_return,return_window_trap,buy_hoodie` for N = 100, 500, 1000 (Flat only up to 100: the API rejects more than 128 tools) |
| Flat at 24 tools for the scaling runs (5.9k tokens) | `report --tasks cancel_and_return,return_window_trap,buy_hoodie` |

`results/archive-*` folders hold superseded runs, each named after the reason it was
superseded; they are kept as records and are not used by the paper. The 2026-07-08 logs
also contain retrieval and ablation variants that the paper no longer reports; the current
code no longer runs them.

## Tests

```sh
.venv/bin/python -m tests.test_invariants     # I1–I6: validity by construction, SHACL guard, pending signifiers
.venv/bin/python -m tests.test_stateless      # S1–S4: the stateless mapping exposes the same A(s, p_ag)
.venv/bin/python -m tests.test_mcp_transport  # T1–T2: protocol versions; results over MCP = in-process results
```
