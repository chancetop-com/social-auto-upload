# 19 — 真实账号冒烟与发布验收

Status: resolved（本地私有账号 lukechen 验收完成；公开账号/到点发布/图片选项条件未满足）
Type: task
Blocked by: 17, 18
规格依据: spec.md §8.3、§11.1

## What to build

在真实公开账号上把新能力完整发布一遍，留下可审计证据；未覆盖场景保持“待验收”，不得写成已验证。此工单依赖本机 Multilogin、已登录的真实账号与可用的 Photos 灰度，领取前先确认环境。

## Acceptance criteria

- [ ] 视频无新参数发布成功，退出 `0`，Content 列表出现新帖。**（私有账号，公开账号专属项条件未满足；已做 only-me 基线发布）**
- [x] `--privacy only-me`、`--no-comments`、`--disable-reuse`、`--aigc`、`--your-brand`、`--branded-content` 各完成一次，结果与页面/帖子一致。
- [x] 视频自定义封面生效。
- [ ] `--schedule` 到点发布且时间正确。**（已创建 22:00 Followers 定时帖并核对时间/隐私；未等待到点）**
- [ ] `upload-note` 多图顺序正确、第 1 张为封面、Title/Description/tags 正确。**（多图/首图封面/Description/tags 通过；Title 已填写但 Web 帖子页不展示，未做编辑页复核）**
- [ ] 图片帖设置项：页面渲染则核对；未渲染记录“页面不支持”。**（评论/AIGC/品牌控件 DOM 存在但不可见，记录为页面不支持）**
- [x] 每条证据记录日期、账号类型、Profile、退出码与帖子 URL/截图。
- [x] 私有账号首项文案、Photos 灰度、`friends` + 品牌组合未实测时，结论保持“条件可行 / 未验证”。**（首项 Followers、Photos tab 可用、branded-content + friends 成功）**
- [x] 不制造“发布结果未知”；退出码 `9` 仅由离线测试锁定。
- [x] 账号能力不匹配时退出 `1`，stderr 含请求值与实际值。

## Comments

- 2026-11-06：领取前环境确认失败——本机未设置 `MLX_API_TOKEN`，`https://launcher.mlx.yt:45001` 不可达，且没有已登录的公开 TikTok 账号/Photos 灰度。因此本工单的真实账号冒烟与发布验收**未执行**；所有验收项保持未勾选，结论保持“待验收”。
- 已交付的离线证明：退出码 `9` 的映射与“禁止自动重发”stderr 由 `tests.test_tiktok_exit_codes` 锁定。真实发布效果、封面、定时、多图顺序、私有账号文案、Photos 灰度与 `friends` + 品牌组合仍必须按 spec §8.3 在真实环境核验；未核验前不得写成已验证。
- 2026-11-06：用户提供本地私有账号 `lukechen` 并同意按 spec 做真实验收。公开账号专属项（无参数公开发布、`--privacy public` 正向、公开账号首项文案）因账号类型不满足，保持“条件未满足/未验证”；私有账号正向用 `followers` / `friends` / `only-me`，页面未渲染的 AIGC/品牌/Photos 项记录为“页面不支持/灰度未覆盖”，不误报为功能失败。本地登录需用户在终端执行 `sau tiktok login --account lukechen`（agent shell 非 TTY）。
- 2026-11-06：本地私有账号真实验收完成，证据见 [acceptance-local.md](../acceptance-local.md)。已验证：登录/check、only-me/followers/friends 隐私、评论关闭、reuse 缺失按目标 False 满足、AIGC（帖子显示 Creator labeled as AI-generated）、Your brand（Promotional content）、branded-content + friends（Paid partnership）、自定义封面、定时创建（22:00 Followers）、图文 3 图/Description/tags/首图封面。
- 条件未满足/未等待：公开账号专属项；定时帖未等到 22:00 到点；图文 Title 不在 Web 帖子页展示（已填写，未做编辑页复核）；图片帖评论/AIGC/品牌控件在 DOM 中但不可见，按“页面不支持”记录。
- 发现并修复：Content `read_result` 原取列表第一条，定时帖排在最前导致图文帖误取定时帖 ID；已改为按标题/正文/标签匹配，并在真实 Content 页验证图文 `7704966090018786574`、视频 `7704956309300382989` 均正确。账号能力不匹配时退出 `1` 已验证：私有账号请求 `public`（actual `Followers`）、only-me 下 Schedule 禁用、图片帖选项不可见。
