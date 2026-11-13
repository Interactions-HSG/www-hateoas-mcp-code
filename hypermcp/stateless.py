"""HyperMCP on stateless MCP (protocol revision 2026-07-28).

The 2026-07-28 revision removes protocol-level sessions (SEP-2575, SEP-2567): `tools/list`
MUST NOT vary per connection or as a side effect of other requests, and cross-call state
lives under explicit, server-minted handles that the model passes back as tool arguments.
The session-scoped realization in `interfaces.HyperInterface` (tools/list re-scoped after
every state change, signalled by `tools/list_changed`) is therefore not available. This
module gives the second realization of A(s, c) described in the paper:

  * `tools/list` returns a state-independent CATALOG (varies only by authorization, i.e.
    the agent's abilities) that clients may cache (ttlMs / cacheScope).
  * The server keeps application state under handles. A call without a handle runs
    against the entry state; if it changes that state (authentication), the server mints
    a handle and stores the resulting state under it.
  * Every result carries an ENVELOPE: the instances of A(s', c) with the handle bound
    and enumerable parameters narrowed, plus pending signifiers. Guidance thus travels
    in the response, as under REST.
  * A conformant host presents to the model only the tools of the latest envelope
    (before the first result: the catalog's entry tools, i.e. those needing no handle).
    Server-side guards reject everything else.

Without the envelope (`use_envelope=False`), the host has nothing but the catalog, and
the server is exactly what SEP-2567 prescribes for state-dependent tools: list every
tool unconditionally, describe the dependency, reject premature calls.

`StatelessServer` and `EnvelopeHost` are transport-independent; `StatelessHyperInterface`
composes them in process for the harness, and `mcp_transport.py` puts them on the wire.
"""
from __future__ import annotations
import copy
import secrets
from dataclasses import dataclass, field
from .core import Env, State, Observation, AgentContext, Affordance, clone
from .interfaces import _Base
from .signifiers import envelope as signifier_envelope

HANDLE = "handle"
HANDLE_PREFIX = "hdl_"


def _handle_property(values: list[str] | None = None) -> dict:
    spec = {"type": "string",
            "description": "State handle returned by an earlier call (e.g. after "
                           "authentication); identifies the interaction's state."}
    if values:
        spec["enum"] = values                            # handle bound (narrowed)
    return spec


def _with_handle(spec: dict, values: list[str] | None, required: bool) -> dict:
    spec = copy.deepcopy(spec)
    schema = spec["input_schema"]
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})[HANDLE] = _handle_property(values)
    if required:
        schema["required"] = [HANDLE] + [r for r in schema.get("required", [])
                                         if r != HANDLE]
    return spec


def requires_handle(spec: dict) -> bool:
    return HANDLE in spec["input_schema"].get("required", [])


@dataclass
class CallResult:
    """A tools/call result as the stateless server produces it (transport-independent)."""
    ok: bool
    text: str
    handle: str | None = None                            # handle the call ran under / minted
    minted: bool = False
    # Envelope (None when the server sends none): tool definitions of the instances of
    # A(s', c) with the handle bound, the pending signifiers, and the signifier view.
    envelope: list[dict] | None = None
    pending: list[str] = field(default_factory=list)
    signifiers: list[dict] = field(default_factory=list)


