# 18 — opt-in 表单级冒烟测试

Status: ready-for-agent
Type: task
Blocked by: 12, 13, 14, 15, 16
规格依据: spec.md §8.2、§8.4

## What to build

一条 opt-in 的表单级冒烟测试，能在真实 Multilogin Profile 上验证控件定位与“设置后回读”，但绝不发布。默认离线套件不应因为缺少浏览器或账号而变慢或失败。

## Acceptance criteria

- [ ] 未设置 `SAU_TIKTOK_SMOKE=1` 时整模块 skip；默认离线套件结果不变。
- [ ] 开关打开但缺少 `MLX_API_TOKEN` / `SAU_MLX_FOLDER_ID` / `SAU_MLX_PROFILE_ID` 时 fail，并指出缺哪个变量。
- [ ] 视频用例：打开上传页、选 `videos/demo.mp4`、展开高级设置、逐控件设置并回读隐私/评论/复用/AIGC/品牌，并验证封面上传入口。
- [ ] 图片用例：先探测 Photos tab；缺失时只 skip 图片用例并输出原因；存在时验证多图、Title/Description/tags 与设置项。
- [ ] 两个用例都绝不点击 Post / Schedule。
- [ ] 未登录/验证码跳转时 fail，并提示先在 Multilogin 登录。
- [ ] 控件缺失或回读不一致时 fail，信息含控件名、已尝试候选、当前 URL 与阶段。
- [ ] 明确提示不要与 `SAU_MLX_SMOKE` 并行使用同一 Profile。
