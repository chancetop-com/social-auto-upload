# 09 — 汇总设计规格

Status: resolved
Type: task
Blocked by: 01, 02, 03, 04, 05, 06, 07, 10, 11, 12, 13
Assignee: —

## Question

把已关闭 ticket 的结论汇总成一份可直接实施的设计规格，写到 `docs/superpowers/specs/` 或 `.scratch/multilogin-browser-mode/spec.md`（按仓库既有习惯选择），至少包含：

1. **目标与非目标**：一句话目的；明确本地模式不变、CLI-only、B 站排除。
2. **术语**：Multilogin 模式、Local 模式、Profile、Folder、Launcher、Owned session、Login required。
3. **CLI 契约**：
   - `MLX_API_TOKEN` 的激活语义；
   - `--folder-id` / `--profile-id` / `--account` 在两种模式下的要求；
   - `--headless` 映射；
   - 退出码表（0 / 1 / 2 / 10）与各失败类别；
   - 示例命令（上传、check、login）。
4. **时序**：start → connect → 登录检测 → 原上传 → 断开 → stop；异常路径同样 stop。
5. **Provider 设计**：`utils/browser_session.py` / `utils/multilogin.py` 的职责、签名、允许/禁止的 Playwright 调用、日志与脱敏。
6. **平台迁移清单**：每个平台改哪个文件、哪个函数、传入什么；YouTube / Meta / 知乎的特殊处理；TikTok 仅 MLX 模式（契约见 ticket 13）；B 站报错。
7. **测试计划**：单元 / 契约 / 可选真机；要锁住的不变量。
8. **运维与排障**：桌面应用/launcher 前置条件、证书、token、429、profile 已在运行、stop 失败、headless 限制。
9. **风险与未决**：真实 MLX 未验证、平台风控、登录检测可靠性、未来远程 launcher。
10. **实施顺序**：建议先 1 个平台打通（抖音），再批量迁移；每步的验证命令与完成标准。

规格中的每个决策都要能回溯到对应 ticket；不要引入未在 ticket 中确认的新约束。

## Answer

规格已写入 [`../spec.md`](../spec.md)（`.scratch/multilogin-browser-mode/spec.md`，遵循 `docs/agents/issue-tracker.md` 的 `<effort>/spec.md` 约定）。

包含内容与 ticket 的对应关系：

| spec 小节 | 来源 |
|---|---|
| 0–3 目标/术语/模式激活 | charter、ticket 01 |
| 4 CLI 契约（参数矩阵、退出码、示例） | ticket 05、06、13 |
| 5 运行时架构（模块、Target/Client、BrowserSession、时序、失败路径、日志） | ticket 01、02、05、06、10 |
| 6 上传器 seam 与平台迁移表、禁止 API | ticket 02、04、06 |
| 7 登录检测与身份 | ticket 03、12 |
| 8 平台特殊行为 | ticket 04 |
| 9 TikTok | ticket 13 |
| 10 部署拓扑与前提 | ticket 10 |
| 11 调度侧责任 | ticket 05、12 |
| 12 依赖与升级 | ticket 11（用户批准 1.64.4） |
| 13 测试策略 | ticket 07 |
| 14–16 实施顺序、验收清单、风险 | 全部 |

补充说明：

- 本次汇总时修正了一个 ticket 06 未覆盖的细节：虎扑的自定义 UA + 内联 stealth 脚本需要 `browser_session` 的 `context_setup` 本地 hook（已回填到 ticket 06 的“补充”小节）。
- ticket 08（真实 MLX 冒烟）仍是外部依赖阻塞；spec 内所有 Launcher 行为已标注 `[官方]` / `[社区]` 置信度，ticket 08 完成后回填，不改本规格的结构。
- 本地模式的验证范围按用户最新指示：patchright 升级只跑测试用例回归，不做真实账号的完整验证回归。
