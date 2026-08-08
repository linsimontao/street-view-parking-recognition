"""Run the coin-parking task against the Gemini API and record cost per image.

Every image goes through the same prompt contract (prompt.py) and the same
1280px downscale (image_utils.py), so two runs differ only in what is being
tested, never in how the input was prepared.

The API key is read from the GEMINI_API_KEY environment variable and is never
written to disk -- do not paste it into this file.

    export GEMINI_API_KEY=...
    python direct/test_gemini.py --model gemini-3.5-flash \
        --testset direct/testset_streetview.jsonl
    python direct/test_gemini.py --list-models      # see what the key can reach
"""

import argparse
import base64
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import prompts  # noqa: E402
from image_utils import load_resized  # noqa: E402

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
FIELDS = ["is_coin_parking", "operator", "max_fee_yen", "rate", "view_type"]

# Negatives sourced from a 月極駐車場 search are the ones that actually
# discriminate: same asphalt, same painted bays, same P sign, no meter.
HARD_NEGATIVE_MAX_INDEX = 40


def is_hard_negative(path):
    name = Path(path).name
    # The street-view negatives were all sourced from a 月極駐車場 search, so
    # every one of them is a hard negative by construction.
    if name.startswith("monthly_parking_sv_"):
        return True
    m = re.search(r"not_parking_(\d+)", name)
    return bool(m) and int(m.group(1)) <= HARD_NEGATIVE_MAX_INDEX


def api_error(response):
    """Google's error body nests the useful sentence; surface just that."""
    try:
        return response.json()["error"]["message"]
    except Exception:
        return response.text[:200]


def list_models(key):
    r = requests.get(f"{API_ROOT}/models", headers={"x-goog-api-key": key}, timeout=30)
    if r.status_code == 400 and "API key not valid" in r.text:
        raise SystemExit(
            "GEMINI_API_KEY is rejected by the API (API_KEY_INVALID).\n"
            "Check that the key is current and that the Generative Language API "
            "is enabled for its project: https://aistudio.google.com/apikey"
        )
    if r.status_code != 200:
        raise SystemExit(f"listing models failed [{r.status_code}]: {api_error(r)}")
    models = [m["name"].replace("models/", "") for m in r.json().get("models", [])
              if "generateContent" in m.get("supportedGenerationMethods", [])]
    return sorted(models)


def encode_image(path, max_side):
    img = load_resized(path, max_side)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def first_json_object(text):
    """Slice out the first balanced {...} run.

    Not rfind('}'): gemini-3.5-flash reliably appends a stray closing brace after
    a complete object, and taking the last one swallows it and breaks the parse.
    Brace counting stops at the first object and ignores anything trailing.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth, in_string, escaped = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    # The model also drops closing braces sometimes -- a complete field list that
    # simply stops, with finishReason STOP rather than MAX_TOKENS. Closing it is
    # the difference between scoring a correct answer and recording a failure, so
    # repair it when the object is otherwise intact (not mid-string).
    if depth > 0 and not in_string:
        return text[start:] + "}" * depth
    return None


def parse_output(text):
    """Pull the JSON object out of a response, or None if there isn't one."""
    if not text:
        return None
    if "```" in text:
        chunks = text.split("```")
        text = max(chunks, key=len).removeprefix("json").strip()
    blob = first_json_object(text)
    if blob is None:
        return None
    try:
        obj = json.loads(blob)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def call_once(key, model, b64, max_tokens, timeout, thinking_budget, prompt):
    # temperature 0 to match the greedy decoding used for the local model.
    gen_config = {"temperature": 0, "maxOutputTokens": max_tokens,
                  "responseMimeType": "application/json"}
    # Gemini 3.x thinks by default and the thinking tokens come out of
    # maxOutputTokens -- at 256 the model burned 246 on reasoning and emitted a
    # truncated "Here is the". Budget 0 gives byte-identical answers here at less
    # than half the tokens and latency, and matches the local model's single pass.
    if thinking_budget is not None:
        gen_config["thinkingConfig"] = {"thinkingBudget": thinking_budget}
    body = {
        "systemInstruction": {"parts": [{"text": prompt["system"]}]},
        "contents": prompt.get("shots", []) + [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                {"text": prompt["user"]},
            ],
        }],
        "generationConfig": gen_config,
    }
    started = time.monotonic()
    r = requests.post(
        f"{API_ROOT}/models/{model}:generateContent",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json=body, timeout=timeout,
    )
    elapsed = time.monotonic() - started
    return r, elapsed


