import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.decompose import decompose
from src.extract import extract_sow
from src.ingest import IngestedDoc, ingest_docx
from src.models import SOWExtraction, WorkItem
from src.schedule import ScheduleReport, WorkingCalendar, schedule
from src.store import Store, default_store


@dataclass
class PipelineResult:
    run_id: str
    ingested: IngestedDoc
    extraction: SOWExtraction
    work_items: list[WorkItem]
    report: ScheduleReport


def run_pipeline(
    sow_path: str | Path,
    *,
    store: Store | None = None,
    calendar: WorkingCalendar | None = None,
) -> PipelineResult:
    """Run every stage against `sow_path` and persist the outputs.

    Idempotency for the same SOW version is caller's responsibility — this
    function always starts a fresh `run_id` unless the caller passes one.
    """
    store = store or default_store()
    calendar = calendar or WorkingCalendar.load()

    ingested = ingest_docx(sow_path)
    extraction = extract_sow(ingested)

    run_id = f"{extraction.sow_id}-v{extraction.version}-{_short_id()}"
    store.start_run(
        run_id=run_id,
        sow_id=extraction.sow_id,
        version=extraction.version,
        source_file=str(sow_path),
    )
    store.save_extraction(run_id, extraction)

    work_items = decompose(extraction)
    report = schedule(extraction, work_items, calendar=calendar)
    store.save_work_items(run_id, work_items)
    store.complete_run(run_id)

    return PipelineResult(
        run_id=run_id,
        ingested=ingested,
        extraction=extraction,
        work_items=work_items,
        report=report,
    )


def load_existing_run(
    run_id: str,
    *,
    store: Store | None = None,
    calendar: WorkingCalendar | None = None,
) -> PipelineResult | None:
    """Recover a previously-persisted run without re-invoking the LLM.

    The schedule report is recomputed on load (cheap; deterministic).
    """
    store = store or default_store()
    calendar = calendar or WorkingCalendar.load()

    extraction = store.load_extraction(run_id)
    if extraction is None:
        return None
    work_items = store.load_work_items(run_id)
    if not work_items:
        return None
    report = schedule(extraction, work_items, calendar=calendar)
    return PipelineResult(
        run_id=run_id,
        ingested=IngestedDoc(source_file="(loaded from store)", clauses=[], annotated_text=""),
        extraction=extraction,
        work_items=work_items,
        report=report,
    )


def _short_id() -> str:
    return uuid.uuid4().hex[:8]
