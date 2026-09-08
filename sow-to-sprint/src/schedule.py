import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import networkx as nx
import yaml
from pydantic import BaseModel

from src.models import SOWExtraction, WorkItem


# ---------------------------------------------------------------------------
# Working calendar
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CALENDAR_PATH = _PROJECT_ROOT / "data" / "config" / "calendar.yaml"

# date.weekday(): Mon=0 … Fri=4, Sat=5, Sun=6.
_WEEKDAY_INDEX = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}


class WorkingCalendar:
    """Wraps calendar.yaml — knows which days are working days."""

    def __init__(self, weekend: list[str], holidays: set[date]) -> None:
        self.weekend_indexes = {_WEEKDAY_INDEX[d] for d in weekend}
        self.holidays = holidays

    @classmethod
    def load(cls, path: str | Path = _CALENDAR_PATH) -> "WorkingCalendar":
        raw = yaml.safe_load(Path(path).read_text())
        holidays = {
            date.fromisoformat(h["date"])
            for h in raw.get("public_holidays_2026", [])
        }
        return cls(weekend=raw["weekend"], holidays=holidays)

    def is_working_day(self, d: date) -> bool:
        return d.weekday() not in self.weekend_indexes and d not in self.holidays

    def previous_working_day(self, d: date) -> date:
        d -= timedelta(days=1)
        while not self.is_working_day(d):
            d -= timedelta(days=1)
        return d

    def subtract_working_days(self, d: date, n: int) -> date:
        """Return the date that is `n` working days *before* `d`.

        If `d` itself is a working day, that counts as day 0 (i.e. a task
        that takes 1 day and ends on `d` has start_date == d).
        """
        if n <= 0:
            return d
        # Move d back to a working day first if it isn't one
        while not self.is_working_day(d):
            d -= timedelta(days=1)
        # n=1 means one full working day, so we consume today + subtract n-1 more
        remaining = n - 1
        while remaining > 0:
            d -= timedelta(days=1)
            if self.is_working_day(d):
                remaining -= 1
        return d


# ---------------------------------------------------------------------------
# Schedule report
# ---------------------------------------------------------------------------

class ScheduleReport(BaseModel):
    signature_date: date | None
    delivery_date: date
    scheduled_start: date  # earliest start across all items
    scheduled_end: date    # latest due across all items
    critical_path_ids: list[str]
    critical_path_days: float
    over_committed_ids: list[str]  # items whose computed start < signature_date


# ---------------------------------------------------------------------------
# DAG construction
# ---------------------------------------------------------------------------

_PHASE_ORDER = ["Discovery", "Build", "UAT", "Launch", "Post-launch"]


def _phase_boundary_node(phase: str) -> str:
    """Virtual node id that marks the boundary just after `phase` ends."""
    return f"__end_of_{phase}__"


def _build_dag(work_items: list[WorkItem]) -> nx.DiGraph:
    """Build a DAG where an edge (u → v) means 'u must finish before v starts'."""
    g: nx.DiGraph = nx.DiGraph()

    by_id: dict[str, WorkItem] = {it.id: it for it in work_items}
    for it in work_items:
        g.add_node(it.id, kind="workitem", estimate=it.estimate_days)

    # Explicit depends_on edges (dependency → dependent).
    for it in work_items:
        for dep_id in it.depends_on:
            if dep_id in by_id:  # ignore unresolved refs; shouldn't happen after decompose
                g.add_edge(dep_id, it.id)

    # Global phase-gate edges via virtual boundary nodes.
    # Every phase's items feed into that phase's boundary; every next-phase
    # item depends on the previous phase's boundary. Constant-size overhead.
    items_by_phase: dict[str, list[str]] = defaultdict(list)
    for it in work_items:
        items_by_phase[it.phase].append(it.id)

    for i, phase in enumerate(_PHASE_ORDER[:-1]):
        next_phase = _PHASE_ORDER[i + 1]
        if not items_by_phase[phase] or not items_by_phase[next_phase]:
            continue
        boundary = _phase_boundary_node(phase)
        g.add_node(boundary, kind="boundary", estimate=0.0)
        for uid in items_by_phase[phase]:
            g.add_edge(uid, boundary)
        for vid in items_by_phase[next_phase]:
            g.add_edge(boundary, vid)

    return g


def _assert_dag(g: nx.DiGraph) -> None:
    if not nx.is_directed_acyclic_graph(g):
        cycle = next(iter(nx.simple_cycles(g)), None)
        raise ValueError(f"schedule DAG contains a cycle: {cycle}")


# ---------------------------------------------------------------------------
# Back-scheduling
# ---------------------------------------------------------------------------

def _back_schedule(
    work_items: list[WorkItem],
    dag: nx.DiGraph,
    calendar: WorkingCalendar,
    delivery_date: date,
) -> None:
    """Fill in `start_date` and `due_date` on every WorkItem, in place."""
    by_id: dict[str, WorkItem] = {it.id: it for it in work_items}

    # Node "end date" — dict keyed by node id, includes virtual boundary nodes.
    # For a real item, end_date == due_date. For a boundary, it's the min
    # start date of any dependent (i.e. the boundary must be "done" by then).
    end_date: dict[str, date] = {}

    # Ensure delivery_date lands on a working day.
    scheduled_delivery = delivery_date
    while not calendar.is_working_day(scheduled_delivery):
        scheduled_delivery = calendar.previous_working_day(scheduled_delivery)

    # Process in reverse topological order — sinks first, sources last.
    order = list(reversed(list(nx.topological_sort(dag))))

    for node in order:
        successors = list(dag.successors(node))
        if not successors:
            # sink: due at delivery
            due = scheduled_delivery
        else:
            due = min(_start_of(succ, dag, by_id, calendar, end_date) for succ in successors)

        kind = dag.nodes[node].get("kind")
        if kind == "boundary":
            end_date[node] = due
            continue

        item = by_id[node]
        est_days = max(1, math.ceil(item.estimate_days))
        start = calendar.subtract_working_days(due, est_days)
        item.due_date = due
        item.start_date = start
        end_date[node] = due


