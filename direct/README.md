# Street View coin parking recognition — Gemini direct call

Identify Japanese coin parking (コインパーキング) in Google Street View captures and extract structured details. No fine-tuning; `gemini-3.5-flash` is called directly.

## Output schema

```json
{
  "is_coin_parking": true,
  "operator": "三井のリパーク",
  "max_fee_yen": 600,
  "rate": "20分/100円",
  "view_type": "lot_wide"
}
```

All fields nullable — unreadable means `null`. When `is_coin_parking` is `false`, every other field is `null`. `view_type` ∈ `lot_wide` | `sign_closeup` | `machine_closeup`.

## Benchmark

`data/testset_streetview.jsonl` — 146 real Street View captures, 67 positive / 79 negative. Always answering one class scores 54.1%.

Positives came from a Places search for コインパーキング / 時間貸駐車場; negatives from 月極駐車場 (monthly parking) — the discriminative case, since a monthly lot has the same asphalt, the same painted bays and the same P sign, and differs only by the absence of a meter or fee board.

Every label is hand-confirmed. The five corrected labels carry a `note` field recording what the evidence was.

## Results

Run 2026-08-08 · `gemini-3.5-flash` · `thinkingBudget=0` · temperature 0 · images downscaled to 1280 px.

### Accuracy

| variant | accuracy | recall | specificity | F1 | TP/FP/TN/FN | errors |
|---|---|---|---|---|---|---|
| **v0_base** | 97.3% | 94.0% | 100.0% | 0.969 | 63/0/79/4 | 4 |
| v1_rules | **97.9%** | 97.0% | 98.7% | 0.977 | 65/1/78/2 | 3 |
| v2_rules | 96.6% | 94.0% | 98.7% | 0.962 | 63/1/78/4 | 5 |

### Time

| variant | wall clock | sum of requests | mean | p50 | p95 | max | failed | retried |
|---|---|---|---|---|---|---|---|---|
| **v0_base** | 254.8 s | 253.5 s | 1.736 s | 1.606 s | 2.629 s | 4.276 s | 0 | 0 |
| v1_rules | 212.5 s | 211.2 s | 1.447 s | 1.361 s | 1.856 s | 3.929 s | 0 | 0 |
| v2_rules | 213.3 s | 212.0 s | 1.452 s | 1.388 s | 1.813 s | 2.320 s | 0 | 0 |

Requests are issued sequentially, so wall clock ≈ sum of request times. The v0 run was slower per image than v1/v2 despite a shorter prompt; with n=146 and no retries this is server-side variance, not a property of the prompt.

### Tokens

| variant | input | output | thinking | total | mean per image |
|---|---|---|---|---|---|
| **v0_base** | 198,414 | 7,655 | 0 | 206,069 | **1,411.4** |
| v1_rules | 230,388 | 7,615 | 0 | 238,003 | 1,630.2 |
| v2_rules | 246,886 | 7,632 | 0 | 254,518 | 1,743.3 |

About 1,080 input tokens per image are the image itself (1280 px, Qwen-style patching); the remainder is the prompt, which is what the rule variants inflate. Output holds steady near 52 tokens — the JSON object — confirming the extra input buys longer instructions, not longer answers.

Costs in currency are deliberately not quoted, since published rates change. `compare.py --price-in X --price-out Y` computes them from rates you supply.

### Which variant to use

**Use `v0_base` — chosen on cost, not accuracy.**

The three variants are statistically indistinguishable here: 4 / 3 / 5 errors, every difference within one or two images. Each label correction flipped the ranking, and all three have held first place at some point:

| variant | after correcting sv_038 | after correcting sv_008 |
|---|---|---|
| v0_base | 97.9% | 97.3% |
| v1_rules | 97.3% | **97.9%** |
| v2_rules | 97.3% | 96.6% |

Since they are equivalent, cost decides: `v0_base` is 13–19% cheaper in tokens and has no extra rules to maintain. That reason will not be overturned by the next label correction.

### The rule variants are a recorded negative result

