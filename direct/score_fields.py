"""Score field extraction on street view, separating "wrong" from "unverifiable".

At street-view resolution a human often cannot read the small print on a 料金看板
even though it is physically there. Scoring those as model errors would measure
the annotator's eyesight, not the model. So each field lands in one of:

  agree        annotator read a value, model matches
  disagree     annotator read a value, model differs  <- the only real errors
  missed       annotator read a value, model said null
  unverifiable annotator could not read it, model produced a value
  both_null    annotator could not read it, model said null too

Only agree/disagree/missed carry signal. A large `unverifiable` count is itself
the finding: that field cannot be validated from this imagery.

    python direct/score_fields.py
"""

import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

OPERATOR_ALIASES = {
    "times": "タイムズ", "タイムズ": "タイムズ", "タイムズパーキング": "タイムズ",
    "24時間タイムズ": "タイムズ",
    "三井のリパーク": "リパーク", "リパーク": "リパーク", "repark": "リパーク",
}


def norm_operator(v):
    if v is None:
        return None
    s = str(v).strip()
    return OPERATOR_ALIASES.get(s.lower(), OPERATOR_ALIASES.get(s, s))


def norm_rate(v):
    """Reduce a rate string to (minutes, yen) so wording cannot count as a miss.

    The model expresses the same reading several ways -- "30分/200円",
    "オールタイム 30分 200円", "200円/30分" all came back for the same board under
    slight input changes. Comparing raw strings would score two of those wrong
    and measure formatting rather than perception.
    """
    if v is None:
        return None
    s = str(v)
    minutes = re.search(r"(\d+)\s*分", s)
    yen = re.search(r"(\d[\d,]*)\s*円", s)
    if minutes and yen:
        return (int(minutes.group(1)), int(yen.group(1).replace(",", "")))
    return re.sub(r"[\s/]", "", s)


NORMALIZERS = {"operator": norm_operator, "max_fee_yen": lambda v: v,
               "rate": norm_rate, "view_type": lambda v: v}
LEGIBLE_KEY = {"operator": "operator_legible", "max_fee_yen": "max_fee_legible",
               "rate": "rate_legible"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path,
                        default=HERE / "data" / "annotations_fields.jsonl")
    parser.add_argument("--results", type=Path,
                        default=HERE / "results" / "v0_base_results.jsonl")
    args = parser.parse_args()

    truth = {json.loads(l)["file"]: json.loads(l)
             for l in args.annotations.read_text().splitlines() if l.strip()}
    preds = {json.loads(l)["file"]: json.loads(l)
             for l in args.results.read_text().splitlines() if l.strip()}

    fields = ["operator", "max_fee_yen", "rate"]
    buckets = {f: {"agree": [], "disagree": [], "missed": [],
                   "unverifiable": [], "both_null": []} for f in fields}

    for path, t in truth.items():
        p = preds.get(path)
        if not p or not p.get("prediction"):
            continue
        pred = p["prediction"]
        for f in fields:
            legible = t[LEGIBLE_KEY[f]]
            gt, got = NORMALIZERS[f](t[f]), NORMALIZERS[f](pred.get(f))
            name = Path(path).name
            if legible:
                if got is None:
                    buckets[f]["missed"].append(name)
                elif got == gt:
                    buckets[f]["agree"].append(name)
                else:
                    buckets[f]["disagree"].append((name, t[f], pred.get(f)))
            else:
                (buckets[f]["unverifiable"] if got is not None
                 else buckets[f]["both_null"]).append(name)

    n = len(truth)
    print(f"街景 {n} 张（人工可读性分档）\n")
    header = f"{'field':<14}{'一致':>6}{'不一致':>8}{'漏读':>6}{'无法验证':>10}{'双方null':>10}{'可验证准确率':>14}"
    print(header)
    print("-" * len(header.encode('utf-8')) // 2 * "-" if False else "-" * 66)
    for f in fields:
        b = buckets[f]
        scorable = len(b["agree"]) + len(b["disagree"]) + len(b["missed"])
        acc = f"{len(b['agree'])/scorable:.0%} ({len(b['agree'])}/{scorable})" if scorable else "n/a"
        print(f"{f:<14}{len(b['agree']):>6}{len(b['disagree']):>8}{len(b['missed']):>6}"
              f"{len(b['unverifiable']):>10}{len(b['both_null']):>10}{acc:>14}")

    for f in fields:
        d = buckets[f]["disagree"]
        if d:
            print(f"\n{f} 不一致:")
            for name, gt, got in d:
                print(f"  {name}: 人工={gt!r} 模型={got!r}")
        m = buckets[f]["missed"]
        if m:
            print(f"\n{f} 漏读（人工能读出、模型给 null）: {', '.join(m)}")

    print("\n无法验证的样本数越大，说明该字段在街景分辨率下人工也读不出，"
          "\n因此无法判定模型是对是错——这本身就是结论。")


if __name__ == "__main__":
    main()
