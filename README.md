# HyperMCP

Reference implementation and evaluation harness for the paper *HyperMCP: state-sensitive
hypermedia affordances for LLM agent tooling* (targeting TheWebConf 2027). The paper source
lives in the companion repository
[`Interactions-HSG/www-hateoas-mcp`](https://github.com/Interactions-HSG/www-hateoas-mcp).

## Idea

MCP exposes tools as a flat, static menu. HyperMCP treats the advertised affordance set as
a **Signifier Exposure Mechanism** (Vachtsevanou et al.): the exposed tools are a function
of **environment state × agent context** (HATEOAS + signifiers). Each step shows only the
tools that are *valid now and relevant to the agent's goal*, narrows their parameter domains
to eligible bindings (enum), and returns a next-step **signifier envelope** (HMAS Interaction
ontology). Result: fewer invalid calls, less context, better task success — and, via the
Yggdrasil bridge, LLM agents that can consume real Hypermedia MAS environments.

Three interfaces over the **same** affordances are compared:

| interface | `list_tools` | invalid calls |
|-----------|--------------|---------------|
| `flat` (B0) | every tool, always | admitted (post-hoc reject) |
| `retrieval` (B1) | top-k by BM25 relevance | admitted; may drop prerequisites |
| `hyper` (HyperMCP) | state-valid affordances + enum-narrowed args + envelope | unreachable by construction |

## Setup

```bash
python3 -m venv --without-pip .venv
# bootstrap pip (this env lacks ensurepip):
curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
.venv/bin/python -m pip install -r requirements.txt
```

## Run

```bash
# No API key needed — scripted agent, reproduces the mechanism-level result:
.venv/bin/python -m hypermcp.run                         # retail
.venv/bin/python -m hypermcp.run --env wot --ablations   # WoT + SEM ablations
.venv/bin/python -m hypermcp.run --ablations --out results   # log runs to results/*.jsonl

# Real LLM numbers (copy .env.example -> .env and set ANTHROPIC_API_KEY):
.venv/bin/python -m hypermcp.run --agent anthropic --model claude-opus-4-8 --ablations

# Open model via an OpenAI-compatible endpoint:
.venv/bin/python -m hypermcp.run --agent openai --model <name> --base-url <url>

# Invariants (12k+ instance-checks; no key needed):
.venv/bin/python -m tests.test_invariants
```

Metrics per run: task success, illegal-tool-call rate, structurally-blocked count,
steps, average menu size (context proxy), tokens. Ablations `hyper-noctx` / `-noenum` /
`-noenv` isolate the agent-context input, enum-narrowing, and the signifier envelope.
Note: enum/envelope steer a *real LLM* toward valid args/next-steps, so their effect
shows under `--agent anthropic|openai`, not in scripted mode.

## Layout

```
hypermcp/
  core.py             State, AgentContext, Affordance (guard/effect/candidates/purposes),
                      state+context-narrowed tool schemas
  envs/retail.py      tau-bench retail policy as guards + tasks (incl. a trap) + agent goals
  interfaces.py       FlatInterface / RetrievalInterface (BM25) / HyperInterface (the SEM)
  signifiers.py       HMAS Interaction ontology envelope (JSON-LD-shaped)
  bridges/yggdrasil.py  HyperMCP<->Yggdrasil bridge (scaffold; live path TODO)
  agents.py           run_scripted + AnthropicAgent + OpenAIAgent (tool-calling loops)
  metrics.py          RunResult + aggregate
  run.py              CLI
prototype/            standalone stdlib PoC of the core mechanism
```
