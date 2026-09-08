from collections import defaultdict
from dataclasses import dataclass, field

from src.models import SOWExtraction, WorkItem
from src.schedule import ScheduleReport
from src.sync import content_hash


@dataclass
class DiffReport:
    v1_run_id: str
    v2_run_id: str

    added: list[WorkItem] = field(default_factory=list)
    removed: list[WorkItem] = field(default_factory=list)
    changed: list[tuple[WorkItem, WorkItem]] = field(default_factory=list)
    unchanged: list[tuple[WorkItem, WorkItem]] = field(default_factory=list)

    v1_critical_path_days: float = 0.0
    v2_critical_path_days: float = 0.0
    v1_over_committed_count: int = 0
    v2_over_committed_count: int = 0

    def summary(self) -> dict:
        return {
            "added": len(self.added),
            "removed": len(self.removed),
            "changed": len(self.changed),
            "unchanged": len(self.unchanged),
            "critical_path_days_delta": (
                self.v2_critical_path_days - self.v1_critical_path_days
            ),
            "over_committed_delta": (
                self.v2_over_committed_count - self.v1_over_committed_count
            ),
        }


# ---------------------------------------------------------------------------
# Matching + diff
# ---------------------------------------------------------------------------

def _group(items: list[WorkItem]) -> dict[tuple[str, str], list[WorkItem]]:
    """Group items by (source_clause_id, type). Order within a group is
    preserved — pair-by-order relies on it."""
    g: dict[tuple[str, str], list[WorkItem]] = defaultdict(list)
    for it in items:
        g[(it.source_clause_id, it.type)].append(it)
    return g


def compute_diff(
    v1_run_id: str,
    v1_items: list[WorkItem],
    v1_report: ScheduleReport,
    v2_run_id: str,
    v2_items: list[WorkItem],
    v2_report: ScheduleReport,
) -> DiffReport:
    g1 = _group(v1_items)
    g2 = _group(v2_items)

    diff = DiffReport(
        v1_run_id=v1_run_id,
        v2_run_id=v2_run_id,
        v1_critical_path_days=v1_report.critical_path_days,
        v2_critical_path_days=v2_report.critical_path_days,
        v1_over_committed_count=len(v1_report.over_committed_ids),
        v2_over_committed_count=len(v2_report.over_committed_ids),
    )

    for key in set(g1) | set(g2):
        a = g1.get(key, [])
        b = g2.get(key, [])
        n_paired = min(len(a), len(b))

        for i in range(n_paired):
            if content_hash(a[i]) == content_hash(b[i]):
                diff.unchanged.append((a[i], b[i]))
            else:
                diff.changed.append((a[i], b[i]))

        # Excess in v2 → added
        for i in range(n_paired, len(b)):
            diff.added.append(b[i])

        # Excess in v1 → removed
        for i in range(n_paired, len(a)):
            diff.removed.append(a[i])

    return diff


# ---------------------------------------------------------------------------
# Human-readable delta reasons for a changed pair
# ---------------------------------------------------------------------------

def field_deltas(v1: WorkItem, v2: WorkItem) -> list[str]:
    """Enumerate which fields changed between a v1 item and its v2 pair."""
    out: list[str] = []
    checks = [
        ("title", v1.title, v2.title),
        ("description", v1.description, v2.description),
        ("acceptance_criteria", v1.acceptance_criteria, v2.acceptance_criteria),
        ("estimate_days", v1.estimate_days, v2.estimate_days),
        ("phase", v1.phase, v2.phase),
        ("start_date", v1.start_date, v2.start_date),
        ("due_date", v1.due_date, v2.due_date),
        ("assignee", v1.assignee, v2.assignee),
        ("squad", v1.squad, v2.squad),
        ("gherkin", v1.gherkin, v2.gherkin),
        ("confidence", v1.confidence, v2.confidence),
    ]
    for name, a, b in checks:
        if a != b:
            out.append(name)
    return out
