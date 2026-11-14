"""Agents that drive an interface to complete a task.

- run_scripted: deterministic, no API key. Authenticates if required, then attempts the
  task's intended action iff the interface makes it visible. Exercises the full pipeline
  and reproduces the mechanism-level difference (illegal calls, menu size, blocking).
- OpenAIAgent: an LLM tool-calling loop over OpenAI's Chat Completions API
  (gpt-4o-mini in the paper). At every step the model sees only the tools the interface
  advertises in the current state; under HyperMCP it calls one tool per step.
- OpenAIResponsesAgent: the same loop over the Responses API, for reasoning models that
  reject function tools on Chat Completions (gpt-6.1-sol in the paper).

Both LLM agents end an episode when the model answers without calling a tool. If the
model stops before the task is done (e.g., to ask a clarifying question) and the task
defines `user_reply`, they give that reply once and continue; the harness has no user
simulator otherwise.
"""
from __future__ import annotations
import json
import os
import re
from .core import Env, Task, State, Observation
from .metrics import RunResult


# --------------------------------------------------------------------------- #
# Helpers shared by all agents (scripted and LLM).
# --------------------------------------------------------------------------- #
def _start(interface, task: Task, model: str) -> tuple[State, RunResult]:
    """Fresh state + run record; hands the task's agent context to the interface (SEM)."""
    interface.agent_ctx = task.agent_ctx
    return task.init(), RunResult(task.id, interface.label, model, success=False)


def _execute(interface, state: State, res: RunResult, name: str,
             args: dict) -> Observation:
    """Execute one tool call and record it in the run metrics."""
    res.steps += 1
    obs = interface.call(state, name, args)
    res.calls.append({"tool": name, "args": args, "ok": obs.ok})
    if not obs.ok:
        res.illegal_calls += 1
    return obs


def _wants_user_reply(task: Task, interface, state: State, res: RunResult) -> bool:
    """Give the task's scripted user reply once, if the model stopped (e.g., to ask a
    clarifying question) before the task was done. Stands in for a user simulator."""
    if task.user_reply and res.user_replies == 0 \
            and not task.goal(interface.current_state(state)):
        res.user_replies += 1
        return True
    return False


def _result_text(obs: Observation) -> str:
    """The tool-result content handed back to the model: the observation plus, under
    HyperMCP, the signifier envelope (next-step and pending affordances). Any LLM loop
    MUST use this so the envelope rendering cannot drift between providers."""
    content = obs.text
    if obs.next_affordances:
        content += f"\n[next valid actions: {', '.join(obs.next_affordances)}]"
    if obs.pending:
        content += f"\n[not yet available: {'; '.join(obs.pending)}]"
    return content


# --------------------------------------------------------------------------- #
# Scripted agent (no key) -- pipeline smoke test.
# --------------------------------------------------------------------------- #
_HANDLE_RE = re.compile(r"\[state handle: (\S+)")


def _bind_handle(interface, state: State, name: str, args: dict, context: str,
                 known: str | None) -> dict:
    """Stateless mapping: supply the state handle. A conformant client fills a
    parameter the advertisement has bound to a single value (enum of length one); without
    an envelope, it threads the handle it last received, as a model would."""
    if "handle" in args:
        return args
    spec = next((s for s in interface.tool_specs(state, context) if s["name"] == name),
                None)
    prop = (spec or {}).get("input_schema", {}).get("properties", {}).get("handle")
    if prop is None:
        return args
    enum = prop.get("enum")
    if enum and len(enum) == 1:
        return {**args, "handle": enum[0]}
    return {**args, "handle": known} if known else args


def run_scripted(interface, env: Env, task: Task, max_steps: int = 8) -> RunResult:
    state, res = _start(interface, task, "scripted")
    intents = list(task.scripted_intent)
    handle = None                     # stateless mapping: last handle received

    for _ in range(max_steps):
        visible = [a.name for a in interface.list_tools(state, task.instruction)]
        res.menu_sizes.append(len(visible))

        # 1) authenticate first if needed and possible
        if interface.current_state(state).authenticated_user is None:
            auth = next((a for a in interface.list_tools(state, task.instruction)
                         if a.rel == "authenticate"), None)
            if auth is not None:
                obs = _execute(interface, state, res, auth.name,
                               state.scratch.get("creds", {}))
                m = _HANDLE_RE.search(obs.text)
                handle = m.group(1) if m else handle
                continue
            # auth prerequisite not advertised (e.g. Retrieval returned only action tools)
            res.blocked += 1
            break

        # 2) pursue the next intended action
        if not intents:
            break
        name, args = intents[0]
        args = _bind_handle(interface, state, name, args, task.instruction, handle)
        # A conformant client selects only among ADVERTISED tools (what the LLM sees),
        # and only instances the interface offers. `name not in visible` also catches
        # env bugs where a solvable action is never advertised.
        if name not in visible or not interface.offers(state, name, args,
                                                       task.instruction):
            res.blocked += 1          # not advertised: retrieval dropped it, or Hyper
            break                     # deems this instance invalid in the current state
        _execute(interface, state, res, name, args)
        intents.pop(0)

    res.success = task.goal(interface.current_state(state))
    return res


