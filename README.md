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

# Real LLM numbers (copy .env.example -> .env and set OPENAI_API_KEY or ANTHROPIC_API_KEY):
.venv/bin/python -m hypermcp.run --agent openai --model gpt-4o-mini --ablations --out results
.venv/bin/python -m hypermcp.run --agent openai --model gpt-4o-mini --no-policy --out results
.venv/bin/python -m hypermcp.run --agent openai --model gpt-4o-mini --distractors 50 --out results
.venv/bin/python -m hypermcp.run --agent anthropic --model claude-opus-4-8 --ablations

# Aggregate all logged runs into a per-(model, condition, interface) table:
.venv/bin/python -m hypermcp.report

# Invariants (13k+ instance-checks; no key needed):
.venv/bin/python -m tests.test_invariants
```

Metrics per run: task success, illegal-tool-call rate, structurally-blocked count,
steps, average menu size (context proxy), tokens. Flags: `--ablations` adds
`hyper-noctx` / `-noenum` / `-noenv` (isolating the agent-context input, enum-narrowing,
and the signifier envelope); `--no-policy` removes the natural-language policy from the
prompt (does the SEM enforce validity structurally?); `--distractors N` pads the env with
N never-applicable tools (the many-servers regime). Note: enum/envelope steer a *real LLM*
toward valid args/next-steps, so their effect shows under a real agent, not scripted mode.

## Preliminary results

`gpt-4o-mini`, retail domain, 5 tasks/cell (reproduce with the commands above + `report`):

| Setting | Interface | Success | Illegal | Tokens |
|---|---|---|---|---|
| policy | flat | 100% | 0 | 1808 |
| policy | retrieval | **40%** | **5** | 566 |
| policy | **hyper** | 100% | 0 | 1452 |
| no policy | flat | 100% | **1** | 1000 |
| no policy | **hyper** | 100% | **0** | 1063 |
| many tools (57) | flat | 100% | 0 | **6205** |
| many tools | retrieval | 40% | 5 | 564 |
| many tools | **hyper** | 100% | 0 | **1547 (−75%)** |

Retrieval trades validity for tokens (it drops the auth prerequisite); HyperMCP keeps
validity **and** stays flat in context as tools scale. Removing the policy text makes flat
begin to violate constraints while HyperMCP stays valid — its guarantees are structural,
not prompt-engineered.

## Layout

```
hypermcp/
  core.py             State, AgentContext, Affordance (guard/effect/candidates/purposes),
                      state+context-narrowed tool schemas
  envs/retail.py      tau-bench retail policy as guards + tasks (traps) + agent goals
  envs/wot.py         Web-of-Things smart space: device state machines as guards
  interfaces.py       FlatInterface / RetrievalInterface (BM25) / HyperInterface (the SEM)
  signifiers.py       HMAS Interaction ontology envelope (JSON-LD-shaped)
  bridges/yggdrasil.py  HyperMCP<->Yggdrasil bridge (scaffold; live path TODO)
  agents.py           run_scripted + AnthropicAgent + OpenAIAgent (tool-calling loops)
  metrics.py          RunResult + aggregate
  report.py           aggregate results/*.jsonl into a comparison table
  run.py              CLI
tests/test_invariants.py  randomised checks of the no-invalid-call guarantee
prototype/            standalone stdlib PoC of the core mechanism
```
