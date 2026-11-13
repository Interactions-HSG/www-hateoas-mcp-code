"""Signifier representation of HyperMCP's envelope in the HMAS Interaction ontology.

Shape: a hmas:Signifier has an rdfs:label, hmas:signifies a td:InteractionAffordance
(td:hasForm + td:hasInputSchema), and hmas:recommendsContext a context node carrying an
rdfs:comment (the natural-language description an LLM reads). HyperMCP extends the
recommended context with a SHACL node shape that encodes the guard in the current state:
one sh:PropertyShape per parameter, whose sh:in lists the parameter's eligible values
(e.g. order_id restricted to the user's pending orders for cancel_order).

This is a lightweight JSON-LD-shaped view whose keys mirror the ontology terms. It travels
with every result (Observation.signifiers; over MCP in CallToolResult._meta) for hMAS
platforms; the LLM reads the tool definitions and the envelope's name list instead.
"""
from __future__ import annotations
from .core import Affordance, State, AgentContext

HMAS = "https://purl.org/hmas/"
TD = "https://www.w3.org/2019/wot/td#"
SH = "http://www.w3.org/ns/shacl#"


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


def guard_shape(aff: Affordance, state: State) -> list[dict]:
    """The guard in state `state` as SHACL property shapes: each parameter that the
    eligible bindings constrain may take only the values of those bindings (sh:in)."""
    elig = aff.eligible(state)
    shapes = []
    for key in aff.parameters.get("properties", {}):
        vals = sorted({b[key] for b in elig if key in b})
        if vals:
            shapes.append({"@type": f"{SH}PropertyShape", "sh:path": key, "sh:in": vals})
    return shapes


def affordance_to_signifier(aff: Affordance, state: State,
                            ctx: AgentContext | None = None) -> dict:
    """Render an exposed affordance as an HMAS signifier (JSON-LD-shaped)."""
    return {
        "@type": f"{HMAS}Signifier",
        "rdfs:label": aff.name,
        "hmas:signifies": _interaction_affordance(aff),
        # recommendsContext: the NL comment an LLM reads PLUS the SHACL guard that
        # encodes validity (the SEM's application-state input) and the purposes served.
        "hmas:recommendsContext": {
            "@type": f"{SH}NodeShape",
            "rdfs:comment": aff.description,
            "sh:property": guard_shape(aff, state),
            "serves-purposes": sorted(aff.purposes) or None,
        },
    }


def envelope(affordances: list[Affordance], state: State,
             ctx: AgentContext | None = None, pending: bool = True) -> list[dict]:
    """The next-step signifier envelope returned with a tools/call result.

    Contains (a) signifiers for the currently-applicable, context-relevant affordances,
    and (b) unless `pending` is False, *pending* signifiers: relevant affordances that are
    not applicable yet, carrying the unmet context (hmas:recommendsContext) instead of a
    guard shape -- so that state-scoped narrowing does not hide the path to the goal."""
    out = [affordance_to_signifier(a, state, ctx)
           for a in affordances if a.available(state) and a.relevant(ctx)]
    if not pending:
        return out
    for a in affordances:
        if a.unlock_hint and a.relevant(ctx) and not a.available(state):
            out.append({
                "@type": f"{HMAS}Signifier",
                "rdfs:label": a.name,
                "hmas:signifies": _interaction_affordance(a),
                "currently-applicable": False,
                "hmas:recommendsContext": {"rdfs:comment": a.unlock_hint},
            })
    return out
