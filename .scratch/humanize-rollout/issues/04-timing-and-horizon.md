# 04 — 长文本阈值与时间预算

Status: resolved
Type: grilling
Blocked by:

## Question

`DEFAULT_PROFILE` 是共享的唯一定义，`type_horizon_chars = 1000`，`keystroke` 均值 ≈ 0.12 s/字符。对小红书够用，对另外 15 个平台未必。

要定的事：

1. **阈值归属**：`type_horizon_chars` 保持 1000 全局唯一，还是允许按平台/按字段分档？（`DEFAULT_PROFILE` 的注释写着「平台不得复制第二份」，改它就是改共享契约。）
2. **长文本现实**：TikTok 正文 4000、YouTube 描述 5000、知乎文章数千字、Instagram 配文 2200。超过阈值的文本会走**一次** `insert_text`——零按键事件，人类化对这类字段等于没生效。接受这个退化，还是要求长文本也逐字（代价：5000 字 ≈ 10 分钟，必然撞 15 分钟预算）？
3. **预算交互**：`PublishTimeoutBudget` 是 15 分钟。人类化在 34 处 `fill` + 12 处 `keyboard.type` + 303 处 `click` 上的最坏增量估算多少？是否需要为「人类化开启」单独放宽预算？还是要求预算不变、超时就按 exit 1？
4. **既有固定 sleep**：各平台现在有大量 `asyncio.sleep(1~3)`。人类化接入后是保留（更慢但更安全）、还是按「人类化已提供节奏」删掉一部分？删除属于行为变更，需不需要真机验证？
5. **`HUMANIZE=0` 的耗时**：关闭后应回到当前速度。是否要求规格给出「开启 / 关闭」两条路径的耗时基线，供运营判断？

产出：阈值策略 + 预算结论 + sleep 处置 + 两条路径的耗时基线定义。

## Answer

2026-11-12，grilling 定案。五项全部定案，可直接作为 06 的输入；证据等级沿用 map 约定。

### 1. 阈值归属：保持 1000、全局唯一、不分档

- `DEFAULT_PROFILE.type_horizon_chars = 1000` 不动（`utils/humanize.py:96`、`:101-113`）。`[code]`
- 不新增构造参数、不按平台/字段分档；生产代码出现第二个 `type_horizon_chars` 字面量即违规。
- 现有静态门继续用，不另加锁：`tests/test_humanize.py:680-690`（`test_type_horizon_has_exactly_one_definition`）已扫描全仓，只允许 `utils/humanize.py` 命中。`[code]`
- 码点口径（`len(text)`，非字素）照旧：约 143 个 ZWJ 家族 emoji 即越线（02 §7.1）。接受。

### 2. 长文本：接受一次性 `insert_text` 退化，逐字段登记 + 补测

超过 1000 码点 → 单次 `insert_text`、零 `press`、零逐字采样、一条 info 日志（`utils/humanize.py:217-221`）。这是有意降级，不是缺陷。

必须逐字段登记「该字段会走 bulk」（行号引自 01 清单）：

| 平台 | 字段 | 调用点 |
| --- | --- | --- |
| 支付宝 | 作品描述 | `alipay_uploader/main.py:457` |
| 大鱼 | 视频简介 | `dayu_uploader/main.py:157` |
| 抖音 | 作品描述 | `douyin_uploader/main.py:477` |
| 虎扑 | 简介 | `hupu_uploader/main.py:556` |
| 快手 | 视频描述 / 图文正文 | `ks_uploader/main.py:798`、`:971` |
| Facebook | 正文 | `facebook_uploader/main.py:347` |
| Facebook Page | 正文 | `facebook_page_uploader/main.py:332` |
| Instagram | 配文 | `insgraph_uploader/main.py:799` |
| 视频号 | 视频描述（同一编辑器两次调用） | `tencent_uploader/main.py:865`、`:874` |
| 微博 | 正文 | `weibo_uploader/main.py:761` |
| TikTok | 配文（现状本就是 `insert_text`） | `tk_uploader/main_chrome.py:2441` |
| YouTube | 标题/简介（`_fill_editable`，07 待定） | `youtube_uploader/main.py:249` |
| 知乎 | 视频介绍 | `zhihu_uploader/video.py:177` |
| 百家号 | 无长正文字段（仅标题 + 合集搜索） | — |

