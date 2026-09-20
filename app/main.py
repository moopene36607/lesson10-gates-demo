"""Issue Tracker API（課堂範例載體）。

刻意只實作 create + list；GET /issues/{id} 故意保留為缺口，
於試教 demo 現場由 Claude Code 補上、Codex 交叉驗證。
"""
from fastapi import FastAPI, HTTPException
from .models import Issue, IssueCreate
from .storage import IssueStore

app = FastAPI(title="Issue Tracker (course sample)")
store = IssueStore()


@app.post("/issues", response_model=Issue, status_code=201)
def create_issue(payload: IssueCreate) -> Issue:
    return store.add(payload)


@app.get("/issues", response_model=list[Issue])
def list_issues() -> list[Issue]:
    return store.all()


@app.get("/issues/{issue_id}", response_model=Issue)
def get_issue(issue_id: int) -> Issue:
    """依 id 取單一 issue；找不到回 404。"""
    issue = store.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="issue not found")
    return issue
