"""Generate the paper's figures from the committed result logs (results/*.jsonl).

Run: python -m hypermcp.figures [results_dir]         (default: results/)
Outputs PDF (vector, for LaTeX) into results/figures/.

Figure 'scaling':  avg tokens/task vs. size of the advertised tool surface, per
                   interface, on the shop scaling subset (3 fixed tasks at every x so
                   the curve is like-for-like). Flat ends at 124 tools: the OpenAI API
                   rejects requests with more than 128 tools, so beyond the cap a flat
                   surface is not expensive but *unusable* (shaded region).
Figure 'quadrant': validity (illegal calls) x cost (avg tokens/task) on the full shop
                   task set -- the money quadrant: HyperMCP is the only interface in
                   the valid-and-cheap corner.

Style: dataviz-skill reference palette (categorical slots 1-4, fixed order), thin
marks, hairline solid grid, text in ink tokens (never series colors), direct labels +
legend, marker shapes as secondary (CVD/print) encoding on the scatter.
"""
from __future__ import annotations
import glob
import json
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Reference palette (dataviz skill, categorical slots 1-4, light mode) + ink tokens.
SLOT = {"flat": "#2a78d6", "retrieval": "#1baf7a",
        "retrieval-emb": "#eda100", "hyper": "#008300"}
NAME = {"flat": "Flat", "retrieval": "Retrieval (BM25)",
        "retrieval-emb": "Retrieval (emb.)", "hyper": "HyperMCP"}
MARKER = {"flat": "o", "retrieval": "s", "retrieval-emb": "D", "hyper": "^"}
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"

SCALING_TASKS = {"cancel_and_return", "return_window_trap", "buy_hoodie"}
API_CAP = 128            # OpenAI: tools array rejected above 128 entries
BASE_TOOLS = 24          # genuine shop tools

plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 7.0,
    "axes.edgecolor": AXIS, "axes.linewidth": 0.6, "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelsize": 6.5, "ytick.labelsize": 6.5,
    "grid.color": GRID, "grid.linewidth": 0.5,
    "legend.frameon": False, "legend.fontsize": 6.5,
    "pdf.fonttype": 42,
})


def load(results_dir: str) -> list[dict]:
    rows = []
    for fp in glob.glob(f"{results_dir}/*.jsonl"):
        with open(fp) as f:
            rows.extend(json.loads(l) for l in f if l.strip())
    return [r for r in rows if r.get("env") == "shop"]


def _cell(rows, cond, iface, tasks=None):
    sel = [r for r in rows if r["condition"] == cond and r["interface"] == iface
           and (tasks is None or r["task_id"] in tasks)]
    if not sel:
        return None
    return {"n": len(sel),
            "tokens": sum(r["total_tokens"] for r in sel) / len(sel),
            "illegal": sum(r["illegal_calls"] for r in sel),
            "success": sum(r["success"] for r in sel) / len(sel)}


