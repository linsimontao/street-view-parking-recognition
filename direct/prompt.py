"""The prompt contract, shared by training and evaluation.

Training and eval MUST use byte-identical prompts -- a fine-tuned model is
sensitive to the exact wording it was trained on, so a drifting prompt makes the
eval numbers meaningless. Both build_dataset.py and evaluate.py import from here.
"""

import json

FIELDS = ["is_coin_parking", "operator", "max_fee_yen", "rate", "view_type"]

SYSTEM_PROMPT = """\
あなたは日本の街景画像を分析するアシスタントです。画像がコインパーキング\
（時間貸し駐車場）かどうかを判定し、読み取れる情報をJSONで出力します。

出力は次のスキーマに厳密に従ったJSONオブジェクトのみとし、説明文は一切加えないでください。

{
  "is_coin_parking": boolean,   // 時間貸しのコインパーキングなら true
  "operator": string | null,    // 運営会社名（例: "三井のリパーク", "タイムズ"）
  "max_fee_yen": integer | null,// 最大料金の円額（数値のみ）
  "rate": string | null,        // 時間貸し料金（例: "20分/100円"）
  "view_type": string | null    // "lot_wide" | "sign_closeup" | "machine_closeup"
}

規則:
- 画像から読み取れない項目は必ず null にする。推測しない。
- is_coin_parking が false の場合、他の項目はすべて null にする。
- 月極駐車場（月契約）は時間貸しではないため false。\
"""

USER_PROMPT = "この画像を分析し、スキーマに従ったJSONのみを出力してください。"


def target_json(record):
    """Serialize an annotation record into the exact assistant string to train on."""
    return json.dumps({k: record[k] for k in FIELDS}, ensure_ascii=False)


def build_messages(record=None):
    """Chat messages for one example.

    mlx-vlm's apply_chat_template takes plain-string content and injects the image
    tokens itself into the last user message, so content must NOT be a content-part
    list here. Pass record=None to get the inference-time prompt (no assistant turn).
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT},
    ]
    if record is not None:
        messages.append({"role": "assistant", "content": target_json(record)})
    return messages
