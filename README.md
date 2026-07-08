# HyperMCP

Reference implementation and evaluation harness for the paper draft *From Flat Tool Menus
to Hypermedia Affordances: A Signifier Exposure Mechanism for the Model Context Protocol*
(working name **HyperMCP**, targeting TheWebConf 2027). The paper source lives in the
companion repository
[`Interactions-HSG/www-hateoas-mcp`](https://github.com/Interactions-HSG/www-hateoas-mcp).

## Idea

MCP exposes tools as a flat, static menu. HyperMCP treats the advertised tool set as a
**Signifier Exposure Mechanism** (SEM; Vachtsevanou et al.): the exposed tools are a
function of **environment state × agent context** (HATEOAS + signifiers). Each step shows
only the tools that are *valid now and relevant to the agent's goal*, narrows their
parameter domains to eligible bindings (enum), and returns a next-step **signifier
envelope** (HMAS Interaction ontology). Result: fewer invalid calls, less context, better
task success — and, via the Yggdrasil bridge, LLM agents that can consume real Hypermedia
MAS environments.

Three interfaces over the **same** affordances are compared:

| interface | `list_tools` | invalid calls |
|-----------|--------------|---------------|
| `flat` (B0) | every tool, always | admitted (post-hoc reject) |
| `retrieval` (B1) | top-k by BM25 relevance | admitted; may drop prerequisites |
| `hyper` (HyperMCP) | state-valid affordances + enum-narrowed args + envelope | unreachable for a conformant client |

## Mapping to the signifier theory (Vachtsevanou et al.)

The harness is a deliberate specialisation of the signifier / SEM theory to LLM agents and
the MCP substrate. The correspondence, and where each concept lives:

| Signifier theory | This codebase | Paper |
|---|---|---|
| Affordance (potential interaction) | `core.Affordance` — MCP tool + guard `g_a(s,β)` + effect `δ_a` + purposes | §3.1, Eq. 1 |
| Artifact / environment state | `core.State` (one per MCP session) | §3.1 |
| Agent profile (abilities, goals) | `core.AgentContext` | §3.2 |
| **Signifier** (reveals an affordance) | `signifiers.affordance_to_signifier` — HMAS-Interaction-ontology rendering, attached to results as `Observation.signifiers` | §3.3, Listing 1 |
| **Signifier Exposure Mechanism** | `interfaces.HyperInterface.list_tools` = `A(s,c)`; enum narrowing in `core.Affordance.tool_spec` | §3.2, Eq. 3 |
| Recommended context (SHACL shapes) | guard functions + eligible bindings (`context-conditions` in the JSON-LD view) | Listing 1 |
| Yggdrasil / HMAS platform | `bridges/yggdrasil.py` (scaffold; live path is a paper deliverable) | §4 |

The theory was built for symbolic (BDI) agents; the extension here is to treat the LLM
tool-calling loop as a new class of signifier consumer, with `tools/list` as the exposure
channel and `notifications/tools/list_changed` as the perception update.

## Open questions for co-authors

1. **Ontology terms (blocking Listing 1 + `signifiers.py`).** The HMAS Interaction
   ontology IRIs and the context-shape idiom used here are placeholders — confirm against
   the published vocabularies and the Yggdrasil implementation before freezing.
2. **Live Yggdrasil bridge.** `bridges/yggdrasil.py` needs: the workspace/artifact
   endpoints to pin, HMAS signifier RDF → `Affordance` parsing (rdflib behind an extra),
   and affordance-form invocation as the effect.
3. **Formal SEM alignment.** Does Eq. 3 (`A(s,c)` with relevance = goal ∈ purposes ∧
   ability restriction) faithfully specialise the Annals-of-Math-&-AI SEM? What should the
   LLM-agent analogue of an *ability* be?
4. **Conformance criterion (iv) vs. real LLM clients.** Advertised-only selection fails
   in two ways in practice: (a) a *parallel tool-call batch* is selected against one
   state, so an earlier call's transition can invalidate a later one — observed live
   (the model batched both auth tools); the HyperMCP client therefore now executes
   serially, one affordance per perceive–act cycle; (b) the model can *fabricate* an
   out-of-advertisement binding despite the enum — the server-side guard rejects it, and
   the `noenum` ablation shows narrowing suppresses this. Question for the theory
   section: is client conformance an assumption of the proposition, or is the guard the
   mechanism's own last line of defence? (Per-call transcripts are in `results/*.jsonl`.)

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

# Invariants (17k+ instance-checks; no key needed):
.venv/bin/python -m tests.test_invariants
```

Metrics per run: task success, illegal-tool-call rate, structurally-blocked count,
steps, average menu size (context proxy), tokens, and a per-call transcript
(`calls` in the JSONL — tool, args, ok). Flags: `--ablations` adds
`hyper-noctx` / `-noenum` / `-noenv` (isolating the agent-context input, enum-narrowing,
and the signifier envelope); `--no-policy` removes the natural-language policy from the
prompt (does the SEM enforce validity structurally?); `--distractors N` pads the env with
N never-applicable tools (the many-servers regime). Note: enum/envelope steer a *real LLM*
toward valid args/next-steps, so their effect shows under a real agent, not scripted mode.

## Preliminary results

`gpt-4o-mini`; retail n=20/cell (5 tasks × 4 runs), WoT n=12/cell (3 tasks × 4 runs):

| Env, setting | Interface | Success | Illegal | Menu | Tokens |
|---|---|---|---|---|---|
| retail, policy | flat | 100% | 1 | 7.0 | 1829 |
| retail, policy | retrieval | **40%** | **21** | 3.0 | 588 |
| retail, policy | **hyper** | 100% | **0** | 2.6 | 1398 (−24%) |
| retail, no policy | flat | 100% | **4** | 7.0 | 1296 |
| retail, no policy | retrieval | 40% | 19 | 3.0 | 408 |
| retail, no policy | **hyper** | 100% | **0** | 2.6 | 1031 (−20%) |
| retail, 57 tools | flat | 100% | 2 | 57.0 | **6364** |
| retail, 57 tools | retrieval | 40% | 22 | 3.0 | 604 |
| retail, 57 tools | **hyper** | 100% | **0** | 2.6 | **1489 (−77%)** |
| wot, policy | flat | 100% | **4** | 7.0 | 1568 |
| wot, policy | retrieval | 33% | 25 | 3.0 | 856 |
| wot, policy | **hyper** | 100% | **0** | 1.3 | 792 (−49%) |

Headlines:
- **Relevance ≠ validity.** Retrieval drops the auth prerequisite: 33–40% success, 19–25
  illegal calls per cell. HyperMCP admits **0 illegal calls in all 84 episodes**.
- **Structure replaces prompt policy.** Flat violates preconditions even *with* the policy
  in context (1 retail / 4 WoT) and gets worse without it (4); HyperMCP stays at 0 in both.
- **Context cost stays flat as tools scale.** 7→57 tools: flat 1829→6364 tokens; HyperMCP
  1398→1489. Retrieval is cheap but invalid — and in WoT its error loops make it *more*
  expensive than HyperMCP (856 vs 792).
- **Ablations isolate the SEM inputs** (retail, policy): removing agent-context (`noctx`)
  inflates the menu 2.6→4.0 and cuts the token saving to −9%; removing enum-narrowing
  (`noenum`) reintroduces 3 fabricated-binding illegal calls; removing the envelope
  (`noenv`) is negligible on these short tasks.

The result logs backing this table (and the paper's Table 1) are committed under
`results/` with per-call transcripts; regenerate the table with
`.venv/bin/python -m hypermcp.report`.

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
tests/test_invariants.py  randomised checks of the no-invalid-call guarantee (I1-I5)
prototype/            standalone stdlib PoC of the core mechanism
results/              committed JSONL logs of the runs behind the paper table
```
