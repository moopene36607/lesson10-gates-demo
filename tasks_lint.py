#!/usr/bin/env python3
"""tasks_lint — 驗證 Spec Kit `tasks.md` 的並行安全性。

為什麼需要這個工具？
--------------------
Spec Kit 的 `/speckit.tasks` 會在可並行的任務上標 `[P]`。它的規則寫在 command
template 裡：「只有當任務操作不同檔案、且不依賴未完成的任務時，才加 [P]」。

但是 —— **這個標記是 LLM 標的，沒有任何機器在驗證它。**

`[P]` 本質上是一個「並行安全證明」。證明沒被檢查，就只是一個聲稱。等到堂 8 你把
tasks.md 餵給 agent team、兩個 teammate 同時開始寫 `app/main.py`，你才會發現。
這支腳本把那個聲稱變成可驗證的斷言。

檢查項目
--------
1. format          每個 task 要有 ID（T###）與至少一個檔案路徑。
2. cycle           依賴圖不得有環。
3. dangling-dep    deps 不得指向不存在的 task。
4. parallel-conflict
                   任兩個「並行」的 task（依賴圖上互相不可達）不得寫同一個檔案。
                   —— 這是真正的判準。`[P]` 標記只是模型的聲稱；並行性由圖決定。
5. write-read      並行的 task 中，一個寫、一個讀同一檔案（較弱，報 WARN）。

並行模型
--------
Spec Kit 的語意是分層的 checkpoint：

    Setup → Foundational → { US1 ∥ US2 ∥ US3 } → Polish

注意中間那層 —— tasks-template 明講「不同的 user story 可以由不同人並行推進」。
所以 **story phase 之間是兄弟，不是先後**。預設我們照這個語意建圖。

而 agent team（堂 8）連 phase barrier 都沒有：它只按**依賴**解鎖。
用 `--no-phase-barriers` 切到那個模型，通常會有更多衝突浮出來。
**這是 demo 的重點：同一份 tasks.md，在不同的執行引擎下，安全性不一樣。**

標註語法（本課的擴充，Spec Kit 原生沒有）
----------------------------------------
    - [ ] T014 [P] [US2] 在 app/main.py 加上 label 篩選 (deps: T009, reads: app/models.py)

    deps:   顯式依賴，逗號分隔的 task ID。
    reads:  唯讀檔案。未列在 reads 的路徑一律視為「寫入」。

用法
----
    python tasks_lint.py specs/001-issue-labels/tasks.md
    python tasks_lint.py tasks.md --no-phase-barriers
    python tasks_lint.py tasks.md --emit-dispatch > briefs.json

退出碼
------
    0  無 ERROR（可有 WARN）
    1  有 ERROR —— 可直接當 CI 步驟或 PostToolUse hook 的守門條件（堂 3、堂 11）
    2  用法錯誤
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ── 解析規則 ─────────────────────────────────────────────────────────────
# - [ ] T014 [P] [US2] 描述 …… (deps: T009, reads: app/models.py)
TASK_RE = re.compile(r"^\s*-\s*\[[ xX]\]\s*(?P<id>T\d{2,4})\b(?P<rest>.*)$")
PHASE_RE = re.compile(r"^\s*#{2,4}\s*Phase\s+(?P<num>\d+)\s*[:：\-—]?\s*(?P<name>.*?)\s*$", re.I)
MARK_P_RE = re.compile(r"\[P\]")
MARK_US_RE = re.compile(r"\[(US\d+)\]")
DEPS_RE = re.compile(r"deps\s*[:：]\s*(?P<v>[^)\]]*)")
READS_RE = re.compile(r"reads\s*[:：]\s*(?P<v>[^)\]]*)")
TASK_REF_RE = re.compile(r"\bT\d{2,4}\b")
EMPTY_PARENS_RE = re.compile(r"[（(]\s*[,，、]*\s*[)）]")

SOURCE_EXT = (
    "py", "pyi", "js", "ts", "tsx", "jsx", "go", "rs", "java", "rb", "sh", "ps1",
    "md", "json", "toml", "yaml", "yml", "cfg", "ini", "txt", "sql", "html", "css",
)
# 反引號優先；其次是裸露的、看起來像路徑的 token。
PATH_BACKTICK_RE = re.compile(r"`([^`\s]+\.(?:%s))`" % "|".join(SOURCE_EXT))
PATH_BARE_RE = re.compile(r"(?<![`\w/.-])([\w][\w./\\-]*\.(?:%s))\b" % "|".join(SOURCE_EXT))


@dataclass
class Task:
    tid: str
    phase: int
    phase_name: str
    line_no: int
    raw: str
    desc: str
    parallel: bool
    story: str | None
    deps: list[str] = field(default_factory=list)
    writes: set[str] = field(default_factory=set)
    reads: set[str] = field(default_factory=set)

    @property
    def touches(self) -> set[str]:
        return self.writes | self.reads


@dataclass
class Finding:
    level: str  # ERROR / WARN
    kind: str
    msg: str


def _norm(p: str) -> str:
    return p.replace("\\", "/").lstrip("./")


def _extract_paths(text: str) -> list[str]:
    found = [m.group(1) for m in PATH_BACKTICK_RE.finditer(text)]
    stripped = PATH_BACKTICK_RE.sub(" ", text)
    found += [m.group(1) for m in PATH_BARE_RE.finditer(stripped)]
    # 去重且保序
    seen, out = set(), []
    for p in map(_norm, found):
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def parse(path: Path) -> list[Task]:
    tasks: list[Task] = []
    phase, phase_name = 0, "(no phase)"

    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if m := PHASE_RE.match(raw):
            phase = int(m.group("num"))
            phase_name = m.group("name") or f"Phase {phase}"
            continue

        m = TASK_RE.match(raw)
        if not m:
            continue

        rest = m.group("rest")
        deps_m, reads_m = DEPS_RE.search(rest), READS_RE.search(rest)
        deps = TASK_REF_RE.findall(deps_m.group("v")) if deps_m else []
        reads = {_norm(p) for p in _extract_paths(reads_m.group("v"))} if reads_m else set()

        # 描述 = 去掉標記與註記後的正文；路徑要從「正文」抽，避免把 reads 當成寫入。
        desc = rest
        for r in (DEPS_RE, READS_RE):
            desc = r.sub(" ", desc)
        body = MARK_US_RE.sub(" ", MARK_P_RE.sub(" ", desc))
        # 拔掉 deps/reads 之後會留下空的 `( )` 或 `(, )`，別讓它跟著進 objective。
        body = EMPTY_PARENS_RE.sub(" ", body)

        writes = {p for p in _extract_paths(body)} - reads
        story_m = MARK_US_RE.search(rest)

        tasks.append(
            Task(
                tid=m.group("id"),
                phase=phase,
                phase_name=phase_name,
                line_no=line_no,
                raw=raw.strip(),
                desc=" ".join(body.split()),
                parallel=bool(MARK_P_RE.search(rest)),
                story=story_m.group(1) if story_m else None,
                deps=deps,
                writes=writes,
                reads=reads,
            )
        )
    return tasks


def phase_rank(phase_num: int, phase_name: str) -> int:
    """把 Spec Kit 的 phase 映射成 barrier 層級。

    Setup(0) → Foundational(1) → 所有 user story 同層(2) → Polish(3)。
    story phase 彼此是**兄弟**（可並行），這是 tasks-template 的語意。
    認不出名字時退回用 phase 編號，行為等同「每個 phase 都是一道 barrier」。
    """
    n = phase_name.lower()
    if "setup" in n:
        return 0
    if "foundation" in n:
        return 1
    if "user story" in n or re.search(r"\bus\d+\b", n):
        return 2
    if "polish" in n or "cross-cutting" in n:
        return 3
    return phase_num


def build_edges(tasks: list[Task], phase_barriers: bool) -> dict[str, set[str]]:
    """回傳 succ: tid -> 後繼集合。邊 = 顯式 deps ∪（可選）phase barrier。"""
    ids = {t.tid for t in tasks}
    succ: dict[str, set[str]] = {t.tid: set() for t in tasks}

    for t in tasks:
        for d in t.deps:
            if d in ids:
                succ[d].add(t.tid)

    if phase_barriers:
        by_rank: dict[int, list[str]] = {}
        for t in tasks:
            by_rank.setdefault(phase_rank(t.phase, t.phase_name), []).append(t.tid)
        ranks = sorted(by_rank)
        for a, b in zip(ranks, ranks[1:]):
            for u in by_rank[a]:
                succ[u].update(by_rank[b])
    return succ


def reachable_from(succ: dict[str, set[str]], src: str) -> set[str]:
    seen, q = set(), deque([src])
    while q:
        u = q.popleft()
        for v in succ.get(u, ()):
            if v not in seen:
                seen.add(v)
                q.append(v)
    return seen


def find_cycle(succ: dict[str, set[str]]) -> list[str] | None:
    WHITE, GREY, BLACK = 0, 1, 2
    color = {u: WHITE for u in succ}
    stack: list[str] = []

    def dfs(u: str) -> list[str] | None:
        color[u] = GREY
        stack.append(u)
        for v in succ[u]:
            if color[v] == GREY:
                return stack[stack.index(v):] + [v]
            if color[v] == WHITE and (c := dfs(v)):
                return c
        stack.pop()
        color[u] = BLACK
        return None

    for u in succ:
        if color[u] == WHITE and (c := dfs(u)):
            return c
    return None


def longest_path(tasks: list[Task], succ: dict[str, set[str]]) -> list[str]:
    """DAG 最長路徑（以 task 數計）＝ critical path。"""
    order = topo_order(tasks, succ)
    best: dict[str, int] = {t.tid: 1 for t in tasks}
    prev: dict[str, str | None] = {t.tid: None for t in tasks}
    for u in order:
        for v in succ[u]:
            if best[u] + 1 > best[v]:
                best[v] = best[u] + 1
                prev[v] = u
    end = max(best, key=lambda k: best[k])
    path = []
    cur: str | None = end
    while cur:
        path.append(cur)
        cur = prev[cur]
    return list(reversed(path))


def topo_order(tasks: list[Task], succ: dict[str, set[str]]) -> list[str]:
    indeg = {t.tid: 0 for t in tasks}
    for u in succ:
        for v in succ[u]:
            indeg[v] += 1
    q = deque(sorted(u for u, d in indeg.items() if d == 0))
    out = []
    while q:
        u = q.popleft()
        out.append(u)
        for v in sorted(succ[u]):
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    return out


def levels(tasks: list[Task], succ: dict[str, set[str]]) -> dict[str, int]:
    lvl = {t.tid: 0 for t in tasks}
    for u in topo_order(tasks, succ):
        for v in succ[u]:
            lvl[v] = max(lvl[v], lvl[u] + 1)
    return lvl


def analyse(tasks: list[Task], succ: dict[str, set[str]]) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    ids = {t.tid: t for t in tasks}

    # 1. format
    for t in tasks:
        if not t.touches:
            findings.append(Finding("WARN", "missing-path", f"{t.tid} 描述裡沒有任何檔案路徑（第 {t.line_no} 行）"))
    dupes = [tid for tid in ids if sum(1 for t in tasks if t.tid == tid) > 1]
    for tid in sorted(set(dupes)):
        findings.append(Finding("ERROR", "duplicate-id", f"{tid} 重複出現"))

    # 2. dangling deps
    for t in tasks:
        for d in t.deps:
            if d not in ids:
                findings.append(Finding("ERROR", "dangling-dep", f"{t.tid} 依賴不存在的 {d}"))

    # 3. cycle
    if cyc := find_cycle(succ):
        findings.append(Finding("ERROR", "cycle", " → ".join(cyc)))
        return findings, {}

    # 4/5. 並行衝突：互相不可達 ＝ 可能同時執行
    reach = {t.tid: reachable_from(succ, t.tid) for t in tasks}
    for i, a in enumerate(tasks):
        for b in tasks[i + 1:]:
            concurrent = b.tid not in reach[a.tid] and a.tid not in reach[b.tid]
            if not concurrent:
                continue
            if ww := sorted(a.writes & b.writes):
                mark = "".join("[P]" if t.parallel else "[ ]" for t in (a, b))
                findings.append(
                    Finding(
                        "ERROR",
                        "parallel-conflict",
                        f"{a.tid} {'[P]' if a.parallel else '   '} ⟂ {b.tid} {'[P]' if b.parallel else '   '}"
                        f"  同時寫入 {', '.join(ww)}",
                    )
                )
            for f in sorted((a.writes & b.reads) | (a.reads & b.writes)):
                findings.append(
                    Finding("WARN", "write-read", f"{a.tid} ⟂ {b.tid}  一方寫、一方讀 {f}（讀到的可能是舊版）")
                )

    # 指標
    cp = longest_path(tasks, succ)
    lvl = levels(tasks, succ)
    width: dict[int, int] = {}
    for v in lvl.values():
        width[v] = width.get(v, 0) + 1

    stats = {
        "tasks": len(tasks),
        "edges": sum(len(v) for v in succ.values()),
        "critical_path": cp,
        "critical_path_len": len(cp),
        "max_width": max(width.values()) if width else 0,
        "ideal_speedup": round(len(tasks) / len(cp), 2) if cp else 0.0,
    }
    return findings, stats


def dispatch_briefs(tasks: list[Task], succ: dict[str, set[str]]) -> list[dict]:
    """把 task 轉成 agent brief。

    欄位取自 Anthropic 多代理研究系統的四要素 —— objective / output format /
    tools / boundaries。Spec Kit 原生的 tasks.md 只給了 objective 和（隱含的）
    output，缺 tools 與 boundaries；那正是他們報告裡「subagent 重複工作」的來源。
    """
    pred: dict[str, list[str]] = {t.tid: [] for t in tasks}
    for u, vs in succ.items():
        for v in vs:
            pred[v].append(u)

    # phase barrier 會製造大量遞移邊（Foundational 的每個 task → story 的每個 task）。
    # brief 裡只留「直接」阻塞者：若 P 中的 u 可以從 P 中另一個 w 走到，u 是遞移的，砍掉。
    reach = {t.tid: reachable_from(succ, t.tid) for t in tasks}

    def minimal_pred(v: str) -> list[str]:
        ps = pred[v]
        return sorted(u for u in ps if not any(w != u and u in reach[w] for w in ps))

    out = []
    for t in tasks:
        out.append(
            {
                "id": t.tid,
                "story": t.story,
                "objective": t.desc,
                "output": sorted(t.writes),
                "tools": ["Read", "Edit", "Write", "Bash(pytest*)"] if t.writes else ["Read", "Grep"],
                "boundaries": {
                    "may_write": sorted(t.writes),
                    "may_read": sorted(t.reads) or ["(依需要)"],
                    "must_not_touch": "任何不在 may_write 的檔案；需要時回報 lead，不要自行擴張範圍",
                },
                "blocked_by": minimal_pred(t.tid),
                "parallel_claim": t.parallel,
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="驗證 Spec Kit tasks.md 的並行安全性")
    ap.add_argument("tasks_md", type=Path)
    ap.add_argument(
        "--no-phase-barriers",
        action="store_true",
        help="不假設 phase 之間有 checkpoint（＝ agent team 依賴解鎖模型，堂 8）",
    )
    ap.add_argument("--emit-dispatch", action="store_true", help="輸出 agent brief JSON")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not args.tasks_md.is_file():
        print(f"找不到檔案：{args.tasks_md}", file=sys.stderr)
        return 2

    tasks = parse(args.tasks_md)
    if not tasks:
        print("沒解析到任何 task —— 確認格式是 `- [ ] T001 …`", file=sys.stderr)
        return 2

    succ = build_edges(tasks, phase_barriers=not args.no_phase_barriers)

    if args.emit_dispatch:
        print(json.dumps(dispatch_briefs(tasks, succ), ensure_ascii=False, indent=2))
        return 0

    findings, stats = analyse(tasks, succ)
    errors = [f for f in findings if f.level == "ERROR"]
    warns = [f for f in findings if f.level == "WARN"]

    mode = "explicit deps" if args.no_phase_barriers else "phase barriers + deps"
    print(f"tasks_lint  {args.tasks_md}")
    print(f"  {len(tasks)} tasks · {stats.get('edges', 0)} edges · 並行模型：{mode}\n")

    for f in errors + warns:
        colour = "ERROR" if f.level == "ERROR" else "WARN "
        print(f"  {colour} {f.kind:<18} {f.msg}")
    if findings:
        print()

    if stats:
        cp = stats["critical_path"]
        print(f"  critical path : {stats['critical_path_len']} tasks  ({' → '.join(cp[:6])}{' → …' if len(cp) > 6 else ''})")
        print(f"  max width     : {stats['max_width']} 個 task 可同時執行")
        print(f"  ideal speedup : {stats['tasks']}/{stats['critical_path_len']} = {stats['ideal_speedup']}×（Amdahl 上限，忽略協調成本）")
        if not args.quiet:
            print()
            print("  ⚠ 成本對照：Anthropic 報告多代理系統的 token 用量約為聊天的 15×、單 agent 約 4×")
            print("    → 多代理相對單 agent 約 3.75×（此為兩數相除的推算，非官方直接數字）。")
            verdict = "值得" if stats["ideal_speedup"] >= 3.75 else "用錢買時間"
            print(f"    你的理論加速 {stats['ideal_speedup']}× vs 成本 ~3.75× → **{verdict}**。")

    print(f"\n{len(errors)} error, {len(warns)} warning")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
