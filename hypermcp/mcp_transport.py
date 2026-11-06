"""HyperMCP over a real MCP transport (official Python SDK, Streamable HTTP).

Both realizations of A(s, c) from the paper, each on the protocol revision it targets:

  hyper            session realization, protocol 2025-11-25 (initialize handshake,
                   Mcp-Session-Id). The server keeps one application state per session;
                   tools/list returns A(s, c) for that session; after a call that changes
                   the advertised set, the server emits notifications/tools/list_changed
                   (request-scoped, so it precedes the result) and the host re-lists.
  hyper-stateless  stateless realization, protocol 2026-07-28 (no handshake, no session).
                   tools/list returns the cacheable catalog (ttlMs/cacheScope); state
                   lives under handles; each CallToolResult carries the envelope in
                   `_meta["io.hypermcp/envelope"]`; the host presents the envelope's tools.
  hyper-stateless-noenv
                   2026-07-28 server without envelope = SEP-2567 guidance (catalog only).

The host asserts the agent context c on every request in `_meta["io.hypermcp/
agentContext"]` (a stand-in for authorization claims), so the server needs no session
for it. One server is started per episode on a free localhost port; the evaluator reads
the server's state in process to score the task goal (not part of the protocol).

`MCPInterface` exposes the harness interface API (list_tools / tool_specs / offers /
call / current_state), so `agents.run_scripted` and `agents.OpenAIAgent` run over the
wire unchanged. Retrieval baselines are host-side and are not wrapped.
"""
from __future__ import annotations
import asyncio
import concurrent.futures
import socket
import threading
from typing import Any, Callable

import mcp_types as types
import uvicorn
from mcp import Client
from mcp.server import Server
from mcp.server.caching import CacheHint
from mcp.server.lowlevel.server import NotificationOptions

from .core import Env, State, Observation, AgentContext, Affordance, clone
from .interfaces import HyperInterface
from .stateless import StatelessServer, EnvelopeHost, CallResult, observation

SESSION_PROTOCOL = "2025-11-25"
STATELESS_PROTOCOL = "2026-07-28"
CTX_KEY = "io.hypermcp/agentContext"
ENVELOPE_KEY = "io.hypermcp/envelope"
CATALOG_TTL_MS = 300_000
NOTIFICATION_SETTLE_S = 0.05
VARIANTS = ("hyper", "hyper-stateless", "hyper-stateless-noenv")


# --------------------------------------------------------------------------- #
# Wire helpers
# --------------------------------------------------------------------------- #
def ctx_to_meta(ctx: AgentContext | None) -> dict:
    if ctx is None:
        return {}
    goals = ctx.goals()
    return {CTX_KEY: {"goal": sorted(goals) if goals is not None else None,
                      "abilities": sorted(ctx.abilities) if ctx.abilities else None}}


def ctx_from_meta(meta: Any) -> AgentContext | None:
    raw = (meta or {}).get(CTX_KEY) if isinstance(meta, dict) else None
    if raw is None:
        return None
    goal = raw.get("goal")
    abilities = raw.get("abilities")
    return AgentContext(goal=set(goal) if goal is not None else None,
                        abilities=set(abilities) if abilities is not None else None)


def _tool(spec: dict) -> types.Tool:
    return types.Tool(name=spec["name"], description=spec["description"],
                      input_schema=spec["input_schema"])


def _spec(tool: types.Tool) -> dict:
    return {"name": tool.name, "description": tool.description or "",
            "input_schema": dict(tool.input_schema)}


def _text(result: types.CallToolResult) -> str:
    return "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")


# --------------------------------------------------------------------------- #
# Servers
# --------------------------------------------------------------------------- #
class SessionHyperServer:
    """Session realization on 2025-11-25: one HyperInterface state per MCP session."""

    def __init__(self, env: Env, entry_state: State):
        self.env = env
        self.entry = clone(entry_state)
        self.sessions: dict[str, tuple[HyperInterface, State]] = {}
        self.last: State | None = None
        self.server = Server("hypermcp-session", version="0.1",
                             on_list_tools=self._list_tools, on_call_tool=self._call_tool)
        self.init_options = self.server.create_initialization_options(
            NotificationOptions(tools_changed=True))

    @staticmethod
    def _session_key(ctx) -> str:
        """The MCP session: the Mcp-Session-Id header on HTTP; otherwise the connection."""
        headers = getattr(ctx.request, "headers", None)
        sid = headers.get("mcp-session-id") if headers is not None else None
        return sid or f"conn-{id(ctx.session._connection)}"

    def _session(self, ctx) -> tuple[HyperInterface, State]:
        key = self._session_key(ctx)
        if key not in self.sessions:
            self.sessions[key] = (HyperInterface(self.env), clone(self.entry))
        iface, state = self.sessions[key]
        iface.agent_ctx = ctx_from_meta(ctx.meta)
        return iface, state

    async def _list_tools(self, ctx, params) -> types.ListToolsResult:
        iface, state = self._session(ctx)
        return types.ListToolsResult(tools=[_tool(s) for s in iface.tool_specs(state, "")])

    async def _call_tool(self, ctx, params) -> types.CallToolResult:
        iface, state = self._session(ctx)
        before = iface.tool_specs(state, "")
        obs = iface.call(state, params.name, dict(params.arguments or {}))
        self.last = state
        if iface.tool_specs(state, "") != before:
            # Request-scoped: delivered on this call's response stream, before the result.
            await ctx.session.send_notification(types.ToolListChangedNotification(),
                                                related_request_id=ctx.request_id)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=obs.text)], is_error=not obs.ok,
            _meta={ENVELOPE_KEY: {"next": obs.next_affordances, "pending": obs.pending}})

    def current_state(self) -> State:
        return self.last if self.last is not None else self.entry


