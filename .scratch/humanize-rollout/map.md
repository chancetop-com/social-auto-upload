# 人类化交互层跨平台落地 — 路线图

## Destination

一份可交给后续会话实施的规格（[`spec.md`](./spec.md)）：把 XHS 已验证的 `utils/humanize.py` 交互层——6 项行为 + 2 条禁令——移植到其余 15 个浏览器上传器，并给出每平台的调用点清单、逐字段清空策略、`force=True` 白名单准入规则、时间预算影响与验收口径。

本 effort 的产物是**规格**，不是实现。规格交付后再另起实施。

> **已交付 2026-11-12**：[`spec.md`](./spec.md)（891 行、10 章、15 张平台表覆盖 371 个交互点）。实施从规格 §7 的 **W0 共享层**开始。

## Notes

### 已确认约束（charter）

由本次 grilling 定下，规格不得越过：

1. **只搬交互层。** 范围限定为 `utils/humanize.py`：真实按键输入、逐字符对数正态节奏、贝塞尔指针、`stillOn` 复核、`mouse.down/hold/up`、`before_submit`/`after_type`/`between_scroll` 停顿；外加两条禁令——无 `el.click()`、坐标点击不接受 `force=True`。
2. **不搬提交语义。** ARM/FIRE/OBSERVE、exit 9/10、`publish_attempted`、`blocked.py`、零网络预检、启动日志、失败截图全部不在范围。
3. **不搬身份层。** UA / Client Hints、`stealth.min.js`、持久 profile、真实 Chrome channel、代理、每账号 fingerprint seed 一律不动。XHS 规格 §8.1 的禁令继续有效。
4. **平台范围 = 15 个浏览器上传器**：抖音、TikTok、快手、视频号、微博、YouTube、Instagram、Facebook、Facebook Page、知乎、雪球、百家号、大鱼、支付宝、虎扑。B 站走 `biliup` CLI，天然不在范围。
5. **接入形态**：每个 uploader 持一个 `Humanizer(page)` 实例，调用点直接用现有原语（`click` / `press` / `type_text`）。**不新增 `type_into` 封装**——清空策略逐字段手写，照 XHS 的做法。
6. **默认开启**，`HUMANIZE=0` 全局退回原生 `fill` / `click` / `keyboard.type`。回滚单位就是这个环境变量。
7. **交互覆盖面**：文本输入（`fill` / `keyboard.type` / `press_sequentially`）与可见点击。文件输入（`set_input_files`）、`select_option`、`evaluate` 保持原生。
8. **`force=True` 默认改严格**，仅白名单保留少数，且每条必须写明理由。准入规则由 ticket 03 决定。
9. **验收**：TikTok、Instagram、小红书做真机验收；其余 12 个平台只做离线测试，规格里标「未验证」。

### 代码事实（已核对）

- `Humanizer` 已存在且零平台知识：`utils/humanize.py:160-361`；`DEFAULT_PROFILE` 是唯一定义（`keystroke` 均值 ≈ 0.12 s/字符，`type_horizon_chars=1000`）。
- `Humanizer.click` 依赖 `utils/dom.py` 的 `check(..., "interactive")` 与 `ensure_in_viewport`——所以移植会连带引入这两个函数，但不引入 dom 的其余能力。
- 待改造的调用点规模：`fill()` 34、`keyboard.type()` 12、`press_sequentially` 1、`click()` 303、`el => el.click()` 9、`force=True` 19、`select_option()` 3、`set_input_files()` 31、`hover()` 1。
- `PublishTimeoutBudget`（15 分钟）已是跨平台共享件（`uploader/publish_timeout.py`），人类化只是消耗预算，不改变其语义。
- `sau_commands/` 无交互调用；`myUtils/login.py` 有 3 处遗留点击，不在范围。
- 仓库无 `.codegraph/`、无 `docs/adr/`。

### 术语

`GLOSSARY.md` 目前**没有**「Humanize 交互层」词条。规格期用 `/domain-modeling` 补一条，定义「行为层 / 交互真实度 / 清空策略 / stillOn」这四个词，避免各平台自造说法。

### 证据标注

研究结论逐条标：`[code]` 工作树可读 / `[doc]` 库或官方文档明示 / `[inferred]` 由代码推导 / `[needs-live]` 需真机。

## Decisions so far

<!-- 一条已关闭工单一行，格式：- [标题](链接) — 一句话结论 -->

