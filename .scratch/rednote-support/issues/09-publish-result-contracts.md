# 保留发布结果并立即拒绝发布按钮歧义

Type: task
Status: resolved
Assignee: Codex
Blocked by: 08

## Question

修正审查确认的两项契约问题：浏览器清理异常覆盖主流程结果，以及发布按钮出现 `ambiguous:N` 后仍继续轮询。检查其他平台的同类发布路径，并用离线故障注入验证成功、结果未知、登录失效和普通错误不会被清理改写，歧义只探测一次且不派发。

## Comments

- 用户明确要求两项都修，并扩展到其他平台的同类问题。此前审查复现脚本再次运行仍得到成功/未知结果均变为退出 1、两个等待入口均在歧义后第二次探测通过。
- 这两项根因已经由审查及当前复现确认；沿用 diagnosing-bugs 的回归与验证步骤，不再重复假设探索。全部验证使用离线假会话/DOM，不需要真实发布。

## Investigation

- 清理异常：Rednote / 小红书两个本地 upload 入口，以及多个平台的本地入口和共享 `_local_session`，直接 await 关闭操作。快手、视频号等还存在成功后 cookie 写回错误覆盖发布结果。Meta Business 结果文件落盘与 Instagram handler 清理也有同类 finally 覆盖。
- `utils/browser_cleanup.py` 分别保护 context/browser，任何一个普通关闭错误都不阻止另一个关闭；异常只记 warning。取消不吞掉。成功后的 cookie 刷新使用独立的 best-effort 写回函数；登录保存仍须成功。
- Rednote / 小红书 ARM 在滚动/几何探测前先确认数量；两个等待入口保留失败原因并立即上抛 `ambiguous:N`，缺席或禁用仍在原窗口内等待。
- 其他复现路径：TikTok 视频/图文完成闸、发布就绪和确认按钮；Instagram 分享就绪；视频号/支付宝上传完成与发布；微博/百家号最终提交；抖音/快手捕获歧义后重试；YouTube 最终发布按钮。只对这些实际代码路径修正唯一性或异常传播，未添加新选择器或翻译。
- Meta Business 最终提交已有 `_unique`，大鱼与虎扑的唯一性检查已立即报歧义；知乎/雪球提交错误不会重新点击。Facebook 表单内末位按钮是已取证的业务顺序，未将其当作可随意删除的兜底。Bilibili 不使用浏览器上传；旧 TikTok `main.py` 不在 CLI 当前调用链内。
- 回归注入覆盖 22 个本地入口、共享会话、普通错误、成功、结果未知与登录信号；真实 CLI 断言关闭失败时保持 `0/9/10`。重复按钮测试保证无点击，歧义后即使下一轮会就绪也不再轮询。另检查取消仍传播、context 取消后仍尝试 browser 关闭。
- 测试使用假会话与本地 HTML 浏览器，不涉及账号发布。扩展回归同步补齐既有测试替身的可见性 API，以及 YouTube 新增的唯一性参数。

- 补充快手两阶段派发边界：首次发布按钮点击成功即记录可能已派发；确认按钮此后发生歧义时立即退出为结果未知，不误报未发布。抖音、快手在 Humanizer 前检查数量，`HUMANIZE=0` 同样先拒绝重复目标。
- Chromium 本地双按钮页面：Rednote ARM / 视频完成闸分别 0.037 / 0.006 秒报歧义，小红书分别 0.012 / 0.007 秒；Instagram Share 同样报 `ambiguous:2`，DOM 点击计数为 0。日志 `.local/rednote-review/duplicate-dom.log`。

## Answer

两项均已修复并扩展到当前 CLI 的同类路径。清理只记录警告且分别尝试关闭，主结果与原异常不变；发布按钮歧义在首次发现时停止。可能已派发后的确认歧义保留结果未知，避免重复发布。现有结构选择器与 Humanizer 保留。

最终验证：

- 新增专项：**17 passed、245 subtests passed**，日志 `contracts-regressions-final.log`。
- 跨平台边界组：**149 passed、30 subtests passed**，包括 Instagram、快手本地 HTML 与抖音/快手派发语义，日志 `contracts-boundary-final.log`。
- Instagram / YouTube 浏览器与清理组：**53 passed、14 subtests passed**，日志 `contracts-browser-refined.log`。
- 全仓分组完成：全量运行先完成 **1335 passed、2 skipped、955 subtests passed**；当时 3 个 Instagram 用例因旧替身不接受 `timeout` 失败，后续已补齐并在上述 149 项组复跑通过。TikTok 图文旧替身缺 `is_visible` 导致空等，停止该次运行并补齐后，该文件 **56 passed、32 subtests passed**；从此文件开始的剩余 24 个文件全部完成，**621 passed、184 subtests passed**。这些组存在重叠，不相加当作测试总数。
- Chromium 真实本地 DOM 的两个发布按钮均立即拒绝，点击计数 0。没有连接真实账号或点击真实发布。
- 32 个修改 Python 文件 Ruff E4/E7/E9/F 对比 HEAD：17 条既有诊断、无新增诊断；新增 helper 与两个专项测试完整 Ruff 通过。`git diff --check` 通过。

测试与复现日志均在忽略目录 `.local/rednote-review/`。纯英文后台和托管 Profile 的真实验收仍由 ticket 06 独立跟进，不影响本次离线契约修复。
