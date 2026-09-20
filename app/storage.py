"""in-memory 儲存層（無 DB 依賴，方便課堂與 demo）。"""
from .models import Issue, IssueCreate


class IssueStore:
    def __init__(self) -> None:
        self._items: dict[int, Issue] = {}
        self._next_id = 1

    def add(self, payload: IssueCreate) -> Issue:
        issue = Issue(id=self._next_id, title=payload.title, status=payload.status)
        self._items[issue.id] = issue
        self._next_id += 1
        return issue

    def all(self) -> list[Issue]:
        return list(self._items.values())

    def get(self, issue_id: int) -> Issue | None:
        return self._items.get(issue_id)
