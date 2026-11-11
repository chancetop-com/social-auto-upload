# 19 — 本地模式浏览器卫生

Status: open
Type: grilling
Blocked by: —
Assignee: —

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
