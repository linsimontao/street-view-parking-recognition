"""Recompute every run's score against the current labels, without re-calling the API.

Hand labels get corrected as errors surface -- twice now, a "model error" turned
out to be a mislabelled image. The predictions are already on disk, so a label
fix must not cost another full run, and every past run has to move to the new
labels together or the comparison silently mixes two ground truths.

    python direct/rescore.py
"""

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def summarize(results, base):
    n = len(results)
    correct = sum(r["correct"] for r in results)
    pos = [r for r in results if r["ground_truth"]]
    neg = [r for r in results if not r["ground_truth"]]
    tp = sum(r["correct"] for r in pos)
    fp = sum(1 for r in neg if not r["correct"])
    fn = len(pos) - tp
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall else None)

    out = dict(base)
    out.update({
        "n": n,
        "accuracy": correct / n if n else 0,
        "precision_positive": precision,
        "recall_positive": recall,
        "f1_positive": f1,
        "specificity_negative": (len(neg) - fp) / len(neg) if neg else None,
        "confusion_tp_fp_tn_fn": [tp, fp, len(neg) - fp, fn],
        "rescored": True,
    })
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=HERE / "results")
    parser.add_argument("--testset", type=Path,
                        default=HERE / "data" / "testset_streetview.jsonl")
    args = parser.parse_args()

    labels = {}
    for line in args.testset.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            labels[r["file"]] = r["is_coin_parking"]

    for res_path in sorted(args.runs_dir.glob("*_results.jsonl")):
        name = res_path.name.removesuffix("_results.jsonl")
        rows = [json.loads(l) for l in res_path.read_text().splitlines() if l.strip()]
        changed = 0
        for r in rows:
            gt = labels.get(r["file"])
            if gt is None:
                continue
            if r["ground_truth"] != gt:
                changed += 1
            r["ground_truth"] = gt
            r["correct"] = r["pred_is_coin_parking"] == gt

        res_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        sum_path = args.runs_dir / f"{name}_summary.json"
        base = json.loads(sum_path.read_text()) if sum_path.exists() else {}
        sum_path.write_text(json.dumps(summarize(rows, base), ensure_ascii=False, indent=2))
        acc = sum(r["correct"] for r in rows) / len(rows)
        print(f"{name:<12} 标签变更 {changed:>2} 张 -> accuracy {acc:.1%}")


if __name__ == "__main__":
    main()
