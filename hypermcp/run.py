"""Run the B0/B1/HyperMCP comparison (and SEM ablations) over an environment's tasks.

Examples:
  python -m hypermcp.run                              # scripted, flat/retrieval/hyper
  python -m hypermcp.run --ablations                 # + hyper-noctx/-noenum/-noenv
  python -m hypermcp.run --env wot --ablations
  python -m hypermcp.run --agent anthropic --model claude-opus-4-8 --ablations --out results
"""
from __future__ import annotations
import argparse
import dataclasses
import datetime as dt
import json
import pathlib

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from .core import Env, Affordance
from .envs import retail, wot
from .interfaces import INTERFACES, ABLATIONS, HyperInterface
from .metrics import aggregate
from .agents import run_scripted, AnthropicAgent, OpenAIAgent

ENVS = {"retail": retail.ENV, "wot": wot.ENV}


def pad_distractors(env: Env, n: int) -> Env:
    """Add n never-applicable 'other server' tools, mimicking a host wired to many MCP
    servers where most tools are irrelevant to the task. Flat advertises them all
    (context blow-up); HyperMCP never exposes them (guard is always false)."""
    if n <= 0:
        return env
    extra = [Affordance(f"aux_op_{i}",
                        f"Auxiliary operation {i} on an unrelated backend subsystem.",
                        {"type": "object", "properties": {}},
                        guard=lambda s, a: False, effect=lambda s, a: "noop",
                        rel="action") for i in range(n)]
    return Env(env.name, list(env.affordances) + extra, env.tasks, env.policy)


def build_agent(kind: str, model: str, base_url: str | None):
    if kind == "scripted":
        return lambda iface, env, task: run_scripted(iface, env, task)
    if kind == "anthropic":
        a = AnthropicAgent(model=model)
        return lambda iface, env, task: a.run(iface, env, task)
    if kind == "openai":
        a = OpenAIAgent(model=model, base_url=base_url)
        return lambda iface, env, task: a.run(iface, env, task)
    raise SystemExit(f"unknown agent: {kind}")


def build_interfaces(env, names: list[str], k: int, ablations: bool):
    """Return an ordered list of (label, interface_instance)."""
    out = []
    for name in names:
        cls = INTERFACES[name]
        iface = cls(env, k=k) if name == "retrieval" else cls(env)
        out.append((name, iface))
        if ablations and name == "hyper":
            for vlabel, kwargs in ABLATIONS.items():
                v = HyperInterface(env, **kwargs)
                v.label = vlabel                       # distinguish in reports/logs
                out.append((vlabel, v))
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--env", default="retail", choices=list(ENVS))
    p.add_argument("--agent", default="scripted",
                   choices=["scripted", "anthropic", "openai"])
    p.add_argument("--model", default="claude-opus-4-8")
    p.add_argument("--base-url", default=None)
    p.add_argument("--interfaces", default="flat,retrieval,hyper")
    p.add_argument("--ablations", action="store_true", help="also run HyperMCP ablations")
    p.add_argument("--k", type=int, default=3, help="top-k for the retrieval baseline")
    p.add_argument("--no-policy", action="store_true",
                   help="omit the natural-language policy from the prompt (tests whether "
                        "the SEM enforces validity structurally, without prompt rules)")
    p.add_argument("--distractors", type=int, default=0,
                   help="pad the env with N never-applicable tools (many-servers regime)")
    p.add_argument("--out", default=None, help="directory to write per-run JSONL logs")
    args = p.parse_args()

    env = ENVS[args.env]
    if args.no_policy:
        env.policy = ""                                  # structural validity only
    env = pad_distractors(env, args.distractors)
    agent = build_agent(args.agent, args.model, args.base_url)
    interfaces = build_interfaces(env, args.interfaces.split(","), args.k, args.ablations)
    results = []

    print(f"env={args.env}  agent={args.agent}  "
          f"model={args.model if args.agent != 'scripted' else '-'}\n")
    print(f"{'interface':<13}{'task':<22}{'ok':<4}{'illegal':<9}{'blocked':<9}"
          f"{'steps':<7}{'menu':<7}{'tokens':<8}")
    print("-" * 79)
    condition = "nopolicy" if args.no_policy else "policy"
    if args.distractors:
        condition += f"+d{args.distractors}"
    for label, iface in interfaces:
        for task in env.tasks:
            r = agent(iface, env, task)
            r.condition = condition
            results.append(r)
            print(f"{r.interface:<13}{r.task_id:<22}{'Y' if r.success else 'N':<4}"
                  f"{r.illegal_calls:<9}{r.blocked:<9}{r.steps:<7}"
                  f"{r.avg_menu:<7.2f}{r.total_tokens:<8}")

    print("\n=== Aggregate by interface ===")
    print(f"{'interface':<13}{'success':<9}{'illegal':<9}{'blocked':<9}"
          f"{'avg_menu':<10}{'avg_tokens':<11}")
    print("-" * 61)
    for iface, s in aggregate(results).items():
        print(f"{iface:<13}{s['success_rate']*100:<9.0f}{s['illegal_calls']:<9}"
              f"{s['blocked']:<9}{s['avg_menu']:<10.2f}{s['avg_tokens']:<11.0f}")

    if args.out:
        outdir = pathlib.Path(args.out)
        outdir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = outdir / f"{args.env}-{args.agent}-{stamp}.jsonl"
        with path.open("w") as f:
            for r in results:
                d = dataclasses.asdict(r)
                d["avg_menu"] = r.avg_menu
                d["total_tokens"] = r.total_tokens
                f.write(json.dumps(d) + "\n")
        print(f"\nwrote {len(results)} runs to {path}")


if __name__ == "__main__":
    main()