class StatelessHyperServer:
    """Stateless realization on 2026-07-28 around `stateless.StatelessServer`."""

    def __init__(self, env: Env, entry_state: State, use_envelope: bool = True):
        self.core = StatelessServer(env, entry_state, use_envelope=use_envelope)
        self.server = Server(
            "hypermcp-stateless", version="0.1",
            on_list_tools=self._list_tools, on_call_tool=self._call_tool,
            cache_hints={"tools/list": CacheHint(ttl_ms=CATALOG_TTL_MS, scope="public")})
        self.init_options = self.server.create_initialization_options()

    async def _list_tools(self, ctx, params) -> types.ListToolsResult:
        c = ctx_from_meta(ctx.meta)
        return types.ListToolsResult(
            tools=[_tool(s) for s in self.core.catalog(c.abilities if c else None)])

    async def _call_tool(self, ctx, params) -> types.CallToolResult:
        r = self.core.call(params.name, dict(params.arguments or {}),
                           ctx_from_meta(ctx.meta))
        meta = {}
        if r.envelope is not None:
            meta[ENVELOPE_KEY] = {"tools": r.envelope, "pending": r.pending,
                                  "signifiers": r.signifiers}
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=r.text)], is_error=not r.ok,
            _meta=meta or None)

    def current_state(self) -> State:
        return self.core.current_state()


def build_server(variant: str, env: Env, entry_state: State):
    if variant == "hyper":
        return SessionHyperServer(env, entry_state)
    if variant == "hyper-stateless":
        return StatelessHyperServer(env, entry_state)
    if variant == "hyper-stateless-noenv":
        return StatelessHyperServer(env, entry_state, use_envelope=False)
    raise ValueError(f"no MCP server for interface {variant!r}; choose from {VARIANTS}")


class HTTPServing:
    """Serve an MCP Server over Streamable HTTP on a free localhost port (own thread)."""

    def __init__(self, server: Server):
        app = server.streamable_http_app()
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}/mcp"
        self._uv = uvicorn.Server(uvicorn.Config(app, log_level="warning",
                                                 lifespan="on"))
        self._thread = threading.Thread(
            target=lambda: asyncio.run(self._uv.serve(sockets=[self.sock])), daemon=True)
        self._thread.start()
        while not self._uv.started:
            if not self._thread.is_alive():
                raise RuntimeError("MCP HTTP server failed to start")
            threading.Event().wait(0.01)

    def close(self) -> None:
        self._uv.should_exit = True
        self._thread.join(timeout=10)
        self.sock.close()


# --------------------------------------------------------------------------- #
# Host (client side), driven synchronously by the harness agents
# --------------------------------------------------------------------------- #
class _ClientWorker:
    """Owns an MCP Client in one long-lived asyncio task (anyio scopes must be entered
    and exited in the same task); the harness submits coroutines to it."""

    def __init__(self, url: str, mode: str, on_message: Callable | None):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._q: asyncio.Queue | None = None
        ready: concurrent.futures.Future = concurrent.futures.Future()
        self._main = asyncio.run_coroutine_threadsafe(
            self._run(url, mode, on_message, ready), self._loop)
        ready.result(timeout=30)

    async def _run(self, url, mode, on_message, ready) -> None:
        self._q = asyncio.Queue()
        try:
            async with Client(url, mode=mode, message_handler=on_message,
                              client_info=types.Implementation(name="hypermcp-host",
                                                               version="0.1")) as client:
                ready.set_result(None)
                while True:
                    fn, fut = await self._q.get()
                    if fn is None:
                        break
                    try:
                        fut.set_result(await fn(client))
                    except Exception as e:                # surfaced to the caller
                        fut.set_exception(e)
        except Exception as e:
            if not ready.done():
                ready.set_exception(e)
            raise

    def submit(self, fn) -> Any:
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(self._q.put_nowait, (fn, fut))
        return fut.result(timeout=120)

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._q.put_nowait, (None, None))
        try:
            self._main.result(timeout=10)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=10)


