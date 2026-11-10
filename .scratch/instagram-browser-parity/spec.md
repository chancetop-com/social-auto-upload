# Instagram 内容发布 — 第一波实施规格

- 版本：v1（2026-11-10）
- 来源：[路线图](./map.md) 与工单 [01](./issues/01-business-api-capabilities.md)–[08](./issues/08-test-strategy.md)
- 状态：可实施；真实账号真发验收尚未执行（见 §8）
- 能力全量对照：[`capability-matrix.md`](./capability-matrix.md)

---

## 1. 目的与范围

### 1.1 目的地

在不接入官方 API、不要求 OAuth / 公网媒体 URL 的前提下，用现有 instagram.com 浏览器流程，补齐 Instagram Content Publishing API 中**网页端可达**的作者侧发布能力，并保持现有命令向后兼容（唯一例外见 §3.4）。

### 1.2 本轮范围（第一波 = 4 项）

| # | 能力 | 命令 | 网页入口 |
|---|---|---|---|
| 1 | `Location` 地点 | `upload-video` / `upload-note` | 配文页 `Add location` |
| 2 | `Alt text` 替代文字 | `upload-note`（单图/轮播） | 配文页 `Accessibility` → `Alt text` |
| 3 | 关闭评论 | `upload-video` / `upload-note` | 配文页 `Advanced settings` → `Turn off commenting` |
| 4 | AI 生成标识 | `upload-video` / `upload-note` | 配文页 `Add AI label` |

### 1.3 本轮不做

- **Collaborators**：07 曾纳入，08 正式移除；验收需要第二账号且“邀请/接受”分离，收益不匹配本轮成本。
- Stories、定时发布、配乐/曲库、选帧封面、user_tags、媒体大小/时长/宽高比校验、滤镜、隐藏点赞、商品标签、品牌内容、caption add-ons。
- 发布后回读对账、洞察、评论管理、webhook（`config_issue` 无网页等价物）。
- 官方 API、OAuth、开发者 App、token 管理、公网媒体 URL、容器轮询。
- Flask 后端、Vue 前端、调度 App、账号↔Profile 映射与身份校验。

### 1.4 与既有行为的关系

- 新参数**全部可选**；不传时完全不动页面默认，也不产生任何回读要求。
- 发布流程、结果三态（`published` / `processing` / `submission_unknown`）、超时预算、失败证据、托管浏览器 seam（MLX / AdsPower）均保持不变。
- 唯一破坏性变更：caption > 2200 的退出码由 `1` 改为 `2`（§3.4）。

---

## 2. 能力基线（摘要）

完整矩阵见 [`capability-matrix.md`](./capability-matrix.md)。本轮只消费其中“网页有入口且已实测”的 4 项。

| 能力 | Business API | Standalone API | 网页端 | 本轮 |
|---|---|---|---|---|
| 单图 / 轮播 / Reels / 配文 / 上传封面 | ✅ | ✅ | 已覆盖 | 保持 |
| Location | ✅ | ❌ | 有入口 | **实现** |
| Alt text（图片，≤1000/张） | ✅ | ✅ | 有入口（轮播逐张） | **实现** |
| 关闭评论 | ✅（仅发布后） | ✅（仅发布后） | 有入口（发布前） | **实现** |
| AI 生成标识 | ✅ | ✅ | 有入口 | **实现** |
| Stories | ✅仅 Business | ✅ | 当前 Personal 账号不可用 | 延后 |
| 定时发布 | ❌ | ❌ | 专业后台，账号资格阻塞 | 延后 |
| 配乐 / 选帧封面 | ✅ | 部分 | 当前账号不可用 | 延后 |
| user_tags / collaborators | ✅ | 部分 | 有入口 | 延后 |
| 滤镜 / 隐藏点赞 | ❌ | ❌ | 有入口 | 延后 |
| 商品标签 / 品牌内容 / caption add-ons | 条件 | 部分 | 很可能 API-only | 排除 |

**基线原则**：按“网页可达并集”对齐，不按两套 API 的交集自砍；API-only 项明确记 `unsupported`，不伪装成已支持。

---

## 3. CLI 契约

### 3.1 参数

两个命令共用同一组发布选项；`--alt-text` 只注册在 `upload-note`。