def run_one(key, model, path, max_side, max_tokens, timeout, retries,
            thinking_budget, prompt):
    """Return (prediction|None, elapsed, usage, error|None, finish_reason, attempts).

    Elapsed time accumulates across retries: a request that only succeeded on the
    third attempt really did cost that much wall clock.
    """
    b64 = encode_image(path, max_side)
    total_elapsed = 0.0
    last_error = None
    attempts = 0
    for attempt in range(retries + 1):
        attempts += 1
        try:
            r, elapsed = call_once(key, model, b64, max_tokens, timeout,
                                   thinking_budget, prompt)
        except requests.RequestException as e:
            total_elapsed += timeout
            last_error = f"request failed: {e}"
            continue
        total_elapsed += elapsed

        if r.status_code == 200:
            data = r.json()
            usage = data.get("usageMetadata", {})
            reason = (data.get("candidates") or [{}])[0].get("finishReason")
            text = ""
            for cand in data.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    text += part.get("text", "")
            pred = parse_output(text)
            err = None if pred is not None else f"no JSON (finishReason={reason})"
            return pred, total_elapsed, usage, err, reason, attempts

        last_error = f"HTTP {r.status_code}: {api_error(r)}"
        # 429/5xx are worth retrying; a 400 will fail identically every time.
        if r.status_code not in (429, 500, 502, 503, 504):
            break
        # Count the backoff as elapsed time too -- otherwise a throttled run
        # reports fast per-image latency while the wall clock says otherwise.
        backoff = 2 ** attempt
        time.sleep(backoff)
        total_elapsed += backoff

    return None, total_elapsed, {}, last_error, None, attempts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemini-3.5-flash")
    parser.add_argument("--testset", type=Path, default=HERE / "data" / "testset_streetview.jsonl")
    parser.add_argument("--out", type=Path, default=HERE / "results" / "v0_base_results.jsonl")
    parser.add_argument("--summary", type=Path, default=HERE / "results" / "v0_base_summary.json")
    parser.add_argument("--max-side", type=int, default=1280)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--thinking-budget", type=int, default=0,
                        help="0 disables thinking (default); -1 leaves the model's "
                             "own default in place")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--prompt-variant", default="v0_base",
                        help=f"one of: {', '.join(prompts.VARIANTS)}")
    args = parser.parse_args()
    prompt = prompts.get(args.prompt_variant)

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("set GEMINI_API_KEY in the environment first")

    if args.list_models:
        for m in list_models(key):
            print(m)
        return

    available = list_models(key)
    if args.model not in available:
        flash = [m for m in available if "flash" in m]
        raise SystemExit(
            f"model {args.model!r} is not available to this key.\n"
            f"flash models this key can reach:\n  " + "\n  ".join(flash or ["(none)"])
        )

    records = [json.loads(l) for l in args.testset.read_text().splitlines() if l.strip()]
    if args.limit:
        records = records[:args.limit]

    results = []
    wall_started = time.monotonic()
    for i, rec in enumerate(records, 1):
        path = PROJECT_ROOT / rec["file"]
        pred, elapsed, usage, err, reason, attempts = run_one(
            key, args.model, path, args.max_side, args.max_tokens,
            args.timeout, args.retries,
            None if args.thinking_budget < 0 else args.thinking_budget,
            prompt,
        )
        # An unparseable or failed response cannot claim "coin parking".
        pred_label = bool(pred.get("is_coin_parking")) if pred else False
        row = {
            "file": rec["file"],
            "ground_truth": rec["is_coin_parking"],
            "prediction": pred,
            "pred_is_coin_parking": pred_label,
            "correct": pred_label == rec["is_coin_parking"],
            "elapsed_sec": round(elapsed, 3),
            "prompt_tokens": usage.get("promptTokenCount"),
            "output_tokens": usage.get("candidatesTokenCount"),
            "thinking_tokens": usage.get("thoughtsTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount"),
            "finish_reason": reason,
            "attempts": attempts,
            "error": err,
        }
        results.append(row)
        mark = "OK " if row["correct"] else "ERR"
        print(f"[{i}/{len(records)}] {mark} {Path(rec['file']).name}  "
              f"{row['elapsed_sec']:.2f}s  {row['total_tokens'] or 0} tok"
              + (f"  <{err}>" if err else ""), flush=True)
    wall_total = time.monotonic() - wall_started

    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results))

    n = len(results)
    correct = sum(r["correct"] for r in results)
    pos = [r for r in results if r["ground_truth"]]
    neg = [r for r in results if not r["ground_truth"]]
    hard = [r for r in neg if is_hard_negative(r["file"])]
    failed = [r for r in results if r["error"]]
    tok = lambda k: sum(r[k] or 0 for r in results)  # noqa: E731
    times = [r["elapsed_sec"] for r in results]

    def pct(vals, p):
        if not vals:
            return None
        s = sorted(vals)
        return round(s[min(len(s) - 1, int(round((len(s) - 1) * p)))], 3)

    tp = sum(r["correct"] for r in pos)
    fp = sum(1 for r in neg if not r["correct"])
    fn = len(pos) - tp
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall else None)

    summary = {
        "model": args.model,
        "prompt_variant": args.prompt_variant,
        "prompt_desc": prompt.get("desc"),
        "thinking_budget": args.thinking_budget,
        "n": n,
        "accuracy": correct / n if n else 0,
        "precision_positive": precision,
        "recall_positive": recall,
        "f1_positive": f1,
        "confusion_tp_fp_tn_fn": [tp, fp, len(neg) - fp, fn],
        "latency_p50": pct(times, 0.50),
        "latency_p95": pct(times, 0.95),
        "retried_requests": sum(1 for r in results if r["attempts"] > 1),
        "specificity_negative": sum(r["correct"] for r in neg) / len(neg) if neg else None,
        "hard_negative_reject": sum(r["correct"] for r in hard) / len(hard) if hard else None,
        "n_hard_negative": len(hard),
        "failed_requests": len(failed),
        "wall_clock_sec": round(wall_total, 2),
        "sum_request_sec": round(sum(times), 2),
        "mean_request_sec": round(sum(times) / n, 3) if n else None,
        "max_request_sec": round(max(times), 3) if n else None,
        "prompt_tokens": tok("prompt_tokens"),
        "output_tokens": tok("output_tokens"),
        "thinking_tokens": tok("thinking_tokens"),
        "total_tokens": tok("total_tokens"),
        "mean_total_tokens": round(tok("total_tokens") / n, 1) if n else None,
    }
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    print(f"\n=== {args.model} / {args.prompt_variant} "
          f"(thinking_budget={args.thinking_budget}) ===")
    print(f"总准确率        {summary['accuracy']:.1%}  ({correct}/{n})")
    # A --limit run can contain only one class, so each line is conditional.
    if pos:
        print(f"  coin_parking  {summary['recall_positive']:.1%}  ({sum(r['correct'] for r in pos)}/{len(pos)})")
    if neg:
        print(f"  非coin_parking {summary['specificity_negative']:.1%}  ({sum(r['correct'] for r in neg)}/{len(neg)})")
    if hard:
        print(f"  └ 难負例(月極) {summary['hard_negative_reject']:.1%}  "
              f"({sum(r['correct'] for r in hard)}/{len(hard)})")
    if precision and recall:
        print(f"P/R/F1          {precision:.3f} / {recall:.3f} / {f1:.3f}")
    print(f"失败请求        {len(failed)}   重试请求 {summary['retried_requests']}")
    print(f"总耗时(墙钟)    {summary['wall_clock_sec']:.1f}s")
    print(f"请求耗时合计    {summary['sum_request_sec']:.1f}s  "
          f"(平均 {summary['mean_request_sec']:.2f}s  "
          f"p50 {summary['latency_p50']:.2f}s  p95 {summary['latency_p95']:.2f}s)")
    print(f"总 token        {summary['total_tokens']}  "
          f"(输入 {summary['prompt_tokens']} / 输出 {summary['output_tokens']}"
          f" / thinking {summary['thinking_tokens']}, "
          f"平均 {summary['mean_total_tokens']}/张)")
    print(f"\n逐张结果 -> {args.out}\n汇总   -> {args.summary}")

    if neg:
        print(f"\n注意: 测试集正负比 {len(pos)}/{len(neg)}，无脑全判 true 就有 "
              f"{len(pos)/n:.1%} 准确率。看分类别的几行，别只看总准确率。")


if __name__ == "__main__":
    main()
