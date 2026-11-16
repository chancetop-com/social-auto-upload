# 修复提交后审查的标题、登录检查与话题刷新问题

Type: task
Status: resolved
Assignee: Codex
Blocked by: 09

## Question

用户要求修正 `6829b21` 审查确认的三项 P2，完成后再次 code review；沿用此前「其他平台有同类问题一起修」的范围。审查必须覆盖人类化与功能实现。

## Requirements

1. 单行标题不得把 `\n`、`\r`、`\t` 交给 Humanizer；显式输入应在浏览器操作前拒绝。由多行正文自动推导标题时，仅整理标题空白，正文原样保留。其他平台确有同类单行标题路径时同步修复，不限制 TikTok 视频 caption 等多行字段。
2. Rednote / 小红书 `check` 的 page/context/browser 清理普通异常不得覆盖已确定的登录结果、登录/验证信号或主流程错误。其他当前 CLI 登录探测的同类清理一起保护；持久化失败仍是失败，取消仍传播，不关闭托管会话不属于本流程的资源。
3. Rednote / 小红书话题快照在扫描后、点击前被替换时，只有确认节点脱离且尚未派发点击才可在原窗口内重扫。仍使用原 Humanizer、结构选择器、全等匹配、点击次数上限和最终话题回读。窗口耗尽后按原规则保留纯文本；新点击 helper 不得吞掉点击阶段的歧义、遮挡、连接探测失败和可能已派发，也不得再次点击这些目标。原扫描阶段的候选缺失降级保持不变。
4. 通过故障注入和真实本地 Chromium DOM 验证，不连接真实账号或发布。最后用 Standards / Spec 两轴独立审查本次未提交改动，基线为 `6829b21`。

## Investigation

- 标题：Rednote、小红书、抖音、支付宝、百家号、微博、大鱼、知乎、雪球及 TikTok 图片标题存在未经单行校验的输入。YouTube、虎扑、视频号短标题和 Meta Business 标题已有归一化；视频号 title、快手与 TikTok 视频使用正文，不套用单行限制。
- 清理：本地 `check` 的 context/browser 与多平台 `is_logged_in` 临时 page 存在同类 finally 覆盖。复用 `close_browser_resources`，只关闭原流程已有清理动作所拥有的资源。
- 候选：TikTok 已在候选点击失败后退出候选循环并降级，百家号已有合集失败跳过路径，未发现同类整条上传中断，因此不更改这两处行为。新增话题点击 helper 只报告确定未派发的节点脱离，重扫时限仍由平台控制。

## Validation

- 新增专项：`review-fixes-regressions.log`，13 passed、145 subtests passed，含真实 `probe_session` 经 CLI 的 page/context/browser 关闭故障、UA 探测、Meta 初始化失败、单行参数解析、支付宝标签、抖音商品短标题与视频号多行描述。
- Chromium 本地 DOM：`review-fixes-dom.log`，25 passed、34 subtests passed。Rednote / 小红书在人类化开关两种模式下，单次节点替换重扫后只点一次、持续刷新按时降级；移动鼠标期间替换也正确恢复。无远端请求。
- 跨平台组：`review-fixes-platforms.log`，564 passed、1 skipped、454 subtests passed。
- 人类化及上传器组：`review-fixes-humanize.log`，485 passed、91 subtests passed。
- 复审补齐后的扩大回归：`review-fixes-final.log`，649 passed、1 skipped、509 subtests passed；两个子用例因旧 Rednote request 替身未带 title 失败，补齐真实请求已有的字段后，`review-fixes-final-targeted.log` 为 27 passed、170 subtests passed。各组有重叠，不累加为测试总数。
- 生产 Python 变更 Ruff E4/E7/E9/F 相对基线没有新增诊断；新 helper 与专项测试完整 Ruff 通过；`git diff --check` 通过。

## Review

以 `6829b21` 为基线，两名独立 fresh-context 审查者分别负责 Standards / Spec。初审识别的字段语义与清理遗漏均已补齐：视频号 title 实为多行描述，支付宝标签会拼进标题，抖音商品短标题单独校验；CLI 预检前移；Rednote / 小红书的实际探测页与 UA 临时 context，以及 Meta 初始化失败路径都保护主结果。

- Standards 最终：0 项未解决（硬性规范违反 0，启发式问题 0）。
- Spec 最终：0 项未解决；审查者独立执行 59 项离线断言全部通过。

## Answer

三项审查问题已修复，同类路径同步处理。标题校验不改变合法多行配文；清理失败保留主结果、取消与持久化错误；候选重扫只处理确定未点击的脱离节点。保留原 Humanizer、选择器、预算与发布前回读。本轮未连接真实账号或发布。