`v1_rules` and `v2_rules` remain in `prompts.py` deliberately. Each rule was written to fix a failure actually observed in the previous run — the right discipline — and on the earlier 85-image benchmark the ladder looked convincing:

| variant | 85 images | 146 images |
|---|---|---|
| v0_base | 97.6% | 97.3% |
| v1_rules | 98.8% | **97.9%** |
| v2_rules | **100.0%** | 96.6% |

- **v1** fixed two misses (a parking entrance occupying a corner of the frame; a backlit, motion-blurred machine) by stating that equipment counts even when peripheral, distant or backlit. Recall rose to 100% on the small set.
- **v2** fixed v1's false positive (vending machines mistaken for a payment machine) by naming what is *not* fee equipment and defaulting to `false` when unsure. That reached 100% on the small set.

On the doubled benchmark both rules backfired: v1's permissiveness produced a false positive on an apartment piloti parking, and v2's "default to false" suppressed a real coin parking whose fee board was small. Rules fitted to five specific errors fix two and break three on new data. **The plain prompt is better calibrated than hand-written rules.**

Few-shot was not attempted for the same reason: if written rules overfit, examples drawn from the same error pool will overfit harder, and at 0.68 points per image there is no power to measure the difference.

## Field extraction

30 Street View positives annotated by hand. Each field is scored by **whether the annotator could read it at all**, because at Street View resolution the small print on a 料金看板 is often physically present but illegible — counting those as model errors would measure eyesight, not the model.

| bucket | meaning |
|---|---|
| agree | annotator read a value, model matches |
| disagree | annotator read a value, model differs — the only real errors |
| missed | annotator read a value, model returned null |
| unverifiable | annotator could not read it, model produced a value |
| both_null | annotator could not read it, model returned null too |

| field | agree | disagree | missed | unverifiable | both_null | verifiable accuracy |
|---|---|---|---|---|---|---|
| operator | 11 | 0 | 0 | 6 | 13 | 100% (11/11) |
| max_fee_yen | 11 | 0 | 0 | 3 | 16 | 100% (11/11) |
| rate | 1 | 0 | 0 | 11 | 18 | 100% (1/1) |

Nothing the annotator could read was answered wrongly or skipped.

**Resolving the unverifiable cases.** The model sees the same 640 px the annotator does, so a value the annotator cannot confirm is either superior low-resolution OCR or confabulation. Repeating the call is not a discriminator — at temperature 0 a confabulation reproduces just as stably. Perturbing the input is: re-asked with 5% cropped off each edge, a genuine reading survives while a value anchored on spurious features drifts.

Of 11 unverifiable `rate` values, **10 were stable** after semantic normalisation and one drifted (`60分/100円` → `40分/200円`), implying roughly a 9% confabulation rate. Two of the three raw-string changes were formatting only — `30分/200円` vs `オールタイム 30分 200円` vs `200円/30分` — which is why `score_fields.py` normalises a rate to a `(minutes, yen)` pair before comparing.

The sample is small: 11, 11 and 1 verifiable cases. This supports *no errors were found*, not *accuracy is 100%*.

## Known issues

**`view_type` should be dropped.** 63 of 65 Street View positives return `lot_wide`. The field distinguishes wide shot / sign close-up / machine close-up, which made sense for promotional photography but not for imagery shot from a passing car. It carries no information in the deployment domain.

**`rate` format is unstable.** The same board yields `30分/200円`, `オールタイム 30分 200円` or `200円/30分` under slight input changes. Splitting it into integer `rate_minutes` / `rate_yen` fields would remove the parsing burden from consumers.

**Label noise is the bottleneck.** Five mislabels found in 146 images (3.4%), all in the negative class, all actually coin parkings — the same magnitude as the model's error count. This is why the variant ranking is unstable and why further prompt tuning cannot be measured here.

## Data

`data/testset_streetview.jsonl` — 146 labels, all hand-confirmed. Corrected entries carry `note`.

