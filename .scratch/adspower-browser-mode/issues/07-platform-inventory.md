# 07 — 逐平台迁移清单与能力对齐

Status: resolved
Type: task
Blocked by: 03
Assignee: OpenCode

## Question

清点仓库中所有与 `multilogin` 相关的接缝，产出一份逐平台迁移清单，证明 AdsPower 模式能复用现有上传逻辑且不遗漏。需要：

1. 列出所有 `sau_commands/*.py` 中对 `sau_commands.multilogin` 的 import 与调用点（`add_multilogin_flags`、`resolve_multilogin_target`、`resolve_account_label`、`reject_multilogin_login`、`login_required_error` 等）。
2. 列出所有 uploader 上传方法接收 `multilogin=` 的位置，以及它们如何使用 session。
3. 列出所有 `tests/test_mlx_*.py` / `tests/test_multilogin_*.py` 覆盖的平台与契约，标出改名/改签名后会受影响的断言。
4. 产出平台 × action 矩阵：每个平台在本地 / MLX / AdsPower 下支持哪些 action；Bilibili 标为不支持；`verify` / `delete` 标为仅本地。
5. 标出平台特有约束：TikTok 语言与 Photos tab 灰度、身份绑定平台（知乎/雪球/大鱼号/Instagram）、Meta 代理、YouTube `YT_PROXY`、图文/视频差异、`--schedule` 支持。
6. 判断哪些平台需要代码改动，哪些只需测试/文档改动；给出理由。
7. 把清单写到 `.scratch/adspower-browser-mode/research/07-platform-inventory.md`，所有结论附 `文件:行`。

## Context

- 该 ticket 是事实清点，不是设计决策；结论供 ticket 03（接缝）、05（测试）、08（规格）引用。
- 现有 MLX 平台迁移参考：`.scratch/multilogin-browser-mode/spec.md` 的逐平台表。
- 不需要真实运行平台；只读代码与测试。

## Answer

清单已写入 [`research/07-platform-inventory.md`](../research/07-platform-inventory.md)。核心结论：

- 17 个平台模块 import `sau_commands.multilogin`；实测调用点：`add_multilogin_flags` 41、`resolve_multilogin_target` 16、`resolve_account_label` 17、`require_local_account` 33、`require_account` 7、`reject_multilogin_login` 17、`reject_multilogin_platform` 1、`login_required_error` 14。map 中的 32/35 与实测不符，以清单为准。
- 16 个浏览器平台共 36 个 `browser_session(...)` 调用点；28 处 `session.mode == "multilogin"`（18 个 uploader 文件，含 insgraph 的 2 处单引号）；26 个内部 `multilogin: bool` 参数。
- 平台 × action × 模式矩阵已补齐：16 个托管平台 + `article`（本地工具）+ `bilibili`（本地子进程）；`login` 全部拒绝，`verify`/`delete` 仅本地。
- 发现两个跨 ticket 风险：
  1. **bilibili 缺口**：只设 `ADSPOWER_API_KEY` 时 `reject_multilogin_*` 不生效，会静默回退本地 login/biliup；必须迁到 `reject_managed_*`。
  2. **测试冲突**：ticket 05 要求 8 个 `test_mlx_*.py` 零改动，但 `test_mlx_smoke.py:377` 与 `test_mlx_hupu_dayu.py:405` 直接调用 `browser_session(multilogin=...)`，签名改名后必须各改 1 行；建议 08 合并时显式豁免。
- 平台特有约束（TikTok 语言/Photos 灰度、Meta/YouTube 代理、身份绑定、时区、剪贴板、schedule、图文/视频差异）均由 `session.managed` 继承 MLX 分支，不需要 AdsPower 专属实现。
