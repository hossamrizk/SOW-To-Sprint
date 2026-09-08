import json
import sqlite3
from datetime import datetime
from pathlib import Path

from src.models import SOWExtraction, SyncRecord, WorkItem


# Anchor the store path to the project root so it doesn't move around
# with the caller's working directory (Streamlit, notebooks, etc.).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _PROJECT_ROOT / "data" / "runs" / "store.db"


class Store:
    def __init__(self, path: str | Path = _DEFAULT_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    # ------------------------------------------------------------------ schema

    def _init_schema(self) -> None:
        c = self._conn.cursor()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id       TEXT PRIMARY KEY,
                sow_id       TEXT NOT NULL,
                version      INTEGER NOT NULL,
                source_file  TEXT,
                started_at   TIMESTAMP,
                completed_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS extractions (
                run_id  TEXT PRIMARY KEY REFERENCES runs(run_id),
                payload TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS work_items (
                run_id     TEXT NOT NULL REFERENCES runs(run_id),
                item_id    TEXT NOT NULL,
                payload    TEXT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'generated',
                updated_at TIMESTAMP,
                PRIMARY KEY (run_id, item_id)
            );

            CREATE TABLE IF NOT EXISTS sync_records (
                run_id           TEXT NOT NULL,
                item_id          TEXT NOT NULL,
                trello_board_id  TEXT NOT NULL,
                trello_list_id   TEXT NOT NULL,
                trello_card_id   TEXT NOT NULL,
                content_hash     TEXT NOT NULL,
                synced_at        TIMESTAMP NOT NULL,
                PRIMARY KEY (run_id, item_id)
            );
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------ runs

    def start_run(self, run_id: str, sow_id: str, version: int, source_file: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, sow_id, version, source_file, started_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, sow_id, version, source_file, datetime.now().isoformat()),
        )
        self._conn.commit()

    def complete_run(self, run_id: str) -> None:
        self._conn.execute(
            "UPDATE runs SET completed_at = ? WHERE run_id = ?",
            (datetime.now().isoformat(), run_id),
        )
        self._conn.commit()

    def list_runs(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT run_id, sow_id, version, source_file, started_at, completed_at "
            "FROM runs ORDER BY started_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def latest_run_for(self, sow_id: str, version: int) -> str | None:
        row = self._conn.execute(
            "SELECT run_id FROM runs WHERE sow_id = ? AND version = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (sow_id, version),
        ).fetchone()
        return row["run_id"] if row else None

    # ------------------------------------------------------------------ extractions

    def save_extraction(self, run_id: str, extraction: SOWExtraction) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO extractions (run_id, payload) VALUES (?, ?)",
            (run_id, extraction.model_dump_json()),
        )
        self._conn.commit()

    def load_extraction(self, run_id: str) -> SOWExtraction | None:
        row = self._conn.execute(
            "SELECT payload FROM extractions WHERE run_id = ?", (run_id,)
        ).fetchone()
        return SOWExtraction.model_validate_json(row["payload"]) if row else None

    # ------------------------------------------------------------------ work items

    def save_work_items(self, run_id: str, items: list[WorkItem]) -> None:
        now = datetime.now().isoformat()
        rows = [
            (run_id, it.id, it.model_dump_json(), it.status, now) for it in items
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO work_items "
            "(run_id, item_id, payload, status, updated_at) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def load_work_items(self, run_id: str) -> list[WorkItem]:
        rows = self._conn.execute(
            "SELECT payload, status FROM work_items WHERE run_id = ? "
            "ORDER BY item_id",
            (run_id,),
        ).fetchall()
        out: list[WorkItem] = []
        for r in rows:
            it = WorkItem.model_validate_json(r["payload"])
            it.status = r["status"]  # ensure current status is applied
            out.append(it)
        return out

    def update_item(self, run_id: str, item: WorkItem) -> None:
        """Persist an edited or reviewed work item back to the store."""
        self._conn.execute(
            "UPDATE work_items SET payload = ?, status = ?, updated_at = ? "
            "WHERE run_id = ? AND item_id = ?",
            (
                item.model_dump_json(),
                item.status,
                datetime.now().isoformat(),
                run_id,
                item.id,
            ),
        )
        self._conn.commit()

    def set_item_status(self, run_id: str, item_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE work_items SET status = ?, updated_at = ? "
            "WHERE run_id = ? AND item_id = ?",
            (status, datetime.now().isoformat(), run_id, item_id),
        )
        self._conn.commit()

    def bulk_set_status_by_function(
        self, run_id: str, function: str, status: str
    ) -> int:
        """Approve/reject every item in a function in one shot. Returns count."""
        # We store payload as JSON, so we need to filter after load. Small.
        items = self.load_work_items(run_id)
        touched = [it for it in items if it.function == function]
        for it in touched:
            it.status = status  # type: ignore[assignment]
        for it in touched:
            self.update_item(run_id, it)
        return len(touched)

    # ------------------------------------------------------------------ sync records

    def save_sync_record(self, run_id: str, rec: SyncRecord) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO sync_records "
            "(run_id, item_id, trello_board_id, trello_list_id, trello_card_id, "
            " content_hash, synced_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                rec.work_item_id,
                rec.trello_board_id,
                rec.trello_list_id,
                rec.trello_card_id,
                rec.content_hash,
                rec.synced_at.isoformat(),
            ),
        )
        self._conn.commit()

    def get_sync_records(self, run_id: str) -> list[SyncRecord]:
        rows = self._conn.execute(
            "SELECT * FROM sync_records WHERE run_id = ?", (run_id,)
        ).fetchall()
        return [
            SyncRecord(
                work_item_id=r["item_id"],
                trello_board_id=r["trello_board_id"],
                trello_list_id=r["trello_list_id"],
                trello_card_id=r["trello_card_id"],
                content_hash=r["content_hash"],
                synced_at=datetime.fromisoformat(r["synced_at"]),
            )
            for r in rows
        ]


def default_store() -> Store:
    return Store()
