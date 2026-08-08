# 街景コインパーキング識別 — Gemini API 直调

从 Google 街景图中识别日本投币停车场（コインパーキング）并抽取结构化信息。不做微调，直接调用 `gemini-3.5-flash`。

**146 张真实街景上 97.9%**，1411 token / 1.7 秒每张，零训练数据。

## 输出 schema

```json
{
  "is_coin_parking": true,
  "operator": "三井のリパーク",
  "max_fee_yen": 600,
  "rate": "20分/100円",
  "view_type": "lot_wide"
}
```

字段全部 nullable，读不到就填 `null`；`is_coin_parking` 为 `false` 时其余字段一律 `null`。

## 结果

146 张真实街景（正 67 / 负 79，全判一类的下限 54.1%）：

| variant | accuracy | 正类召回 | 负类特異度 | F1 | 错误数 | 平均tok | 平均秒 | p95秒 |
|---|---|---|---|---|---|---|---|---|
| **v0_base** | 97.3% | 94.0% | 100.0% | 0.969 | 4 | **1411** | 1.74 | 2.63 |
| v1_rules | 97.9% | 97.0% | 98.7% | 0.977 | 3 | 1630 | 1.45 | 1.86 |
| v2_rules | 96.6% | 94.0% | 98.7% | 0.962 | 5 | 1743 | 1.45 | 1.81 |

**推荐用 `v0_base`，但理由不是准确率。**

三个变体在这个基准上无法区分：错误数 4/3/5，差异全在 1–2 张内，而**每修正一处标签排名就翻转一次**（先后出现过三个不同的第一名）。所谓"差异"完全被标注噪声吞没。既然等价，就按成本选——`v0_base` 最便宜（省 13–19% token）且没有额外规则要维护，这个理由不会被下次标签修正推翻。

`v1_rules` / `v2_rules` 保留在 `prompts.py` 里作为**负面结果的记录**：它们是从 85 张基准上的具体错误反推出来的规则，在那批数据上看着漂亮（97.6%→98.8%→100%），扩到 146 张后就反转了。典型的过拟合。

### 字段抽取

30 张街景人工标注，按**人工可读性分档**评分（把标注者读不出的记成模型错，测的是视力不是模型）：

| 字段 | 一致 | 不一致 | 漏读 | 无法验证 | 可验证准确率 |
|---|---|---|---|---|---|
| operator | 11 | 0 | 0 | 6 | 100% (11/11) |
| max_fee_yen | 11 | 0 | 0 | 3 | 100% (11/11) |
| rate | 1 | 0 | 0 | 11 | 100% (1/1) |

「无法验证」是模型给了值而人工在 640px 下读不出。用**裁边 5% 的扰动测试**判别（真实读取应存活，编造值会漂移）：语义归一后 10/11 稳定，说明多数确实读出来了；1 张漂移，约 9% 编造率。

样本量很小，可验证的只有 11/11/1 张。**只能说「未发现错误」，不能说「准确率 100%」。**

## 已知问题

- **`view_type` 应删除**：街景上 63/65 都是 `lot_wide`，零信息量。它是为宣传照设计的（广角/看板特写/精算机特写），在街景域不成立。
- **`rate` 格式不稳定**：同一块看板会输出 `30分/200円`、`オールタイム 30分 200円`、`200円/30分` 三种写法。建议拆成 `rate_minutes` / `rate_yen` 两个整数字段。`score_fields.py` 已用语义归一（提取「分钟数+日元」对）绕开这一点。
- **标注噪声约 3.4%**：146 张里已确认 5 处错标，全在负样本、全是「实为 coin parking」。基准分辨率已被标注质量卡死。

## 数据

`data/testset_streetview.jsonl` —— 146 张的标签，**全部人工确认**。5 处修正带 `note` 字段说明依据。

`data/annotations_fields.jsonl` —— 30 张的字段标注，含 `operator_legible` / `max_fee_legible` / `rate_legible` 三个可读性标记。

`data/manifest_*.jsonl` —— 每张的溯源：`pano_id`、坐标、地址、拍摄年月、全景与登记坐标的距离。