| Flag | 适用命令 | argparse 形态 | 取值 | 未传时 |
|---|---|---|---|---|
| `--location TEXT` | `upload-video` / `upload-note` | `str` | 地点名，非空 | `None`，不动页面默认 |
| `--alt-text TEXT` | **`upload-note` only** | `action="append"` | 每张图一条，0 或 N 条，每条 1–1000 字符 | `None`，不动页面默认 |
| `--no-comments` | `upload-video` / `upload-note` | `action="store_true"` | 请求关闭评论 | `None`，不动页面默认 |
| `--ai-generated` | `upload-video` / `upload-note` | 互斥组，`dest="ai_generated"`，`store_const=True` | 请求开启 AI 标识 | `None` |
| `--no-ai-generated` | 同上 | 互斥组，`store_const=False` | 请求关闭 AI 标识 | `None` |

实现约定：

- `--no-comments` 解析为 `comments = False if args.no_comments else None`，**不要**默认成 `False`。
- `--ai-generated` / `--no-ai-generated` 用 `argparse.add_mutually_exclusive_group()`；同传由 argparse 直接 `SystemExit(2)`。
- 三项布尔/三态值必须保留 `True / False / None`，禁止在传递过程中压缩成二值。
- 新 flag 不设 `required`，不给 `default=True/False`。

### 3.2 示例

```bash
sau instagram upload-video --account creator --file demo.mp4 --title "标题" \
  --location "Shanghai" --no-comments --ai-generated

sau instagram upload-note --account creator --images 1.jpg 2.jpg --title "标题" \
  --alt-text "第一张图的描述" --alt-text "第二张图的描述" \
  --location "Shanghai" --no-comments
```

### 3.3 静态校验（全部在浏览器启动前）

新增 `validate_instagram_publish_request(...)`，在 `sau_commands/instagram.py:run()` 构造 `InstagramUploadRequest` 之后、调用 `upload_instagram_content()` 之前执行。所有失败抛 `utils.errors.UsageError` → 退出码 **2**，且不得启动浏览器 / 托管 Profile。

| 校验 | 规则 | 错误信息要求 |
|---|---|---|
| caption 长度 | `len(caption) > 2200` → `UsageError`（**由 1 改为 2**） | 说明标题+正文+标签合计上限 |
| 媒体互斥 | 视频与图片同时提供，或都不提供 | 原文案保留 |
| thumbnail 适用 | `--thumbnail` 只能用于视频 | 原文案保留 |
| `--alt-text` 数量 | 必须为 0 或等于图片张数 N | 报出实际条数与图片张数 |
| `--alt-text` 单条长度 | 每条 `1..1000` 字符（空串也算非法） | 报出第几条与长度 |
| `--location` | `strip()` 后非空 | 报“地点不能为空” |
| AI 互斥 | 由 argparse 处理 | `SystemExit(2)` |

边界说明：

- 标题为空、素材不存在、素材后缀不支持等**既有**校验保持原异常类型与退出码 `1`，不在本轮迁移范围内；不要顺手扩大破坏面。
- 校验函数不访问网络、不读页面、不构造 uploader。
- `InstagramUploader.__init__` 内的同类校验改为调用共享纯函数并抛 `UsageError`，防止绕过 CLI 时又退回 `ValueError → 1`。

### 3.4 向后兼容与破坏性变更

- 不新增必填参数；不传新 flag 时，参数、行为、结果文件字段与退出码与现状一致。
- **有意破坏**：caption 超过 2200 由 `ValueError → 1` 改为 `UsageError → 2`，与 TikTok / 小红书一致。依赖旧退出码的外部脚本需适配。必须在 `CHANGELOG.md` 明确标注。
- 新增结果字段 `options` 是纯增量，旧消费方忽略即可。

---

## 4. 发布流程与 UI 路径

### 4.1 插入点

现有流程：`_upload_files` → `_advance_media_editor` → `_publish`（填配文 → 等待 `--not-before` → 点 Share → 旁听 `POST /api/v1/media/configure`）。

本轮在 `_publish` 内插入一步：

```text
填入配文并回读一致
→ self.stage = 'options'
→ await self._apply_options(page, budget=budget)
→ budget.wait_until_allowed(...)      # --not-before，原有逻辑
→ budget.check_pre_click()
→ 点 Share
```

- 选项**必须在点击 Share 之前**完成；任何选项失败都表示“尚未发布”，退出码为 `1`，不是 `9`。
- 选项耗时计入既有 15 分钟总预算；每一步前 `budget.check_pre_click()`，所有等待用 `budget.clamp_ms(...)` 收紧。
- 四个选项共用同一个创建弹窗（`page.get_by_role('dialog')`）；所有定位都必须**限定在该 dialog 内**，禁止全页 `nth()`。
- 失败时沿用 `_capture_failure`：`stage='options'`，保存 `page.png` + `page.html`。