`data/annotations_fields.jsonl` — 30 field annotations with `operator_legible` / `max_fee_legible` / `rate_legible` flags.

`data/manifest_*.jsonl` — provenance per image: `pano_id`, coordinates, address, capture date, distance from the panorama to the registered coordinates.

**The images themselves are not in this repository.** Google Maps Platform terms do not permit redistributing Street View content, so what is committed is provenance. Rebuild the identical benchmark with your own key:

```bash
export GOOGLE_MAPS_API_KEY=...
python direct/refetch_images.py --dry-run   # how many billed requests
python direct/refetch_images.py
```

Fetching is by `pano_id`, not coordinates: the panorama at a location changes when the survey car passes again, while a pano id always resolves to the same photograph.

## Running

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...              # read from the environment only; never commit it

python direct/test_gemini.py --list-models      # what this key can reach
python direct/test_gemini.py --model gemini-3.5-flash --prompt-variant v0_base

python direct/compare.py                            # all runs side by side
python direct/compare.py --diff v0_base v1_rules    # which images changed verdict
python direct/score_fields.py                       # field extraction by legibility
python direct/rescore.py                            # re-score offline after a label fix
```

`test_gemini.py` validates `--model` against the models the key can actually reach and exits with the available flash models if it cannot — rather than failing 146 requests before revealing a typo.

`results/*_results.jsonl` records per image: prediction JSON, ground truth, correctness, elapsed seconds, prompt / output / thinking / total tokens, `finishReason`, attempt count, and error reason.

`--diff` matters more than the accuracy column: an accuracy that moved because two errors swapped places is not progress.

## Files

| File | Purpose |
|---|---|
| `prompt.py` | Prompt contract — system, user, target JSON serialisation |
| `prompts.py` | v0/v1/v2 variants; comments record which observed error each rule addresses |
| `image_utils.py` | 1280 px downscale, project-root-relative path resolution |
| `test_gemini.py` | Benchmark runner; 8 metrics per image |
| `compare.py` | Multi-run table plus `--diff` |
| `rescore.py` | Re-score stored predictions against corrected labels without re-calling the API |
| `score_fields.py` | Field scoring separating "wrong" from "unverifiable" |
| `fetch_streetview.py` | Places search → free metadata check → billed image fetch |
| `refetch_images.py` | Rebuild the benchmark from manifest pano ids |

## Pitfalls

**gemini-3.5-flash is a thinking model, and thinking tokens come out of `maxOutputTokens`.** At 256 the model spent 246 on reasoning and emitted a truncated `"Here is the"` with `finishReason=MAX_TOKENS`. `thinkingBudget=0` returns byte-identical answers on this task at less than half the tokens and latency (1.5 s / 1,406 tok vs 3.5 s / 1,903 tok), so it is the default here.

**The model emits both too many and too few closing braces.** Sometimes a stray `}` follows a complete object; sometimes the closing `}` is missing outright while `finishReason` is still `STOP`. Slicing with `rfind('}')` fails on both, turning correct answers into recorded failures and understating accuracy. The parser counts braces from the first `{`, stops at the first balanced object, and repairs a missing closer when the object is otherwise intact — but still fails a string truncated mid-value rather than guessing.

**Review resolution determines label quality.** Three mislabels survived review on 360 px contact sheets. Re-reviewing 60 negatives at 560 px surfaced 19 contaminated images (32%) in a single pass — a coin parking captured near a 月極駐車場 coordinate is common.

**"The model disagrees with me" is not a reliable review trigger.** It fails precisely when model and annotator make the same mistake, such as both overlooking a small sign in the background. The fix is a separate high-recall screener asking a *different* question — "is any fee equipment anywhere in this frame?" — whose failure modes are uncorrelated with the classifier's. Run over 80 negatives it flagged 17 for review, and human confirmation found one further mislabel.

## Licence and attribution

Street View imagery is © Google and is **not** included in this repository; only derived annotations and metadata are. Using `fetch_streetview.py` or `refetch_images.py` requires your own API key and compliance with Google Maps Platform terms.
