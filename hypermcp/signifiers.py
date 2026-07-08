"""Signifier representation aligning HyperMCP's affordance envelope with the HMAS
Interaction ontology (Vachtsevanou et al.), so exposed affordances are interoperable
with Yggdrasil-based Hypermedia MAS.

A *signifier* reveals an *affordance* to an agent under context conditions. We render each
exposed affordance instance as a signifier: it points at the affordance (the MCP tool +
eligible bindings), states the guard as a precondition/context-condition, and can carry a
recommended interaction. This is a lightweight JSON-LD-shaped view; the full ontology terms
(hmas:Signifier, hmas:signifies, hmas:recommendsAbility, ...) are filled in against the
published HMAS-core / HMAS-Interaction vocabularies during integration.

TODO(align-with-danai): confirm exact term IRIs + shape against the HMAS Interaction
ontology used in github.com/Interactions-HSG/yggdrasil before freezing the vocabulary.
"""
from __future__ import annotations
from .core import Affordance, State, AgentContext

HMAS = "https://purl.org/hmas/"          # placeholder base IRI; confirm against published ontology


def affordance_to_signifier(aff: Affordance, state: State,
                            ctx: AgentContext | None = None) -> dict:
    """Render an exposed affordance as an HMAS-style signifier (JSON-LD-shaped)."""
    eligible = aff.eligible(state)
    return {
        "@type": f"{HMAS}Signifier",
        "signifies": {
            "@type": f"{HMAS}ActionSpecification",
            "tool": aff.name,                        # the MCP tool that realizes the affordance
            "rel": aff.rel,
            "description": aff.description,
        },
        # The guard, exposed as the context-condition under which the signifier is revealed:
        "context-conditions": {
            "eligible-bindings": eligible,           # concrete valid parameterizations now
            "serves-purposes": sorted(aff.purposes) or None,
        },
        # Agent-context relevance (SEM): whether this matches the agent's goal/abilities.
        "relevant-to-agent": aff.relevant(ctx),
    }


def envelope(affordances: list[Affordance], state: State,
             ctx: AgentContext | None = None) -> list[dict]:
    """The next-step signifier envelope returned with a tools/call result."""
    return [affordance_to_signifier(a, state, ctx)
            for a in affordances if a.available(state) and a.relevant(ctx)]
