"""Per-run metrics and aggregation."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class RunResult:
    task_id: str
    interface: str
    model: str
    success: bool
    condition: str = ""             # experimental condition, e.g. "policy" / "nopolicy"
    illegal_calls: int = 0          # tools/call that violated a guard (server-rejected)
    blocked: int = 0                # intended actions structurally unavailable (HyperMCP)
    steps: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    menu_sizes: list[int] = field(default_factory=list)

    @property
    def avg_menu(self) -> float:
        return sum(self.menu_sizes) / len(self.menu_sizes) if self.menu_sizes else 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def aggregate(results: list[RunResult]) -> dict[str, dict]:
    """Group by interface -> summary stats."""
    out: dict[str, dict] = {}
    by_iface: dict[str, list[RunResult]] = {}
    for r in results:
        by_iface.setdefault(r.interface, []).append(r)
    for iface, rs in by_iface.items():
        n = len(rs)
        out[iface] = {
            "n": n,
            "success_rate": sum(r.success for r in rs) / n,
            "illegal_calls": sum(r.illegal_calls for r in rs),
            "blocked": sum(r.blocked for r in rs),
            "avg_menu": sum(r.avg_menu for r in rs) / n,
            "avg_tokens": sum(r.total_tokens for r in rs) / n,
        }
    return out
