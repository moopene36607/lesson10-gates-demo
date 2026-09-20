#!/usr/bin/env python3
"""gate_from_severity — 把 AI 審查的嚴重度變成一道『真的會擋』的關卡。

本堂核心論點
------------
託管 Code Review 的 check run **刻意恆為 neutral，永遠不擋 merge** —— 因為
AI 的結論不是核可。要 gate，就得由**你**讀嚴重度、由**你**決定 exit 1。
這支腳本就是那個「你」：它讀一份嚴重度 JSON，Important（會壞生產的 bug）
超過門檻就 `exit 1`，接上 branch protection，merge 按鈕就變灰。

它刻意吃兩種形狀的 JSON —— 因為 gate 不該在乎是哪一層審查產出的：

  1) 託管 Code Review 的 bughunter-severity（counts 形狀）：
       {"normal": 2, "nit": 1, "pre_existing": 0}
     normal = 🔴 Important 的條數。important = normal。

  2) 自建 / 跨供應商互審的 findings（堂 9 review.schema.json 形狀）：
       {"reviewer": "...", "findings": [{"severity": "critical"|"high"|...}]}
     important = critical + high 的條數。

  → 兩種都正規化成一個「important 數」，超過 --max-important（預設 0）就 exit 1。

這道 gate 是本堂三類檢查裡的第二類：**執行是確定性的，輸入來自 AI 審查。**
紅燈 ＝ AI 說有該修的 bug、由你的規則擋；綠燈只代表 AI 沒報，不是 code 沒問題。
不依賴 AI 的底線是 gates.yml 裡的 pytest 與 tasks_lint。

退出碼
------
    0  important <= 門檻（放行）
    1  important >  門檻（擋 merge —— 給 branch protection 用）
    2  用法錯誤 / 讀不到 JSON

用法
----
    # 讀本地檔（demo / 離線，確定性）
    python gate_from_severity.py severity.red.json          # → exit 1
    python gate_from_severity.py severity.green.json         # → exit 0
    python gate_from_severity.py snapshots/codex_review.json # findings 形狀也吃

    # 讀 stdin（接在 gh api / claude --json-schema 之後）
    gh api repos/O/R/check-runs/ID --jq '...bughunter-severity...' \
        | python gate_from_severity.py -

    # 放寬門檻：容忍 1 條 high、只擋 critical 用另一支（見 --min-severity）
    python gate_from_severity.py review.json --max-important 0 --min-severity high

⚠️ bughunter-severity 的 gh api --jq 取值語法屬託管 Code Review 研究預覽期格式，
   錄製當天對真實 check run 重驗一次（reference.md 堂 10 段）。
"""
import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# 哪些 severity 算「Important（會壞生產、該擋）」
IMPORTANT_BY_LEVEL = {
    "critical": {"critical"},
    "high": {"critical", "high"},
    "medium": {"critical", "high", "medium"},
}


def read_json(src: str):
    if src == "-":
        text = sys.stdin.read()
    else:
        p = Path(src)
        if not p.exists():
            print(f"[gate] 讀不到 {src}", file=sys.stderr)
            raise SystemExit(2)
        text = p.read_text(encoding="utf-8")
    text = text.strip()
    if not text:
        print("[gate] 輸入是空的 —— 沒有審查結果可判斷", file=sys.stderr)
        raise SystemExit(2)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[gate] JSON 解析失敗：{e}", file=sys.stderr)
        raise SystemExit(2)


def important_count(data: dict, min_severity: str) -> tuple[int, dict, str]:
    """回傳 (important 條數, 完整分佈, 這份 JSON 的形狀名)。"""
    # 形狀一：bughunter-severity counts
    if isinstance(data, dict) and "normal" in data and "findings" not in data:
        counts = {
            "important": int(data.get("normal", 0)),
            "nit": int(data.get("nit", 0)),
            "pre_existing": int(data.get("pre_existing", 0)),
        }
        # counts 形狀下，normal 已經是「該擋的 Important」，min_severity 不適用
        return counts["important"], counts, "bughunter-severity (counts)"

    # 形狀二：findings 陣列（堂 9 review.schema.json）
    findings = data.get("findings") if isinstance(data, dict) else None
    if isinstance(findings, list):
        dist: dict[str, int] = {}
        for f in findings:
            sev = str(f.get("severity", "")).lower()
            dist[sev] = dist.get(sev, 0) + 1
        blocking = IMPORTANT_BY_LEVEL.get(min_severity, IMPORTANT_BY_LEVEL["high"])
        important = sum(n for sev, n in dist.items() if sev in blocking)
        return important, dist, f"findings[] (min-severity={min_severity})"

    print("[gate] 認不得的 JSON 形狀（既非 bughunter-severity counts、"
          "也非 findings 陣列）", file=sys.stderr)
    raise SystemExit(2)


def main() -> int:
    ap = argparse.ArgumentParser(description="讀審查嚴重度、Important 超標就 exit 1（給 branch protection）")
    ap.add_argument("source", help="嚴重度 JSON 檔路徑，或 '-' 讀 stdin")
    ap.add_argument("--max-important", type=int, default=0,
                    help="容忍的 Important 條數上限（預設 0：一條都不容忍）")
    ap.add_argument("--min-severity", choices=["critical", "high", "medium"], default="high",
                    help="findings 形狀下，哪個等級（含）以上算 Important（預設 high）")
    args = ap.parse_args()

    data = read_json(args.source)
    important, dist, shape = important_count(data, args.min_severity)

    print(f"[gate] 讀到形狀：{shape}")
    print(f"[gate] 分佈：{json.dumps(dist, ensure_ascii=False)}")
    print(f"[gate] Important（該擋）＝ {important}，門檻 ＝ {args.max_important}")

    if important > args.max_important:
        print(f"❌ [gate] Important {important} > 門檻 {args.max_important} —— 擋 merge（exit 1）")
        print("   執行是確定性的，輸入來自 AI 審查：AI 說有該修的 bug，由你的規則擋。")
        return 1
    print(f"✅ [gate] Important {important} <= 門檻 {args.max_important} —— 放行（exit 0）")
    print("   綠燈只代表 AI 沒報，不是 code 沒問題；不靠 AI 的底線是 pytest 與 tasks_lint。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
