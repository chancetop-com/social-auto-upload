# 15 — `upload-note` 图文帖核心路径

Status: ready-for-agent
Type: task
Blocked by: 10
规格依据: spec.md §4.2、§4.5、§5.3、§6.2

## What to build

新增 `sau tiktok upload-note`，把 1–35 张本地图片按传入顺序发成一条图文帖，第 1 张即封面。命令只在账号有 Photos tab 时继续；没有入口就在选文件前失败，绝不把图片送进视频 input。

此工单只交付“能发一条纯图帖子”的核心路径，不含文案字段与发布选项。

## Acceptance criteria

- [ ] `upload-note` 注册为合法子命令；`--images` 必填且支持多值。
- [ ] 图片少于 1 张、超过 35 张、格式不是 JPG/JPEG/PNG/WEBP（大小写不敏感）或单张超过 50 MB 时，在启动浏览器前退出 `2`。
- [ ] 进入上传页后先探测 Photos tab；缺失时在选文件前退出 `1`，错误信息说明账号未覆盖。
- [ ] 图片按 `--images` 传入顺序进入图片 input，第 1 张作为封面。
- [ ] 图文帖复用同一套登录检测、15 分钟预算与发布循环；本地模式直接报错。
- [ ] 发布成功时 stdout 输出一行含图片数量的提交结果；退出 `0`。
- [ ] 发布结果未知/需要登录/运行失败分别走与视频相同的 `9`/`10`/`1` 语义。
- [ ] `upload-note` 不注册 `--disable-reuse`、`--thumbnail`、`--cover-index`、`--bgm`。
