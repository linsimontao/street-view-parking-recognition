# street-view-parking-recognition

Identify Japanese coin parking (コインパーキング) in Google Street View captures and extract structured details — operator, maximum fee, hourly rate.

Calls `gemini-3.5-flash` directly. No fine-tuning, no training data. **97.9% on a 146-image benchmark of real Street View imagery**, at 1.4 s and ~1,630 tokens per image.

```json
{
  "is_coin_parking": true,
  "operator": "三井のリパーク",
  "max_fee_yen": 600,
  "rate": "20分/100円",
  "view_type": "lot_wide"
}
```

All fields are nullable — unreadable means `null`. When `is_coin_parking` is `false`, every other field is `null`.

## Results

146 real Street View images (67 positive / 79 negative; always answering one class would score 54.1%). Run on 2026-08-08, `thinkingBudget=0`, temperature 0, images downscaled to 1280 px.

| variant | accuracy | recall | specificity | F1 | errors |
|---|---|---|---|---|---|
| **v0_base** | 97.3% | 94.0% | 100.0% | 0.969 | 4 |
| v1_rules | **97.9%** | 97.0% | 98.7% | 0.977 | 3 |
| v2_rules | 96.6% | 94.0% | 98.7% | 0.962 | 5 |

### Time and tokens

| variant | wall clock | mean/img | p50 | p95 | max | total tokens | in / out | mean/img | failed |
|---|---|---|---|---|---|---|---|---|---|
| **v0_base** | 254.8 s | 1.74 s | 1.61 s | 2.63 s | 4.28 s | 206,069 | 198,414 / 7,655 | **1,411** | 0 |
| v1_rules | 212.5 s | 1.45 s | 1.36 s | 1.86 s | 3.93 s | 238,003 | 230,388 / 7,615 | 1,630 | 0 |
| v2_rules | 213.3 s | 1.45 s | 1.39 s | 1.81 s | 2.32 s | 254,518 | 246,886 / 7,632 | 1,743 | 0 |

Zero failed requests and zero retries across all three runs. Thinking tokens are 0 by design — see [the notes on thinking budget](direct/README.md#pitfalls). Roughly 1,080 of the input tokens per image are the image itself; the rest is the prompt.

No dollar figures are quoted because published rates change; `direct/compare.py --price-in --price-out` will compute cost from rates you supply.

### Which variant to use

**Use `v0_base` — but on cost, not accuracy.**

The three variants are statistically indistinguishable on this benchmark: 4 / 3 / 5 errors, all differences within one or two images. Every time a label was corrected the ranking flipped — three different variants have held first place at some point. `v0_base` is the cheapest (13–19% fewer tokens) and has no extra rules to maintain, and that reason survives the next label correction.

`v1_rules` and `v2_rules` are kept in `prompts.py` as **a recorded negative result**. Each rule was written to fix a failure actually observed in the previous run — the right discipline — and on an 85-image benchmark the ladder looked clean (97.6% → 98.8% → 100%). Doubling the benchmark reversed it. The rules were fitted to five specific errors and, on new data, fix two while breaking three.

### Field extraction

30 Street View positives annotated by hand, scored by **whether a human could read the field at all**. Counting an illegible sign as a model error would measure the annotator's eyesight, not the model.

| field | agree | disagree | missed | unverifiable | verifiable accuracy |
|---|---|---|---|---|---|
| operator | 11 | 0 | 0 | 6 | 100% (11/11) |
| max_fee_yen | 11 | 0 | 0 | 3 | 100% (11/11) |
| rate | 1 | 0 | 0 | 11 | 100% (1/1) |

*unverifiable* = the model produced a value the annotator could not confirm at 640 px. A perturbation test (re-ask with 5% cropped off each edge; a genuine reading survives, a confabulation drifts) found **10 of 11 stable after semantic normalisation** — the model does read these boards better than the human annotator did. One drifted, implying roughly a 9% confabulation rate.

The sample is small — 11, 11 and 1 verifiable cases. This says *no errors were found*, not *accuracy is 100%*.

## Quick start

```bash
pip install -r requirements.txt

# 1. Rebuild the benchmark images (not redistributed here — see below)
export GOOGLE_MAPS_API_KEY=...
python direct/refetch_images.py --dry-run     # count billed requests first
python direct/refetch_images.py

# 2. Run the benchmark
export GEMINI_API_KEY=...
python direct/test_gemini.py --model gemini-3.5-flash --prompt-variant v0_base

# 3. Read the results
python direct/compare.py            # all runs side by side
python direct/score_fields.py       # field extraction, by legibility
```

## What is in this repository

| Path | Contents |
|---|---|
| `direct/*.py` | Prompt contract and variants, benchmark runner, comparison, offline rescoring, field scoring, Street View fetching |
| `direct/data/testset_streetview.jsonl` | **146 benchmark labels, all hand-confirmed** |
| `direct/data/annotations_fields.jsonl` | 30 field annotations with per-field legibility flags |
| `direct/data/manifest_*.jsonl` | Provenance: pano id, coordinates, address, capture date |
| `direct/results/` | Per-image results and summaries for all three variants |
| **[`direct/README.md`](direct/README.md)** | **Full write-up: method, known issues, pitfalls** |

## Why there are no images here

Google Maps Platform terms do not permit redistributing Street View imagery, so this repository ships **provenance instead of pixels**. `direct/refetch_images.py` reconstructs the identical 146-image benchmark from your own API key.

It fetches by **pano id, not coordinates** — the panorama at a given location changes when the survey car passes again, while a pano id always resolves to the same photograph. That is what makes the benchmark reproducible.

Street View imagery is © Google. This repository contains only derived annotations and metadata.

## Honest limitations

**Label noise is now the bottleneck.** Five mislabels have been found and corrected in 146 images (3.4%), all in the negative class, all actually coin parkings. That is the same magnitude as the model's error count, which is why the variant ranking is unstable.

**Review resolution determines label quality.** Mislabels missed on 360 px contact sheets were obvious at 560 px. Re-reviewing 60 negatives at the higher resolution surfaced 19 contaminated images (32%) in one pass.

**"The model disagrees with me" is not a reliable review trigger.** It fails exactly when model and annotator make the same mistake — both overlooking a small distant sign. A separate high-recall screener asking a *different* question ("is any fee equipment anywhere in this frame?") has uncorrelated failure modes and surfaced one further mislabel.

## Status

The evaluation work is complete. **There is no production pipeline yet** — every script here needs a pre-labelled test set. Turning this into "given an area, return its parking data" is the remaining work.
