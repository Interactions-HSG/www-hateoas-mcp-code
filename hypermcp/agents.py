"""Agents that drive an interface to complete a task.

- run_scripted: deterministic, no API key. Authenticates if required, then attempts the
  task's intended action iff the interface makes it visible. Exercises the full pipeline
  and reproduces the mechanism-level difference (illegal calls, menu size, blocking).
- AnthropicAgent / OpenAIAgent: real LLM tool-calling loops (gated on an API key), where
  the model re-reads the advertised tools each step. This is where the paper's headline
  numbers come from.
"""
from __future__ import annotations
import json
import os
from .core import Env, Task, State
from .metrics import RunResult


# --------------------------------------------------------------------------- #
# Scripted agent (no key) -- pipeline smoke test.
# --------------------------------------------------------------------------- #
def run_scripted(interface, env: Env, task: Task, max_steps: int = 8) -> RunResult:
    state = task.init()
    interface.agent_ctx = task.agent_ctx                 # SEM: expose per agent context
    res = RunResult(task.id, interface.label, "scripted", success=False)
    intents = list(task.scripted_intent)

    for _ in range(max_steps):
        visible = [a.name for a in interface.list_tools(state, task.instruction)]
        res.menu_sizes.append(len(visible))

        # 1) authenticate first if needed and possible
        if state.authenticated_user is None:
            auth = next((a for a in interface.list_tools(state, task.instruction)
                         if a.rel == "authenticate"), None)
            if auth is not None:
                res.steps += 1
                creds = state.scratch.get("creds", {})
                obs = interface.call(state, auth.name, creds)
                res.calls.append({"tool": auth.name, "args": creds, "ok": obs.ok})
                if not obs.ok:
                    res.illegal_calls += 1
                continue
            # auth prerequisite not advertised (e.g. B1 retrieved only action tools)
            res.blocked += 1
            break

        # 2) pursue the next intended action
        if not intents:
            break
        name, args = intents[0]
        # A conformant client selects only among ADVERTISED tools (what the LLM sees),
        # and only instances the interface offers. `name not in visible` also catches
        # env bugs where a solvable action is never advertised.
        if name not in visible or not interface.offers(state, name, args,
                                                       task.instruction):
            res.blocked += 1          # not advertised: retrieval dropped it, or Hyper
            break                     # deems this instance invalid in the current state
        res.steps += 1
        obs = interface.call(state, name, args)
        res.calls.append({"tool": name, "args": args, "ok": obs.ok})
        if not obs.ok:
            res.illegal_calls += 1
        intents.pop(0)

    res.success = task.goal(state)
    return res


# --------------------------------------------------------------------------- #
# Shared helpers for LLM agents
# --------------------------------------------------------------------------- #
def _system_prompt(env: Env) -> str:
    base = (f"{env.persona} Fulfil the user's request by calling the "
            "available tools. Only call a tool when its use is appropriate.")
    # HyperMCP's claim: the SEM makes the textual policy unnecessary (validity is
    # structural). When env.policy is empty (--no-policy), the agent gets no rules text.
    return f"{base}\n\nPOLICY:\n{env.policy}" if env.policy else base


def _context(task: Task, last_obs: str) -> str:
    return f"{task.instruction} {last_obs}".strip()


