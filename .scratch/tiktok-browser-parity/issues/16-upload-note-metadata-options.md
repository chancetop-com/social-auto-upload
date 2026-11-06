# 16 — 图文帖文案与发布选项

Status: ready-for-agent
Type: task
Blocked by: 12, 13, 15
规格依据: spec.md §4.2、§4.5、§5.3、§6.1

## What to build

图文帖可以填 Title、Description 和 tags，并使用与视频相同的隐私、评论、AIGC、品牌选项。所有显式设置都回读一致才发布；超长或超限在启动浏览器前报错，不截断。

## Acceptance criteria

- [ ] `--title` 可选，≤90 字符；超长时在启动浏览器前退出 `2`，不截断。
- [ ] `--note` 与 `--notef` 互斥；`--notef` 读取 txt/md 作为 Description，文件不可读时退出 `2`。
- [ ] Description（含 tags 展开后的文本）≤4000 字符、hashtag 总数 ≤50；超限退出 `2`，不截断。
- [ ] 不传 Title/Description 时保持页面空值，不写入空字符串覆盖。
- [ ] tags 规范化后追加到 Description；网页不单独保存 hashtags。
- [ ] 图文帖复用隐私/评论/AIGC/品牌选项与设置后回读；不调用内容复用控件。
- [ ] 图文帖不暴露 `--disable-reuse` 或 `--thumbnail`；图片第 1 张即封面。
- [ ] 账号未渲染 AIGC/品牌控件但显式请求时退出 `1`，不静默忽略。
- [ ] 发布成功时 stdout 与视频风格一致，并含图片数量。