- 离线：每平台测试对自己那个正文字段断言「一次 `insert_text` + 零 `press` + 一次 `after_type`」。模板已有：`tests/test_humanize.py:329`（1001 字 → 单次 insert_text）。平台侧补的是**调用点确实把整段文本交给 `type_text`**；不允许平台自己切段/分片，否则等于第二份阈值。
- 真机：TikTok / Instagram / 小红书 若实发正文 >1000，必须确认目标编辑器接受 `insert_text` 且读回一致（TikTok Draft.js、IG Lexical、XHS contenteditable）。失败 → 该平台长正文标「人类化不生效」并保持 bulk，**不得调阈值**。
- TikTok 的特殊性：`fill_caption` 本来就是 `keyboard.insert_text(text)`（`tk_uploader/main_chrome.py:2441`），所以 >1000 的改法与今天等价；变化只发生在 ≤1000 的配文（变为逐字）。`[code]`
- 对 07 的一个事实（不代为决定）：YouTube `_fill_editable` 的「# 触发联想、不要逐字」冲突只在 ≤1000 字时成立；>1000 仍走 bulk，行为不变。`[inferred]`
- 短字段（标题/标签/地点/时间/链接/搜索词）全部 <1000，不受影响；搜索型输入仍归 07 处置。

### 3. 预算：15 分钟不变，停顿只吃剩余预算

- `PUBLISH_TIMEOUT_SECONDS = 15*60`（`uploader/publish_timeout.py:19`）不变；不新增「人类化预算」。`[code]`
- 每个平台构造 `Humanizer(page, sleep=<pause>)`，pause 语义照 XHS `_humanize_pause`（`xiaohongshu_uploader/main.py:2324-2333`）：

  ```python
  remaining = max(0.0, budget.remaining_seconds())
  if seconds > remaining:
      <WARNING，每流程一次>
  await asyncio.sleep(min(seconds, remaining))
  ```

- 预算耗尽时收缩到 0，**不抛**；超时判据仍只在锚点 / 发布点击：点击前 `pre_click_error()`（exit 1），点击后 `PublishResultUnknownError`（exit 9）。
- 新增可观测性（XHS 当前没有）：clamp 真发生（`seconds > remaining`）时打一次 WARNING，带 `remaining`；每流程一次，避免刷屏。
- **已知限制（本轮接受，不缓解）**：horizon 是 per-call，多个 <1000 字段可累积吃光预算。最坏是 IG carousel alt text（每张 ≤1000 字、逐张 `fill`，`insgraph_uploader/controls/alt_text.py:183` 的 `set()`）。后果是点击前 exit 1（不发布）；唯一缓解是 `HUMANIZE=0`。

### 4. 固定 sleep：不改不删，对齐 XHS

- 交互层提交对 `asyncio.sleep` / `wait_for_timeout` 的增删上限：**0 删、1 增**（新增的只有 pause 包装）。XHS 实测 `f429242`：删 0、增 1。`[code]`
- 338 处裸 wait（105 `asyncio.sleep` + 233 `wait_for_timeout`）原样保留。
- 依据：这些 wait 是 UI settle / 轮询，不是行为节奏；XHS `_settle` 注释明说「固定 UI 静置（点击/输入后的界面动画），不是就绪判据」（`main.py:2312-2314`）。`[code]`
- 「把 wait 接预算」是 XHS `53c723f` 那类独立工作（删 32 增 7：合并相邻重复、字面值→常量、全部 clamp），与本交互层是两个提交边界；已记入 map 的 **Out of scope**。

### 5. 耗时基线：只做三平台真机实测

- 规格**不写静态预算表**、不承诺数字。
- 只在 3 个真机平台验收时记录：同内容各跑一次 `HUMANIZE=1` / `HUMANIZE=0`，记录总墙钟、上传等待、人类化增量、是否成功。
- 其余 12 个标「未验证」，不估算、不推导。
- 注意 `HUMANIZE=0` 是**语义切换**而非同路径去停顿（`locator.click` / 单次 `insert_text`，`utils/humanize.py:212-215`、`:247-255`），成功集合可能不同；「关」也要记成功与否，不能只记耗时。`[code]`

### 给 06 的硬性条款

1. 阈值唯一（1000）+ 沿用既有静态门，不新增第二处定义。
2. 上表逐字段登记 + 每平台 bulk 断言 + 三平台真机读回。
3. `sleep=budget_clamped_pause` 是构造 `Humanizer` 的强制形态；clamp 时 WARNING 一次/流程。
4. sleep 增删上限 0 删 / 1 增；禁止顺手删 wait。
5. 基线只记三平台实测，其余标「未验证」。
6. 两条已知限制必须进规格「限制」章：码点口径（emoji 提前越线）；per-call 累积成本（IG alt text 最坏）。
