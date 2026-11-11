# 03 — 发布提交语义：预算底座 + 单次点击

Status: resolved
Type: grilling
Blocked by: 01
Assignee: wayfinder-session (opencode)

## Question

决定发布提交的语义，使“点一次发布最多只发一次”成立。需要确认：

1. **预算底座**：是否先把小红书迁到 `uploader/publish_timeout.py` 的 `PublishTimeoutBudget`（预算、`--not-before` 顺延、`clamp_ms`/`clamp_seconds`、`pre_click_error`、`timeout_error`、exit 1/9）？现为自建 `_new_publish_deadline` + 手写顺延，且**没有 clamp**，固定超时会超支预算。
2. **点击策略**：单次点击。观察窗多长（现 3s，上游 15s）？
3. **成功信号**：`publish/success` 字样，还是“URL 离开 `/publish/publish`”（上游）？两者关系是取代还是并集？
4. **唯一允许重试的条件**：页面未变 + 按钮仍可点 + 未命中拒绝词？最多几次？
5. **exit 9 边界**：观察窗耗尽 → `PublishResultUnknownError`；预算耗尽（点击后）→ 同上；预算耗尽（点击前）→ exit 1。是否保留这一三分。
6. `--no-publish` 干跑是否复用同一预算（且不进入提交循环）。

产出：判定表（事件 × 观测信号 × 结论 × 退出码 × 是否可重试），可直接进 spec。

## Evidence from 02（真机取证）

- `xhs-publish-btn[submit-disabled]` 在**标题为空**时为 `false` → 该属性只表达「上传/处理可提交」，不能当「表单已填完」的判据；点击前自检需另行定义。
- 元素 `innerText` 为空，任何基于「发布」文字的等待/点击在现网都不会命中。

## Answer

**决议**：提交段重写为 `ARM → FIRE → OBSERVE → 三分类`。语义与运行模式无关（本地 / 托管共用同一条实现），参照对象为 `xpzouying/xiaohongshu-mcp` 的 `findPublishButton` / `waitForPublishButtonClickable` / `clickPublishButton` / `waitPublishSuccess` 四段式，但按 charter ① 改掉其不安全处（见 §7）。

### 0. 判定表（可直接进 spec）

| 阶段 | 观测 | 结论 | 退出码 | 是否可重试 |
|---|---|---|---|---|
| ARM | 就绪谓词未满足 | 继续等（1s / 轮） | — | **是（唯一允许重试的地方）** |
| ARM | 窗口 `min(60s, 预算)` 用尽 | 确定未发布 | 1 | 是 |
| ARM | 预算耗尽 | 确定未发布 | 1 | 是 |
| FIRE | 派发后任意异常 | 可能已发布 | 9 | 否 |
| OBSERVE | URL 命中 `publish/success` | 成功 | 0 | — |
| OBSERVE | 命中拒绝词（词表归 04） | 平台拒绝 | 1 | 由 04 定 |
| OBSERVE | 预算耗尽 | 结果未知 | 9 | 否 |
| OBSERVE | 落在登录 / 验证页 | 结果未知（点击已发出） | 9 | 否 |

### 1. 预算底座（工单原前提作废）

`PublishTimeoutBudget` **已经落地**（`main.py:648` `start_publish_budget`，`:1097`、`:1305` 各自调用；`wait_until_allowed` 顺延在 `:1164`、`:1347`）。**仍缺的是 clamp**：小红书目前 0 处 `clamp_ms` / `clamp_seconds`（对比：TikTok / 抖音 / 知乎 / 微博 均有）。本决议要求把这些固定超时全部纳入预算：

- `:1106` / `:1314` `page.wait_for_url(publish_url)`（Playwright 默认 30s）
- `:1112` `wait_for_selector('input.upload-input', timeout=3000)`
- `:1320` `upload_input.wait_for(state="attached", timeout=30000)`
- `:1328` `title_container.wait_for(state="visible", timeout=3000)`
- ARM 的窗口（唯一需要上限的地方）；OBSERVE **不设上限**，见 §4
- 现存的 `sleep(2)` / `sleep(1)` / `sleep(0.5)` 不 clamp，但每轮循环必须经 `check_pre_click()`。

`--not-before` 顺延保持现有语义（`GLOSSARY.md` 已定义）。**注释声称 / 代码明确**：`PublishTimeoutBudget` 的 15 分钟契约见 `uploader/publish_timeout.py:1-9`。

### 2. ARM —— 就绪轮询（重试唯一发生处）

- 间隔 **1s**；**每轮重新解析按钮**，不缓存 locator（抗重渲染；参考实现同）。
- 就绪谓词（选择器本体与命中日志归 05，语义在此固定）：
  1. `xhs-publish-btn` 存在且可见；
  2. `is-publish != "false"`（属性缺失视为通过）；
  3. `submit-disabled != "true"`（属性缺失视为通过）；
  4. 找到新版但被禁用时**不回落旧版**（`02` 证旧版现网为 0；回落只会在新版翻车时点错目标）。
- 窗口 = `min(60s, budget.clamp_seconds(...))`；超时抛出带 `disabledReason` 的 `RuntimeError` → **exit 1**。
- **不采用**参考实现的固定 15s：视频就绪实测约 12s 且抖动（`02`），15s 余量不足；exit 1 可安全重跑，不值得为省 45s 冒险。

### 3. FIRE —— 单次派发，不可重试

