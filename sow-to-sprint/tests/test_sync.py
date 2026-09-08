from datetime import date, datetime
from pathlib import Path

import pytest

from src.models import SOWExtraction, WorkItem
from src.store import Store
from src.sync import content_hash, sync


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _FakeTrelloClient:
    """In-memory replacement for TrelloClient — records every call."""

    def __init__(self) -> None:
        self.boards: dict[str, dict] = {}
        self.lists: dict[str, dict] = {}
        self.cards: dict[str, dict] = {}
        self.checklists: dict[str, dict] = {}
        self._id_counter = 0

    def _next_id(self, prefix: str) -> str:
        self._id_counter += 1
        return f"{prefix}-{self._id_counter}"

    def get_or_create_board(self, name: str) -> dict:
        for b in self.boards.values():
            if b["name"] == name:
                return b
        bid = self._next_id("board")
        self.boards[bid] = {"id": bid, "name": name}
        return self.boards[bid]

    def get_or_create_list(self, board_id: str, name: str) -> dict:
        for lst in self.lists.values():
            if lst["idBoard"] == board_id and lst["name"] == name:
                return lst
        lid = self._next_id("list")
        self.lists[lid] = {"id": lid, "name": name, "idBoard": board_id}
        return self.lists[lid]

    def create_card(
        self,
        list_id: str,
        name: str,
        desc: str,
        due: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict:
        cid = self._next_id("card")
        self.cards[cid] = {
            "id": cid,
            "name": name,
            "desc": desc,
            "idList": list_id,
            "due": due,
        }
        return self.cards[cid]

    def update_card(self, card_id: str, **fields) -> dict:
        self.cards[card_id].update(fields)
        return self.cards[card_id]

    def move_card_to_list(self, card_id: str, list_id: str) -> dict:
        return self.update_card(card_id, idList=list_id)

    def add_checklist(self, card_id: str, name: str, items: list[str]) -> dict:
        cl_id = self._next_id("checklist")
        self.checklists[cl_id] = {
            "id": cl_id,
            "idCard": card_id,
            "name": name,
            "items": items,
        }
        return self.checklists[cl_id]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mk_extraction() -> SOWExtraction:
    return SOWExtraction(
        sow_id="TEST",
        version=1,
        client_name="Client",
        project_name="Proj",
        signature_date=date(2026, 1, 1),
        delivery_date=date(2026, 6, 30),
        modules=["M"],
    )


def _mk_item(id: str, title: str, status: str = "approved") -> WorkItem:
    return WorkItem(
        id=id,
        type="user_story",
        function="technical",
        title=title,
        description="desc",
        acceptance_criteria=["ac1"],
        estimate_days=2.0,
        depends_on=[],
        phase="Build",
        source_clause_id="C-001",
        source_excerpt="excerpt",
        confidence="high",
        status=status,  # type: ignore[arg-type]
        start_date=date(2026, 2, 1),
        due_date=date(2026, 2, 5),
    )


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_first_sync_creates_every_approved_item(store: Store):
    ext = _mk_extraction()
    items = [_mk_item(f"T-{i}", f"item {i}") for i in range(3)]
    store.start_run("run-1", ext.sow_id, ext.version, "test.docx")
    store.save_work_items("run-1", items)

    client = _FakeTrelloClient()
    result = sync("run-1", ext, items, store, client=client)

    assert len(result.created) == 3
    assert len(result.updated) == 0
    assert len(result.skipped) == 0
    assert len(client.cards) == 3


def test_second_identical_sync_creates_zero_duplicates(store: Store):
    """Master plan §9 Phase 6 acceptance line."""
    ext = _mk_extraction()
    items = [_mk_item(f"T-{i}", f"item {i}") for i in range(3)]
    store.start_run("run-1", ext.sow_id, ext.version, "test.docx")
    store.save_work_items("run-1", items)

    client = _FakeTrelloClient()
    sync("run-1", ext, items, store, client=client)
    cards_after_first = dict(client.cards)

    # Run again with unchanged items
    result2 = sync("run-1", ext, items, store, client=client)

    assert len(result2.created) == 0, "should not create new cards on identical re-run"
    assert len(result2.updated) == 0, "no updates expected — nothing changed"
    assert len(result2.skipped) == 3
    assert client.cards == cards_after_first, "no cards should have changed"


def test_editing_one_item_causes_exactly_one_update(store: Store):
    ext = _mk_extraction()
    items = [_mk_item(f"T-{i}", f"item {i}") for i in range(3)]
    store.start_run("run-1", ext.sow_id, ext.version, "test.docx")
    store.save_work_items("run-1", items)
    client = _FakeTrelloClient()
    sync("run-1", ext, items, store, client=client)

    # Edit one item's title
    items[1].title = "item 1 (edited)"
    items[1].status = "edited"

    result = sync("run-1", ext, items, store, client=client)

    assert len(result.created) == 0
    assert len(result.updated) == 1
    assert result.updated == ["T-1"]
    assert len(result.skipped) == 2
    # No new Trello card was made — total card count unchanged.
    assert len(client.cards) == 3


def test_content_hash_stable_for_identical_items():
    a = _mk_item("A", "same")
    b = _mk_item("B", "same")  # different id, same content
    assert content_hash(a) == content_hash(b)


def test_content_hash_changes_when_title_changes():
    a = _mk_item("A", "before")
    b = _mk_item("A", "after")
    assert content_hash(a) != content_hash(b)


def test_rejected_items_not_pushed(store: Store):
    ext = _mk_extraction()
    items = [
        _mk_item("T-0", "keep", status="approved"),
        _mk_item("T-1", "drop", status="rejected"),
        _mk_item("T-2", "still-thinking", status="generated"),
    ]
    store.start_run("run-1", ext.sow_id, ext.version, "test.docx")
    store.save_work_items("run-1", items)
    client = _FakeTrelloClient()
    result = sync("run-1", ext, items, store, client=client)

    assert result.created == ["T-0"]
    assert len(client.cards) == 1
