# 34 — 人类化交互：逐字符打字与坐标点击

**What to build:** 小红书链路里的每一次打字和点击都走一套共享的行为层：ASCII 逐字符真按键、中文逐字符插入、超长正文一次性批量插入；点击走贝塞尔移动 + 落点复核 + 按下保持。同一个 seed 完全可复现，`HUMANIZE=0` 时退化为零时延快路径。

**Blocked by:** 32（点击前的 `interactive` 落点复核、DOM 夹具）.

Status: resolved

- [x] 11 个动作的参数表（均值/σ/上下界）原样落成唯一定义，平台不得复制；平台差异只允许派生副本
- [x] 打字：长度 ≤1000 逐字符——ASCII 走真实按键事件，中文/emoji 走插入文本，每字符后采样按键间隔；长度 >1000 一次性插入，零按键、零采样，并打一条 info 说明批量插入与字数
- [x] 每次输入结束都走一次"输入后停顿"
- [x] **禁止**剪贴板粘贴、**禁止** `fill()`；清理键保留并走采样；全选快捷键在 macOS 下有效
- [x] 点击顺序固定：包围盒 → 内缩随机落点 → 贝塞尔移动（步数随距离收紧）→ 指针稳定停顿 → 落点复核（元素仍是目标、位置 ±1px、`interactive` 档）→ 按下 → 保持 → 抬起
- [x] 内部零重试（重试只发生在 ARM）；包围盒不可得或复核不符 → 抛"确定未派发"；按下之后任何异常 → 标记"可能已派发"
- [x] 小红书接线：导航后一次、每次点击、每次文本输入完、FIRE 前一次、真实滚动处；`Reading`/`AfterInteract`/`BeforeClick`/`AfterClick` 不接
- [x] 小红书目录内 `fill(` / `el.click()` / `force=True` 静态计数为 0（YouTube 的豁免不在本票）
- [x] 测试：字符分派、1000/1001 边界（1001 恰一次插入、零按键）、点击序列、复核失败时无"按下"、同 seed 可复现、`HUMANIZE=0` 零停顿
- [x] 记录时间上界：20 字标题 ≈2.7s、1000 字正文 ≈2.3min、10 标签 ≈10.9s，总计 ≈2.6min，仍在 15 分钟预算内
- [ ] 真机 dry-run：`--no-publish` 走通；`HUMANIZE=0` 对照同输入走通

## Comments