### 4.2 应用顺序与幂等

顺序（理由：先处理会开关模态框的项，最后展开高级设置，避免面板遮挡）：

1. `alt_text` —— 打开 `Accessibility` 模态框、逐张填写、关闭并重新打开回读。
2. `location` —— 行内搜索联想。
3. `ai_generated` —— 配文页开关。
4. `comments` —— 最后展开 `Advanced settings`。

幂等要求：

- `Advanced settings` 若已展开（开关可见 / `aria-expanded="true"`），不再点击。
- 开关已是目标状态时不点击，直接按状态归类（§5.2）。
- 每项独立解析、独立失败；某项失败不阻止后续项继续尝试，最后统一抛错（便于结果文件一次看全）。预算耗尽等硬异常立即中止。

### 4.3 各项 UI 路径与选择器

> 证据等级：**已实测** = 2026-11-10 English UI 真实账号观察（[06 记录](./research/06-entry-probe.md)）；**候选** = 按现有代码风格设计的回退，需真实 DOM 用例固定。语言策略：英文为主，中文回退；禁止只按可见文案的单一定位。

#### 4.3.1 Location

| 项 | 内容 |
|---|---|
| 阶段 | 配文页 |
| 主选择器（已实测） | `input[placeholder="Add location"]` |
| 回退（候选） | `input[name="creation-location-input"]`（实测 DOM 结构属性）、`input[placeholder*="location" i]`、`input[placeholder*="地点"]`、`input[aria-label*="location" i]` |
| 联想列表（已实测） | 真实 DOM **没有** `[role="option"]`：portal 滚动容器挂页面根，候选是普通 `div` 行；从输入框出发按几何（下方 520px 内、行高 40–80px、宽 >200px）枚举，再按精确文本选中 |
| 交互 | 填入地点 → 等待列表 → 规范化精确匹配 → 点击唯一候选 |
| 回读 | 输入框 `value`；为空时读已选 chip 文本（候选，DOM 用例固定） |
| 规范化 | `" ".join(text.split()).casefold()`；大小写、首尾/连续空白不敏感 |
| 无匹配 | 退出 1，错误信息列出观察到的候选（最多 10 条）；**不**点模糊匹配 |
| 同名候选 | 取第一个，不额外报歧义 |
| 入口缺失 / disabled | 请求值 → `unsupported` + `entry_missing` / `account_ineligible`，退出 1 |

实现细节：

- 输入后等待列表出现（建议 10s，按剩余预算收紧）；若列表始终为空，清空重输一次再失败，避免 debounce 竞态。
- 选中后以页面回读值为 `applied`，但只有回读值与**被点候选的标签**规范化一致才算 `set`；请求值与被点候选不精确相等时不得点击。
- `--location` 只影响本选项；失败不改变其他选项的处理。

#### 4.3.2 Alt text

| 项 | 内容 |
|---|---|
| 阶段 | 配文页 |
| 入口（已实测） | `Accessibility` 按钮/行（英文；中文回退「无障碍」/「替代文字」） |
| 输入（已实测） | 行内折叠区内 `input[aria-label="Alt text"]` / `input[placeholder="Alt text"]`，2 图轮播观察到 2 个 |
| 回退（候选） | `input[aria-label*="alt" i]`、`input[placeholder*="alt" i]`、`textarea[aria-label*="alt" i]`、`textarea[placeholder*="alt" i]`、中文「替代文字」 |
| 交互 | 展开 `Accessibility` 行内折叠区 → 断言输入框数量 = 图片数 N → 按图片顺序逐张 `fill` 并 blur → 再次激活该行收起 |
| 回读 | 收起后重新展开，读取 N 个输入框的值，按顺序比较 |
| 数量不符 | 0 个 → `unsupported` + `entry_missing`；1..N-1 个 → `mismatch`（入口存在但无法表达全部图片），退出 1 |
| 长度 | 每条 1–1000，已在 §3.3 静态校验；运行时不再截断 |
| 关闭动作 | 再次激活 `Accessibility` 折叠行（实测无 `Done`/`Save` 按钮）；收不起来 → `mismatch`，退出 1 |

实现细节：

