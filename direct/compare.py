"""Tabulate every run under direct/runs/ so each step's delta is visible.

The point of the ladder (prompt rules -> few-shot -> fine-tuning) is that each
rung has to earn its place. This prints accuracy next to what it cost in tokens
and latency, and lists which images changed verdict between two runs -- an
accuracy that moved because two errors swapped places is not progress.

    python direct/compare.py
    python direct/compare.py --diff v0_base v1_rules
"""

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_runs(runs_dir):
    runs = {}
    for f in sorted(runs_dir.glob("*_summary.json")):
        name = f.name.removesuffix("_summary.json")
        summary = json.loads(f.read_text())
        results_path = runs_dir / f"{name}_results.jsonl"
        results = ([json.loads(l) for l in results_path.read_text().splitlines() if l.strip()]
                   if results_path.exists() else [])
        runs[name] = {"summary": summary, "results": results}
    return runs


def fmt(v, spec="{:.1%}"):
    return "   -  " if v is None else spec.format(v)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=HERE / "results")
    parser.add_argument("--diff", nargs=2, metavar=("RUN_A", "RUN_B"),
                        help="list images whose verdict changed between two runs")
    parser.add_argument("--price-in", type=float, default=None,
                        help="USD per 1M input tokens (optional; no default is "
                             "assumed because rates change)")
    parser.add_argument("--price-out", type=float, default=None,
                        help="USD per 1M output tokens")
    args = parser.parse_args()

    runs = load_runs(args.runs_dir)
    if not runs:
        raise SystemExit(f"no runs found in {args.runs_dir}")

    rows = ["variant", "n", "accuracy", "正类召回", "负类特異度", "F1",
            "平均秒", "p95秒", "平均token", "总token", "失败"]
    print(f"{'variant':<12} {'n':>4} {'accuracy':>9} {'正类召回':>9} {'负类特異度':>10} "
          f"{'F1':>7} {'平均秒':>7} {'p95秒':>7} {'平均tok':>8} {'总tok':>8} {'失败':>5}")
    print("-" * 104)
    for name, run in runs.items():
        s = run["summary"]
        print(f"{name:<12} {s['n']:>4} {fmt(s.get('accuracy')):>9} "
              f"{fmt(s.get('recall_positive')):>9} {fmt(s.get('specificity_negative')):>10} "
              f"{fmt(s.get('f1_positive'), '{:.3f}'):>7} "
              f"{fmt(s.get('mean_request_sec'), '{:.2f}'):>7} "
              f"{fmt(s.get('latency_p95'), '{:.2f}'):>7} "
              f"{fmt(s.get('mean_total_tokens'), '{:.0f}'):>8} "
              f"{s.get('total_tokens', 0):>8} {s.get('failed_requests', 0):>5}")

    if args.price_in and args.price_out:
        print("\n成本（按你提供的单价）:")
        for name, run in runs.items():
            s = run["summary"]
            cost = (s["prompt_tokens"] / 1e6 * args.price_in
                    + (s["output_tokens"] + s.get("thinking_tokens", 0)) / 1e6 * args.price_out)
            print(f"  {name:<12} ${cost:.4f}  (${cost / s['n'] * 1000:.2f} / 1000张)")

    if args.diff:
        a, b = args.diff
        for name in (a, b):
            if name not in runs:
                raise SystemExit(f"unknown run {name!r}; have: {', '.join(runs)}")
        by_file_a = {r["file"]: r for r in runs[a]["results"]}
        fixed, broken = [], []
        for rb in runs[b]["results"]:
            ra = by_file_a.get(rb["file"])
            if ra is None or ra["correct"] == rb["correct"]:
                continue
            (fixed if rb["correct"] else broken).append(rb)

        print(f"\n=== {a} -> {b} ===")
        print(f"修复 {len(fixed)} 张 / 新引入错误 {len(broken)} 张 "
              f"(净 {len(fixed) - len(broken):+d})")
        for label, group in (("修复", fixed), ("新错误", broken)):
            for r in group:
                print(f"  [{label}] {Path(r['file']).name}  真值={r['ground_truth']} "
                      f"-> 判定={r['pred_is_coin_parking']}")


if __name__ == "__main__":
    main()
