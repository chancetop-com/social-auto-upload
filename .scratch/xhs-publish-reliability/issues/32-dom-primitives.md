# 32 — 判定原语：四档角色、hit-test 与覆盖层清障

**What to build:** 一套共享的元素判定原语，回答的不是"页面上有没有这个选择器"，而是"它是不是真的存在、能不能看见、能不能点中、能不能输入"。被浮层挡住时先按已知覆盖层清障，而不是 `force=True` 硬点或摘掉节点。同时提供"页面已经安静下来"的一次性闸门。

**Blocked by:** 28（虚拟时钟与 DOM 夹具）.

**Status:** ready-for-agent

- [ ] 四档角色各有明确判据与 reason：`attached`（在 DOM 且 connected，集合基数必须为 1，多义返回 `ambiguous:N` 且禁止 `.first`）、`visible`（自身可见 + 祖先链 display/visibility/opacity 计算样式 + 自身 `aria-hidden`）、`interactive`（在 visible 之上加非 disabled、`pointer-events != none`、真实落点 `elementFromPoint` 命中自身或后代）、`editable`（在 visible 之上加可写）
- [ ] 落点默认取包围盒中心；发布按钮取 65% x 处
- [ ] 不确定性分档：`visible`/`attached` 探测抛异常 → 放行 + warning；`interactive` 落点探测抛异常 → 阻断（reason `probe-failed`）
- [ ] 覆盖层清障最多 2 轮，每步后重新落点：已知覆盖层注册表（数据驱动）→ `Esc` → 再探测；仍未通过则报 `covered-by:<标识>`
- [ ] **永不**摘节点、**永不**注入 `display:none`、**永不**点空白；正文字段输入中不清障（已知引导按钮例外）
- [ ] 页面就绪：统一 `domcontentloaded` + clamp；首次交互前执行一次 DOM 静默门（连续 500ms 无变更通过，总上限 3s）；未静默只 warning 不失败，且只做一次
- [ ] 之后每个动作只等自己的目标，不再有就绪类固定 sleep
- [ ] 共享层依赖方向成立：只依赖 patchright、stdlib 与通用错误类型，不 import 平台或命令层
- [ ] 契约单测：四档边界、`ambiguous:N`、`probe-failed` 阻断 vs 可见性探测失败放行、两轮上限、静默门 500ms/3s、所有等待实参可收紧