- `--alt-text` 只在 `upload-note` 注册；视频命令即使手写该 flag 也由 argparse 拒绝。
- 单图 = 1 条；轮播 = N 条；顺序严格对应 `--images` 顺序。
- 回读必须收起后重新展开折叠区；不能以“填进去时的输入框值”代替回读。
- 图片数 N 从 `self.image_files` 取，不用 DOM 猜测。

#### 4.3.3 关闭评论

| 项 | 内容 |
|---|---|
| 阶段 | 配文页 → `Advanced settings` |
| 入口（已实测） | `Advanced settings` 展开后 `Turn off commenting` 开关 |
| 主选择器（候选） | 含文案 `Turn off commenting` / `关闭评论` 的行内 `input[role="switch"]`；回退 `div[role="switch"]`、`[role="checkbox"]` |
| 语义 | **开关 checked = 评论已关闭**；`read()` 对外返回 `comments_enabled`（checked 取反），禁止把 `aria-checked` 直接当“评论开启” |
| 交互 | 展开 Advanced settings（幂等）→ 请求 off 且当前 on → 点击；请求 off 且已 off → 不点击 |
| 回读 | 重新读取开关 `aria-checked`，换算成 `comments_enabled` |
| 入口缺失 + off | `default_off` + `reason=entry_missing`，退出 0（入口缺失等价于无法开启评论） |
| 入口 disabled + off | `default_off`，退出 0，不点击 |
| 入口缺失/disabled + 请求 on | 本轮没有 `--comments`，不适用；若未来新增，必须 `unsupported` + reason，退出 1 |

#### 4.3.4 AI 生成标识

| 项 | 内容 |
|---|---|
| 阶段 | 配文页 |
| 入口（已实测） | `Add AI label` 开关；`input[role="switch"]`，`aria-checked=false` |
| 回退（候选） | 含文案 `Add AI label` / `AI label` / `AI 标签` / `添加 AI 标签` 的行内 `input[role="switch"]`；再退 `div[role="switch"]`、`[role="checkbox"]` |
| 交互 | 读取 `aria-checked` → 与请求值不同时点击 → 回读 |
| 回读 | `aria-checked` 布尔值 |
| 请求 `True` + 入口缺失/disabled | `unsupported` + reason，退出 1 |
| 请求 `False` + 入口缺失/disabled 或已 false | `default_off`，退出 0 |
| 请求 `False` + 当前 true | 点击关闭 → 回读 false 记 `set`；点击后仍 true → `mismatch`，退出 1 |

说明：AI 标识与关闭评论是两个**独立**开关，无互斥；不要复用 TikTok 的 `--aigc` 命名。

### 4.4 语言与漂移

- 06 只在 English (US) 下实测；中文文案为回退，未验证。定位优先级：结构 / `placeholder` / `role` → 英文文案 → 中文文案。
- 所有“入口缺失”分支都是显式结果（`unsupported`），不是崩溃；选择器漂移会先表现为 `entry_missing`，并被真实 DOM 哨兵（§7.3）捕获。
- 不引入 manifest、不引入选择器注册表、不做自动修复。

---

## 5. 结果与失败语义

### 5.1 结果文件

发布结果新增顶层 `options` 对象，四项**始终存在**（未传也写 `not_requested`）：

```json
"options": {
  "location": {"requested": "Shanghai", "applied": "Shanghai", "status": "set"},
  "alt_text": {"requested": ["第一张", "第二张"], "applied": ["第一张", "第二张"], "status": "set"},
  "comments": {"requested": false, "applied": false, "status": "set"},
  "ai_generated": {"requested": true, "applied": true, "status": "set"}
}
```

未请求项：

```json
"location": {"requested": null, "applied": null, "status": "not_requested"}
```

字段：

| 字段 | 含义 |
|---|---|
| `requested` | CLI 请求值；未传为 `null` |
| `applied` | 页面回读值；无法读取为 `null` |
| `status` | `not_requested` / `set` / `default_off` / `unsupported` / `mismatch`（5 个，不新增） |
| `reason` | 可选；`entry_missing` / `account_ineligible`；无归因时省略 |

- `options` 在开始应用前写入结果对象，任何一次选项处理完成后都落盘；失败时由 `_capture_failure` 一并保存。
- 成功发布的结果同时保留既有 `published` / `content_id` / `post_id` / `post_url` / `media_count` / `schedule`。

### 5.2 状态映射

