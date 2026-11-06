# 19 — 真实账号冒烟与发布验收

Status: ready-for-agent
Type: task
Blocked by: 17, 18
规格依据: spec.md §8.3、§11.1

## What to build

在真实公开账号上把新能力完整发布一遍，留下可审计证据；未覆盖场景保持“待验收”，不得写成已验证。此工单依赖本机 Multilogin、已登录的真实账号与可用的 Photos 灰度，领取前先确认环境。

## Acceptance criteria

- [ ] 视频无新参数发布成功，退出 `0`，Content 列表出现新帖。
- [ ] `--privacy only-me`、`--no-comments`、`--disable-reuse`、`--aigc`、`--your-brand`、`--branded-content` 各完成一次，结果与页面/帖子一致。
- [ ] 视频自定义封面生效；`--schedule` 到点发布且时间正确。
- [ ] `upload-note` 多图顺序正确、第 1 张为封面、Title/Description/tags 正确。
- [ ] 图片帖设置项：页面渲染则核对；未渲染记录“页面不支持”。
- [ ] 每条证据记录日期、账号类型、Profile、退出码与帖子 URL/截图。
- [ ] 私有账号首项文案、Photos 灰度、`friends` + 品牌组合未实测时，结论保持“条件可行 / 未验证”。
- [ ] 不制造“发布结果未知”；退出码 `9` 仅由离线测试锁定。
- [ ] 账号能力不匹配时退出 `1`，stderr 含请求值与实际值。
