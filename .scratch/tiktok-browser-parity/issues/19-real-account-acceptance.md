# 19 — 真实账号冒烟与发布验收

Status: resolved（私有/公开本地账号验收完成；定时到点发布已由用户确认，17:35 公开定时帖仅作补充证据）
Type: task
Blocked by: 17, 18
规格依据: spec.md §8.3、§11.1

## What to build

在真实公开账号上把新能力完整发布一遍，留下可审计证据；未覆盖场景保持“待验收”，不得写成已验证。此工单依赖本机 Multilogin、已登录的真实账号与可用的 Photos 灰度，领取前先确认环境。

## Acceptance criteria

- [x] 视频无新参数发布成功，退出 `0`，Content 列表出现新帖。**（公开账号 `7704974050090683661`，Content 行 Everyone）**
- [x] `--privacy only-me`、`--no-comments`、`--disable-reuse`、`--aigc`、`--your-brand`、`--branded-content` 各完成一次，结果与页面/帖子一致。**（公开账号 v2 `7704978171703069966`、only-me v3 `7704985011614764302` 均实际定位并取消 Reuse of content 后回读成功；旧“控件缺失=已满足”结论已撤销）**
- [x] 视频自定义封面生效。
- [x] `--schedule` 到点发布且时间正确。**（2026-11-06 用户确认到点自动发布正常；另创建公开账号 17:35 定时帖 `TB19 scheduled public 1735` 作补充证据，创建时 Content 行 `5:35 PM (GMT+8) Shanghai` + Everyone）**
- [x] `upload-note` 多图顺序正确、第 1 张为封面、Title/Description/tags 正确。**（多图/首图封面/Description/tags 通过；Title 已填写，2026-11-06 用户确认公开展示正常）**
- [x] 图片帖设置项：页面渲染则核对；未渲染记录“页面不支持”。**（公开账号复验：全局 Show more 后评论/AIGC/品牌可见；`--privacy public --no-comments --aigc --your-brand` 发布成功，帖子页显示 Promotional content + AI 标签）**
- [x] 每条证据记录日期、账号类型、Profile、退出码与帖子 URL/截图。
- [x] 私有账号首项文案、Photos 灰度、`friends` + 品牌组合未实测时，结论保持“条件可行 / 未验证”。**（首项 Followers、Photos tab 可用、branded-content + friends 成功）**
- [x] 不制造“发布结果未知”；退出码 `9` 仅由离线测试锁定。
- [x] 账号能力不匹配时退出 `1`，stderr 含请求值与实际值。

## Comments

- 2026-11-06：领取前环境确认失败——本机未设置 `MLX_API_TOKEN`，`https://launcher.mlx.yt:45001` 不可达，且没有已登录的公开 TikTok 账号/Photos 灰度。因此本工单的真实账号冒烟与发布验收**未执行**；所有验收项保持未勾选，结论保持“待验收”。
- 已交付的离线证明：退出码 `9` 的映射与“禁止自动重发”stderr 由 `tests.test_tiktok_exit_codes` 锁定。真实发布效果、封面、定时、多图顺序、私有账号文案、Photos 灰度与 `friends` + 品牌组合仍必须按 spec §8.3 在真实环境核验；未核验前不得写成已验证。
- 2026-11-06：用户提供本地私有账号 `lukechen` 并同意按 spec 做真实验收。公开账号专属项（无参数公开发布、`--privacy public` 正向、公开账号首项文案）因账号类型不满足，保持“条件未满足/未验证”；私有账号正向用 `followers` / `friends` / `only-me`，页面未渲染的 AIGC/品牌/Photos 项记录为“页面不支持/灰度未覆盖”，不误报为功能失败。本地登录需用户在终端执行 `sau tiktok login --account lukechen`（agent shell 非 TTY）。
- 2026-11-06：本地私有账号真实验收完成，证据见 [acceptance-local.md](../acceptance-local.md)。已验证：登录/check、only-me/followers/friends 隐私、评论关闭、reuse（当时误记为“控件缺失按目标 False 满足”，后证实是折叠+文案误判）、AIGC（帖子显示 Creator labeled as AI-generated）、Your brand（Promotional content）、branded-content + friends（Paid partnership）、自定义封面、定时创建（22:00 Followers）、图文 3 图/Description/tags/首图封面。
- 后续已补齐：公开账号专属项与图片帖评论/AIGC/品牌控件均已复验通过（见下方 2026-11-06 条目）；图文 Title 由用户确认真实公开展示正常；仅剩“定时到点自动发布”未取得有效证据。
- 发现并修复：Content `read_result` 原取列表第一条，定时帖排在最前导致图文帖误取定时帖 ID；已改为按标题/正文/标签匹配，并在真实 Content 页验证图文 `7704966090018786574`、视频 `7704956309300382989` 均正确。账号能力不匹配时退出 `1` 已验证：私有账号请求 `public`（actual `Followers`）、only-me 下 Schedule 禁用、图片帖选项不可见。
- 2026-11-06：用户将 `lukechen` 切换为**公开账号**，复验公开账号专属项，并复查图片帖评论/AIGC/品牌控件（用户界面可见，需重新定位 Settings 展开方式/可见性判断）。
- 2026-11-06：公开账号复验完成。无新参数发布 `7704974050090683661`、`--privacy public` `7704974226096246029` 均为 Content **Everyone**；`--privacy followers` 严格失败（requested followers / actual Everyone）。图片帖选项确认支持：图片页没有 `advanced_settings_container`，点击全局 **Show more** 后评论/AIGC/品牌控件可见；`--privacy public --no-comments --aigc --your-brand` 图片帖 `7704976028485176590` 发布成功，帖子页显示 **Promotional content** + **Creator labeled as AI-generated**，Content 行 Everyone。此前“图片页选项页面不支持”的结论已撤销。
- 2026-11-06：公开账号 `--disable-reuse` 补测发现当前文案是 **“Reuse of content”**，旧候选漏配导致 v1 未实际取消；已补候选并缩短点击超时，v2 `7704978171703069966` 日志 `reuse resolved by candidate #0 (Reuse of content)` 并成功发布。
- 2026-11-06：图文 Title 公开展示由用户确认正常，验收项勾选；不再列为未确认。
- 2026-11-06：公开账号新建 17:35 定时帖 `TB19 scheduled public 1735`（`--privacy public --schedule "2026-11-06 17:35"`），退出 `0`；Content 行显示 `Nov 6, 5:35 PM (GMT+8) Shanghai` + **Everyone**，确认已进入定时状态。用户随后确认到点自动发布正常；17:37 探针仅作补充证据。
- 2026-11-06：reuse 语义纠正。only-me 实测控件存在（Show more 后可见，默认 `checked=true`、`enabled`），旧“私有账号不渲染/禁用”结论来自折叠 + 旧文案误判。代码新增 `_reuse_control_absent`：只有 `user_perm_container` 完全没有 Reuse 文案时才把缺失视为已满足；文案存在但控件解析失败 → 退出 `1`，避免选择器漂移静默通过。only-me `--disable-reuse` v3 `7704985011614764302` 实际取消并回读成功。
