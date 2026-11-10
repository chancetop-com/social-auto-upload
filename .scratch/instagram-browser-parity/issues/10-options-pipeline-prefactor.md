# 10 — 共用选项管线与静态校验（纯预置）

Status: resolved
Type: task
Blocked by: 无 — 可立即开始
规格依据: spec.md §3.3、§5、§6.1–§6.3、§7.1

## What to build

为后续四个发布选项建立一条统一管线：CLI 请求可以携带三态选项，uploader 在点 Share 前有一个空钩子，结果文件始终包含四项 `not_requested` 记录。此工单不新增任何用户可见 flag，也不操作任何页面控件。

唯一可观察变化：caption 超长的退出码由 `1` 改为 `2`，以及结果 JSON 多出 `options` 字段。

## Acceptance criteria

- [x] 不传任何新参数时，两个上传命令的页面操作顺序、stdout 与退出码与今天一致；结果 JSON 仅新增 `options`。
- [x] `options` 始终包含 location / alt_text / comments / ai_generated 四项，默认 `requested=null`、`applied=null`、`status=not_requested`，不带 reason。
- [x] caption >2200 在浏览器 / 托管 Profile 启动前抛 `UsageError`，退出 `2`；视频+图片、`--thumbnail` 用于图片同样退出 `2`。
- [x] 既有素材不存在 / 后缀不支持保持原异常与退出码 `1`，不扩大破坏面。
- [x] CLI 请求对象可携带三态选项；本地 cookie 与托管（MLX / AdsPower）两条路径都能透传到 uploader。
- [x] 全为 `None` 时选项钩子零控件交互（连读取都不做）。
- [x] 记录与状态映射的纯函数可单测；A 层覆盖三态不被压缩、5 个 status 与 reason 的合法组合。
- [x] 结果文件在选项钩子前后都保留 `options`；失败证据仍保存页面截图与 HTML。
- [x] 现有 Instagram 离线套件全绿；除 caption 用例改为断言退出 `2` 外，不改既有断言。

## Comments

- 2026-11-10：由 `spec.md` 拆分。
- 2026-11-10：已实现于 `feat/instagram-parity`（`26481c2`…`3a757fd`）。`options.py` 纯逻辑 + `controls/` 注册槽 + `_apply_options` 通用管线；caption 超长改抛 `UsageError`（退出 2）；新增 `OptionMismatchError` 供控件声明“无法表达”，保留失败回读值。A/B 层 26 例全绿，既有 Instagram 套件不回归。
