"""Run the Flat/Retrieval/HyperMCP comparison (and ablations) on the shop environment.

Examples:
  python -m hypermcp.run                              # scripted, flat/retrieval-emb/hyper
  python -m hypermcp.run --ablations                 # + hyper-noctx/-nopending
  python -m hypermcp.run --agent openai --ablations --out results
  python -m hypermcp.run --interfaces hyper,hyper-stateless --ablations   # both mappings
  python -m hypermcp.run --interfaces hyper,hyper-stateless --transport mcp  # over MCP HTTP
  python -m hypermcp.run --agent openai --interfaces flat,hyper --distractors 100
  python -m hypermcp.run --agent openai-responses --model gpt-6.1-sol --out results
"""
from __future__ import annotations
import argparse
import dataclasses
import functools
import datetime as dt
import json
import pathlib

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from .envs import shop
from .interfaces import INTERFACES, ABLATIONS, HyperInterface
from .stateless import StatelessHyperInterface
from .distractors import pad as pad_distractors
from .metrics import aggregate
from .agents import run_scripted, OpenAIAgent, OpenAIResponsesAgent

# Stateless mapping (MCP 2026-07-28). Its ablation drops the envelope, which leaves
# the catalog-only server that SEP-2567 prescribes for state-dependent tools.
STATELESS_ABLATIONS = {"hyper-stateless-noenv": {"use_envelope": False}}
ALL_INTERFACES = {**INTERFACES, "hyper-stateless": StatelessHyperInterface,
                  **{label: functools.partial(StatelessHyperInterface, **kw)
                     for label, kw in STATELESS_ABLATIONS.items()}}


def build_agent(kind: str, model: str, max_steps: int):
    if kind == "scripted":
        return lambda iface, env, task: run_scripted(iface, env, task,
                                                     max_steps=max_steps)
    if kind == "openai":
        a = OpenAIAgent(model=model)
        return lambda iface, env, task: a.run(iface, env, task, max_steps=max_steps)
    if kind == "openai-responses":
        a = OpenAIResponsesAgent(model=model)
        return lambda iface, env, task: a.run(iface, env, task, max_steps=max_steps)
    raise SystemExit(f"unknown agent: {kind}")


def build_interfaces(env, names: list[str], k: int, ablations: bool,
                     transport: str = "inproc"):
    """Return an ordered list of (label, interface_instance)."""
    if transport == "mcp":
        from .mcp_transport import MCPInterface, VARIANTS
        labels = list(names)
        if ablations and "hyper-stateless" in names and \
                "hyper-stateless-noenv" not in names:
            labels += list(STATELESS_ABLATIONS)
        bad = [n for n in labels if n not in VARIANTS]
        if bad:
            raise SystemExit(f"--transport mcp supports {', '.join(VARIANTS)}; got {bad}")
        return [(n, MCPInterface(env, n)) for n in labels]
    out = []
    for name in names:
        cls = ALL_INTERFACES[name]
        iface = cls(env, k=k) if name.startswith("retrieval") else cls(env)
        iface.label = name
        out.append((name, iface))
        if ablations and name == "hyper":
            for vlabel, kwargs in ABLATIONS.items():
                v = HyperInterface(env, **kwargs)
                v.label = vlabel                       # distinguish in reports/logs
                out.append((vlabel, v))
        if ablations and name == "hyper-stateless":
            for vlabel, kwargs in STATELESS_ABLATIONS.items():
                v = StatelessHyperInterface(env, **kwargs)
                v.label = vlabel
                out.append((vlabel, v))
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--agent", default="scripted", choices=["scripted", "openai", "openai-responses"])
    p.add_argument("--model", default="gpt-4o-mini")
    p.add_argument("--interfaces", default="flat,retrieval-emb,hyper")
    p.add_argument("--ablations", action="store_true", help="also run HyperMCP ablations")
    p.add_argument("--k", type=int, default=3, help="top-k for the retrieval baseline")
    p.add_argument("--distractors", type=int, default=0,
                   help="pad the env with N realistic other-service tools "
                        "(many-servers regime)")
    p.add_argument("--max-steps", type=int, default=12,
                   help="max perceive-act cycles per task")
    p.add_argument("--tasks", default=None,
                   help="comma-separated task ids to run (default: all)")
    p.add_argument("--out", default=None, help="directory to write per-run JSONL logs")
    p.add_argument("--transport", default="inproc", choices=["inproc", "mcp"],
                   help="mcp: serve each HyperMCP mapping as a real MCP server over "
                        "Streamable HTTP (2025-11-25 sessions / 2026-07-28 stateless)")
    args = p.parse_args()

    env = pad_distractors(shop.ENV, args.distractors)
    if args.tasks:
        keep = set(args.tasks.split(","))
        env = dataclasses.replace(env, tasks=[t for t in env.tasks if t.id in keep])
    agent = build_agent(args.agent, args.model, args.max_steps)
    interfaces = build_interfaces(env, args.interfaces.split(","), args.k, args.ablations,
                                  args.transport)
    results = []

    print(f"env=shop  agent={args.agent}  "
          f"model={args.model if args.agent != 'scripted' else '-'}\n")
    print(f"{'interface':<26}{'task':<22}{'ok':<4}{'illegal':<9}{'blocked':<9}"
          f"{'steps':<7}{'menu':<7}{'tokens':<8}")
    print("-" * 92)
    condition = "policy"                               # label kept for log continuity
    if args.distractors:
        condition += f"+d{args.distractors}"
    for label, iface in interfaces:
        for task in env.tasks:
            r = agent(iface, env, task)
            r.condition = condition
            results.append(r)
            print(f"{r.interface:<26}{r.task_id:<22}{'Y' if r.success else 'N':<4}"
                  f"{r.illegal_calls:<9}{r.blocked:<9}{r.steps:<7}"
                  f"{r.avg_menu:<7.2f}{r.total_tokens:<8}")
        if hasattr(iface, "close"):
            iface.close()                              # MCP transport: stop server/client

    print("\n=== Aggregate by interface ===")
    print(f"{'interface':<26}{'success':<9}{'illegal':<9}{'blocked':<9}"
          f"{'avg_menu':<10}{'avg_tokens':<11}")
    print("-" * 74)
    for iface, s in aggregate(results).items():
        print(f"{iface:<26}{s['success_rate']*100:<9.0f}{s['illegal_calls']:<9}"
              f"{s['blocked']:<9}{s['avg_menu']:<10.2f}{s['avg_tokens']:<11.0f}")

    if args.out:
        outdir = pathlib.Path(args.out)
        outdir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = outdir / f"shop-{args.agent}-{stamp}.jsonl"
        with path.open("w") as f:
            for r in results:
                d = dataclasses.asdict(r)
                d["env"] = "shop"
                d["avg_menu"] = r.avg_menu
                d["total_tokens"] = r.total_tokens
                f.write(json.dumps(d) + "\n")
        print(f"\nwrote {len(results)} runs to {path}")


if __name__ == "__main__":
    main()
