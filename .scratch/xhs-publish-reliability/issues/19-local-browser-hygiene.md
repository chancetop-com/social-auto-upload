# 19 — 本地模式浏览器卫生

Status: resolved
Type: grilling
Blocked by: —
Assignee: wayfinder-session (opencode)

## Question

本地模式（无 Profile）目前是「每次一个**全新指纹**的无头 Chromium + UA 半修 + 注入 `stealth.min.js`」，是双模式里封禁风险最弱的一环。决定是否按 patchright 官方最佳实践改造。

事实基线（`main.py:93-101`、`utils/base_social_media.py:21-24`、`utils/browser_session.py:173-177`）：

- `playwright.chromium.launch(channel="chromium")` + `new_context(storage_state=...)` —— **每次全新 profile，无历史/无缓存**。
- `_xhs_user_agent()` 把 `HeadlessChrome` 换成 `Chrome`，再用 `new_context(user_agent=...)` —— `UserAgentMetadata`（brands / fullVersionList）不同步，属于"半修"。
- `stealth.min.js` 在 patchright 之上再注入一次 JS 补丁。
- 默认 `headless=True`。

需要确认：

1. 是否改用 `launch_persistent_context(user_data_dir=每个账号一个)`？与现有 `cookies/<platform>_<account>.json`（`storage_state`）如何共存：迁移、双写、还是 `user_data_dir` 取代。
2. `channel`：保留 bundled `chromium` 还是改 `chrome`（真 Chrome）？CI/无 Chrome 环境如何降级（且降级必须可观测，不能静默）。
3. 是否**删除** `_xhs_user_agent()`（patchright 明确要求不要自定义 UA/headers；上游也刻意不设 UA）。
4. 是否**删除** `stealth.min.js` 注入（patchright 已做驱动层补丁；上游注释同样反对 JS 注入）。删除后用什么验证没有变差。
5. 本地默认是否有头（与 14 的 CLI 默认值交叉引用：14 管开关与文案，本票管浏览器配置）。
6. 波及面：这套配置在 `browser_session` 里是共享的，改 `user_data_dir` 会同时影响 16 个平台的本地模式。要不要先只给小红书开（按平台 opt-in）？
7. **验收方式**：如何证明"改完更安全"而不是拍脑袋——指纹自查页（browserleaks / creepjs）前后对比 + 一次真实登录/发布的存活观察。要写清证据形式。

产出：目标配置清单（config diff 粒度）+ 迁移与兼容策略 + 波及面与灰度方案 + 验收证据形式。

## Comments

- 来自 **12**（2026-11-11）：12 已删掉本地发布前的 `cookie_auth` 与托管发布前的 `is_logged_in`，给本地 `check` 加了「读 `storage_state` 的 `galaxy_creator_session_id` 存在性与 `expires`」的零网络快路，并定义「仅成功后原子写回」。**若本票改为 `launch_persistent_context(user_data_dir=…)` 取代 `storage_state`**，则 12 的写回时机、过期快路、以及“一次发布一次浏览器”的计数都要重定 —— 届时请在本票一并裁决并回写 12 的 Answer。另：12 判定 `_xhs_user_agent()` 的多余 context 归本票（问题 3）处理，12 只负责“发布链路里不再额外启动浏览器”。

## Answer

**决议（2026-11-11，用户）：本轮不改本地模式的浏览器配置。** 维持现状——`launch` + `new_context(storage_state=…)`、`channel="chromium"`、`_xhs_user_agent()` 的 UA 半修、`stealth.min.js` 注入、自定义 viewport / headless 参数全部不动。逐项：

1. `launch_persistent_context(user_data_dir=…)`：**不采用**。
2. `channel="chrome"`：**不改**，继续用 bundled `chromium`。
3. 删除 `_xhs_user_agent()`：**不删**。
4. 删除 `stealth.min.js`：**不删**。
5. 本地默认是否有头：本票**不再追加约束**；沿用 14 的决议（默认有头）。14 改的是 CLI 参数默认值，不是本票的浏览器配置改造，16 汇总时不要把两者混为一谈。
6. 波及面 / 按平台 opt-in：**本轮无改动，不适用**。
7. 验收取证：**不做**（没有改动可验收）。

**代码事实（修正本票基线，2026-11-11 核实）**：

- 本地发布**并不经过** `utils/browser_session.py`：`uploader/xiaohongshu_uploader/main.py` 的 `upload()` 自建 `playwright.chromium.launch(...)` + `new_context(...)`，`browser_session` 的本地分支只覆盖部分非上传路径。
- 全仓 `playwright.chromium.launch(...)` 共 **52 处**；任何「改共享层就覆盖 16 个平台」的设想都不成立，必须逐点收敛。
- 本版 `launch_persistent_context` 签名**不接受 `storage_state`**；将来若重开，迁移必须先显式 `add_cookies()` 导入 `cookies/*.json`。
- 12 的 `storage_state` 读写时机与 `galaxy_creator_session_id` 零网络快路**不受影响**（本轮无改动）。

**已知代价（明确接受）**：本地模式仍是「每次全新 profile、无历史无缓存 + 半修 UA + JS 注入」，双模式里最弱的一环本轮不消解；本票**不提供**任何「现状足够安全」的断言。

**未来重开的门槛**（仅作为重开条件记录，不是本票的遗留待办）：若出现「本地模式被拒/封显著高于托管」的真机证据，或托管不可用成为常态，另开 effort 重做，届时再回答 persistent / `channel=chrome` / `no_viewport` / 删 UA / 删 stealth 五个问题，并补齐 browserleaks × creepjs 前后对比与一次真实登录发布观察。