- 顺序固定：**先置 `publish_clicked = True`，再派发**。派发后无论抛什么异常都不再触碰按钮。
- 点击目标由 ARM 谓词解析得到，**与发布策略无关**：定时发布也点同一个按钮，不按策略换 `button:has-text("定时发布")`（现状 `:1180`、`:1363` 是错的：把策略混进了控件解析）。定时态的实际按钮文案与 DOM **需真机验证**。
- 点击**机制**（元素 `locator.click` / 坐标 `mouse.click` + 人类化）归 **10**；对 03 的接口约束只有一条：**必须能区分「确定未派发」与「可能已派发」**；做不到就退回元素 click。若 10 选坐标点击，必须在按下前补一次落点复核（参考实现的 widget 路径**没有**这一步，是已知盲点，不照抄）。

### 4. OBSERVE —— 成功判据与窗口

- 判据**不变**：**只认** URL 命中 `publish/success`（含查询串）。现状 `:699` 已经是这个判据，本决议**不修改**它。**不采用**参考实现的「URL 不含 `/publish/publish` 即成功」——该判据会把登录页、验证页、任意跳转当成功（`research/01` §2，**代码明确**）。
- 窗口**不变**：外层循环持续到预算耗尽（现状 `:1171-1201` / `:1354-1384` 已如此），**本决议不加 60s 上限**。给观察窗设上限会把「慢但对」的发布推进 `exit 9`，与 charter ② 相反；上限的唯一收益是少等几分钟，不成立。
- 轮询间隔沿用现状 0.3s；扫描成本（现状每 0.3s × 7 类容器 × 最多 12 元素）归 **04**。
- 用尽预算 → `PublishResultUnknownError`（**exit 9**）。
- 点击后仍在页面上、但命中拒绝词 → `XhsPublishRejectedError`（**exit 1**）；**词表与扫描频率归 04**（现状 `:657` 的 `_find_publish_failure`，且刻意排除了限流词 `:63-66`）。

> 修正记录（2026-11-10）：本决议初稿误把「只认 `publish/success`」和「60s 窗口」写成对现状的改动。事实上判据现状已然如此；窗口设上限则是**收窄**（现状≈剩余预算），会抬高 exit 9 频率。两项均已撤回为「保持现状」。

### 5. 点击后落登录 / 验证页 = exit 9（与 07 的交叉）

点击已发出，帖子可能已成；因此**不得**再走 `LoginRequiredError`（10）。现状 `:1172-1175` 与 `:1196-1197` 会在预算耗尽或轮询异常时先调 `_raise_if_login_required(page)`，导致点击后跳登录页被判成 10 —— **必须加 `publish_clicked is False` 守卫**。点击前（ARM 阶段）落登录页仍归 10，最终以 07 的结论为准。

### 6. `--no-publish`

复用同一预算（现状已在提交段之前 `return`，`:1160` / `:1343`），**不进入 ARM / FIRE / OBSERVE**。

### 7. 与参照实现的九处差异（其余照搬）

| # | 环节 | 参考实现 | 本决议 | 理由 |
|---|---|---|---|---|
| 1 | ARM 窗口 | 固定 15s | `min(60s, 预算)` | 视频就绪余量；exit 1 可重跑 |
| 2 | 预算 | 无总预算概念 | 全部 clamp | 我们已有预算，裸超时会超支 |
| 3 | 成功判据 | 不含 `/publish/publish` | 只认 `publish/success`（**与现状一致，不改**） | 前者把登录/验证页当成功 |
| 4 | 观察窗口 | 15s | 预算耗尽为止（**与现状一致，不改**） | 15s 会把「慢但对」判成未知；给窗口设上限只会抬高 exit 9 |
| 5 | 失败分档 | 无，返回 error | 0 / 1 / 9 / 10 | 调度器需要机器可读且禁止自动重发 |
| 6 | 拒绝词扫描 | 发布链路不调用 | 点击后扫，词表归 04 | 补它缺的，不是对齐 |
| 7 | 点击命中复核 | widget 路径无 | 坐标点击必须补 | 避免点空后静默进 9 |
| 8 | 定时按钮 | 同一个通用按钮 | 同参考 | 策略不应改变控件 |
| 9 | 点击重试 | 无循环 | 循环只在 ARM，FIRE 后零重试 | 效果同，机制更安全 |

完全照搬、建议 05 直接进矩阵：属性缺失按可点击；`is-publish=="false"` 跳过；`submit-disabled=="true"` 视为禁用且不回落；旧版 `disabled` **存在即禁用**；先新版后旧版。

### 8. 对下游工单的约束

- **05**：沿用上述就绪谓词与优先级；按钮选择器必须能在 `innerText` 为空的前提下命中（`02` 已证文字类选择器全部失效）。
- **04**：拒绝词表 + 扫描频率；限流词不得继续排除在拒绝词之外。
- **07**：点击后登录/验证页的唯一归属 = 9（见 §5）。
- **10**：点击机制必须能回答「确定未派发 / 可能已派发」（见 §3）。
- **06**：ARM 的「可见」判定复用 06 的可见性 helper，不再各自 `count()`。
- **16**：把 §0 判定表做成可执行镜像；见下方「需真机」。

### 9. 需真机验证（阻塞性风险）

1. **定时发布成功后是否跳转 `publish/success`** —— 若不跳转（例如只弹 toast），每一次定时发布都会等到预算耗尽才进 `exit 9`。**现状已是如此，不是本决议引入的**；但它是 exit 9 的基线频率，也是 20（自动对账）收益的直接来源，必须先在 16 的真机验收里确证。
2. `publish/success` 的精确 URL 形态（`02` 未覆盖 query，**需真机验证**）。
3. 定时态发布按钮的实际 DOM / 文案（**需真机验证**）。
4. 点击后落登录页在托管模式下现在会被判成 `10`（`:1172-1175`、`:1196-1197`）；`publish_clicked` 守卫加上后是否还有别的分支会把 9 抢成 10（**需真机验证触发频率**）。
