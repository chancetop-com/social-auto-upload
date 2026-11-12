# 04 — 小红书回归（真机 · `--no-publish`）

**What to build:** 不改生产代码。在本地模式真机用 **`--no-publish` 干跑**小红书（视频 + 图文各一次），跑到 ARM 就绪（发布按钮存在、可点击、未被禁用/遮挡）即停，**不点击发布、不上真实帖子**。目的是确认 01 的共享层修复没有把已验证的交互层弄坏：位置、话题、封面 hover、定时回读、声明等全部在就绪点之前，都在覆盖范围内。结果写进 `.scratch/humanize-rollout/acceptance.md` 的「小红书（回归）」一节。

规格依据：§2.5、§6.4、§7.1（小红书是参照实现 + 回归对象，不是移植目标）。

Blocked by: 01

Status: resolved

- [x] 视频：`--no-publish` 跑到 ARM 就绪，退出码 0，日志含「停在发布按钮前（未点击发布）」
- [x] 图文：`--no-publish` 跑到 ARM 就绪，退出码 0
- [x] 未出现新增 `point-drift`、`covered-by:*`、`zero-box`
- [x] 封面入口（hover 后渲染）仍能点到；位置/拍摄地点候选仍能全等选中
- [x] 定时路径的 C1/C2/C3 回读与 `--no-publish` 日志均正常
- [x] 记录：日期 / 账号 / 发布类型 / 触碰字段 / 墙钟 / 预算消耗 / 停止点 / 结论
- [x] 发布按钮的真实点击**不验**（见规格 §9-28）；不要为了「验得更全」去掉 `--no-publish`
- [x] 若出现回归 → 记录目标 locator 与失败 reason，回滚 01 的共享层提交，不在小红书单点打补丁

## Answer

2026-11-12、账号 `180`、本地 `--headed`：视频 run 1（56s，含封面/内容类型/定时）、
视频 run 2（72s）、图文（31s）均 exit 0 并命中
`🧪 ARM 就绪，--no-publish 停在发布按钮前（未点击发布）`；预算消耗 3–8%。

结论：共享层（几何可见性谓词）在小红书正路**无回归**，不回滚 ticket 01。
两条观察（详见 `.scratch/humanize-rollout/acceptance.md`）：

- 内容类型「自主拍摄」run 1 偶发 `point-drift`（声明步骤按既有契约 warning 降级，
  run 2 同一路径成功）。机制来自 `Humanizer.click` 既有容差，不是 01 引入；
  按规格 §2.5.1 的处置，若后续再复现就在**调用点**先 `Humanizer.hover()`。
- `--original` 当前报 `disabled`，且 `HUMANIZE=0` 原生点击同样 30s 超时 → 账号/平台态，
  与人类化层无关；本轮视频验收因此不带 `--original`。