**图片本身不在仓库里。** Google Maps Platform 条款不允许再分发街景影像，所以提交的是溯源信息。用你自己的 key 即可重建完全相同的基准：

```bash
export GOOGLE_MAPS_API_KEY=...
python direct/refetch_images.py --dry-run   # 先看要取多少张
python direct/refetch_images.py
```

按 `pano_id` 而非坐标取图——同一坐标的全景会随街景车重新拍摄而变化，`pano_id` 则永远对应同一张照片。这是可复现的关键。

## 运行

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...              # 只从环境变量读，不要写进文件

python direct/test_gemini.py --list-models     # 先确认 key 能用哪些模型
python direct/test_gemini.py --model gemini-3.5-flash --prompt-variant v0_base \
  --testset direct/data/testset_streetview.jsonl \
  --out direct/results/v0_base_results.jsonl \
  --summary direct/results/v0_base_summary.json

python direct/compare.py --runs-dir direct/results                    # 所有 run 并列
python direct/compare.py --runs-dir direct/results --diff v0_base v1_rules  # 哪些图改判了
python direct/score_fields.py                                         # 字段抽取分档评分
python direct/rescore.py --runs-dir direct/results                    # 标签修正后离线重算
```

脚本会先校验 `--model` 是否在该 key 可访问的列表里，不在就列出可用的 flash 型号并退出——省得 146 次请求全废了才发现模型名写错。

`results/*_results.jsonl` 每张记录：预测 JSON、真值、是否正确、耗时、prompt/output/thinking/total token、`finishReason`、重试次数、错误原因。

## 文件

| 文件 | 作用 |
|---|---|
| `prompt.py` | prompt 契约（system / user / 目标 JSON 序列化） |
| `prompts.py` | v0/v1/v2 变体，注释写明每条规则对应哪次实测错误 |
| `image_utils.py` | 1280px 预缩放 + 项目根相对路径解析 |
| `test_gemini.py` | 主评测，逐张记录 8 项指标 |
| `compare.py` | 多 run 并列 + `--diff` 列出改判的具体图片 |
| `rescore.py` | 标签修正后离线重算，不烧 API |
| `score_fields.py` | 字段评分，区分「模型错」与「人工无法验证」 |
| `fetch_streetview.py` | 街景获取：Places 搜坐标 → 免费 metadata 筛全景 → 付费取图 |
| `refetch_images.py` | 按 manifest 的 pano_id 重建基准 |
| `build_testset.py` | 从本地图库抽样构建测试集清单 |

## 踩过的坑

**gemini-3.5-flash 是 thinking 模型，thinking token 从 `maxOutputTokens` 里扣。** `maxOutputTokens=256` 时 246 个被推理吃掉，只剩 6 个吐出截断的 `"Here is the"`，`finishReason=MAX_TOKENS`。实测 `thinkingBudget=0` 与默认 thinking 输出逐字相同，但快一倍多、省 26% token，故默认关闭。

**模型的花括号会多也会少。** 有时在完整对象后多吐一个 `}`，有时漏掉结尾的 `}`（`finishReason` 仍是 `STOP`）。用 `rfind('}')` 截取两种情况都会解析失败——**本可正确的答案被记成失败，从而低估准确率**。改为从第一个 `{` 起做括号配对扫描，并在对象完整仅缺尾括号时补全；真正断在字符串中途的仍判失败，不猜测。

**审阅分辨率决定标签质量。** 用 360px 缩略图筛选时漏掉 3 处错标；改 560px 后当场在 60 张负样本里揪出 19 张污染（32%）——「月極駐車場」坐标附近拍到 coin parking 是高频现象。

**「模型不同意」不是可靠的复核触发器。** 当模型和标注者犯同样的错误（都漏看远处的小看板）时完全失效。补救办法是用一个**问不同问题的高召回筛查器**（「画面任何位置有没有计费设备」），其失效模式与分类器不相关。80 张负样本里标出 17 张可疑，人工复核后又确认了 1 处错标。

## 免责

街景影像版权归 Google 所有，本仓库不含影像，仅含派生的标注与元数据。使用 `fetch_streetview.py` / `refetch_images.py` 需自备 API key 并遵守 Google Maps Platform 条款。
