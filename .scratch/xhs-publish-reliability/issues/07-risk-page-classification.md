# 07 — 风控页与登录失效的分级

Status: open
Type: grilling
Blocked by: 03
Assignee: —

## Question

决定“被踢出登录 / 被要求验证”时抛什么、退出码是什么、两种模式是否一致。需要确认：

1. **判定依据**：按 path（`/website-login/captcha` vs `/website-login`）还是 path + DOM？是否采用等价于 CDP `Page.getFrameTree` 的主框架读取（不注入 JS）？是否会误把 `?redirectPath=/website-login/captcha` 的登录页判成验证页（上游用 `EscapedPath` 规避）。
2. **错误类型与退出码**：新增 `VerificationRequiredError`？复用 `LoginRequiredError` + exit 10？还是同一错误带 `reason` 字段？调度侧的可操作性差异是什么（人工扫码 vs 人工重登）。
3. **模式一致**：本地模式现在完全不判风控页，是否同步。
4. **检查点位置**：goto 后、填写中、点发布前、点发布后——分别做什么。现只有 goto 后与 `except` 分支。
5. **与 03 的交叉**：已点发布后被踢登录，是“结果未知（9）”还是“登录失效（10）”？必须给出唯一答案。

产出：状态机（检测点 × 命中 × 抛什么 × 退出码 × 是否可重试）+ 与 03 判定表的合并方式。

## Evidence from 02（真机取证）

- 无会话访问 `/publish/publish…` 与 `/`，落地均为 **`https://creator.xiaohongshu.com/login…`**（带 `redirectReason=401&lastUrl=…`），且 `div[class*='login-box']` = 1。
- **未观察到** `/website-login` 或 `/website-login/captcha`；本次未触发验证码，验证页 path 仍属「需真机验证」。
- 上游 `EscapedPath` 处理的是网页端 `/website-login` 场景，与 creator 后台 `/login` 不同源。
