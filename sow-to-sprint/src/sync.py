import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

from typing import TYPE_CHECKING

from src.config import get_settings
from src.models import SOWExtraction, SyncRecord, WorkItem
from src.store import Store
from src.trello_client import TrelloClient

if TYPE_CHECKING:
    from src.diff import DiffReport


REMOVED_LIST_NAME = "Removed by CR"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SyncResult:
    created: list[str] = field(default_factory=list)   # work_item ids
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    archived: list[str] = field(default_factory=list)  # moved to "Removed by CR"

    def summary(self) -> str:
        return (
            f"created={len(self.created)}, updated={len(self.updated)}, "
            f"skipped={len(self.skipped)}, archived={len(self.archived)}"
        )


# ---------------------------------------------------------------------------
# Content hashing (the anchor of idempotency)
# ---------------------------------------------------------------------------

def content_hash(item: WorkItem) -> str:
    """Stable hash over the fields that determine card content.

    Deliberately excludes `id`, `status`, `depends_on`, `source_*` — those
    are metadata / provenance, not user-visible card content.
    """
    payload = json.dumps(
        {
            "title": item.title,
            "description": item.description,
            "acceptance_criteria": item.acceptance_criteria,
            "gherkin": item.gherkin,
            "due_date": str(item.due_date) if item.due_date else None,
            "start_date": str(item.start_date) if item.start_date else None,
            "assignee": item.assignee,
            "squad": item.squad,
            "estimate_days": item.estimate_days,
            "phase": item.phase,
            "confidence": item.confidence,
        },
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Card content builders
# ---------------------------------------------------------------------------

_BOARD_PREFIX = "Delta Rewards"


def _board_name(function: str) -> str:
    return f"{_BOARD_PREFIX} — {function.title()}"


def _card_description(item: WorkItem, extraction: SOWExtraction) -> str:
    parts: list[str] = [item.description.strip()]

    if item.gherkin:
        parts.append("\n**Gherkin**")
        parts.append("```gherkin")
        parts.append(item.gherkin.strip())
        parts.append("```")

    parts.append("")
    parts.append("**Delivery metadata**")
    if item.squad:
        parts.append(f"- Squad: {item.squad}")
    if item.assignee:
        parts.append(f"- Assignee: {item.assignee}")
    parts.append(f"- Estimate: {item.estimate_days} working days")
    parts.append(f"- Phase: {item.phase}")
    parts.append(f"- Confidence: {item.confidence}")
    parts.append("")
    parts.append("---")
    parts.append(
        f"_Source: {extraction.sow_id} v{extraction.version}, clause "
        f"`{item.source_clause_id}`_"
    )
    parts.append(f"> {item.source_excerpt}")
    return "\n".join(parts)


def _due_iso(item: WorkItem) -> str | None:
    return item.due_date.isoformat() if item.due_date else None


# ---------------------------------------------------------------------------
# Sync orchestration
# ---------------------------------------------------------------------------

def sync(
    run_id: str,
    extraction: SOWExtraction,
    work_items: list[WorkItem],
    store: Store,
    *,
    client: TrelloClient | None = None,
    include_rejected: bool = False,
) -> SyncResult:
    """Push approved WorkItems to Trello. Returns a SyncResult breakdown.

    Only items with `status in {approved, edited}` are pushed; the rest
    (`generated`, `rejected`) are considered "not to be pushed" and, if
    they had cards from a previous run, are archived to "Removed by CR".
    """
    if client is None:
        settings = get_settings()
        client = TrelloClient(settings.trello_api_key, settings.trello_api_token)

    push_states = {"approved", "edited"}
    to_push = [it for it in work_items if it.status in push_states]
    push_ids = {it.id for it in to_push}

    existing = {sr.work_item_id: sr for sr in store.get_sync_records(run_id)}

    # Cache resource ids we've resolved this run — one round-trip per (board,
    # list) pair instead of one per card.
    board_id_by_function: dict[str, str] = {}
    list_id_by_key: dict[tuple[str, str], str] = {}

    def _board_for(function: str) -> str:
        if function not in board_id_by_function:
            b = client.get_or_create_board(_board_name(function))
            board_id_by_function[function] = b["id"]
        return board_id_by_function[function]

    def _list_for(board_id: str, name: str) -> str:
        key = (board_id, name)
        if key not in list_id_by_key:
            lst = client.get_or_create_list(board_id, name)
            list_id_by_key[key] = lst["id"]
        return list_id_by_key[key]

    result = SyncResult()

    # ---- 1a. pre-resolve every (board, list) sequentially -------------------
    # Trello has no atomic get-or-create, so if multiple worker threads race
    # on the same missing board/list they'd both create it. Resolve them all
    # upfront on the main thread. Cheap: at most ~20 calls per sync.

    for item in to_push:
        board_id = _board_for(item.function)
        _list_for(board_id, item.phase)

    # ---- 1b. push / update the approved queue in parallel --------------------
    # Each card is 5+ API calls (create + checklist + one per criterion), so
    # sequential sync scales linearly with cards. A bounded thread pool
    # (max_workers=8) keeps us well under Trello's 100-req/10s rate limit
    # while cutting a 74-card push from ~110s to ~15-20s.
    #
    # `store_lock` serializes sqlite writes across worker threads — the
    # default sqlite connection cannot handle concurrent transactions even
    # with check_same_thread=False. Store writes are ~1ms so the lock is
    # not a bottleneck.

    store_lock = threading.Lock()

    def _save_record(rec: SyncRecord) -> None:
        with store_lock:
            store.save_sync_record(run_id, rec)

    def _push_one(item: WorkItem) -> None:
        board_id = board_id_by_function[item.function]
        list_id = list_id_by_key[(board_id, item.phase)]
        desc = _card_description(item, extraction)
        due = _due_iso(item)
        h = content_hash(item)

        prev = existing.get(item.id)
        if prev is None:
            card = client.create_card(list_id, item.title, desc, due=due)
            if item.acceptance_criteria:
                client.add_checklist(
                    card["id"], "Acceptance criteria", item.acceptance_criteria
                )
            _save_record(SyncRecord(
                work_item_id=item.id,
                trello_board_id=board_id,
                trello_list_id=list_id,
                trello_card_id=card["id"],
                content_hash=h,
                synced_at=datetime.now(),
            ))
            result.created.append(item.id)
            return

        unchanged = prev.content_hash == h and prev.trello_list_id == list_id
        if unchanged:
            result.skipped.append(item.id)
            return

        client.update_card(
            prev.trello_card_id, name=item.title, desc=desc, due=due or ""
        )
        if prev.trello_list_id != list_id:
            client.move_card_to_list(prev.trello_card_id, list_id)
        _save_record(SyncRecord(
            work_item_id=item.id,
            trello_board_id=board_id,
            trello_list_id=list_id,
            trello_card_id=prev.trello_card_id,
            content_hash=h,
            synced_at=datetime.now(),
        ))
        result.updated.append(item.id)

    if to_push:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for fut in [pool.submit(_push_one, it) for it in to_push]:
                fut.result()  # re-raises any worker exception on the main thread

    # ---- 2. archive cards for items dropped from the push queue -------------
    # (only if the caller wants CR-style archival)

    if include_rejected:
        for wid, prev in existing.items():
            if wid in push_ids:
                continue
            removed_list_id = _list_for(prev.trello_board_id, REMOVED_LIST_NAME)
            client.move_card_to_list(prev.trello_card_id, removed_list_id)
            store.save_sync_record(
                run_id,
                SyncRecord(
                    work_item_id=wid,
                    trello_board_id=prev.trello_board_id,
                    trello_list_id=removed_list_id,
                    trello_card_id=prev.trello_card_id,
                    content_hash=prev.content_hash,
                    synced_at=datetime.now(),
                ),
            )
            result.archived.append(wid)

    return result


# ---------------------------------------------------------------------------
# Dry-run (no API calls)
# ---------------------------------------------------------------------------

def apply_change_request(
    base_run_id: str,
    cr_run_id: str,
    diff: "DiffReport",
    cr_extraction: SOWExtraction,
    cr_items: list[WorkItem],
    store: Store,
    *,
    client: TrelloClient | None = None,
) -> SyncResult:
    """Push a change-request run (v2) to Trello, reusing the Trello card ids
    from the base run (v1) for structurally-matched items.

    For each pair in `diff.unchanged + diff.changed`, we copy the v1 card
    id onto a fresh SyncRecord keyed by the v2 (run, item). Then we run the
    normal `sync()` with `include_rejected=True`, which will:
        - skip unchanged pairs (same hash)
        - update changed pairs (different hash on the existing card)
        - create cards for `diff.added` items
        - archive cards that existed under `base_run_id` but not under `cr_run_id`
    """
    # 1. Carry v1's card ids onto v2's run_id for matched pairs.
    base_syncs = {sr.work_item_id: sr for sr in store.get_sync_records(base_run_id)}
    for v1_it, v2_it in diff.unchanged + diff.changed:
        prev = base_syncs.get(v1_it.id)
        if not prev:
            continue
        store.save_sync_record(
            cr_run_id,
            SyncRecord(
                work_item_id=v2_it.id,
                trello_board_id=prev.trello_board_id,
                trello_list_id=prev.trello_list_id,
                trello_card_id=prev.trello_card_id,
                content_hash=prev.content_hash,  # keep v1 hash — the update path will refresh it
                synced_at=prev.synced_at,
            ),
        )
    # 2. Also carry SyncRecords for `removed` items so `include_rejected` finds them.
    for removed_v1 in diff.removed:
        prev = base_syncs.get(removed_v1.id)
        if not prev:
            continue
        # Mark under cr_run_id but the item isn't in the v2 push queue,
        # so `include_rejected=True` will archive the card.
        store.save_sync_record(
            cr_run_id,
            SyncRecord(
                work_item_id=removed_v1.id,
                trello_board_id=prev.trello_board_id,
                trello_list_id=prev.trello_list_id,
                trello_card_id=prev.trello_card_id,
                content_hash=prev.content_hash,
                synced_at=prev.synced_at,
            ),
        )

    # 3. Now sync — carried records make it idempotent.
    return sync(
        cr_run_id,
        cr_extraction,
        cr_items,
        store,
        client=client,
        include_rejected=True,
    )


def dry_run(
    run_id: str,
    extraction: SOWExtraction,
    work_items: list[WorkItem],
    store: Store,
) -> SyncResult:
    """Simulate `sync` without hitting the Trello API.

    Uses the stored `SyncRecord`s to decide create vs update vs skip so the
    numbers match what a real push would do.
    """
    push_states = {"approved", "edited"}
    to_push = [it for it in work_items if it.status in push_states]
    existing = {sr.work_item_id: sr for sr in store.get_sync_records(run_id)}
    result = SyncResult()
    for item in to_push:
        h = content_hash(item)
        prev = existing.get(item.id)
        if prev is None:
            result.created.append(item.id)
        elif prev.content_hash == h:
            result.skipped.append(item.id)
        else:
            result.updated.append(item.id)
    return result
