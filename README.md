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
| **Pending signifiers / `recommendsContext`** | `Affordance.unlock_hint` → envelope's "[not yet available: …]" + `currently-applicable: false` signifiers — relevant-but-not-applicable affordances stay *visible* without being *callable* | Discussion |
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
5. **Pending signifiers = `recommendsContext`?** On the shop's purchase task we observed
   the discoverability cost of pure narrowing live: `place_order` (guarded on a
   non-empty cart) stayed invisible, and agents looped in inspections instead of adding
   to cart. We now expose relevant-but-not-applicable affordances as *pending*
   signifiers carrying their unmet context (`Affordance.unlock_hint`) — visible, not
   callable. Is this the right MCP rendering of `hmas:recommendsContext`, and should the
   unmet context eventually be the machine-readable guard (SHACL shape) rather than
   prose?

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
.venv/bin/python -m hypermcp.run --env shop --max-steps 12   # realistic large-surface shop

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

## Results

`gpt-4o-mini`; episodes/cell: retail 20, WoT 12, shop 40 (figures regenerate via
`python -m hypermcp.figures`):

| Env, setting | Interface | Success | Illegal | Menu | Tokens |
|---|---|---|---|---|---|
| retail, policy | flat | 100% | 1 | 7.0 | 1829 |
| retail, policy | retrieval | **40%** | **21** | 3.0 | 588 |
| retail, policy | **hyper** | 100% | **0** | 2.6 | 1398 (−24%) |
| retail, no policy | flat | 100% | **4** | 7.0 | 1296 |
| retail, no policy | **hyper** | 100% | **0** | 2.6 | 1031 (−20%) |
| retail, 57 tools | flat | 100% | 0 | 57.0 | **9663** |
| retail, 57 tools | **hyper** | 100% | **0** | 2.6 | **1438 (−85%)** |
| wot, policy | flat | 100% | **4** | 7.0 | 1568 |
| wot, policy | retrieval | 33% | 25 | 3.0 | 856 |
| wot, policy | **hyper** | 100% | **0** | 1.3 | 792 (−49%) |
| **shop**, policy | flat | 98% | **13** | 24.0 | 4849 |
| shop, policy | retrieval (BM25) | **50%** | **66** | 3.0 | 1309 |
| shop, policy | retrieval (emb.) | **50%** | **57** | 3.0 | 1428 |
| shop, policy | **hyper** | **100%** | 4* | 4.8 | **3013 (−38%)** |

\* all 4 = model-fabricated out-of-advertisement bindings, rejected server-side; 0
invalid calls through advertised instances in all 121 hyper episodes.

Headlines:
- **Hard tasks break the ceiling — hyper wins all three axes on the shop.** 100% success
  (flat 98%: it attempts the tier-forbidden gift-card refund and abandons the legal
  return), 4 rejected fabrications vs flat's 13 violations, −38% tokens.
- **Relevance ≠ validity, and embeddings don't fix it.** Both retrieval variants: 50%
  success, 57–66 illegal calls on the shop.
- **Scaling (fig-scaling):** flat 5.9k→20.6k tokens at 24→124 tools, **infeasible >128
  tools (OpenAI API cap)**; hyper ≈4.4k flat through 1,024 tools at 100% success.
- **Ablations (shop):** no agent-context → menu 4.8→14.0, saving −38%→**+1%** (the second
  SEM input is *the* cost lever); no enum → 6 illegal + success drops to 95%; envelope
  negligible on short horizons — but **pending signifiers** (recommendsContext) took the
  purchase task from 0/4 to 4/4.

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
  envs/shop.py        realistic large-surface online shop: 24 genuine tools, seeded world
                      (~1000 products / 240 users / ~700 orders), 11-rule policy, 10
                      multi-constraint tasks (ordering, window/tier/ownership traps)
  distractors.py      realistic cross-service tool pool (many-servers regime)
  interfaces.py       FlatInterface / Retrieval (BM25) / EmbeddingRetrieval /
                      HyperInterface (the SEM)
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