- 共享层：`utils/humanize.py` 新增 `LogNormal` / `HumanizeProfile`（11 动作 + `type_horizon_chars=1000` + `enabled=True`）/ `DEFAULT_PROFILE` / `Humanizer`。参数表是唯一定义（`tests/test_humanize.py::ParameterTableTests` 用 spec 表格的独立字面量逐项对照，并断言 20000 次采样均值 = 0.136s）。零平台 import（AST 断言）。
- 打字：`type_text(text)` 内部分流。≤1000 逐字符——可打印 ASCII 走 `keyboard.press`，中文/emoji 走 `keyboard.insert_text`，换行/制表符映射到 `Enter`/`Tab`（`press("\n")` 在 Playwright 是非法键）；每字符后采样 `Keystroke`。>1000 恰一次 `insert_text`、零 `press`、零采样、一条 `info`（`type_text→bulk insert_text, chars=NNN`）。两条路径都以一次 `after_type` 结束（选中即"每次输入完停顿"）。另加 `press(key)` 供清理键（`Backspace`/`ControlOrMeta+A`/`Delete`/`Enter`）复用同一 `Keystroke` 采样。
- 点击：`bounding_box` → 以比例锚点为中心、`min(size*0.15, 8px)` 内缩抖动 → 三次贝塞尔（`steps=clamp(round(dist/10), 10, 40)`，控制点沿法向随机偏移 `dist*(0.05+0.10*r)`，每步 5–9ms，`easeInOut`）→ `PointerSettle` → stillOn 复核（包围盒四边 ±1px + `utils.dom.check(..., "interactive", point=...)` 的落点命中）→ `mouse.down` → `ClickHold` → `mouse.up`。零内部重试；`down` 之前失败抛 `ElementUnusableError`（`no-bounding-box` / `zero-box` / `point-drift` / `covered-by:…`，`publish_clicked=False`）；`down` 起任何异常打 `click_dispatched = "maybe"` 标记后原样上抛。
- 小红书接线：`uploader/xiaohongshu_uploader/main.py`。`XiaoHongShuBaseUploader._humanizer(page)` 每页一个实例（指针位置与随机流连续），`sleep` 注入 `_humanize_pause`——只吃预算上限（`min(delay, remaining)`）、从不自己抛超时，符合 ticket 15 §7「行为层不读取 deadline」。`goto` 后 `after_navigate`（发布页两条链路 + `cookie_auth` + 扫码登录页）；`fill_title`/`fill_desc`/`fill_tags`/定时时间/地点/自主拍摄地点与日期/转载来源全部 `type_text`（标题、定时时间、日期过滤框用 `focus()` 聚焦，避免点开日历）；约 22 处点击全部 `Humanizer.click`；`scroll_into_view_if_needed` 后接 `between_scroll`；发布点击前 `before_submit`。`_js_click_by_text` 及其 JS `el.click()` 分支删除，转载声明确认改走候选层 `XHS_DECLARATION_CONFIRM_CANDIDATES`。`XHS_PUBLISH_CLICK_TIMEOUT_MS` 随之成为死常量并删除（FIRE 的预算归 ticket 36）。
- 清理键语义保留：`Backspace` → `ControlOrMeta+A`（macOS 下 `Control+KeyA` 无效，已替换）→ `Delete` → 键入 → `Enter`，全部经 `Humanizer.press` 采样。
- 静态门：`tests/test_humanize.py::XhsStaticGateTests` 断言包内 `fill(` / `el.click()` / `force=True` / `_js_click_by_text` 计数为 0，且除 `humanizer.click(` 外没有任何 `.click(`；`Control+KeyA` 不再出现。另断言 `type_horizon_chars` 只出现在 `utils/humanize.py`。
- 时间上界（spec §3 U5 F，均值 136ms/字）：标题 20 字 ≈2.7s；正文 1000 字 ≈2.3min；10 个标签 ≈10.9s（每个标签另有一次 `after_type` ≈0.65s，故实际 ≈17.4s）；10 次点击 ≈4.1s；`after_navigate`+3×`after_type`+`before_submit` ≈4.4s。合计 ≈2.7min，仍在 15 分钟预算内。上限写在 `utils/humanize.py` 模块 docstring。
- 测试：`tests/test_humanize.py` 31 条（参数表/`LogNormal` 截断与均值、字符分派、换行映射、1000/1001 边界、bulk 日志、`press` 采样、点击事件序列与 5–9ms 步长、落点内缩与比例锚点、stillOn 失败无 `down`、包围盒漂移拒绝、无包围盒、`down` 后异常标记、同 seed 复现/不同 seed 分叉、`HUMANIZE=0` 与 `profile.enabled=False` 零停顿、快路径 `press` 仍派发、共享层边界、静态门、XHS 接线集成：一次 `mouse.down/up`、零 `locator.click`、stillOn 在按下之前、`before_submit` 在移动之前、标题逐字插入）。既有用例按机制迁移：`tests/test_xhs_budget.py` 三条链路类改用官方快路径 `HUMANIZE=0`（只验证 clamp/退出码）；`test_xiaohongshu_uploader.py`/`test_xhs_selectors.py` 的键盘与标题断言改为 `insert_text` + 聚焦；`tests/fakes_xhs_dom.py` 的 `FakeLocator` 增加 `focus()`。
- 全量：`python -m unittest discover -s tests -t .` → 1258 tests OK（skipped=2）。
- 真机项：`未验证（无真机环境）` —— ① `--no-publish` 正路需确认贝塞尔 + stillOn 在真实发布页的通过率；② `HUMANIZE=0` 对照同输入需同结果；③ 定时时间/拍摄日期逐字键入是否被平台格式化纠正；④ 开关/复选框这类小控件的抖动误点率。
