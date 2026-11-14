"""The three tool-exposure interfaces compared in the paper.

All three sit over the SAME set of affordances (env.affordances). They differ only in
what `list_tools` advertises and whether invalid calls are reachable:

  FlatInterface         (baseline)  static full menu; guard enforced only by post-hoc
                                    rejection.
  EmbeddingRetrievalInterface (baseline) top-k by dense-embedding similarity of tool text to the
                                    running context (user request + latest tool result);
                                    relevance, not validity -> can surface invalid tools.
  HyperInterface        (HyperMCP)  state-scoped affordances + next-step envelope;
                                    invalid calls are unreachable by construction.
"""
from __future__ import annotations
import math
from .core import State, Env, Observation, Affordance, AgentContext
from .signifiers import envelope


# --------------------------------------------------------------------------- #
# Interfaces
# --------------------------------------------------------------------------- #
class _Base:
    label = "base"
    # Should the client execute tool calls serially (one per perception)? Vanilla MCP
    # hosts batch parallel calls, so the baselines keep that default.
    serial_calls = False

    def __init__(self, env: Env):
        self.env = env
        self._by = env.by_name()
        self.agent_ctx: AgentContext | None = None      # set per-task by the runner (SEM)

    def list_tools(self, state: State, context: str) -> list[Affordance]:
        """The affordances advertised to the client this step (the interface's essence)."""
        raise NotImplementedError

    def offers(self, state: State, name: str, args: dict, context: str = "") -> bool:
        """Is this concrete affordance *instance* (name+args) advertised to the client?"""
        return True

    def tool_specs(self, state: State, context: str) -> list[dict]:
        """Tool definitions handed to the LLM this step (baselines: state-independent)."""
        return [a.tool_spec(None) for a in self.list_tools(state, context)]

    def current_state(self, state: State) -> State:
        """The interaction state the task goal is evaluated on (evaluator view). In-process
        interfaces mutate the episode state directly; the stateless mapping keeps it
        server-side under a handle, and the MCP transport in another server object."""
        return state

    def call(self, state: State, name: str, args: dict) -> Observation:
        """Baseline call: guard-checked, no envelope (HyperInterface overrides)."""
        return self._call_checked(state, name, args, next_affs=[])

    def _call_checked(self, state: State, name: str, args: dict,
                      next_affs: list[str]) -> Observation:
        aff = self._by[name]
        if not aff.guard(state, args):
            return Observation(ok=False,
                               text=f"ERROR: precondition violated for {name}({args})",
                               next_affordances=next_affs)
        return Observation(ok=True, text=aff.effect(state, args),
                           next_affordances=next_affs)


class FlatInterface(_Base):
    """Flat baseline: plain MCP -- every tool, always."""
    label = "flat"

    def list_tools(self, state: State, context: str) -> list[Affordance]:
        return list(self.env.affordances)


class _RetrievalBase(_Base):
    """Shared shape of the retrieval baselines: advertise the top-k tools by textual
    relevance to the running context. Subclasses supply the ranker (`_rank`); by design
    neither has any notion of state or validity -- that is the gap HyperMCP closes."""

    def __init__(self, env: Env, k: int = 3):
        super().__init__(env)
        self.k = k

    def _rank(self, query: str) -> list[str]:
        """Top-k affordance names for this query."""
        raise NotImplementedError

    def list_tools(self, state: State, context: str) -> list[Affordance]:
        top = set(self._rank(context))
        return [a for a in self.env.affordances if a.name in top]

    def offers(self, state: State, name: str, args: dict, context: str = "") -> bool:
        return name in self._rank(context)                # relevance, arg-independent


class EmbeddingRetrievalInterface(_RetrievalBase):
    """Retrieval baseline: relevance-based top-k retrieval over dense embeddings (MCP-Zero / ScaleMCP style).

    Uses OpenAI text-embedding-3-small; tool vectors are computed once per interface,
    the query (task + last observation) is embedded per step.
    """
    label = "retrieval-emb"

    def __init__(self, env: Env, k: int = 3, model: str = "text-embedding-3-small"):
        super().__init__(env, k)
        self.model = model
        self._client = None
        self._tool_vecs: dict[str, list[float]] | None = None
        self._query_cache: dict[str, list[float]] = {}

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._client is None:
            import os
            from openai import OpenAI
            self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = self._client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]

    def _rank(self, query: str) -> list[str]:
        if self._tool_vecs is None:
            docs = [f"{a.name} {a.description}" for a in self.env.affordances]
            vecs = []
            for i in range(0, len(docs), 512):          # API batch limit safety
                vecs.extend(self._embed(docs[i:i + 512]))
            self._tool_vecs = {a.name: v for a, v in zip(self.env.affordances, vecs)}
        if query not in self._query_cache:
            self._query_cache[query] = self._embed([query])[0]
        q = self._query_cache[query]
        qn = math.sqrt(sum(x * x for x in q)) or 1.0

        def cos(v):
            vn = math.sqrt(sum(x * x for x in v)) or 1.0
            return sum(a * b for a, b in zip(q, v)) / (qn * vn)

        return sorted(self._tool_vecs, key=lambda n: cos(self._tool_vecs[n]),
                      reverse=True)[:self.k]