# --------------------------------------------------------------------------- #
# Shared helpers for LLM agents
# --------------------------------------------------------------------------- #
def _system_prompt(env: Env) -> str:
    base = (f"{env.persona} Fulfil the user's request by calling the "
            "available tools. Only call a tool when its use is appropriate.")
    # The policy is given to every interface, as in the paper.
    return f"{base}\n\nPOLICY:\n{env.policy}" if env.policy else base


def _context(task: Task, last_obs: str) -> str:
    return f"{task.instruction} {last_obs}".strip()


# --------------------------------------------------------------------------- #
# OpenAI tool-calling loop
# --------------------------------------------------------------------------- #
class OpenAIAgent:
    def __init__(self, model: str, max_tokens: int = 1024):
        from openai import OpenAI
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "x"))
        self.model = model
        self.max_tokens = max_tokens

    def _tools(self, interface, state, ctx):
        specs = interface.tool_specs(state, ctx)
        return [{"type": "function",
                 "function": {"name": s["name"], "description": s["description"],
                              "parameters": s["input_schema"]}} for s in specs], len(specs)

    def run(self, interface, env: Env, task: Task, max_steps: int = 8) -> RunResult:
        state, res = _start(interface, task, self.model)
        messages = [{"role": "system", "content": _system_prompt(env)},
                    {"role": "user", "content": task.instruction}]
        last_obs = ""

        for _ in range(max_steps):
            tools, n = self._tools(interface, state, _context(task, last_obs))
            res.menu_sizes.append(n)
            kwargs = dict(model=self.model, max_tokens=self.max_tokens, messages=messages)
            if tools:                                    # OpenAI rejects an empty tools list
                kwargs["tools"] = tools
                if interface.serial_calls:
                    # Conformant hypermedia client: one affordance per perceive-act cycle.
                    kwargs["parallel_tool_calls"] = False
            resp = self.client.chat.completions.create(**kwargs)
            if resp.usage:
                res.prompt_tokens += resp.usage.prompt_tokens
                res.completion_tokens += resp.usage.completion_tokens
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                if _wants_user_reply(task, interface, state, res):
                    messages.append({"role": "user", "content": task.user_reply})
                    continue
                break
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                obs = _execute(interface, state, res, tc.function.name, args)
                last_obs = obs.text
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": _result_text(obs)})

        res.success = task.goal(interface.current_state(state))
        return res


# --------------------------------------------------------------------------- #
# OpenAI Responses API loop (reasoning models, e.g. gpt-6.1-sol, which reject
# function tools combined with reasoning on /v1/chat/completions)
# --------------------------------------------------------------------------- #
class OpenAIResponsesAgent:
    """Same perceive-act loop as OpenAIAgent, over /v1/responses at the model's
    default reasoning effort. The conversation is threaded server-side via
    previous_response_id, so reasoning items carry over between steps; the advertised
    tools are re-sent at every step, as in OpenAIAgent. Token counts include
    reasoning tokens (reported by the API as output tokens)."""

    def __init__(self, model: str, max_output_tokens: int = 8000):
        from openai import OpenAI
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "x"))
        self.model = model
        self.max_output_tokens = max_output_tokens

    def _tools(self, interface, state, ctx):
        specs = interface.tool_specs(state, ctx)
        return [{"type": "function", "name": s["name"], "description": s["description"],
                 "parameters": s["input_schema"]} for s in specs], len(specs)

    def run(self, interface, env: Env, task: Task, max_steps: int = 8) -> RunResult:
        state, res = _start(interface, task, self.model)
        instructions = _system_prompt(env)
        pending = [{"role": "user", "content": task.instruction}]
        previous = None
        last_obs = ""

        for _ in range(max_steps):
            tools, n = self._tools(interface, state, _context(task, last_obs))
            res.menu_sizes.append(n)
            kwargs = dict(model=self.model, instructions=instructions, input=pending,
                          max_output_tokens=self.max_output_tokens)
            if previous:
                kwargs["previous_response_id"] = previous
            if tools:
                kwargs["tools"] = tools
                if interface.serial_calls:
                    kwargs["parallel_tool_calls"] = False
            resp = self.client.responses.create(**kwargs)
            previous = resp.id
            if resp.usage:
                res.prompt_tokens += resp.usage.input_tokens
                res.completion_tokens += resp.usage.output_tokens
            calls = [o for o in resp.output if o.type == "function_call"]
            if not calls:
                if _wants_user_reply(task, interface, state, res):
                    pending = [{"role": "user", "content": task.user_reply}]
                    continue
                break
            pending = []
            for fc in calls:
                args = json.loads(fc.arguments or "{}")
                obs = _execute(interface, state, res, fc.name, args)
                last_obs = obs.text
                pending.append({"type": "function_call_output", "call_id": fc.call_id,
                                "output": _result_text(obs)})

        res.success = task.goal(interface.current_state(state))
        return res