- [01 — 15 个平台的交互调用点清单与分类](./issues/01-interaction-inventory.md) — 386 个唯一行、371 个真实交互；处置 改 Humanizer 246 / 保持原生 54 / 待定 45。两个全局事实：`check(...,"interactive")` 要求 locator `count()==1`（裸 `get_by_role` 必须先收窄）；hit-test 在元素所在 frame 内计算，跨 iframe 的 `stillOn` 成立。
- [02 — Humanizer 的可移植性边界](./issues/02-portability.md) — iframe **能**（坐标与 hit-test 同为视口 CSS px）；内层 shadow DOM **不能**（`elementFromPoint` 重定向到 host，`contains` 判否）；新 tab 必须重建实例；托管模式 `connect_over_cdp` 强制 `noDefaultViewport`，`page.viewport_size` 为 `None`，`ensure_in_viewport` 静默退回 1280×720，**15 个平台同时受影响**。
- [03 — `force=True` 白名单准入规则](./issues/03-force-whitelist.md) — 判据：**走不通人类化才用 force**，判断顺序「先改点 → 再判是否原生路径 → 最后才是真不可能」。三条硬事实推翻了大半白名单理由：force 只跳过遮挡**检查**、仍在坐标上派发真实鼠标事件（被浮层盖住时点到浮层）；`interactive` 的命中判定接受后代（`hit === el || el.contains(hit)`），所以「被组件装饰层盖住」改点容器即解；零尺寸禁止 force（会点到别的元素）。18 条判完**真残余 0 条**，剩 4 条全是「不走」的原生路径（2FA ×2、引导层、hidden file input）。因此不建白名单表——产出是判据顺序 + **AST 标记门**（每个残留 `force` 必须同行带 `# humanize-impossible: <失败模式>；<依据等级>；已排除替代`）。失败语义照 XHS：`Humanizer.click` 不传 `what`；`ElementMissing`=选择器问题、`ElementUnusable`=页面问题。过渡一次到位，回滚靠 `HUMANIZE=0`，force 不得当回滚网。
- [04 — 长文本阈值与时间预算](./issues/04-timing-and-horizon.md) — 阈值保持 1000 全局唯一、不分档（沿用既有「唯一定义」静态门）；>1000 接受单次 `insert_text`，逐字段登记 + 每平台 bulk 断言 + 三平台真机读回。预算 15 分钟不变：人类化停顿只吃剩余预算（`min(sample, remaining)`，耗尽收缩到 0 不抛，clamp 时 WARNING 一次/流程），超时判据仍只在锚点 / 发布点击。固定 sleep **0 删 1 增**（对齐 XHS `f429242`），338 处裸 wait 接预算归 Out of scope。基线只在 TikTok / IG / XHS 记 `HUMANIZE=1` 与 `=0` 实测，其余 12 个标「未验证」。两条限制进规格：码点口径（emoji 提前越线）；per-call 累积成本（IG alt text 最坏可吃光预算 → 点击前 exit 1）。
- [05 — 波次、回滚与文档同步](./issues/05-waves-and-rollback.md) — 五波：W1 三真机（IG / TikTok / 小红书作参照+回归）→ W2 其余国外（YouTube / FB / FB Page）→ W3 国内冲突（抖音 / 微博）→ W4 国内主体（知乎 / 大鱼 / 视频号 / 快手）→ W5 长尾（支付宝 / 百家号 / 虎扑 / 雪球）。回滚只有全局 `HUMANIZE=0` + revert 平台提交，不做运行时自动降级、`force` 不当回滚网。平台完成 = 事件序列 + 字段值读回 + 平台静态门三条全过。真机记录落 `.scratch/humanize-rollout/acceptance.md`，只验本地模式（无托管账号，托管行为归未验证）。文档改四处：`docs/CLI.md` / `GLOSSARY.md` / `CHANGELOG.md` / umbrella skill，均随 W1；README 与 17 个平台 SKILL.md 不改。
- [06 — 汇总实施规格](./issues/06-assemble-spec.md) — 交付 [`spec.md`](./spec.md)（10 章、15 张平台表覆盖 371 个交互点）。九项必含内容全部落位；新增 **W0 共享层**（08 三处修复先于 W1）。补齐 03/07 边界留下的 5 处空档：9 处 `el.click()` 逐条去向（仅微博三处照 07，其余全删，抖音 `:686` 走 hover 显形、仍 hidden 即硬失败）、TikTok 话题改逐字+候选全等、`ElementHandle`/`page.click(selector)` 先换 Locator、门 B/D 定为行内标记门（`# native-click` / `# native-fill`，与 `force` 标记门同构）、54 个 `N/*` 行即原生点击登记册。未验证清单 27 项。
- [07 — 已知会坏的站点：例外规则与改造顺序](./issues/07-known-conflicts.md) — 四处冲突全判「改」，**零豁免**：微博发布按钮用 `point=(0.65,0.5)`（备用 `0.35`）比例落点、`:941` 直接 Humanizer、不留 `el.click()`；YouTube 对齐 XHS「逐字 + 在 `tp-yt-iron-dropdown` 按文本全等点选 `#` 候选」、失败降级纯文本；搜索/过滤输入（百家号合集、抖音地点）逐字 + 有界等待 + 候选全等，`.first` 仅降级；删除抖音 `_native_click`（含合成事件重放），8 处改 Humanizer、状态校验循环保留，验证码 `:846/:854` 仍归原生。三条全局口径：多义硬错、收窄责任在调用点（Humanizer 不自动 `.first`）；豁免零新增（沿用 03 标记门 + 06 实施表）；05 五波不动，热点在波内置顶（W2 YouTube、W3 抖音/微博、W5 百家号）。五项 `[needs-live]` 进 06 未验证清单。
- [08 — 共享层三处前置缺陷：hover 漂移、托管视口、容器裁剪](./issues/08-shared-layer-defects.md) — 三处全「修」，全落在已携带的 `check` / `ensure_in_viewport` / `Humanizer.click` 内部，**charter 原文不改**（规格加一句「携带＝携带正确工作」）。① hover 漂移：**接受**，`click` 一行不改、零重试、容差 1px 不动；真机出现 `point-drift` 就在调用点先 `Humanizer.hover()`（XHS `.cover-edit-entry` 模式），01 清单加「是否需前置 `hover()`」列（默认否）。② 托管视口：**尺寸彻底退出判定**——`ensure_in_viewport` 改在元素自身 frame 内求「落点是否几何可见」谓词，删 `DEFAULT_VIEWPORT_*` 与 1280×720 静默兜底，求值异常保守滚；托管 Profile 拥有尺寸但不可观测，而 `elementFromPoint` 只认真实布局视口。③ 容器裁剪：**修**，同一谓词两级应用（同 frame 视口 + 逐层 `overflow` 祖先 rect；子 frame 投影回主 frame 再问一次），`false` 才 `scroll_into_view_if_needed`；覆盖抖音侧滑面板 / antd·FB 日历 / 知乎下拉 / TikTok 上传 iframe，`hover` 共用。切分原则：**可见性是几何问题（可修、滚），可点性是命中问题（不修、不猜）**——`covered-by:*` 仍硬失败、不重试。不新增 reason、不缓存可见性。托管路径只离线验证，标「托管未真机验证」。