# --------------------------------------------------------------------------- #
# Anthropic tool-calling loop
# --------------------------------------------------------------------------- #
class AnthropicAgent:
    def __init__(self, model: str = "claude-opus-4-8", max_tokens: int = 1024):
        from anthropic import Anthropic
        self.client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = model
        self.max_tokens = max_tokens

    def run(self, interface, env: Env, task: Task, max_steps: int = 8) -> RunResult:
        state = task.init()
        interface.agent_ctx = task.agent_ctx             # SEM: expose per agent context
        res = RunResult(task.id, interface.label, self.model, success=False)
        messages = [{"role": "user", "content": task.instruction}]
        last_obs = ""

        for _ in range(max_steps):
            tools = interface.tool_specs(state, _context(task, last_obs))
            res.menu_sizes.append(len(tools))
            kwargs = {}
            if tools and getattr(interface, "serial_calls", False):
                # Conformant hypermedia client: one affordance per perceive-act cycle.
                kwargs["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
            resp = self.client.messages.create(
                model=self.model, max_tokens=self.max_tokens,
                system=_system_prompt(env), tools=tools, messages=messages, **kwargs)
            res.prompt_tokens += resp.usage.input_tokens
            res.completion_tokens += resp.usage.output_tokens
            messages.append({"role": "assistant", "content": resp.content})

            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if not tool_uses:
                break
            results = []
            for tu in tool_uses:
                res.steps += 1
                obs = interface.call(state, tu.name, dict(tu.input))
                res.calls.append({"tool": tu.name, "args": dict(tu.input), "ok": obs.ok})
                if not obs.ok:
                    res.illegal_calls += 1
                last_obs = obs.text
                content = obs.text
                if obs.next_affordances:
                    content += f"\n[next valid actions: {', '.join(obs.next_affordances)}]"
                if obs.pending:
                    content += f"\n[not yet available: {'; '.join(obs.pending)}]"
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": content, "is_error": not obs.ok})
            messages.append({"role": "user", "content": results})

        res.success = task.goal(state)
        return res


# --------------------------------------------------------------------------- #
# OpenAI-compatible tool-calling loop (for open models via an OpenAI-style endpoint)
# --------------------------------------------------------------------------- #
class OpenAIAgent:
    def __init__(self, model: str, base_url: str | None = None, max_tokens: int = 1024):
        from openai import OpenAI
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "x"),
                             base_url=base_url or os.environ.get("OPENAI_BASE_URL"))
        self.model = model
        self.max_tokens = max_tokens

    def _tools(self, interface, state, ctx):
        specs = interface.tool_specs(state, ctx)
        return [{"type": "function",
                 "function": {"name": s["name"], "description": s["description"],
                              "parameters": s["input_schema"]}} for s in specs], len(specs)

    def run(self, interface, env: Env, task: Task, max_steps: int = 8) -> RunResult:
        state = task.init()
        interface.agent_ctx = task.agent_ctx             # SEM: expose per agent context
        res = RunResult(task.id, interface.label, self.model, success=False)
        messages = [{"role": "system", "content": _system_prompt(env)},
                    {"role": "user", "content": task.instruction}]
        last_obs = ""

        for _ in range(max_steps):
            tools, n = self._tools(interface, state, _context(task, last_obs))
            res.menu_sizes.append(n)
            kwargs = dict(model=self.model, max_tokens=self.max_tokens, messages=messages)
            if tools:                                    # OpenAI rejects an empty tools list
                kwargs["tools"] = tools
                if getattr(interface, "serial_calls", False):
                    # Conformant hypermedia client: one affordance per perceive-act cycle.
                    kwargs["parallel_tool_calls"] = False
            resp = self.client.chat.completions.create(**kwargs)
            if resp.usage:
                res.prompt_tokens += resp.usage.prompt_tokens
                res.completion_tokens += resp.usage.completion_tokens
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                break
            for tc in msg.tool_calls:
                res.steps += 1
                args = json.loads(tc.function.arguments or "{}")
                obs = interface.call(state, tc.function.name, args)
                res.calls.append({"tool": tc.function.name, "args": args, "ok": obs.ok})
                if not obs.ok:
                    res.illegal_calls += 1
                last_obs = obs.text
                content = obs.text
                if obs.next_affordances:
                    content += f"\n[next valid actions: {', '.join(obs.next_affordances)}]"
                if obs.pending:
                    content += f"\n[not yet available: {'; '.join(obs.pending)}]"
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})

        res.success = task.goal(state)
        return res