class StatelessServer:
    """Server side of the stateless realization: catalog, handle store, envelope."""

    def __init__(self, env: Env, entry_state: State, use_envelope: bool = True):
        self.env = env
        self._by = env.by_name()
        self.entry = clone(entry_state)                  # never mutated
        self.store: dict[str, State] = {}
        self.last_handle: str | None = None              # for the evaluator only
        self.use_envelope = use_envelope
        # Entry affordances are applicable without any interaction state; they take an
        # optional handle. Every other affordance requires one. This depends only on the
        # server's entry state, not on any client, so the catalog stays cacheable.
        self.entry_names = {a.name for a in env.affordances if a.available(self.entry)}

    # -- tools/list ------------------------------------------------------------------ #
    def catalog(self, abilities: set[str] | None = None) -> list[dict]:
        """State-independent tool list, in a deterministic order. May vary by the
        authorization presented (here: the agent's abilities), never by state."""
        return [_with_handle(a.tool_spec(None), None,
                             required=a.name not in self.entry_names)
                for a in self.env.affordances
                if abilities is None or a.name in abilities]

    # -- tools/call ------------------------------------------------------------------ #
    def exposed(self, state: State, ctx: AgentContext | None) -> list[Affordance]:
        """A(s, c): applicable and context-relevant affordances."""
        return [a for a in self.env.affordances
                if a.available(state) and a.relevant(ctx)]

    def _envelope(self, state: State, handle: str | None,
                  ctx: AgentContext | None) -> tuple[list[dict] | None, list[str], list[dict]]:
        if not self.use_envelope:
            return None, [], []
        tools = []
        for a in self.exposed(state, ctx):
            spec = a.tool_spec(state)
            tools.append(_with_handle(spec, [handle], required=True) if handle else spec)
        pending = [f"{a.name} ({a.unlock_hint})" for a in self.env.affordances
                   if a.unlock_hint and a.relevant(ctx) and not a.available(state)]
        return tools, pending, signifier_envelope(self.env.affordances, state, ctx)

    def _error(self, text: str, state: State | None, handle: str | None,
               ctx: AgentContext | None) -> CallResult:
        env_tools, pending, sigs = (self._envelope(state, handle, ctx) if state is not None
                                    else (None, [], []))
        return CallResult(False, f"ERROR: {text}", handle, envelope=env_tools,
                          pending=pending, signifiers=sigs)

    def call(self, name: str, args: dict, ctx: AgentContext | None = None) -> CallResult:
        args = dict(args or {})
        handle = args.pop(HANDLE, None)
        aff = self._by.get(name)
        if aff is None:
            return self._error(f"unknown tool {name}", None, None, ctx)
        if handle is None:
            if name not in self.entry_names:
                return self._error(
                    f"{name} requires a state handle; obtain one by authenticating first",
                    self.entry, None, ctx)
            state = clone(self.entry)                    # a fresh interaction
        elif handle in self.store:
            state = self.store[handle]
        else:
            return self._error(f"state handle {handle!r} is unknown or has expired; "
                               "authenticate again to obtain a new one", None, None, ctx)

        if not aff.guard(state, args):
            return self._error(f"precondition violated for {name}({args})",
                               state, handle, ctx)
        text = aff.effect(state, args)
        minted = False
        if handle is None and state != self.entry:      # the call created interaction state
            handle = HANDLE_PREFIX + secrets.token_urlsafe(16)   # opaque, 128 bits
            self.store[handle] = state
            minted = True
            text += (f"\n[state handle: {handle} -- pass it as `{HANDLE}` "
                     "to subsequent calls]")
        if handle is not None:
            self.last_handle = handle
        env_tools, pending, sigs = self._envelope(state, handle, ctx)
        return CallResult(True, text, handle, minted, env_tools, pending, sigs)

    def current_state(self) -> State:
        """Evaluator access (not part of the protocol): the state of the most recently
        used handle, or the entry state if none was created."""
        return self.store.get(self.last_handle, self.entry) if self.last_handle \
            else self.entry


class EnvelopeHost:
    """Host side: which tools the model sees. Before any result, the catalog's entry
    tools; afterwards, the tools of the latest envelope (restricted to the catalog).
    Without envelopes (SEP-2567 server), the whole catalog."""

    def __init__(self, catalog: list[dict], use_envelope: bool = True):
        self.catalog = catalog
        self._names = {t["name"] for t in catalog}
        self.use_envelope = use_envelope
        self.presented = ([t for t in catalog if not requires_handle(t)]
                          if use_envelope else list(catalog))

    def absorb(self, envelope: list[dict] | None) -> None:
        if self.use_envelope and envelope is not None:
            self.presented = [t for t in envelope if t["name"] in self._names]


class StatelessHyperInterface(_Base):
    """In-process harness interface for the stateless realization (server + host).

    The harness hands every call the episode's entry state; this interface keeps the
    interaction state server-side under handles instead and exposes it to the evaluator
    through `current_state`."""
    label = "hyper-stateless"
    serial_calls = True                                  # conformance criterion (iv)

    def __init__(self, env: Env, use_envelope: bool = True):
        super().__init__(env)
        self.use_envelope = use_envelope
        self._episode: State | None = None
        self.server: StatelessServer | None = None
        self.host: EnvelopeHost | None = None

    def _ensure(self, state: State) -> None:
        if self._episode is not state:                   # new episode: fresh server/host
            self._episode = state
            self.server = StatelessServer(self.env, state, self.use_envelope)
            abilities = self.agent_ctx.abilities if self.agent_ctx else None
            self.host = EnvelopeHost(self.server.catalog(abilities), self.use_envelope)

    def tool_specs(self, state: State, context: str) -> list[dict]:
        self._ensure(state)
        return list(self.host.presented)

    def list_tools(self, state: State, context: str) -> list[Affordance]:
        return [self._by[t["name"]] for t in self.tool_specs(state, context)]

    def offers(self, state: State, name: str, args: dict, context: str = "") -> bool:
        self._ensure(state)
        spec = next((t for t in self.host.presented if t["name"] == name), None)
        if spec is None:
            return False
        args = dict(args)
        handle = args.pop(HANDLE, None)
        allowed = spec["input_schema"].get("properties", {}).get(HANDLE, {}).get("enum")
        if allowed and handle not in allowed:
            return False
        s = self.server.store.get(handle, self.server.entry) if handle else \
            self.server.entry
        return self._by[name].guard(s, args)

    def call(self, state: State, name: str, args: dict) -> Observation:
        self._ensure(state)
        r = self.server.call(name, args, self.agent_ctx)
        self.host.absorb(r.envelope)
        return observation(r)

    def current_state(self, state: State) -> State:
        self._ensure(state)
        return self.server.current_state()


def observation(r: CallResult) -> Observation:
    """Render a stateless CallResult in the harness's Observation shape (the envelope's
    tool names become the `[next valid actions: ...]` hint, as under the session
    realization, so the text the model reads is comparable across realizations)."""
    return Observation(ok=r.ok, text=r.text,
                       next_affordances=[t["name"] for t in (r.envelope or [])],
                       pending=list(r.pending), signifiers=list(r.signifiers))
