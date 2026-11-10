# 07 — 第一波 9 项的参数契约与默认值

Status: resolved
Type: grilling
Blocked by: 06

## Question

为第一波 9 项设计 CLI 参数契约，保持现有 `upload-video` / `upload-note` 向后兼容：

- 每项用独立 flag 还是分组：`--location`、`--collaborators`、`--user-tags`、`--alt-text`、`--ai-generated/--no-ai-generated`、`--comments/--no-comments`、`--cover-frame-ms`、`--audio`、`--story`、`--schedule`。
- 默认值：未传时是否动页面默认（对齐现有“未传就不动”原则）。
- 互斥/依赖：Stories 与视频/图片的关系；定时与 `--not-before` 的关系；配乐与视频类型。
- 超长/超限/格式不符的报错语义。
- 入口不存在或账号资格不满足时的结果状态（`unsupported` / `skipped` / 失败）。
- 哪些参数只对 `upload-video`、哪些只对 `upload-note`、哪些两者都适用。

## Answer

用户确认（2026-11-10）。第一波只覆盖已实测有入口的能力；`--user-tags`（tag people）、Stories、定时、配乐、选帧封面不纳入。

### 参数

| Flag | 适用命令 | 取值 | 未传时 | 行为 |
|---|---|---|---|---|
| `--location TEXT` | `upload-video` / `upload-note` | 地点名 | 不动页面默认 | 联想列表精确匹配（大小写不敏感）；无精确匹配 → 失败并列出候选 |
| `--collaborators a,b` | `upload-video` / `upload-note` | ≤3 个用户名 | 不动页面默认 | 逗号分隔，去空白与 `@`；>3 → argparse 报错 |
| `--alt-text TEXT`（可重复） | **`upload-note` only** | 每张图的 alt | 不动页面默认 | 数量必须为 0 或 N（N=图片数）；每个 ≤1000 字符 |
| `--no-comments` | `upload-video` / `upload-note` | 开关 | 不动页面默认 | 单向；请求 off + 入口缺失 = 满足 |
| `--ai-generated` / `--no-ai-generated` | `upload-video` / `upload-note` | 互斥 | 不动页面默认 | on + 入口缺失 = 失败；off + 入口缺失 = 满足 |
| `--thumbnail PATH` | **`upload-video` only** | 封面图 | 默认封面 | 现有行为不变 |
| `--not-before TIME` | `upload-video` / `upload-note` | 时间 | 立即发布 | 现有行为不变 |

### 统一语义

- **未传**：完全不动页面默认，不产生回读要求。
- **显式 on/值**：设置后回读；读回不一致 → exit 1。
- **显式 off + 入口缺失**：入口缺失本来就等于 off，视为满足 → exit 0。
- **显式 on/值 + 入口缺失**：无法达到请求状态 → exit 1。
- 退出码沿用 0 / 1 / 2 / 9 / 10 / 11。

### 结果文件

新增 `options` 对象，逐项记录 `requested / applied / status`：

```json
"options": {
  "location": {"requested": "Shanghai", "applied": "Shanghai", "status": "set"},
  "collaborators": {"requested": ["alice", "bob"], "applied": ["alice", "bob"], "status": "set"},
  "alt_text": {"requested": ["a", "b"], "applied": ["a", "b"], "status": "set"},
  "comments": {"requested": false, "applied": false, "status": "default_off"},
  "ai_generated": {"requested": true, "applied": true, "status": "set"}
}
```

`status` 取值：`not_requested` / `set` / `default_off` / `unsupported` / `mismatch`。

### 校验

- 配文仍 ≤2200 字符（现有）。
- `--alt-text` 数量为 0 或等于图片数；每个 ≤1000 字符。
- `--collaborators` 最多 3 个；去空白与 `@`；空项忽略。
- `--location` 非空；精确匹配失败时错误信息包含候选列表。
- `--ai-generated` 与 `--no-ai-generated` 互斥（argparse group）。
- `--alt-text` 只注册在 `upload-note`；`--thumbnail` 只注册在 `upload-video`。

### 向后兼容

- 不新增必填参数；不传新 flag 时，`upload-video` / `upload-note` 的行为、参数、退出码与现状完全一致。

### 示例

```bash
sau instagram upload-video --account creator --file demo.mp4 --title "标题" \
  --location "Shanghai" --collaborators alice,bob --no-comments --ai-generated

sau instagram upload-note --account creator --images 1.jpg 2.jpg --title "标题" \
  --alt-text "第一张" --alt-text "第二张" --location "Shanghai" --no-comments
```

### 明确不纳入

`--user-tags`、`--story`、`--schedule`、`--audio`、`--cover-frame-ms`。定时仍只用 `--not-before`；等 Creator/Business 账号复核后再补。

### 修订（2026-11-10，由 08 触发）

- **`--collaborators` 从第一波移除**，本轮不实现。原因：真发验收需要第二账号，且“邀请发出”与“对方接受”分离，收益不匹配本轮成本。上表与示例中的 collaborators 作废；协作帖转入地图 Not yet specified。
- **退出码变更**：caption >2200 由 `ValueError → 1` 改为 `UsageError → 2`，与 TikTok / 小红书一致。上表“退出码沿用”与“向后兼容”两处的原意不再成立；这是有意修订，不是回归。
- 其余 4 项（location、alt_text、`--no-comments`、AI 标识）契约不变。
