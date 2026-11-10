# 17 — 本地模式固定英文界面（locale 参数）

Status: resolved
Type: task
Blocked by: 无 — 由账号验收前的讨论触发
规格依据: spec.md §4.4（语言与漂移）、§6.4（兼容性检查）

## What to build

与 TikTok / 小红书一致：本地模式下把浏览器 context 固定为 English (US)，让四个发布选项的英文选择器不再受操作系统浏览器语言影响。此前 `INSTAGRAM_CONTEXT_KWARGS` 是空表，本地 `new_context` 也完全没有应用它（只有托管分支把它传给 `browser_session`，而在托管分支会被忽略）。

## Acceptance criteria

- [x] `INSTAGRAM_CONTEXT_KWARGS` 为 `{"locale": "en-US", "extra_http_headers": {"Accept-Language": "en-US,en;q=0.9"}}`。
- [x] `_open_instagram_page` 与 `instagram_setup` 的本地 context 应用该参数，登录窗口同样固定英文。
- [x] 托管模式（MLX / AdsPower）不应用；Profile 界面必须人工保持 English。
- [x] 选项入口缺失/不一致时日志打印页面 `html[lang]`，用于区分“选择器漂移”与“账号语言不是英文”。
- [x] `tests.test_mlx_meta` 的本地 golden 断言更新；Instagram 全套测试保持全绿。
- [ ] 真实账号确认账号自身语言设为中文时的渲染行为 → 并入 [16](./16-real-account-acceptance.md) 的验收步骤，不在本工单单独验收。

## Comments

- 2026-11-10：本地固定 `en-US` + `Accept-Language`；托管模式的行为不变（Profile 即身份，语言由 Profile 决定）。`docs/CLI.md`、`CHANGELOG.md`、`skills/instagram-upload/SKILL.md` 同步说明。
