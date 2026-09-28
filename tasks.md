<!--
  預錄的 `/speckit.tasks` 產出（feature: issue 標籤與查詢）。

  這份檔案是 demo 的 fallback，也是 Act 4 的教材：模型在 T012 與 T014 都標了 [P]，
  但兩者都寫 `app/main.py`。Spec Kit 的 command template 明確禁止這件事
  （「[P] 只在操作不同檔案時加」），模型還是做了。**沒有機器在檢查。**

  `(deps: …, reads: …)` 的行內標註不是 Spec Kit 原生格式，是本課用 constitution
  第五條要求模型補上的 —— 目的就是讓 tasks_lint.py 能建圖。
-->

# Tasks: Issue 標籤與查詢

**Feature**: `001-issue-labels` ｜ **Input**: `specs/001-issue-labels/plan.md`
**Tests**: 每個 user story 先寫失敗測試再實作（constitution §3）

## Phase 1: Setup

- [ ] T001 在 `requirements.txt` 補上 `httpx` 與 `pytest-asyncio` 測試依賴
- [ ] T002 [P] 建立共用 fixture（TestClient、乾淨的 store）於 `tests/conftest.py`

## Phase 2: Foundational

> 這一層阻塞所有 user story：資料模型與儲存層介面先定案，story 才能並行。

- [ ] T003 在 `app/models.py` 為 `Issue` 與 `IssueCreate` 加上 `labels: list[str] = []` 欄位
- [ ] T004 在 `app/storage.py` 為 `IssueStore` 加上 `_by_label` 反向索引與 `add()` 的維護邏輯 (deps: T003)
- [ ] T005 [P] 在 `app/errors.py` 定義 `IssueNotFound` 例外與 `to_http()` 轉換 helper (deps: T003)

## Phase 3: User Story 1 — 依 id 取得單一 issue (P1)

**目標**：`GET /issues/{issue_id}` 回傳單一 issue；不存在時回 404。
**獨立驗收**：不依賴 US2／US3 即可測。

- [ ] T006 [P] [US1] 在 `tests/test_issues.py` 補上 `test_get_by_id` 與 `test_get_missing_returns_404`（先紅）(deps: T002)
- [ ] T007 [US1] 在 `app/storage.py` 確認 `get()` 回 `Optional[Issue]`、不 raise (deps: T004)
- [ ] T008 [US1] 在 `app/main.py` 實作 `GET /issues/{issue_id}`，路由層把 `None` 轉成 `HTTPException(404)` (deps: T006, T007, reads: `app/models.py`)
- [ ] T009 [US1] 移除 `tests/test_issues.py` 既有的 `xfail` 標記 (deps: T008)

## Phase 4: User Story 2 — 依 label 篩選 (P2)

**目標**：`GET /issues?label=bug` 只回帶該 label 的 issue。
**獨立驗收**：US1 未完成也能測。

- [ ] T010 [P] [US2] 在 `tests/test_labels.py` 寫 `test_filter_by_label`、`test_unknown_label_returns_empty`（先紅）(deps: T002)
- [ ] T011 [P] [US2] 在 `app/storage.py` 實作 `by_label(label: str) -> list[Issue]`，走反向索引 (deps: T004)
- [ ] T012 [P] [US2] 在 `app/main.py` 為 `GET /issues` 加上 `label: str | None = None` query 參數與篩選分支 (deps: T011)
- [ ] T013 [P] [US2] 在 `app/models.py` 加上 `LabelQuery` 驗證模型（label 需為小寫、長度 1–32）(deps: T003)
- [ ] T014 [P] [US2] 在 `app/main.py` 套用 `LabelQuery` 驗證，非法 label 回 422 (deps: T013)

## Phase 5: User Story 3 — 清單分頁 (P3)

**目標**：`GET /issues?limit=&offset=` 分頁，並在 `X-Total-Count` 回總數。

- [ ] T015 [P] [US3] 在 `tests/test_pagination.py` 寫 `test_limit_offset`、`test_total_count_header`（先紅）(deps: T002)
- [ ] T016 [P] [US3] 在 `app/storage.py` 為 `all()` 加上 `limit`／`offset` 參數與 `count()` (deps: T004)
- [ ] T017 [P] [US3] 在 `app/main.py` 為 `GET /issues` 加上分頁參數與 `X-Total-Count` 標頭 (deps: T016)
- [ ] T018 [P] [US3] 在 `docs/api.md` 補上分頁與篩選的說明 (deps: T017)

## Phase 6: Polish

- [ ] T019 [P] 在 `README.md` 更新 endpoint 一覽表 (deps: T008, T012, T017)
- [ ] T020 [P] 在 `tests/test_issues.py` 補上 label + 分頁的組合情境測試 (deps: T012, T017)
- [ ] T021 全量跑 `pytest -q`，確認無 `xpassed` (deps: T019, T020)

## Dependencies & Execution Order

- Phase 1 → Phase 2 為硬性 checkpoint。
- Phase 3／4／5 三個 story 彼此獨立，理論上可由三個 agent 並行認領。
- Phase 6 需等所有 story 完成。
