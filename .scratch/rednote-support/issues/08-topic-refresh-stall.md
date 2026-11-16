# 修正动态候选刷新时的偶发长停顿

Type: task
Status: resolved
Assignee: Codex
Blocked by: 05

## Question

用户使用 `自动化,小红书` 标签时，偶尔长时间停在“新建话题”候选框。定位并修正实际等待原因，保持结构选择器、精确话题匹配和 Humanizer 行为，并以本地回归测试及真实账号 `--no-publish` 验证。

用户随后要求检查其他平台和 Rednote 的其他指令；范围扩展到共用话题路径及可复现的动态候选读取问题。

## Comments

- 2026-11-16：真实账号中性双图干跑复现：第一个标签耗时 33.000 秒，其中候选第二项 `.name` 的 `text_content()` 耗时 30.008 秒。诊断脚本断言标签阶段小于 10 秒失败；未执行发布。
- 本地诊断记录：`.local/rednote-debug/topic-timing-before.log`。下一步固定候选列表刷新时序，确认是否读取了已消失的旧位置。

## Investigation

- 根因：先 `count()` 再按旧数量读取 `nth(index)`，异步搜索刷新后某个位置消失，`text_content()` / `inner_text()` 仍等待默认超时。外层 3–5 秒轮询窗口不能约束内部 30 秒等待。列表重排还会使同一序号指向别的候选。
- 真实 Rednote 日志中，候选列表曾有 10 项，第二项 `.name` 读取等待 30.008 秒；整条标签处理耗时 33.000 秒。此段还没有执行原创或 AI 声明。
- 本地 Chromium 将默认超时缩短为 1.5 秒并固定在集合获取后刷新 DOM，Rednote、小红书、TikTok、百家号均复现超过 1 秒的读取；重排测试均确认旧序号会点向错误候选。Rednote / 小红书话题回读在编辑器节点被替换时也复现。
- 改为候选节点快照并及时释放句柄；点击仍走原有 Humanizer，TikTok 保留先悬停再点击。编辑器话题使用 `evaluate_all` 一次读完。未添加文本选择器、猜测翻译或新的点击兜底。
- 检查全仓 `nth()` / `all()` 使用点：其余标签输入多为直接键入；日期单元格、固定图片槽和其他非搜索列表没有本次输入触发异步候选替换的复现证据，未批量替换。
- Rednote `upload-note` 与 `upload-video` 共用基类话题路径；`login` / `check` 不执行该路径。百家号此问题位于视频上传的合集搜索。

## Answer

已修复 Rednote / 小红书话题候选与编辑器回读、TikTok 话题候选、百家号合集候选。节点快照消除了旧序号的默认等待和重排后指向其他候选的问题，保留原有匹配、降级、回读与人类化行为。

- Rednote 中性双图真实干跑：两条标签分别 2.989 秒、2.984 秒；原创与 AI 声明成功，18:45:35 达到发布前就绪，退出 0。
- Rednote `upload-video` 实际 CLI（12 秒中性视频）：两条标签分别 2.037 秒、2.753 秒；原创与 AI 声明成功，18:52:28 达到发布前就绪，输出 `prepared (not published)`，退出 0。
- 最终扩展回归：457 passed、177 subtests passed，覆盖小红书、Rednote、真实 Chromium 动态候选及会话接口。此前 TikTok / 百家号 / 小红书话题专项测试：157 passed、24 subtests passed；两组有重叠，不累加为总数。
- 修改文件 Ruff E4/E7/E9/F 与 HEAD 对比没有新增问题；9 条既有诊断保留。`git diff --check` 通过。
- 其他平台本轮只执行离线 DOM 与契约回归，没有新增账号上传。全部 Rednote 线上验证保持 `--no-publish`，未点击发布。

诊断与测试日志保存在忽略目录 `.local/rednote-debug/`；复现脚本明确为本地调试用途，没有向生产代码添加调试日志。验收汇总见 [验收记录](../acceptance.md)。