| 情形 | status | reason | applied | 退出 |
|---|---|---|---|---|
| 未传 | `not_requested` | — | `null` | 0 |
| 请求值/on，入口缺失 | `unsupported` | `entry_missing` | `null` | 1 |
| 请求值/on，入口存在但 disabled / 账号不合格 | `unsupported` | `account_ineligible` | `null` | 1 |
| 设置后回读一致 | `set` | — | 回读值 | 0 |
| 设置后回读不一致 | `mismatch` | — | 实际回读值 | 1 |
| location 无精确匹配（入口存在） | `mismatch` | — | `null` | 1 |
| alt_text 输入框数量 1..N-1 | `mismatch` | — | 实际列表 | 1 |
| 请求 off（comments/AI），入口缺失 | `default_off` | `entry_missing` | `null` | 0 |
| 请求 off，入口存在且已 off | `default_off` | — | `false` | 0 |
| 请求 off，入口存在但 disabled 且已 off | `default_off` | `account_ineligible` | `false` | 0 |
| 请求 off，当前 on，点击后回读 off | `set` | — | `false` | 0 |

补充：

- `default_off` 只用于“请求的是 off，且无需动作即已满足”；主动点击关闭成功记 `set`。
- 位置“无匹配”不走 `unsupported`：入口存在、只是值没有精确候选，记 `mismatch`。
- 一旦出现任何 `unsupported` / `mismatch`，**不点击 Share**，抛出 `RuntimeError`（退出 1），错误信息汇总所有失败项：`location=unsupported(entry_missing); comments=mismatch`。

### 5.3 退出码

| 码 | 含义 | 本轮变化 |
|---|---|---|
| 0 | 成功（含 off 已满足 / 入口缺失但 off） | 保持 |
| 1 | 运行时失败：mismatch、入口缺失且请求 on/值、location 无匹配 | 保持 |
| 2 | 静态输入错误：argparse 冲突、caption >2200、alt-text 数量/长度、location 空串、媒体互斥、thumbnail 误用 | **caption 由 1 改 2** |
| 9 | 已点发布但结果未知 | 保持；选项失败发生在点击前，绝不使用 9 |
| 10 | 需要登录 | 保持 |
| 11 | 限流 | 保持 |

### 5.4 明确不做

- 不做发布后回读对账（alt/location/comments/AI 是否真的落在最终帖子上）。本轮只保证“点击发布前，页面状态与请求一致”；最终效果由 §8 真发验收覆盖。
- 不把 `submission_unknown` / `processing` 当成功；不自动重发。
- 不修改 `verify` / `delete` 的参数或语义。

---

## 6. 代码改动清单

### 6.1 新增 `uploader/meta_uploader/insgraph_uploader/options.py`

纯逻辑 + 控件协议，不启动浏览器：

```python
@dataclass(frozen=True, slots=True)
class InstagramPublishOptions:
    location: str | None = None
    alt_texts: tuple[str, ...] | None = None
    comments: bool | None = None          # False = 关闭评论
    ai_generated: bool | None = None

# status 常量
NOT_REQUESTED = "not_requested"
SET = "set"
DEFAULT_OFF = "default_off"
UNSUPPORTED = "unsupported"
MISMATCH = "mismatch"
```

纯函数（全部可单测，零浏览器）：

| 函数 | 职责 |
|---|---|
| `normalize_text(text) -> str` | 空白折叠 + `casefold()`，供 location/alt 比较 |
| `validate_publish_options(options, *, image_count, caption) -> None` | §3.3 的静态校验，失败抛 `UsageError` |
| `empty_option_record(options) -> dict` | 生成四项 `not_requested` 骨架 |
| `location_matches(requested, applied) -> bool` | 规范化后相等 |
| `alt_texts_match(requested, applied) -> bool` | 长度相等且逐项相等 |
| `option_status(requested, applied, *, kind, present, ineligible) -> tuple[str, str|None]` | §5.2 映射；`kind` 为 `value` / `toggle` |
| `option_failures(record) -> list[str]` | 汇总 `unsupported` / `mismatch`，生成人类可读错误 |

控件协议（duck-typed，只要求测试实现被调用的方法）：

```python
class InstagramOptionControl(Protocol):
    async def resolve(self) -> str:   # "present" | "missing" | "ineligible"
        ...
    async def read(self) -> object:   # str | list[str] | bool | None
        ...
    async def set(self, requested) -> None:
        ...
```

`resolve` 的三态覆盖 08 的只读/缺失/disabled 分支；`read` 必须返回**语义值**（comments 返回 `comments_enabled`，不是原始 `aria-checked`）。

