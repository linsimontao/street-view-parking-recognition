"""Prompt variants for the street-view benchmark, so each step is measurable.

USE v0_base. v1 and v2 are kept as the record of a negative result, not as
options to reach for.

v1 and v2 were each written to fix a failure actually observed in the previous
run -- the right discipline -- and on the 85-image benchmark the ladder looked
clean: 97.6% -> 98.8% -> 100%. Expanding the benchmark to 146 images reversed
the order: 98.6% (v0) vs 97.9% (both rule variants). The rules were fitted to
five specific errors and, on new data, fix two while breaking three, at +24%
prompt tokens. The plain prompt is better calibrated than the hand-written rules.

The lesson is about the benchmark, not the rules: a 85-image set resolves 1.2
points per image, so a two-image swing read as a real gain. Do not add a variant
without enough data to distinguish it from noise.
"""

from prompt import SYSTEM_PROMPT as V0_SYSTEM, USER_PROMPT as V0_USER

# --- v1 -----------------------------------------------------------------
# Observed on the v0 street-view run (94.1%, 5 errors):
#   n013, n037  a parking lot IS in frame, but with no meter/fee board --
#               the model still answered true
#   087, 121    the coin parking occupies a corner of the frame or sits in
#               glare/motion blur -- the model answered false
# Both are boundary calls, not perception limits, so they are addressable by
# stating the decision rule instead of leaving it implied.
V1_RULES = """

判定の基準（重要）:
1. コインパーキング（時間貸し）と断定できるのは、次のいずれかが画像内に見える場合のみ:
   - 料金看板（「最大料金」「20分/100円」など金額の表示）
   - 精算機・自動料金機
   - ロック板（フラップ板）、またはナンバー認識カメラ付きの車室
   - 時間貸し事業者のブランド看板（タイムズ、三井のリパーク、名鉄協商 など）
2. 駐車場らしき区画・白線・停まっている車だけでは false。
   月極駐車場・私有駐車場・社員駐車場と区別できないため、推測しない。
3. 上記1の設備が画面の端・遠方・逆光であっても、判別できるなら true とする。
   画像の主題である必要はない。
4. 画面内に複数の駐車場が写る場合、いずれか一つでも1の条件を満たせば true。
"""

V1_SYSTEM = V0_SYSTEM + V1_RULES

# --- v2 -----------------------------------------------------------------
# v1 lifted recall to 100% but cost specificity: all 3 remaining errors are false
# positives with the same shape -- a paved lot with parked cars plus some
# machine-like object, called true without confirming what the machine is.
#   n008  car under an apartment piloti; the machines beside it are 自動販売機
#   n037  lot next to a house, no equipment at all
#   n013  genuinely ambiguous
# So name what does NOT count, and make "cannot identify" resolve to false.
V2_RULES = """
5. 次のものは精算機・料金設備ではない。これらを根拠に true としてはならない:
   - 自動販売機、宅配ボックス、電力量計、消火設備、ゴミ集積ボックス
   - 建物の看板・広告、店舗の券売機
6. マンション1階のピロティ駐車、戸建ての車庫、施設の来客用駐車場は、
   料金設備が見えない限り false。
7. 設備の種類が特定できない場合は false にする。迷ったら false。
"""

V2_SYSTEM = V1_SYSTEM + V2_RULES

VARIANTS = {
    "v0_base": {"system": V0_SYSTEM, "user": V0_USER,
                "desc": "素のプロンプト（基準線・推奨）"},
    "v1_rules": {"system": V1_SYSTEM, "user": V0_USER,
                 "desc": "v0 + 判定境界の明文化（設備の有無で決める）— 146枚で v0 に劣る"},
    "v2_rules": {"system": V2_SYSTEM, "user": V0_USER,
                 "desc": "v1 + 設備でないものの明示と迷ったら false — 146枚で v0 に劣る"},
}


def get(name):
    if name not in VARIANTS:
        raise SystemExit(f"unknown prompt variant {name!r}; have: {', '.join(VARIANTS)}")
    return VARIANTS[name]