def fig_scaling(rows, outdir: pathlib.Path) -> None:
    xs = {BASE_TOOLS: "policy", 124: "policy+d100", 524: "policy+d500",
          1024: "policy+d1000"}
    fig, ax = plt.subplots(figsize=(3.35, 2.15), dpi=300)
    ax.set_axisbelow(True)
    ax.grid(True, axis="y")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    # Infeasibility region: the API rejects >128 tools, flat cannot issue a request.
    ax.axvspan(API_CAP, 1400, color=GRID, alpha=0.35, lw=0)
    ax.axvline(API_CAP, color=AXIS, lw=0.6)

    ends = {}
    for iface in ("flat", "retrieval", "retrieval-emb", "hyper"):
        pts = []
        for x, cond in xs.items():
            c = _cell(rows, cond, iface, SCALING_TASKS)
            if c:
                pts.append((x, c["tokens"]))
        if not pts:
            continue
        px, py = zip(*sorted(pts))
        ax.plot(px, py, color=SLOT[iface], lw=1.4, marker=MARKER[iface], ms=3.4,
                mec="white", mew=0.6, label=NAME[iface], clip_on=False)
        ends[iface] = (px[-1], py[-1])

    ax.set_xscale("log")
    ax.set_xticks(list(xs))
    ax.set_xticklabels([str(x) for x in xs])
    ax.minorticks_off()
    ax.set_xlim(BASE_TOOLS * 0.85, 1400)
    ax.set_ylim(0, None)
    ax.set_xlabel("advertised tool surface (number of tools, log scale)")
    ax.set_ylabel("avg. tokens per task")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v/1000:g}k" if v else "0")

    # Selective direct labels: the two lines the story is about.
    if "flat" in ends:
        x, y = ends["flat"]
        ax.annotate(f"{y/1000:.1f}k", (x, y), textcoords="offset points",
                    xytext=(0, 5), ha="center", fontsize=6.5, color=INK)
    if "hyper" in ends:
        x, y = ends["hyper"]
        ax.annotate(f"{y/1000:.1f}k", (x, y), textcoords="offset points",
                    xytext=(0, 5), ha="center", fontsize=6.5, color=INK)
    ax.text(API_CAP * 1.07, ax.get_ylim()[1] * 0.97,
            "flat infeasible:\nAPI rejects >128 tools",
            fontsize=6.0, color=MUTED, va="top")
    ax.legend(loc="center left", handlelength=1.6, borderaxespad=0.4)
    fig.tight_layout(pad=0.4)
    fig.savefig(outdir / "fig-scaling.pdf")
    fig.savefig(outdir / "fig-scaling.png")      # raster twin for README/inspection
    plt.close(fig)


def fig_quadrant(rows, outdir: pathlib.Path) -> None:
    fig, ax = plt.subplots(figsize=(3.35, 2.05), dpi=300)
    ax.set_axisbelow(True)
    ax.grid(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    cells = {}
    for iface in ("flat", "retrieval", "retrieval-emb", "hyper"):
        c = _cell(rows, "policy", iface)
        if c:
            cells[iface] = c
    for iface, c in cells.items():
        ill = c["illegal"] / c["n"]
        ax.scatter(c["tokens"], ill, s=42, color=SLOT[iface],
                   marker=MARKER[iface], edgecolors="white", linewidths=1.2,
                   zorder=3)
        if iface == "flat":                       # right-most point: label leftwards
            dx, dy, ha = -7, 2, "right"
        elif iface == "retrieval-emb":
            dx, dy, ha = 7, -8, "left"
        else:
            dx, dy, ha = 7, 2, "left"
        ax.annotate(f"{NAME[iface]}", (c["tokens"], ill),
                    textcoords="offset points", xytext=(dx, dy), fontsize=6.8,
                    color=INK, ha=ha)
        ax.annotate(f"{c['success']*100:.0f}% success",
                    (c["tokens"], ill), textcoords="offset points",
                    xytext=(dx, dy - 7), fontsize=6.0, color=INK2, ha=ha)
    ax.set_xlim(0, max(c["tokens"] for c in cells.values()) * 1.12)
    ax.set_ylim(-0.08, None)
    ax.set_xlabel("avg. tokens per task")
    ax.set_ylabel("illegal calls per episode")
    ax.annotate("valid + cheap", xy=(0.02, 0.04), xycoords="axes fraction",
                fontsize=6.0, color=MUTED, style="italic")
    fig.tight_layout(pad=0.4)
    fig.savefig(outdir / "fig-quadrant.pdf")
    fig.savefig(outdir / "fig-quadrant.png")     # raster twin for README/inspection
    plt.close(fig)


def main() -> None:
    results_dir = sys.argv[1] if len(sys.argv) > 1 else "results"
    rows = load(results_dir)
    if not rows:
        raise SystemExit(f"no shop rows found in {results_dir}/*.jsonl")
    outdir = pathlib.Path(results_dir) / "figures"
    outdir.mkdir(parents=True, exist_ok=True)
    fig_scaling(rows, outdir)
    fig_quadrant(rows, outdir)
    print(f"wrote {outdir}/fig-scaling.pdf and fig-quadrant.pdf "
          f"from {len(rows)} shop rows")


if __name__ == "__main__":
    main()