class MCPInterface:
    """Harness interface whose tools live behind a real MCP server over HTTP.

    One server + client per episode (the harness hands each episode a fresh entry
    state). `variant` selects the realization (see module docstring)."""

    def __init__(self, env: Env, variant: str = "hyper-stateless"):
        if variant not in VARIANTS:
            raise ValueError(f"unknown MCP variant {variant!r}")
        self.env = env
        self._by = env.by_name()
        self.variant = variant
        self.label = f"{variant}@mcp"
        self.serial_calls = True                         # conformance criterion (iv)
        self.agent_ctx: AgentContext | None = None
        self.protocol = SESSION_PROTOCOL if variant == "hyper" else STATELESS_PROTOCOL
        self._episode: State | None = None
        self._backend = None
        self._http: HTTPServing | None = None
        self._worker: _ClientWorker | None = None
        self.presented: list[dict] = []
        self._host: EnvelopeHost | None = None
        self._dirty = False

    # -- lifecycle ----------------------------------------------------------------- #
    def _ensure(self, state: State) -> None:
        if self._episode is state:
            return
        self.close()
        self._episode = state
        self._backend = build_server(self.variant, self.env, state)
        self._http = HTTPServing(self._backend.server)
        mode = "legacy" if self.protocol == SESSION_PROTOCOL else self.protocol
        self._worker = _ClientWorker(self._http.url, mode, self._on_message)
        if self.protocol == SESSION_PROTOCOL:
            self.presented = self._list()
            self._host = None
        else:
            self._host = EnvelopeHost(self._list(), self.variant == "hyper-stateless")
            self.presented = self._host.presented

    def close(self) -> None:
        if self._worker is not None:
            self._worker.close()
            self._worker = None
        if self._http is not None:
            self._http.close()
            self._http = None

    async def _on_message(self, message) -> None:
        root = getattr(message, "root", message)
        if isinstance(root, types.ToolListChangedNotification):
            self._dirty = True

    # -- protocol ------------------------------------------------------------------- #
    def _meta(self) -> dict:
        return ctx_to_meta(self.agent_ctx)

    def _list(self) -> list[dict]:
        # Session era: the list depends on the session and the asserted context, so the
        # context is sent and nothing is cached. Stateless era: the catalog depends on
        # neither and the SDK's response cache honors the server's ttlMs/cacheScope.
        meta = self._meta() if self.protocol == SESSION_PROTOCOL else None
        mode = "refresh" if self.protocol == SESSION_PROTOCOL else "use"
        res = self._worker.submit(lambda c: c.list_tools(meta=meta or None,
                                                         cache_mode=mode))
        return [_spec(t) for t in res.tools]

    def _call(self, name: str, args: dict) -> types.CallToolResult:
        meta = self._meta() or None
        return self._worker.submit(lambda c: c.call_tool(name, args, meta=meta))

    def request(self, fn) -> Any:
        """Run `await fn(client)` on this episode's MCP client (for tests and probes)."""
        return self._worker.submit(fn)

    @property
    def list_changed_seen(self) -> bool:
        """Whether a tools/list_changed notification arrived since the last call."""
        return self._dirty

    # -- harness interface API ------------------------------------------------------ #
    def tool_specs(self, state: State, context: str) -> list[dict]:
        self._ensure(state)
        return list(self.presented)

    def list_tools(self, state: State, context: str) -> list[Affordance]:
        return [self._by[t["name"]] for t in self.tool_specs(state, context)]

    def offers(self, state: State, name: str, args: dict, context: str = "") -> bool:
        """Scripted oracle only: advertised, and the guard holds in the server's state."""
        self._ensure(state)
        if name not in {t["name"] for t in self.presented}:
            return False
        args = {k: v for k, v in args.items() if k != "handle"}
        return self._by[name].guard(self.current_state(state), args)

    def call(self, state: State, name: str, args: dict) -> Observation:
        self._ensure(state)
        self._dirty = False
        try:
            res = self._call(name, args)
        except Exception as e:                            # protocol-level error
            return Observation(ok=False, text=f"ERROR: {e}")
        meta = (res.meta or {}).get(ENVELOPE_KEY)
        if self.protocol == SESSION_PROTOCOL:
            # The notification precedes the result on the response stream, but the SDK
            # dispatches it in its own task; let the client loop settle before checking.
            self._worker.submit(lambda c: asyncio.sleep(NOTIFICATION_SETTLE_S))
            if self._dirty:                               # tools/list_changed received
                self.presented = self._list()
            return Observation(ok=not res.is_error, text=_text(res),
                               next_affordances=(meta or {}).get("next", []),
                               pending=(meta or {}).get("pending", []))
        r = CallResult(ok=not res.is_error, text=_text(res),
                       envelope=meta["tools"] if meta else None,
                       pending=meta["pending"] if meta else [],
                       signifiers=meta["signifiers"] if meta else [])
        self._host.absorb(r.envelope)
        self.presented = self._host.presented
        return observation(r)

    def current_state(self, state: State) -> State:
        self._ensure(state)
        return self._backend.current_state()
