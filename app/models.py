"""資料模型（Pydantic）。課堂範例：issue tracker。"""
from datetime import datetime, timezone
from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IssueCreate(BaseModel):
    """建立 issue 時的輸入。"""
    title: str = Field(min_length=1, max_length=200)
    status: str = Field(default="open")


class Issue(BaseModel):
    """完整 issue（含系統產生欄位）。"""
    id: int
    title: str
    status: str
    created_at: datetime = Field(default_factory=_now)