### 6.2 `sau_commands/instagram.py`

- 新增 `_add_instagram_option_flags(parser, *, include_alt_text: bool)`，在两个 upload 子命令上注册 §3.1 的 flag。
- `InstagramUploadRequest` 增加 `options: InstagramPublishOptions | None = None`。
- `run()` 中：
  1. 构造 request；
  2. `validate_instagram_publish_request(request)`；
  3. 再进入 `upload_instagram_content()` / 托管 Profile 分支。
- `_build_uploader()` 把 `options=request.options` 传给 `InstagramUploader`。
- 不传任何新 flag 时 `options=None`，保持真正的 legacy 路径（零控件交互，连读都不读），与 TikTok 的 `_build_publish_options` 同构。

### 6.3 `uploader/meta_uploader/insgraph_uploader/main.py`

- `InstagramUploader.__init__` 增加 `options: InstagramPublishOptions | None = None`，保存为 `self.options`，并在 `self.result` 中初始化 `options` 记录。
- 新增 `async def _apply_options(self, page, *, budget, controls=None) -> None`：
  - `controls is None` 时调用 `resolve_instagram_option_controls(page)`；
  - 按 §4.2 顺序逐项应用；
  - 每项写 `self.result['options'][key]` 并落盘；
  - 结束后若有失败项，抛 `RuntimeError`。
- 新增 `async def resolve_instagram_option_controls(page) -> InstagramOptionControls`（可放在 `options.py`，也可放 `main.py`；测试通过 `controls=` 注入 fake）。
- `_publish()` 在配文回读之后、`wait_until_allowed` 之前调用 `_apply_options`。
- `_validate_media` 与构造校验复用 `options.py` 的纯函数；同类错误统一抛 `UsageError`。
- 结果发布时保留 `options`；`_capture_failure` 无需特殊处理（结果对象已含 `options`）。

### 6.4 兼容性检查

- 本地 cookie 模式与托管（MLX / AdsPower）模式共用 `_upload_steps`，选项逻辑不得依赖 `account_file`。
- 不得引入新的浏览器依赖；继续使用 Patchright + 工程 Chrome。
- `check` / `login` / `verify` / `delete` 不感知新参数。

---

## 7. 测试策略

三层：纯逻辑 → fake 控制件 → 真实 DOM。新增 `tests/test_instagram_options.py`；`tests/test_instagram_uploader.py` 只加真实 DOM 与 10/11 守卫。

### 7.1 A. 纯逻辑（无浏览器）

| # | 测点 |
|---|---|
| A1 | parser 注册：两个命令都有 `--location`、`--no-comments`、`--ai-generated/--no-ai-generated`；`--alt-text` 只在 `upload-note`；`--thumbnail` 仍只在 `upload-video` |
| A2 | `--ai-generated` + `--no-ai-generated` 同传 → `SystemExit(2)` |
| A3 | 全不传 → 四项 `not_requested`，不产生回读要求 |
| A4 | `True` / `False` / `None` 三态不被压缩 |
| A5 | 以下均 `UsageError` → 2：caption >2200、视频+图片、thumbnail 用于图片、alt-text 数量非 0 且 ≠ 图数、单条 >1000、单条为空、location 空串 |
| A6 | `options` 结构：四项齐全，5 个 status 全覆盖，`reason` 仅在需要时出现 |

### 7.2 B. fake 控制件（不登录、不启动 Chrome）

| # | 场景 | 期望 |
|---|---|---|
| B1 | set → 回读一致 | `set` / exit 0 |
| B2 | set → 回读不一致 | `mismatch` / exit 1 / 不点 Share |
| B3 | 请求值/on + `missing` | `unsupported` + `entry_missing` / exit 1 |
| B4 | 请求 off + `missing` | `default_off` / exit 0 |
| B5 | 请求 off + `present` 且已 off | `default_off`，`set` 未被调用 / exit 0 |
| B6 | `ineligible` 但已满足 | `default_off`，不点击 / exit 0 |
| B7 | 未传 | 零控件交互 |
| B8 | location：大小写不敏感精确匹配；无匹配 → 错误含候选 / exit 1；同名取第一个 |
| B9 | alt_text：单图 1 条 / 轮播 N 条，顺序严格对应；数量不符的分类 |
| B10 | Advanced settings 未展开 → 先展开；重复调用幂等（只展开一次） |
| B11 | 多项同时失败 → 结果文件包含所有失败项，错误信息聚合，仍不点 Share |
| B12 | 预算耗尽/硬异常 → 中止，不继续后续项 |

