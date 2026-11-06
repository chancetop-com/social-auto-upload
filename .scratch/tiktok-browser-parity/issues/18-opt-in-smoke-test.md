# 18 — opt-in 表单级冒烟测试

Status: wontfix（已删除：真实账号手工验收替代）
Type: task
Blocked by: 12, 13, 14, 15, 16
规格依据: spec.md §8.2、§8.4

## What to build

一条 opt-in 的表单级冒烟测试，能在真实 Multilogin Profile 上验证控件定位与“设置后回读”，但绝不发布。默认离线套件不应因为缺少浏览器或账号而变慢或失败。

## Acceptance criteria

- [x] （历史实现，已删除）未设置 opt-in 开关时整模块 skip；默认离线套件结果不变。
- [x] 开关打开但缺少 `MLX_API_TOKEN` / `SAU_MLX_FOLDER_ID` / `SAU_MLX_PROFILE_ID` 时 fail，并指出缺哪个变量。
- [x] 视频用例：打开上传页、选 `videos/demo.mp4`、展开高级设置、逐控件设置并回读隐私/评论/复用/AIGC/品牌，并验证封面上传入口。
- [x] 图片用例：先探测 Photos tab；缺失时只 skip 图片用例并输出原因；存在时验证多图、Title/Description/tags 与设置项。
- [x] 两个用例都绝不点击 Post / Schedule。
- [x] 未登录/验证码跳转时 fail，并提示先在 Multilogin 登录。
- [x] 控件缺失或回读不一致时 fail，信息含控件名、已尝试候选、当前 URL 与阶段。
- [x] 明确提示不要与 `SAU_MLX_SMOKE` 并行使用同一 Profile。

## Comments

- 2026-11-06：实现完成并合入 `integration/tiktok-browser-parity`（feature commit `141645f`）。TikTok 专项 188 tests 全绿；默认离线套件 726 tests，基线 5 failures + 1 error + 2 skips 均为既有、非 TikTok 问题。真实账号发布验收见 ticket 19，尚未执行。 本票历史实现已删除；opt-in 开关未设置时整模块 skip，真实环境未执行。
- 2026-11-06：真实账号手工验收已覆盖控件定位/设置/回读，opt-in 冒烟不再提供额外价值；测试模块与 opt-in 开关引用已删除，本工单标记 wontfix。