## Not yet specified

以下是能看出存在、但现在还表述不成一个问题的雾。01–08 已全部落地（06 交付 [`spec.md`](./spec.md)），**本图已无 open ticket**；下列仅剩真机观察项（不是决策，靠 §9 验收清单关闭）：

- ~~每个平台具体字段该用哪种清空策略~~ → **已并入 06**：01 已交付每个文本输入点的「默认值」列，06 要求 #3 已强制「逐条给出改法 / 清空策略 / 保留原生」。唯一要留意的特例是**大鱼 `#author` 预填（清空会抹掉作者）**，01 风险 Top 5 已记。
- **YouTube Studio 的 `ytcp-*` 控件是否在 shadow root 内。** 02 判定内层 shadow DOM 无法坐标点击，而 YouTube 是唯一可能大面积踩中的平台。需要一次真机 `evaluate` 才能定，本机无浏览器。
- 真机验收时人类化是否引入**新的卡死模式**（例如 `stillOn` 在动画按钮上反复失败、hover 浮层盖住目标后报 `covered-by:*`、几何可见性谓词在真实页面上是否与真机一致）。只能等实施后跑真机才知道。

## Out of scope

- 身份层：UA / Client Hints、`stealth.min.js`、持久 `user_data_dir`、真实 Chrome `channel`、代理、每账号 fingerprint seed。
- 提交语义与失败契约：ARM/FIRE/OBSERVE、退出码 `9` / `10`、`publish_attempted`、`utils/blocked.py`、零网络预检、启动日志、失败截图。
- `utils/dom.py` 的其余能力：唯一锚点解析、浮层注册表、Esc 清理、禁止删除节点。本次只带 `Humanizer.click` 必需的 `check` 与 `ensure_in_viewport`。
- 文件选择器（`expect_file_chooser`）、下拉选择（`select_option`）、日期键入回读、话题点击重试回读。
- 限流 / 冷却 / 每日上限 / 熔断。
- 各平台 338 处裸 wait（105 `asyncio.sleep` + 233 `wait_for_timeout`）接预算——即 XHS `53c723f` 那类「单一时间源」重构；不属于交互层。本次只要求人类化停顿自身受预算 clamp（04）。
- B 站 `biliup` CLI、`myUtils/login.py` 遗留登录、Flask 后端、Vue 前端。
- 托管模式（Multilogin X / AdsPower）下的人类化行为验证：本轮无托管账号，只验本地模式（05）。08 已定处置：视口缺陷**修**（谓词化、无常量），但托管路径只做离线验证，仍不进真机验收。
- 新增 `type_into` 之类封装（已决议：各平台手写）。
- 把人类化效果与封禁率挂钩的任何断言。