fake 只需实现 `resolve / read / set`；用 `InstagramUploader._apply_options(page=None, controls=fake)` 注入，避免真实 DOM。

### 7.3 C. 真实 DOM（`test_instagram_uploader.py`，`page.set_content` + 工程 Chrome）

只验 happy path，不重复堆缺失/降级分支（那些在 B 层）：

| # | 测点 | fixture 要点 |
|---|---|---|
| C1 | location 输入 → 联想 → 选中 → 回读 | 输入时 JS 延迟生成 `[role="option"]`；回读值可观察 |
| C2 | Accessibility 模态框 → N 个 alt 输入 → 关闭 → 重新打开回读 | 模态框可开关；2 个输入 |
| C3 | Advanced settings 展开 → `Turn off commenting` 开关 → 回读 | `aria-checked` 初始 false，点击后 true |
| C4 | `Add AI label` 开关 → 回读 | `input[role="switch"]`，`aria-checked` 翻转 |

- 这些用例同时是漂移哨兵：选择器一变 CI 立刻红，不依赖登录态。
- 新增 1 条 guarded 路径：Instagram 未登录 → `LoginRequiredError`（退出 10 的映射）；11 的映射已有 `tests/test_adspower_cli.py:547/558` 覆盖，不重复。
- 现有 `test_instagram_uploader.py` 中 caption 用例需同步改为断言 `UsageError`（退出 2）。

### 7.4 D. 退出码

| 码 | 覆盖 |
|---|---|
| 0 | B1/B4/B5/B6 |
| 1 | B2/B3/B8/B11 |
| 2 | A2/A5（浏览器未启动） |
| 9 | 现有用例保留 |
| 10 | 新增 1 条 Instagram 守卫 |
| 11 | 复用既有映射测试 |

### 7.5 运行命令

```bash
python -m unittest tests.test_instagram_options tests.test_instagram_uploader -v
```

C 层需要本机 Chrome；无 Chrome 的环境至少保证 A/B 全绿。

### 7.6 明确不测

Stories、定时、配乐、选帧封面、user_tags、collaborators、caption add-ons、商品标签、品牌内容、发布后洞察/通知/webhook/评论管理、网络层与真实 Instagram 后端的契约。

---

## 8. 待验收附录（真实账号真发，不阻塞合并）

本轮**不做**真实账号真发验收。实现合并后，4 项在文档中标注 `offline-verified / post-publish unverified`；未完成本附录前，不得对外宣称“已支持”。

### 8.1 前置条件

- 一个可正常发帖的 Instagram 账号；English UI（或中文 UI 复跑一次选择器）。
- `sau instagram check --account <alias>` 通过；准备 1 张图、2 张图、1 条 ≤60s MP4。
- 不记录账号名、Cookie、Profile ID。

### 8.2 用例

| # | 步骤 | 通过判据 |
|---|---|---|
| 1 | `upload-note` + `--location "<已知地点>"` 发布单图 | 结果 `options.location.status=set`；帖子显示该地点；无“地点不可用”提示 |
| 2 | `upload-note` + 2 张图 + 两条 `--alt-text` | 发布后编辑页 `Accessibility` 逐张回读与输入一致；轮播顺序一致 |
| 3 | `upload-video` / `upload-note` + `--no-comments` | 发布后评论区关闭（无法评论） |
| 4 | `upload-video` / `upload-note` + `--ai-generated` | 发布后帖子显示 AI 标识 |
| 5 | 负向：`--location "不存在的地点 xyz"` | 退出 1；错误含候选；主页无新帖 |
| 6 | 负向：`--alt-text` 条数 ≠ 图片数 | 退出 2；浏览器未启动 |

可选：中文 UI 复跑 1–4，确认选择器回退有效。

### 8.3 证据与清理

- 结论、时间、帖子 URL 写入 `research/08-acceptance-evidence.md`（进 Git）。
- 截图/录屏放仓库外，文内只引用路径与时间（沿用 06 约定）。
- 验完用 `sau instagram delete --post-url ... --expected-text ...` 删帖；删除结果未知时先 `verify`，不重删。

---

## 9. 文档、发布与回滚

### 9.1 文档