class HyperInterface(_Base):
    """HyperMCP: a Signifier Exposure Mechanism (SEM) for MCP tool surfaces.

    The exposed affordance set is a function of BOTH environment state and agent context
    (Vachtsevanou et al.): A(s, ctx) = { a : a is applicable in s AND relevant to ctx }.
    Concrete affordance instances are advertised (parameter domains narrowed to eligible
    bindings), and results carry a next-step signifier envelope.

    Ablation switches (the two reported in the paper):
      use_context -- also condition exposure on agent context (the 2nd SEM input)
      use_pending -- also return pending signifiers (relevant, not yet applicable)
    """
    label = "hyper"
    # Conformance criterion (iv): the client selects only *advertised* instances. A batch
    # of parallel calls is selected against ONE state, but each call transitions it, so a
    # later call in the batch can become invalid (observed live: the model batched both
    # auth tools; the first authenticated, invalidating the second). A conformant
    # hypermedia client therefore follows one affordance per perceive-act cycle.
    serial_calls = True

    def __init__(self, env: Env, use_context: bool = True, use_pending: bool = True):
        super().__init__(env)
        self.use_context = use_context
        self.use_pending = use_pending

    def _ctx(self):
        return self.agent_ctx if self.use_context else None

    def list_tools(self, state: State, context: str) -> list[Affordance]:
        ctx = self._ctx()
        return [a for a in self.env.affordances
                if a.available(state) and a.relevant(ctx)]

    def offers(self, state: State, name: str, args: dict, context: str = "") -> bool:
        # Instance-level: advertised iff the binding satisfies the guard AND is ctx-relevant.
        aff = self._by[name]
        return aff.guard(state, args) and aff.relevant(self._ctx())

    def tool_specs(self, state: State, context: str) -> list[dict]:
        return [a.tool_spec(state) for a in self.list_tools(state, context)]

    def call(self, state: State, name: str, args: dict) -> Observation:
        aff = self._by[name]
        # Safety net: a conformant client only selects advertised, eligible affordances.
        if not aff.guard(state, args):
            return Observation(ok=False,
                               text=f"ERROR: precondition violated for {name}({args})",
                               next_affordances=self._envelope(state),
                               pending=self._pending(state))
        text = aff.effect(state, args)
        # Envelope AFTER the effect: results advertise the *successor* affordances
        # (conformance criterion iii -- hypermedia as the engine of application state).
        return Observation(ok=True, text=text,
                           next_affordances=self._envelope(state),
                           pending=self._pending(state),
                           signifiers=self._signifiers(state))

    def _envelope(self, state: State) -> list[str]:
        return [a.name for a in self.list_tools(state, "")]

    def _pending(self, state: State) -> list[str]:
        """Pending signifiers: goal-relevant affordances that are not applicable yet,
        with their unmet context (hmas:recommendsContext). Advertised as information,
        not as callable tools -- criterion (ii) is untouched."""
        if not self.use_pending:
            return []
        return [f"{a.name} ({a.unlock_hint})" for a in self.env.affordances
                if a.unlock_hint and a.relevant(self._ctx())
                and not a.available(state)]

    def _signifiers(self, state: State) -> list[dict]:
        """HMAS-Interaction-ontology view of the envelope (see signifiers.py): the same
        exposed affordances, rendered as signifiers for Hypermedia MAS interop."""
        return envelope(self.env.affordances, state, self._ctx(),
                        pending=self.use_pending)


INTERFACES = {"flat": FlatInterface, "retrieval-emb": EmbeddingRetrievalInterface,
              "hyper": HyperInterface}

# Named ablation variants of HyperMCP (kwargs applied at construction).
ABLATIONS = {
    "hyper-noctx": {"use_context": False},               # environment-state-only SEM
    "hyper-nopending": {"use_pending": False},           # applicability alone, no pending
}
