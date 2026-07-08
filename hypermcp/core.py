"""Core model: application state, affordances (guarded tools), environments, tasks.

An Affordance is a tool augmented with a *guard* (precondition over application
state) and an *effect* (state transition). The three interfaces in `interfaces.py`
differ only in *which* affordances they advertise and whether invalid calls are
reachable -- the affordances themselves are shared, so B0/B1/HyperMCP are compared
over an identical underlying capability set.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Any
import copy


@dataclass
class State:
    """Per-session application state (the 'engine of application state')."""
    authenticated_user: str | None = None
    db: dict[str, Any] = field(default_factory=dict)   # users, orders, ...
    scratch: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentContext:
    """The agent's own context, consumed by the Signifier Exposure Mechanism.

    In Vachtsevanou et al.'s SEM, exposure depends on environment state AND the agent's
    context (its goals/abilities). `goal` selects purpose-relevant affordances (a single
    purpose or, for multi-constraint tasks, a set of purposes); `abilities` optionally
    restricts to affordances the agent can actually operate.
    """
    goal: str | set[str] | None = None
    abilities: set[str] | None = None                  # None = no ability restriction

    def goals(self) -> set[str] | None:
        if self.goal is None:
            return None
        return self.goal if isinstance(self.goal, set) else {self.goal}


def _default_candidates(_s: "State") -> list[dict]:
    return [{}]


@dataclass
class Affordance:
    name: str
    description: str
    parameters: dict[str, Any]                          # JSON-schema for LLM tool spec
    guard: Callable[[State, dict], bool]                # precondition over state
    effect: Callable[[State, dict], str]                # returns an observation string
    rel: str = "action"                                 # semantic link relation / type
    # Candidate arg-bindings to test the guard against for state-scoped advertisement
    # (e.g. one per order the user owns). Default: a single empty binding.
    candidates: Callable[[State], list[dict]] = _default_candidates
    purposes: set[str] = field(default_factory=set)     # goals this affordance serves
    # Unmet-context hint for the envelope's *pending* signifiers (recommendsContext in
    # the HMAS Interaction ontology): shown when the affordance is goal-relevant but not
    # applicable yet, so narrowing does not hide the path to the goal. Restores parity
    # with flat, where the model can always read the precondition in the description.
    unlock_hint: str | None = None

    def relevant(self, ctx: "AgentContext | None") -> bool:
        """Agent-context filter (SEM): affordance is relevant to the agent's context."""
        if ctx is None:
            return True
        goals = ctx.goals()
        if self.purposes and goals is not None and not (goals & self.purposes):
            return False
        if ctx.abilities is not None and self.name not in ctx.abilities:
            return False
        return True

    def eligible(self, s: State) -> list[dict]:
        """Bindings that satisfy the guard in state `s` (used for advertisement)."""
        return [c for c in self.candidates(s) if self.guard(s, c)]

    def available(self, s: State) -> bool:
        return len(self.eligible(s)) > 0

    def tool_spec(self, s: State | None = None) -> dict:
        """Anthropic/OpenAI-style tool definition. When `s` is given (HyperMCP), the
        parameter domains are narrowed to the currently-eligible bindings (enum) and the
        description is annotated -- so the model cannot even name an invalid target."""
        desc = self.description
        params = self.parameters
        if s is not None:
            elig = self.eligible(s)
            params = copy.deepcopy(self.parameters)
            enum_vals: list[str] = []
            for key, spec in params.get("properties", {}).items():
                vals = sorted({c[key] for c in elig if key in c})
                # Narrow only when the domain is small enough to be an enum an LLM can
                # use; a large domain (e.g. every in-stock product) stays free-form.
                if 0 < len(vals) <= 16:
                    spec["enum"] = vals                 # state-narrowed parameter domain
                    enum_vals.extend(str(v) for v in vals)
            hint = ", ".join(sorted(set(enum_vals)))
            if hint:
                desc = f"{desc} [currently valid for: {hint}]"
        return {"name": self.name, "description": desc, "input_schema": params}


@dataclass
class Observation:
    ok: bool
    text: str
    # HyperMCP envelope: names of the successor affordances (compact hint for the LLM) ...
    next_affordances: list[str] = field(default_factory=list)
    # ... goal-relevant affordances that are NOT yet applicable, with their unmet context
    # ("place_order (requires a non-empty cart)") -- pending signifiers ...
    pending: list[str] = field(default_factory=list)
    # ... and the same envelope as HMAS-Interaction-ontology signifiers (for MAS interop).
    signifiers: list[dict] = field(default_factory=list)


@dataclass
class Task:
    id: str
    instruction: str                                    # the user's request (for LLM/user-sim)
    init: Callable[[], State]                           # fresh initial state
    goal: Callable[[State], bool]                       # success predicate on final state
    # Optional scripted intent for no-key smoke runs: ordered (tool, args) the agent *wants*.
    scripted_intent: list[tuple[str, dict]] = field(default_factory=list)
    agent_ctx: "AgentContext | None" = None             # agent goal/abilities for the SEM


@dataclass
class Env:
    name: str
    affordances: list[Affordance]
    tasks: list[Task]
    policy: str = ""                                     # natural-language policy (B0/B1)
    # Who the agent is in this environment (system-prompt persona; interface-independent).
    persona: str = "You are an agent acting on behalf of the user."

    def by_name(self) -> dict[str, Affordance]:
        return {a.name: a for a in self.affordances}


def clone(state: State) -> State:
    return copy.deepcopy(state)
