import time
from typing import Any

import requests


class TrelloError(RuntimeError):
    pass


class TrelloClient:
    BASE_URL = "https://api.trello.com/1"

    def __init__(self, api_key: str, api_token: str) -> None:
        if not api_key or not api_token:
            raise TrelloError(
                "TRELLO_API_KEY and TRELLO_API_TOKEN must both be set."
            )
        self.api_key = api_key
        self.api_token = api_token
        self._session = requests.Session()

    # ------------------------------------------------------------------ core

    def _auth_params(self) -> dict[str, str]:
        return {"key": self.api_key, "token": self.api_token}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.BASE_URL}{path}"
        merged: dict[str, Any] = {**self._auth_params(), **(params or {})}
        for attempt in range(6):
            r = self._session.request(method, url, params=merged, timeout=30)
            if r.status_code == 429:
                # Rate limited — exponential backoff up to ~30s
                delay = min(2 ** attempt, 30)
                time.sleep(delay)
                continue
            if not r.ok:
                raise TrelloError(
                    f"{method} {path} → HTTP {r.status_code}: {r.text[:200]}"
                )
            if not r.content:
                return {}
            return r.json()
        raise TrelloError(f"{method} {path} failed after retries (rate limited)")

    # ------------------------------------------------------------------ boards

    def list_boards(self) -> list[dict]:
        return self._request(
            "GET", "/members/me/boards", params={"fields": "id,name,closed"}
        )

    def get_or_create_board(self, name: str) -> dict:
        for b in self.list_boards():
            if b["name"] == name and not b.get("closed"):
                return b
        # `defaultLists=false` prevents Trello from creating its default To-Do /
        # Doing / Done lists — we want to control the list set ourselves.
        return self._request(
            "POST", "/boards/", params={"name": name, "defaultLists": "false"}
        )

    # ------------------------------------------------------------------ lists

    def list_lists(self, board_id: str) -> list[dict]:
        return self._request(
            "GET", f"/boards/{board_id}/lists", params={"fields": "id,name"}
        )

    def get_or_create_list(self, board_id: str, name: str) -> dict:
        for lst in self.list_lists(board_id):
            if lst["name"] == name:
                return lst
        return self._request(
            "POST", "/lists", params={"name": name, "idBoard": board_id}
        )

    # ------------------------------------------------------------------ labels

    def list_labels(self, board_id: str) -> list[dict]:
        return self._request(
            "GET",
            f"/boards/{board_id}/labels",
            params={"fields": "id,name,color", "limit": 1000},
        )

    def get_or_create_label(
        self, board_id: str, name: str, color: str = "sky"
    ) -> dict:
        for l in self.list_labels(board_id):
            if l["name"] == name:
                return l
        return self._request(
            "POST",
            "/labels",
            params={"name": name, "color": color, "idBoard": board_id},
        )

    # ------------------------------------------------------------------ cards

    def create_card(
        self,
        list_id: str,
        name: str,
        desc: str,
        due: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict:
        params: dict[str, Any] = {
            "idList": list_id,
            "name": name,
            "desc": desc,
        }
        if due:
            params["due"] = due
        if label_ids:
            params["idLabels"] = ",".join(label_ids)
        return self._request("POST", "/cards", params=params)

    def update_card(self, card_id: str, **fields: Any) -> dict:
        """Update card fields — `name`, `desc`, `due`, `idList`, `closed`."""
        return self._request("PUT", f"/cards/{card_id}", params=fields)

    def move_card_to_list(self, card_id: str, list_id: str) -> dict:
        return self.update_card(card_id, idList=list_id)

    # ------------------------------------------------------------------ checklists

    def add_checklist(
        self, card_id: str, name: str, items: list[str]
    ) -> dict:
        checklist = self._request(
            "POST", "/checklists", params={"idCard": card_id, "name": name}
        )
        for item in items:
            self._request(
                "POST",
                f"/checklists/{checklist['id']}/checkItems",
                params={"name": item},
            )
        return checklist
