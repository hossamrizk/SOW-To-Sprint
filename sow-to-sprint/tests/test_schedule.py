from datetime import date
from typing import Iterable

import pytest

from src.models import SOWExtraction, ScopeItem, WorkItem
from src.schedule import (
    WorkingCalendar,
    _assert_dag,
    _build_dag,
    schedule,
)

def _mk_extraction(
    *,
    signature: date = date(2026, 1, 12),
    delivery: date = date(2026, 6, 30),
) -> SOWExtraction:
    return SOWExtraction(
        sow_id="TEST-SOW",
        version=1,
        client_name="Test Client",
        project_name="Test Project",
        signature_date=signature,
        delivery_date=delivery,
        modules=["Test Module"],
        scope_items=[],
    )


def _mk_item(
    id: str,
    *,
    phase: str,
    estimate: float,
    depends_on: list[str] | None = None,
    function: str = "technical",
    type_: str = "user_story",
) -> WorkItem:
    return WorkItem(
        id=id,
        type=type_,  # type: ignore[arg-type]
        function=function,  # type: ignore[arg-type]
        title=f"item {id}",
        description="test item",
        acceptance_criteria=[],
        estimate_days=estimate,
        depends_on=depends_on or [],
        phase=phase,  # type: ignore[arg-type]
        source_clause_id="C-001",
        source_excerpt="test",
        confidence="high",
    )


CALENDAR = WorkingCalendar.load()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_cycle_detection_fires():
    """A dependency cycle should raise ValueError with the offending cycle."""
    items = [
        _mk_item("A", phase="Build", estimate=1.0, depends_on=["B"]),
        _mk_item("B", phase="Build", estimate=1.0, depends_on=["A"]),
    ]
    dag = _build_dag(items)
    with pytest.raises(ValueError, match="cycle"):
        _assert_dag(dag)


def test_every_scheduled_item_lands_on_working_day():
    """After scheduling, no start_date or due_date should fall on a
    weekend or holiday from calendar.yaml."""
    items = [
        _mk_item("A", phase="Discovery", estimate=2.0),
        _mk_item("B", phase="Build", estimate=3.0),
        _mk_item("C", phase="UAT", estimate=2.0),
        _mk_item("D", phase="Launch", estimate=2.0),
    ]
    extraction = _mk_extraction()
    schedule(extraction, items, calendar=CALENDAR)

    for it in items:
        assert it.start_date is not None
        assert it.due_date is not None
        assert CALENDAR.is_working_day(it.start_date), (
            f"item {it.id} starts on non-working day {it.start_date}"
        )
        assert CALENDAR.is_working_day(it.due_date), (
            f"item {it.id} ends on non-working day {it.due_date}"
        )


def test_over_commitment_triggers_on_compressed_sow():
    """Give the scheduler a SOW where the critical path can't fit before
    delivery. Every item at the head of the critical path should end up
    in `over_committed_ids`."""
    # 6 items x 20 days each on the critical path = 120 working days.
    # Signature 2026-06-01, delivery 2026-06-30 → less than a month available.
    extraction = _mk_extraction(
        signature=date(2026, 6, 1),
        delivery=date(2026, 6, 30),
    )
    items = [
        _mk_item("H1", phase="Discovery", estimate=20.0),
        _mk_item("H2", phase="Discovery", estimate=20.0, depends_on=["H1"]),
        _mk_item("H3", phase="Build",     estimate=20.0, depends_on=["H2"]),
        _mk_item("H4", phase="Build",     estimate=20.0, depends_on=["H3"]),
        _mk_item("H5", phase="UAT",       estimate=20.0, depends_on=["H4"]),
        _mk_item("H6", phase="Launch",    estimate=20.0, depends_on=["H5"]),
    ]
    report = schedule(extraction, items, calendar=CALENDAR)

    # At least H1 must be over-committed (it can't start before signature
    # given the total 120-day critical path against a 30-day window).
    assert "H1" in report.over_committed_ids, (
        f"expected H1 to be over-committed, got {report.over_committed_ids}"
    )
    # The critical path should include all 6 items.
    assert set(report.critical_path_ids) >= {f"H{i}" for i in range(1, 7)}


def test_realistic_sow_produces_no_over_commitment():
    """The v1 loyalty SOW has 5.5 months of runway; the critical path
    should fit comfortably and produce zero over-committed items."""
    extraction = _mk_extraction()  # Jan 12 → Jun 30
    items = [
        _mk_item("A", phase="Discovery", estimate=8.0),
        _mk_item("B", phase="Build",     estimate=5.0, depends_on=["A"]),
        _mk_item("C", phase="UAT",       estimate=2.0, depends_on=["B"]),
        _mk_item("D", phase="Launch",    estimate=5.0, depends_on=["C"]),
    ]
    report = schedule(extraction, items, calendar=CALENDAR)
    assert report.over_committed_ids == []
    assert report.critical_path_days == 20.0


def test_working_calendar_skips_egypt_weekend():
    """Friday and Saturday are non-working; Sunday and weekdays are."""
    cal = CALENDAR
    # Jan 30 2026 is a Friday
    assert not cal.is_working_day(date(2026, 1, 30))
    # Jan 31 2026 is a Saturday
    assert not cal.is_working_day(date(2026, 1, 31))
    # Feb 1 2026 is a Sunday — working day in Egypt
    assert cal.is_working_day(date(2026, 2, 1))
    # May 1 2026 is Labor Day (in calendar.yaml)
    assert not cal.is_working_day(date(2026, 5, 1))
