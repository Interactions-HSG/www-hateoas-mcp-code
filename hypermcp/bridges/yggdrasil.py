"""HyperMCP <-> Yggdrasil bridge (scaffold).

Goal: let an LLM agent consume a *real* Hypermedia MAS environment (Yggdrasil,
github.com/Interactions-HSG/yggdrasil) through MCP. The bridge fetches the signifiers that
Yggdrasil's Signifier Exposure Mechanism currently exposes for a workspace/artifact, and
turns each into a HyperMCP Affordance (an MCP tool + guard + effect). Because Yggdrasil is
HTTP-native and serves RDF (HMAS-core / HMAS-Interaction, Thing Descriptions), the bridge
is a *client* -- no Java/JaCaMo in-process interop is required.

Status: interface + offline mock only. Live integration is a paper deliverable (WoT
scenario). It needs: (1) a running Yggdrasil with the SEM enabled, (2) parsing HMAS
signifier RDF into Affordances, (3) mapping signifier action specs -> MCP tool schemas,
(4) invoking the affordance's form (HTTP request) as the Affordance effect.

TODO(integration):
  - pin the Yggdrasil API (workspace/artifact endpoints; profile publication) and the
    HMAS Interaction ontology terms used for signifiers;
  - add an RDF parser (rdflib) behind an extra so the core stays dependency-light;
  - map hmas:Signifier -> Affordance(name, params from TD/action-spec, guard from
    context-conditions, effect = perform the affordance's HTTP form).
"""
from __future__ import annotations
from typing import Iterable
from ..core import Affordance, Env


class YggdrasilBridge:
    def __init__(self, base_url: str, ontology: str = "hmas"):
        self.base_url = base_url.rstrip("/")
        self.ontology = ontology

    # --- live path (to implement) ------------------------------------------ #
    def fetch_signifiers(self, workspace: str, artifact: str) -> list[dict]:
        """GET the currently-exposed signifiers for an artifact (HMAS RDF -> dicts)."""
        raise NotImplementedError("live Yggdrasil fetch not yet implemented; use load_mock")

    def to_affordances(self, signifiers: Iterable[dict]) -> list[Affordance]:
        """Map HMAS signifiers to HyperMCP affordances (tool + guard + effect)."""
        raise NotImplementedError("signifier->affordance mapping not yet implemented")

    # --- offline path (works now) ------------------------------------------ #
    @staticmethod
    def load_mock(env: Env) -> Env:
        """Return an Env unchanged -- placeholder so downstream code can target the bridge
        API today against a hand-built Env (e.g. the WoT smart-space env) while the live
        Yggdrasil path is being wired."""
        return env