| 文件 | 更新 |
|---|---|
| `docs/CLI.md` Instagram 段 | 新增 4 个 flag 的说明、示例、默认“不动页面”；说明 caption 退出码变更；把“上述选填功能当前未接入”改为“已接入 location/alt text/关评论/AI 标识，其余保留默认” |
| `CHANGELOG.md` `[Unreleased]` | 新能力条目；**破坏性变更**单独标注 caption 退出码 1→2；真发验收标“待验收” |
| `skills/meta-upload/SKILL.md` | 如果仍写“Instagram 当前暂停”，按现状修正并列出新参数；不宣称未验收能力 |
| `map.md` | 本规格完成后由 wayfinder 流程更新（不由本规格直接改） |

### 9.2 发布

- 纯 Python 增量，无数据库/配置迁移。
- 合并顺序：`options.py` + 测试 → CLI flag/校验 → `main.py` 接线 → 文档。
- 发布前必须：A/B/C/D 全绿；`docs/CLI.md` 与 `CHANGELOG.md` 已更新；无新增必填参数。

### 9.3 回滚

- 代码回滚 = revert 对应 commit；不传新 flag 的旧调用行为完全不变（除 caption 退出码，需随 CHANGELOG 说明）。
- 新 flag 无持久化副作用；失败证据目录 `.local/instagram-errors/` 可保留用于排查。
- 若某一项入口漂移导致 `entry_missing`，可单独回滚该选项的 UI 步骤，不影响其他三项与既有发布流程。

---

## 10. 完成定义（DoD）

1. `upload-video` / `upload-note` 注册 §3.1 全部 flag；`--alt-text` 仅 `upload-note`。
2. 所有静态校验在浏览器启动前完成，统一 `UsageError → 2`；caption 同步改为 2。
3. `_apply_options` 在点 Share 前完成，支持四选项的 set → 回读 → 结果记录。
4. 结果文件包含 §5.1 的 `options`，5 个 status + 2 个 reason 与 §5.2 完全一致。
5. 任何选项失败都不点击 Share，退出 1；不使用 9；不自动重发。
6. A/B/C/D 测试全绿；C 层真实 DOM 四条哨兵存在。
7. `docs/CLI.md`、`CHANGELOG.md`、`skills/meta-upload/SKILL.md` 已更新；真发验收标注“待验收”。
8. 不传新 flag 时，现有参数/行为/结果/退出码不变（caption 除外，已记录）。

---

## 11. 风险与待验证

| 风险 | 影响 | 处理 |
|---|---|---|
| 选择器仅在 English UI、Personal 账号观察 | 中文/专业账号可能 `entry_missing` | 双语回退 + 真实 DOM 哨兵 + 验收附录复跑 |
| `Accessibility` 模态框的关闭按钮文案未知 | 无法回读 alt text | DOM 用例固定主按钮；失败记 `mismatch`，不猜文案 |
| location 联想为异步搜索，存在 debounce | 误判无候选 | 10s 等待 + 一次重输重试；不点模糊匹配 |
| location 回读可能被规范化（如 “Shanghai, China”） | 严格比较误报 mismatch | 与“被点候选标签”比较，而非与原始输入比较 |
| “Turn off commenting” 开关语义反转 | 写反状态 | `read()` 返回 `comments_enabled`，DOM 用例显式断言取反 |
| 轮播 alt text 输入框数量/逐张顺序 | 张冠李戴 | 数量 = 图片数；顺序严格按 `--images`；数量不符记 mismatch |
| Advanced settings 展开后遮挡其他控件 | 后续点击失败 | 高级设置放最后；必要时收起后再结束 |
| 账号资格/实验门控 | 入口时有时无 | `unsupported` + reason，不崩溃；真发验收确认 |
| 发布后元数据被平台降级（`config_issue` 等价） | 页面设置成功但最终帖子未生效 | 本轮不做发布后对账；由 §8 验收覆盖，文档不得提前宣称 |

---

## 12. 实施顺序（建议）

1. `options.py`：dataclass、纯函数、status 映射 + `tests/test_instagram_options.py` A 层。
2. CLI：flag 注册、request 字段、静态校验 → A 层 parser/校验用例。
3. `main.py`：`_apply_options` + control 协议 + 结果记录 → B 层 fake 用例。
4. 真实 DOM 解析器 + 四个 C 层用例（红→绿固定选择器）。
5. 结果落盘/失败聚合/证据路径复核。
6. 文档与 CHANGELOG；标注待验收。
7. 真发验收（独立进行，不阻塞合并）。
