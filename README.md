# street-view-parking-recognition

从 Google 街景图中识别日本投币停车场（コインパーキング）并抽取结构化信息——运营商、最大料金、时段费率。

用 `gemini-3.5-flash` 直接调用，不做微调。**146 张真实街景上 97.9%**，1411 token / 1.7 秒每张，零训练数据。

```json
{
  "is_coin_parking": true,
  "operator": "三井のリパーク",
  "max_fee_yen": 600,
  "rate": "20分/100円",
  "view_type": "lot_wide"
}
```

## 快速开始

```bash
pip install -r requirements.txt

# 1. 重建基准图片（仓库不含影像，见下）
export GOOGLE_MAPS_API_KEY=...
python direct/refetch_images.py --dry-run
python direct/refetch_images.py

# 2. 跑评测
export GEMINI_API_KEY=...
python direct/test_gemini.py --model gemini-3.5-flash --prompt-variant v0_base \
  --testset direct/data/testset_streetview.jsonl \
  --out direct/results/v0_base_results.jsonl \
  --summary direct/results/v0_base_summary.json

# 3. 看结果
python direct/compare.py --runs-dir direct/results
python direct/score_fields.py
```

## 仓库内容

| 路径 | 内容 |
|---|---|
| `direct/*.py` | 评测代码：prompt 契约、变体、主评测、对比、离线重算、字段评分、街景获取 |
| `direct/data/testset_streetview.jsonl` | **146 张测试集标签，全部人工确认** |
| `direct/data/annotations_fields.jsonl` | 30 张字段标注，含逐字段可读性标记 |
| `direct/data/manifest_*.jsonl` | 街景溯源：pano_id、坐标、地址、拍摄年月 |
| `direct/results/` | 三个 prompt 变体的逐张结果与汇总 |
| **[`direct/README.md`](direct/README.md)** | **完整说明：结果、方法、已知问题、踩过的坑** |

## 为什么仓库里没有图片

Google Maps Platform 条款不允许再分发街景影像，所以提交的是**溯源信息**而非图片。`direct/refetch_images.py` 按 `pano_id` 重建完全相同的 146 张基准——用 pano_id 而非坐标是关键，同一坐标的全景会随街景车重新拍摄而变化。

影像版权归 Google 所有；本仓库仅含派生的标注与元数据。

## 主要结论

**分类已经够用**：97.9%，且三个 prompt 变体在此基准上统计不可区分——每修正一处标签排名就翻转一次。按成本选最便宜的 `v0_base`。

**手写 prompt 规则是过拟合**：在 85 张基准上 97.6%→98.8%→100% 的漂亮阶梯，扩到 146 张后完全反转。规则版保留在 `prompts.py` 里作为负面结果的记录。

**标注质量才是瓶颈**：146 张里已确认 5 处错标（3.4%），与模型误差同量级。审阅分辨率直接决定标签质量——360px 缩略图漏掉的错标，560px 下一眼可见。

细节见 [`direct/README.md`](direct/README.md)。

## 状态

评测部分完成。**尚无「输入区域 → 输出该区域停车场数据」的生产管线**，现有代码全部需要预先标注好的测试集。
