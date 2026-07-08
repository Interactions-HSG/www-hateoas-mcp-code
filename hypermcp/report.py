"""Summarise result logs (results/*.jsonl) into a per-(model, condition, interface) table.

Run: python -m hypermcp.report [results_dir_or_file ...]   (default: results/)
"""
from __future__ import annotations
import glob
import json
import sys


def load(paths: list[str]) -> list[dict]:
    files: list[str] = []
    for p in paths:
        files.extend(glob.glob(f"{p}/*.jsonl") if not p.endswith(".jsonl") else [p])
    rows = []
    for fp in files:
        with open(fp) as f:
            rows.extend(json.loads(line) for line in f if line.strip())
    return rows


def summarise(rows: list[dict]) -> dict[tuple[str, str, str, str], dict]:
    groups: dict[tuple[str, str, str, str], list[dict]] = {}
    for r in rows:
        key = (r["model"], r.get("env", "?"), r.get("condition", ""), r["interface"])
        groups.setdefault(key, []).append(r)
    out = {}
    for key, rs in groups.items():
        n = len(rs)
        out[key] = {
            "n": n,
            "success": sum(r["success"] for r in rs) / n,
            "illegal": sum(r["illegal_calls"] for r in rs),
            "blocked": sum(r["blocked"] for r in rs),
            "avg_menu": sum(r["avg_menu"] for r in rs) / n,
            "avg_tokens": sum(r["total_tokens"] for r in rs) / n,
        }
    return out


def main() -> None:
    paths = sys.argv[1:] or ["results"]
    rows = load(paths)
    if not rows:
        print("no result rows found in", paths)
        return
    summ = summarise(rows)
    # token baseline per (model, env, condition) = the 'flat' interface, for a savings column
    flat_tok = {(m, e, c): s["avg_tokens"]
                for (m, e, c, i), s in summ.items() if i == "flat"}

    print(f"{'model':<16}{'env':<8}{'cond':<12}{'interface':<13}{'n':<4}{'success':<9}"
          f"{'illegal':<9}{'blocked':<9}{'avg_menu':<10}{'avg_tokens':<12}{'vs_flat':<8}")
    print("-" * 118)
    for (model, env, cond, iface) in sorted(summ):
        s = summ[(model, env, cond, iface)]
        base = flat_tok.get((model, env, cond))
        vs = f"{(s['avg_tokens']/base-1)*100:+.0f}%" if base else "-"
        print(f"{model:<16}{env:<8}{cond:<12}{iface:<13}{s['n']:<4}{s['success']*100:<9.0f}"
              f"{s['illegal']:<9}{s['blocked']:<9}{s['avg_menu']:<10.2f}"
              f"{s['avg_tokens']:<12.0f}{vs:<8}")


if __name__ == "__main__":
    main()
