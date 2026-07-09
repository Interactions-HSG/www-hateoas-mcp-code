"""Agents that drive an interface to complete a task.

- run_scripted: deterministic, no API key. Authenticates if required, then attempts the
  task's intended action iff the interface makes it visible. Exercises the full pipeline
  and reproduces the mechanism-level difference (illegal calls, menu size, blocking).
- OpenAIAgent: a real LLM tool-calling loop (gated on an API key; also serves open
  models via an OpenAI-compatible endpoint), where the model re-reads the advertised
  tools each step. This is where the paper's headline numbers come from.
"""
from __future__ import annotations
import json
import os
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
def run_scripted(interface, env: Env, task: Task, max_steps: int = 8) -> RunResult:
    state, res = _start(interface, task, "scripted")
    intents = list(task.scripted_intent)

    for _ in range(max_steps):
        visible = [a.name for a in interface.list_tools(state, task.instruction)]
        res.menu_sizes.append(len(visible))

        # 1) authenticate first if needed and possible
        if state.authenticated_user is None:
            auth = next((a for a in interface.list_tools(state, task.instruction)
                         if a.rel == "authenticate"), None)
            if auth is not None:
                _execute(interface, state, res, auth.name,
                         state.scratch.get("creds", {}))
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
        _execute(interface, state, res, name, args)
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
                break
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                obs = _execute(interface, state, res, tc.function.name, args)
                last_obs = obs.text
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": _result_text(obs)})

        res.success = task.goal(state)
        return res
