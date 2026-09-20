<!--
  Act 4 的修正結果。三種修法各出現一次 —— 這是本堂最重要的分類：

  A. 架構切割（accidental conflict）
     T008/T011 原本都改 `app/main.py`，只因為所有 route 擠在同一個檔案。
     把 main.py 拆成 APIRouter（T006 於 Foundational 一次做完），衝突就消失。
     → 「並行度是架構屬性，不是排程屬性。」

  B. 序列化（essential conflict）
     US2 的 label 篩選和 US3 的分頁**都在改同一個 list handler 的簽名**。
     這不是檔案擺放的問題，拆檔救不了。只能加依賴讓它們排隊：T013 (deps: T011)。

  C. 單一寫者（same-module churn）
     原本 T007/T011/T016 三個 task 輪流改 `app/storage.py`。
     合併成 T004 一個 task、一個擁有者，一次改完。

  驗收：`python tasks_lint.py tasks.fixed.md --no-phase-barriers` → 0 error。
  注意理論加速從 3.5× 掉到 2.83× —— **安全性是用並行度換的。** 這是實話，要講。

  ⚠ 這份檔案**故意留了一個 WARN**：T008 讀 `app/errors.py`，卻沒有依賴寫它的 T005。
     這是真的 write-read hazard（T008 可能讀到還不存在的檔案），不是假的。
     Demo Act 4 收尾時現場把 `T005` 加進 T008 的 deps，就會看到 0 error 0 warning。
     這個 bug 是 linter 在我寫這份「正確答案」時抓到的 —— 照實講，那才是它的價值。
-->

# Tasks: Issue 標籤與查詢（修正後）

**Feature**: `001-issue-labels` ｜ **Input**: `specs/001-issue-labels/plan.md`
**驗收**：`tasks_lint.py --no-phase-barriers` 零 error（constitution §5）

## Phase 1: Setup

- [ ] T001 在 `requirements.txt` 補上 `httpx` 與 `pytest-asyncio` 測試依賴
- [ ] T002 [P] 建立共用 fixture（TestClient、乾淨的 store）於 `tests/conftest.py`

## Phase 2: Foundational

> 所有 story 的共用寫入都收斂到這一層，且**每個檔案只有一個擁有者**。
> Story phase 一旦開始，`app/models.py`、`app/storage.py`、`app/main.py` 就不再被任何人碰。

- [ ] T003 在 `app/models.py` 一次加完 `Issue.labels: list[str]` 與 `LabelQuery` 驗證模型（單一寫者）
- [ ] T004 在 `app/storage.py` 一次加完 `_by_label` 反向索引、`by_label()`、`all(limit, offset)` 與 `count()`；`get()` 維持回 `Optional[Issue]` 不 raise（單一寫者，修法 C）(deps: T003)
- [ ] T005 [P] 在 `app/errors.py` 定義 `IssueNotFound` 與 `to_http()` (deps: T003)
- [ ] T006 把 `app/main.py` 改為只做 `APIRouter` 掛載，路由實作移到 `app/routers/__init__.py`（修法 A：拆掉三個 story 的共同寫入點）(deps: T003)

## Phase 3: User Story 1 — 依 id 取得單一 issue (P1)

- [ ] T007 [P] [US1] 在 `tests/test_issues.py` 補上 `test_get_by_id` 與 `test_get_missing_returns_404`（先紅）(deps: T002)
- [ ] T008 [US1] 在 `app/routers/detail.py` 實作 `GET /issues/{issue_id}`，路由層把 `None` 轉成 `HTTPException(404)` (deps: T004, T006, T007, reads: `app/models.py`, `app/errors.py`)
- [ ] T009 [US1] 移除 `tests/test_issues.py` 的 `xfail` 標記 (deps: T008)

## Phase 4: User Story 2 — 依 label 篩選 (P2)

- [ ] T010 [P] [US2] 在 `tests/test_labels.py` 寫 `test_filter_by_label`、`test_invalid_label_returns_422`（先紅）(deps: T002)
- [ ] T011 [US2] 在 `app/routers/query.py` 建立 `GET /issues` 清單端點，含 `label` query 參數與 `LabelQuery` 驗證 (deps: T004, T006, T010, reads: `app/models.py`)

## Phase 5: User Story 3 — 清單分頁 (P3)

> ⚠ T013 **不能**標 [P]。它和 T011 改的是同一個 handler 的簽名 —— 這是 essential
> conflict，拆檔案救不了，只能排隊（修法 B）。

- [ ] T012 [P] [US3] 在 `tests/test_pagination.py` 寫 `test_limit_offset`、`test_total_count_header`（先紅）(deps: T002)
- [ ] T013 [US3] 在 `app/routers/query.py` 為 `GET /issues` 加上 `limit`／`offset` 與 `X-Total-Count` 標頭 (deps: T011, T012)
- [ ] T014 [P] [US3] 在 `docs/api.md` 補上篩選與分頁說明 (deps: T013)

## Phase 6: Polish

- [ ] T015 [P] 在 `README.md` 更新 endpoint 一覽表 (deps: T008, T013)
- [ ] T016 [P] 在 `tests/test_integration.py` 補 label + 分頁的組合情境（新檔，避免與 US1 的測試檔互踩）(deps: T008, T013)
- [ ] T017 全量跑 pytest，確認無 `xpassed` (deps: T015, T016, reads: `tests/conftest.py`)

## Dependencies & Execution Order

- Setup → Foundational 為硬性 checkpoint；Foundational 決定所有共用檔案的最終形狀。
- US1（T007–T009）與 US2（T010–T011）可完全並行：檔案集不相交。
- US3 的 T013 必須等 T011 —— 兩者共用 handler。US3 的測試（T012）不必等。
- 理論加速 2.83×，低於多代理約 3.75× 的成本倍數 → 這個規模**單 agent 跑就好**。
  真正值得開 team 的是 fan-out 更寬的 feature（堂 8 的 Capstone）。
