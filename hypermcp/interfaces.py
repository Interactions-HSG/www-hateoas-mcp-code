"""The three tool-exposure interfaces compared in the paper.

All three sit over the SAME set of affordances (env.affordances). They differ only in
what `list_tools` advertises and whether invalid calls are reachable:

  FlatInterface      (B0)  static full menu; guard enforced only by post-hoc rejection.
  RetrievalInterface (B1)  top-k by BM25 over tool text vs. the running context;
                           relevance, not validity -> can surface invalid tools.
  HyperInterface     (HyperMCP) state-scoped affordances + next-step envelope;
                           invalid calls are unreachable by construction.
"""
from __future__ import annotations
import math
import re
from .core import State, Env, Observation, Affordance, AgentContext


# --------------------------------------------------------------------------- #
# Tiny BM25 (pure python, no numpy) for the B1 retrieval baseline.
# --------------------------------------------------------------------------- #
def _tok(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class BM25:
    def __init__(self, docs: dict[str, str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.ids = list(docs)
        self.toks = {i: _tok(t) for i, t in docs.items()}
        self.dl = {i: len(t) for i, t in self.toks.items()}
        self.avgdl = (sum(self.dl.values()) / len(self.dl)) if self.dl else 0.0
        self.df: dict[str, int] = {}
        for t in self.toks.values():
            for w in set(t):
                self.df[w] = self.df.get(w, 0) + 1
        self.N = len(self.ids)

    def _idf(self, w: str) -> float:
        n = self.df.get(w, 0)
        return math.log(1 + (self.N - n + 0.5) / (n + 0.5))

    def rank(self, query: str, k: int) -> list[str]:
        q = _tok(query)
        scores = {}
        for i in self.ids:
            tf: dict[str, int] = {}
            for w in self.toks[i]:
                tf[w] = tf.get(w, 0) + 1
            s = 0.0
            for w in q:
                if w not in tf:
                    continue
                idf = self._idf(w)
                denom = tf[w] + self.k1 * (1 - self.b + self.b * self.dl[i] / (self.avgdl or 1))
                s += idf * (tf[w] * (self.k1 + 1)) / denom
            scores[i] = s
        return sorted(self.ids, key=lambda i: scores[i], reverse=True)[:k]


# --------------------------------------------------------------------------- #
# Interfaces
# --------------------------------------------------------------------------- #
class _Base:
    label = "base"

    def __init__(self, env: Env):
        self.env = env
        self._by = env.by_name()
        self.agent_ctx: AgentContext | None = None      # set per-task by the runner (SEM)

    def offers(self, state: State, name: str, args: dict, context: str = "") -> bool:
        """Is this concrete affordance *instance* (name+args) advertised to the client?"""
        return True

    def tool_specs(self, state: State, context: str) -> list[dict]:
        """Tool definitions handed to the LLM this step (baselines: state-independent)."""
        return [a.tool_spec(None) for a in self.list_tools(state, context)]

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
    """B0: vanilla MCP -- every tool, always."""
    label = "flat"

    def list_tools(self, state: State, context: str) -> list[Affordance]:
        return list(self.env.affordances)

    def call(self, state: State, name: str, args: dict) -> Observation:
        return self._call_checked(state, name, args, next_affs=[])


class RetrievalInterface(_Base):
    """B1: relevance-based top-k retrieval (MCP-Zero / ScaleMCP style)."""
    label = "retrieval"

    def __init__(self, env: Env, k: int = 3):
        super().__init__(env)
        self.k = k
        self.bm25 = BM25({a.name: f"{a.name} {a.description}" for a in env.affordances})

    def list_tools(self, state: State, context: str) -> list[Affordance]:
        top = set(self.bm25.rank(context, self.k))
        return [a for a in self.env.affordances if a.name in top]

    def offers(self, state: State, name: str, args: dict, context: str = "") -> bool:
        return name in set(self.bm25.rank(context, self.k))   # relevance, arg-independent

    def call(self, state: State, name: str, args: dict) -> Observation:
        return self._call_checked(state, name, args, next_affs=[])


class HyperInterface(_Base):
    """HyperMCP: a Signifier Exposure Mechanism (SEM) for MCP tool surfaces.

    The exposed affordance set is a function of BOTH environment state and agent context
    (Vachtsevanou et al.): A(s, ctx) = { a : a is applicable in s AND relevant to ctx }.
    Concrete affordance instances are advertised (parameter domains narrowed to eligible
    bindings), and results carry a next-step signifier envelope.

    Ablation switches isolate each design element:
      use_context  -- also condition exposure on agent context (the 2nd SEM input)
      use_enum     -- narrow parameter domains to eligible bindings in the tool schema
      use_envelope -- return the next-step affordances with each result
    """
    label = "hyper"

    def __init__(self, env: Env, use_context: bool = True, use_enum: bool = True,
                 use_envelope: bool = True):
        super().__init__(env)
        self.use_context = use_context
        self.use_enum = use_enum
        self.use_envelope = use_envelope

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
        return [a.tool_spec(state if self.use_enum else None)
                for a in self.list_tools(state, context)]

    def call(self, state: State, name: str, args: dict) -> Observation:
        aff = self._by[name]
        nxt = [a.name for a in self.list_tools(state, "")] if self.use_envelope else []
        # Safety net: a conformant client only selects advertised, eligible affordances.
        if not aff.guard(state, args):
            return Observation(ok=False,
                               text=f"ERROR: precondition violated for {name}({args})",
                               next_affordances=nxt)
        return Observation(ok=True, text=aff.effect(state, args), next_affordances=nxt)


INTERFACES = {"flat": FlatInterface, "retrieval": RetrievalInterface, "hyper": HyperInterface}

# Named ablation variants of HyperMCP (kwargs applied at construction).
ABLATIONS = {
    "hyper-noctx": {"use_context": False},               # environment-state-only SEM
    "hyper-noenum": {"use_enum": False},                 # no parameter-domain narrowing
    "hyper-noenv": {"use_envelope": False},              # no next-step signifier envelope
}