def _start_of(
    node: str,
    dag: nx.DiGraph,
    by_id: dict[str, WorkItem],
    calendar: WorkingCalendar,
    end_date_cache: dict[str, date],
) -> date:
    """Return the start date of `node`. For a boundary, the boundary's own
    due date. For a real item, its computed start_date."""
    kind = dag.nodes[node].get("kind")
    if kind == "boundary":
        return end_date_cache[node]
    item = by_id[node]
    if item.start_date is None:
        # Should have been set by back_schedule already
        raise RuntimeError(f"item {node} has no start_date during back-schedule")
    return item.start_date


# ---------------------------------------------------------------------------
# Critical path
# ---------------------------------------------------------------------------

def _critical_path(dag: nx.DiGraph, work_items: list[WorkItem]) -> tuple[list[str], float]:
    """Longest path through the DAG weighted by estimate_days."""
    # Weight = -estimate on the edge's target node (nx.dag_longest_path
    # supports weight-on-edges only pre-3.x; on ≥3.0 it supports node
    # weights via `weight=` on the graph). We compute manually for clarity.
    weight_of: dict[str, float] = {}
    for n in dag.nodes:
        w = dag.nodes[n].get("estimate", 0.0)
        weight_of[n] = float(w)

    # DP over topological order: longest_ending[n] = max path length ending at n
    longest_ending: dict[str, float] = {}
    prev: dict[str, str | None] = {}
    for n in nx.topological_sort(dag):
        preds = list(dag.predecessors(n))
        if not preds:
            longest_ending[n] = weight_of[n]
            prev[n] = None
        else:
            best_p = max(preds, key=lambda p: longest_ending[p])
            longest_ending[n] = longest_ending[best_p] + weight_of[n]
            prev[n] = best_p

    end_node = max(longest_ending, key=lambda k: longest_ending[k])
    total = longest_ending[end_node]

    # Reconstruct path, filtering out virtual boundary nodes
    path: list[str] = []
    cur: str | None = end_node
    while cur is not None:
        if dag.nodes[cur].get("kind") != "boundary":
            path.append(cur)
        cur = prev.get(cur)
    path.reverse()
    return path, total


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def schedule(
    extraction: SOWExtraction,
    work_items: list[WorkItem],
    calendar: WorkingCalendar | None = None,
) -> ScheduleReport:
    """Assign `start_date` / `due_date` to every work item and return a
    schedule report. Mutates the WorkItems in place.
    """
    if calendar is None:
        calendar = WorkingCalendar.load()

    dag = _build_dag(work_items)
    _assert_dag(dag)
    _back_schedule(work_items, dag, calendar, extraction.delivery_date)
    critical_ids, critical_days = _critical_path(dag, work_items)

    over_committed = [
        it.id
        for it in work_items
        if it.start_date is not None
        and extraction.signature_date is not None
        and it.start_date < extraction.signature_date
    ]

    real_starts = [it.start_date for it in work_items if it.start_date]
    real_dues = [it.due_date for it in work_items if it.due_date]

    return ScheduleReport(
        signature_date=extraction.signature_date,
        delivery_date=extraction.delivery_date,
        scheduled_start=min(real_starts) if real_starts else (extraction.signature_date or extraction.delivery_date),
        scheduled_end=max(real_dues) if real_dues else extraction.delivery_date,
        critical_path_ids=critical_ids,
        critical_path_days=critical_days,
        over_committed_ids=over_committed,
    )


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def _demo() -> None:
    import json
    import sys

    default_ext = Path("data/runs/SOW-2026-014-v1-extraction.json")
    default_items = Path("data/runs/SOW-2026-014-v1-workitems.json")
    ext_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_ext
    items_path = Path(sys.argv[2]) if len(sys.argv) > 2 else default_items

    extraction = SOWExtraction.model_validate_json(ext_path.read_text())
    work_items = [
        WorkItem.model_validate(x) for x in json.loads(items_path.read_text())
    ]
    print(f"scheduling {len(work_items)} items against delivery {extraction.delivery_date} …")

    report = schedule(extraction, work_items)

    print(f"\n=== schedule report ===")
    print(f"signature_date:      {report.signature_date}")
    print(f"delivery_date:       {report.delivery_date}")
    print(f"scheduled_start:     {report.scheduled_start}")
    print(f"scheduled_end:       {report.scheduled_end}")
    print(f"critical_path_days:  {report.critical_path_days}")
    print(f"critical_path items: {len(report.critical_path_ids)}")
    for i, wid in enumerate(report.critical_path_ids[:10]):
        it = next(x for x in work_items if x.id == wid)
        print(f"  {i + 1:2}. {wid}  [{it.type:>16}]  {it.title[:70]}")
    if len(report.critical_path_ids) > 10:
        print(f"  … and {len(report.critical_path_ids) - 10} more")
    print(f"over-committed items: {len(report.over_committed_ids)}")

    out_path = Path("data/runs") / items_path.name.replace("workitems", "scheduled")
    out_path.write_text(
        json.dumps([it.model_dump(mode="json") for it in work_items], indent=2, default=str)
    )
    print(f"\nwrote {out_path}")

    report_path = Path("data/runs") / items_path.name.replace("workitems", "schedule-report")
    report_path.write_text(report.model_dump_json(indent=2))
    print(f"wrote {report_path}")


if __name__ == "__main__":
    _demo()
