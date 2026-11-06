"""Signifier representation aligning HyperMCP's affordance envelope with the HMAS
Interaction ontology, following the signifier shape of Lemee ("Integrating Agentic Web
Standards in Multi-Agent Systems Using Hypermedia", LNCS 2026) so that HyperMCP signifiers
use the same vocabulary as the group's multi-standard SEM and are interoperable with
Yggdrasil-based Hypermedia MAS.

Shape (per Lemee): a hmas:Signifier has an rdfs:label, hmas:signifies a
td:InteractionAffordance (td:hasForm + td:hasInputSchema), and hmas:recommendsContext a
context node carrying an rdfs:comment (the natural-language description an LLM reads).
HyperMCP's distinctive addition: the recommended context ALSO carries a machine-readable
guard (SHACL-style property shapes / eligible bindings) that encodes *validity*, not only
relevance -- the state input of the SEM that the relevance-only selection does not model.

This is a lightweight JSON-LD-shaped view whose keys mirror the ontology terms; keep it in
sync with Listing 1 in the paper.

TODO(align-with-danai): confirm the final term IRIs + shape against the published HMAS
Interaction ontology used in github.com/Interactions-HSG/yggdrasil before freezing.
"""
from __future__ import annotations
from .core import Affordance, State, AgentContext

HMAS = "https://purl.org/hmas/"                   # confirm against published ontology
TD = "https://www.w3.org/2019/wot/td#"


def _interaction_affordance(aff: Affordance) -> dict:
    """The td:InteractionAffordance that a signifier hmas:signifies (tool + HTTP form)."""
    return {
        "@type": f"{TD}InteractionAffordance",
        "hmas:tool": aff.name,                       # the MCP tool that realizes the affordance
        "td:hasForm": {
            "http:methodName": "POST",
            "hctl:hasTarget": "mcp:tools/call",
            "hctl:forContentType": "application/json",
            "rel": aff.rel,
        },
        "td:hasInputSchema": aff.parameters,
    }


def affordance_to_signifier(aff: Affordance, state: State,
                            ctx: AgentContext | None = None) -> dict:
    """Render an exposed affordance as an HMAS-style signifier (JSON-LD-shaped),
    in the signifier shape of Lemee; HyperMCP adds the SHACL guard in the context node."""
    eligible = aff.eligible(state)
    return {
        "@type": f"{HMAS}Signifier",
        "rdfs:label": aff.name,
        "hmas:signifies": _interaction_affordance(aff),
        # recommendsContext: the NL comment an LLM reads (Lemee) PLUS the machine-readable
        # guard HyperMCP adds for validity (the SEM's application-state input).
        "hmas:recommendsContext": {
            "rdfs:comment": aff.description,
            "sh:property": {
                "eligible-bindings": eligible,       # concrete valid parameterizations now
                "serves-purposes": sorted(aff.purposes) or None,
            },
        },
        # Agent-context relevance (SEM): whether this matches the agent's goal/abilities.
        "relevant-to-agent": aff.relevant(ctx),
    }


def envelope(affordances: list[Affordance], state: State,
             ctx: AgentContext | None = None) -> list[dict]:
    """The next-step signifier envelope returned with a tools/call result.

    Contains (a) signifiers for the currently-applicable, context-relevant affordances,
    and (b) *pending* signifiers: relevant affordances that are not applicable yet,
    carrying the unmet context (hmas:recommendsContext) instead of eligible bindings --
    so that state-scoped narrowing does not hide the path to the agent's goal."""
    out = [affordance_to_signifier(a, state, ctx)
           for a in affordances if a.available(state) and a.relevant(ctx)]
    for a in affordances:
        if a.unlock_hint and a.relevant(ctx) and not a.available(state):
            out.append({
                "@type": f"{HMAS}Signifier",
                "rdfs:label": a.name,
                "hmas:signifies": _interaction_affordance(a),
                "currently-applicable": False,
                # pending signifier: NL recommended context only, no eligible bindings yet
                "hmas:recommendsContext": {"rdfs:comment": a.unlock_hint},
            })
    return out
