# 05 — CLI 参数契约与默认值

Status: resolved
Type: grilling
Blocked by: 01, 02, 03, 04

## Question

新增能力如何暴露为 CLI 参数，缺省行为是什么？需要确定：

1. 新增 flag 的命名与取值：隐私级别、评论/合拍/拼接、AI 标识、品牌内容、封面帧/封面图；是否复用其他平台已有命名。
2. 哪些参数互斥，哪些可以组合；冲突时是报错还是取优先级。
3. 缺省值策略：未传参数时是保持 TikTok 页面当前默认，还是显式设置成固定值？如何保证不改变现有 `upload-video` 行为。
4. `upload-note` 的字段：`--title`、`--note` / `--notef` / `--desc`、`--tags`、`--images`、配乐、封面、`--schedule`。
5. 校验：图片数量/格式/大小、标题长度、tags 规范化、时间格式。
6. 哪些 API 概念明确不做（`PULL_FROM_URL`、`MEDIA_UPLOAD`、`post_mode`）。

## Answer

### 命令面

`upload-video` 保持现有 positional 参数与行为不变，新增 keyword-only flag：

| 参数 | 取值 | 语义 |
| --- | --- | --- |
| `--privacy` | `public` / `friends` / `followers` / `only-me` | 省略 = 不动页面默认；显式传则设置并回读 |
| `--no-comments` | 开关 | 取消 `Allow comments`；省略 = 不动 |
| `--disable-reuse` | 开关 | 取消 `Allow reuse of content`（覆盖 Duet/Stitch/Stickers/Story）；省略 = 不动 |
| `--aigc` / `--no-aigc` | 三态 | 省略 = 不动；显式开启/关闭 `AI-generated content` |
| `--your-brand` | 开关 | 勾选 `Your brand`；省略 = 不动 |
| `--branded-content` | 开关 | 勾选 `Branded content`；省略 = 不动 |
| `--thumbnail` | 现有 | 自定义视频封面，保持原语义 |

`upload-note` 新增：

| 参数 | 必填 | 语义 |
| --- | --- | --- |
| `--images` | 是 | 1..35 张本地图片，按传入顺序展示，第 1 张即封面 |
| `--title` | 否 | 页面 Title，≤90 字符 |
| `--note` | 否 | 页面 Description，≤4000 字符 |
| `--notef` | 否 | 从 txt/md 读 Description；与 `--note` 互斥 |
| `--tags` | 否 | 逗号分隔，追加到 Description，计入 50 个 hashtag / 4000 字符 |
| `--schedule` | 否 | 与视频相同的定时格式 |
| `--privacy` / `--no-comments` / `--aigc` / `--no-aigc` / `--your-brand` / `--branded-content` | 否 | 与视频相同语义，但图片帖不适用 Duet/Stitch，因此没有 `--disable-reuse` |

`upload-note` 不提供：`--bgm`（网页无自动配乐，手动选曲不纳入 v1）、`--thumbnail`（第 1 张即封面）、`--cover-index`（网页只能第一张）、`--disable-reuse`（图片帖无此设置）。

### 隐私枚举映射

| CLI 值 | API 枚举 | 页面文案 | 账号限制 |
| --- | --- | --- | --- |
| `public` | `PUBLIC_TO_EVERYONE` | `Everyone` / `Public` | 仅公开账号 |
| `friends` | `MUTUAL_FOLLOW_FRIENDS` | `Friends` | 公开/私有账号 |
| `followers` | `FOLLOWER_OF_CREATOR` | `Followers` | 仅私有账号 |
| `only-me` | `SELF_ONLY` | `Only you` | 公开/私有账号 |

账号类型不匹配时按严格策略失败，不自动改名或回退。

### 默认值与组合规则

1. 未传任何新参数 → 不操作对应控件，保持 TikTok 页面原生默认；旧 `upload-video` 行为不变。
2. 显式传参 → 设置后回读；回读不一致视为失败，不发布。
3. `--aigc` 与 `--no-aigc` 互斥；`--note` 与 `--notef` 互斥。
4. `--your-brand` 与 `--branded-content` 可同时为真；只要有一项为真，就自动打开 `Disclose post content`，并显式设置两个复选框（未请求的一项设为未勾选）。
5. `--branded-content` + `--privacy only-me` → 本地直接报错；`public` / `friends` 允许，但发布前以页面实际可用性为准（`friends` 标为待实测）。
6. `--disable-reuse` 是单开关，文档必须注明同时影响 Stickers/Story；API 的 `disable_duet` / `disable_stitch` 不再分别暴露。
7. 不提供 `--cover-ms`；API 的 `video_cover_timestamp_ms` 标记为“浏览器只能近似，本次不实现”。
8. 不提供 `--ai-remix`；这是 API 之外的页面开关，v1 不暴露。

### 本地校验

- 图片：1..35 张；仅 JPG/JPEG/PNG/WebP；单张 ≤50 MB；启动浏览器前校验。
- Photo Title ≤90；Description ≤4000；hashtag 总数 ≤50；超长直接报错，不截断。
- `--privacy` 只接受四个枚举值。
- `--schedule` 沿用现有格式与校验。
- 视频 caption 不新增长度校验，保持旧行为。

### 明确不做的 API 概念

`PULL_FROM_URL`、图床/域名验证、分片上传、`MEDIA_UPLOAD` 收件箱、`post_mode`、`auto_add_music`、`photo_cover_index`、`video_cover_timestamp_ms`。这些要么是传输机制，要么网页端无法等价表达。

## Comments
