# 40 — 元数据、越限与定时回读

**What to build:** 不可逆动作之前，表单状态尽量可证：标题超长不再静默截断而是开浏览器前就拒绝；正文越限在点击前拦下；定时开关与时间在两个时点回读，不一致就不点发布，避免"日期被页面回滚却按错误时间发出去"。

**Blocked by:** 33（控件锚点）、34（逐字输入）、39（正文与话题全部输入完之后才检查长度）.

Status: resolved

**标题**

- [x] 长度口径按平台加权：每个 UTF-16 码元 >127 记 2，否则记 1，加总后除 2 向上取整，上限 20
- [x] 显式传入超限 → 校验期抛错，浏览器未启动，消息含"当前 X / 上限 20"并注明口径；**不截断**
- [x] 自动推导标题 → 同口径截到 ≤20 并 warning
- [x] 删除填充时的静默截断
- [x] 输入后等待 ≥350ms（轮询至 500ms）再查长度后缀警示节点的**存在性**；存在 → `1`

**正文**

- [x] 正文 + 话题全部输入完成后单次检查长度错误节点；节点存在即失败（不判可见、不读数值）
- [x] 计数口径：正文逐字符，上限 1000；话题锚点计入且按 `#name` 计（`#旅行pov[话题]#` → 7）
- [x] 已知：越限时发布按钮仍可用，点击前检查是唯一闸门

**定时（即时发布完全不进入检查）**

- [x] C1 点开关后：开关状态为已选中（状态类含选中且不含未选中）+ 时间输入框 `attached`
- [x] C2 写入后：失焦 → 约 300ms → 单次读输入值；解析后**按分钟**等于请求值；开关同 C1
- [x] C3 FIRE 前：开关 + 值同 C1/C2，且请求值仍晚于本机当前时间；时点在 ARM 就绪之后、`--not-before` 之后、FIRE 之前
- [x] 解析比较，不要求字符串全等；读失败/空值/不可解析 = 不一致；**不重试**
- [x] 失焦只允许 `blur()`；**禁止** Tab / Enter / 点空白区
- [x] 边界：请求时间须晚于现在 2 小时、不晚于现在 14 天；越界在参数校验期 → `1`（浏览器未启动）；墙上时间语义，带时区偏移的输入忽略偏移、按其自带墙上时间格式化
- [x] `--no-publish` 同样执行 C1/C2/C3

**其余控件**

- [x] 原创 `true`：点前读状态；未开则点击 + 确认弹窗（勾选须知 → 声明原创）；任一步失败 → `1`；点后不读
- [x] 原创 `false`：开着则点一次关；控件缺失视为关；点后不读；失败 warning 继续
- [x] 原创 `None`：不操作
- [x] 内容类型声明与视频封面维持现有流程，失败 warning 继续（封面首帧兜底）

**失败语义**

- [x] 全部发生在点击前 → `1`，`publish_attempted=False`；不产生 `9`，不写回账号文件

**测试**

- [x] 标题加权（ASCII / CJK / emoji / 组合字符边界）、自动标题截断、2h/14d 边界、带偏移输入、长度警示等待窗口、正文长度错误、C1/C2/C3 五种失败（回滚、迟到重置、时效过期、读失败、不可解析）、干跑同拦、即时发布不进检查

## Comments

- 标题口径：`xhs_title_length()` / `xhs_truncate_title()` / `validate_title_length()`（`uploader/xiaohongshu_uploader/main.py`）。按 UTF-16 码元加权（>127 记 2、否则记 1），`ceil(weighted/2)`。显式标题在 `validate_upload_args` 抛 `ValueError`（含「当前 X / 上限 20」并注明 UTF-16 口径），不截断；自动标题在 `XiaoHongShuNote.__init__` 同口径截到 ≤20，校验期补 warning。`fill_title` 删除 `self.title[:20]`，改为原样键入 + 输入后 350ms 起、500ms 止的越限后缀存在性检查（`.edit-container .suffix.max_suffix` / `.d-input-wrapper.c-input_max`，存在 → `ElementUnusableError`，点击前 `1`）。
- 正文口径：`xhs_body_length(desc, tags)`，正文逐字符 + 每个话题锚点 `len("#name") + 1`（`#旅行pov` → 7）。`fill_meta` 在 `fill_desc` + `fill_tags` 全部完成后单次检查 `div.edit-container div.length-error` 的存在性；存在即抛错，不读数值、不判可见。
- 定时回读：`set_schedule_time_xiaohongshu` 内 C1（`.d-switch-simulator` class 含 `checked` 且不含 `unchecked` + `.date-picker-container input` attached）与 C2（`blur()` 唯一失焦方式 → 300ms → 单次 `input_value()` → `%Y-%m-%d %H:%M` 解析后按分钟比较，不重试）。`_verify_schedule_before_fire(page)` 是 C3：在两条链路各自 `_wait_for_arm` 成功之后、`_fire_publish` 之前调用（`--no-publish` 分支同样调用），复查开关、值，并要求请求时间仍 `> datetime.now()`。即时发布（`publish_date == 0`）直接 return，不解析任何定时选择器。
- 定时边界：`xhs_validate_schedule_time()` 在 `validate_base_args` 内执行 `now + 2h < t <= now + 14d`（14 天为新增上界，只作用于小红书），aware 输入 `replace(tzinfo=None)` 后按墙上时间校验与 `strftime`。越界在浏览器启动前 `1`。
- 原创：`true` 改用 `utils.controls.read_switch_state` 点前读取；未开/未知 → 点击 + `_confirm_original_declaration`（勾选须知 → `声明原创`），弹窗缺失或任一步异常直接上抛（`1`），点后不回读。`false` 开着则点一次关；控件缺失/不可用视为已关；点后不回读；失败 warning + Escape 继续。`None` 无操作。内容类型声明与封面流程未改。
- 测试：新增 `tests/test_xhs_metadata.py`（51 项）覆盖标题 ASCII/CJK/emoji/组合字符、自动截断、显式超限文案与不截断、2h/14d 边界、aware offset 忽略、350/500ms 等待窗口、正文 `length-error` 单次检查、C1/C2/C3 的回滚/迟到重置/过期/读失败/不可解析、`--no-publish` 同拦、即时发布不进检查、原创 true/false 失败语义。
- 真机项：定时 C1/C2/C3 的 simulator class 与日期输入框结构、标题越限后缀节点、原创确认弹窗在真机上的渲染时序 → **未验证（无真机环境）**。

## Comments

- **2026-11-12 真机验收**：定时 `--schedule "2026-11-13 12:00" --no-publish` → 0，C1/C2/C3 全过。
- **修正**：日期 filter input 自带默认值（now+~1h），`focus` 后直接键入会追加成两段日期；改为 `ControlOrMeta+A` 全选后逐字替换，仍只 `blur()`、不按 Tab/Enter。
