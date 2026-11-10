# 03 — 现有 instagram.com 浏览器实现能力清单

Status: resolved
Type: research
Blocked by: 无

## Question

盘点现有浏览器实现已经具备的内容发布能力，逐项对应代码位置，作为差距分析的“现状”一侧。至少覆盖：

- 命令与参数：`upload-video` / `upload-note` / `verify` / `delete` 的全部参数、默认值、必填关系。
- 媒体类型与限制：视频/图片格式、数量、封面、轮播顺序。
- 配文与元数据：标题/正文/标签如何合并、长度校验、哪些字段未接入。
- 发布行为：立即发布、`--not-before`、结果文件、退出码、失败/未知语义。
- 账号与登录：本地 cookie、托管 Profile、身份核验差异。
- 测试覆盖：已有测试文件与覆盖点。

产出写入 `research/03-current-browser-inventory.md`，并在本文件 `## Answer` 下给出能力表与代码位置索引。

## Answer

现有实现是纯 DOM 自动化，不调用官方发布 API；仅在点发布后旁听 `POST /api/v1/media/configure` 确认结果（`insgraph_uploader/main.py:466-512`）。完整清单见 `research/03-current-browser-inventory.md`。

能力表（capability | 现状 | 位置）：

| 能力 | 现状 | 代码位置 |
| --- | --- | --- |
| 命令面 | `login`/`check`/`upload-video`/`upload-note`/`verify`/`delete`；无 `--schedule` | `sau_commands/instagram.py:42-90` |
| 视频/Reel | 单文件 MP4/MOV；固定 Reels 路径 | `main.py:524`、`364-369,508` |
| 图片/轮播 | JPG/JPEG/PNG/AVIF/HEIC/HEIF，1..N 按传入顺序；无显式张数上限 | `instagram.py:72`、`main.py:362-363,524` |
| 自定义封面 | 仅视频，JPG/JPEG/PNG，预览 SHA-256 校验 | `main.py:284-285,382-412,515-519` |
| 配文 | 标题+正文+标签以 `\n\n` 合并，≤2200；响应配文须完全相等 | `main.py:294-302,266-267` |
| 未接入元数据 | alt text/location/collaborators/product tags/user tags/AI 标识/评论点赞设置/share to feed/audio/滤镜/裁剪/Stories/feed video | 无代码路径；`docs/CLI.md:616` |
| 立即发布 | 是；`--not-before` 为客户端闸门，等待不计预算 | `main.py:453-461`、`publish_gate.py:44-89` |
| 结果三态 | `published`/`processing`(202)/`submission_unknown`(点击前预写) | `main.py:462-464,500-512` |
| 退出码 | 0/1/2/9(结果未知)/10(需登录)/11(限流)；`deletion_unknown` 仅落盘仍退 1 | `sau_cli.py:84-99`、`posts.py:93-115` |
| 失败证据 | `.local/instagram-errors/<uuid>/page.png+page.html` | `main.py:542-550` |
| 账号 | 本地 `cookies/instagram_<account>.json`；托管 Profile 不读写 cookie、跳过身份比对 | `main.py:182-198,559-588`、`instagram.py:142-163` |
| 测试 | 契约/真 Chrome 回归/托管 seam；无真实账号 e2e | `tests/test_instagram_uploader.py` 等（见研究文件 §7） |

最明显缺口：定时发布、Stories/feed video、全部发布元数据、媒体大小/时长/宽高比校验、容器式错误/幂等语义、发布后自动对账。
