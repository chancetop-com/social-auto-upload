# 11 — 设置后回读与元数据校验

Status: open
Type: grilling
Blocked by: 05
Assignee: —

## Question

决定控件“设置后回读”的覆盖范围与内容校验口径。需要确认：

1. **回读覆盖**：GLOSSARY 定义 `设置后回读`，但小红书只对原创开关做了状态回读（`_switch_is_on`）。定时开关（现直接 click，不判断原状态）、内容类型声明、封面是否补齐？
2. **标题长度**：采用 UTF-16 口径（上游 `CalcTitleLength`：非 ASCII 记 2、ASCII 记 1、`(bytes+1)/2`）还是 Python 码点？超限是**报错**还是截断（现在是静默 `title[:20]`）？CLI 侧是否前置校验。
3. **正文长度**：读 `div.edit-container div.length-error` 的时机（填完立即？发布前？）与失败文案。
4. **定时时间**：下界现 2h、上界无；时区口径（本机 `datetime.now()` vs Profile 时区）如何定义与提示。
5. **失败语义**：回读不一致时是抛错、重试一次、还是降级继续（原创/声明/封面三项现有降级策略是否保留）。

产出：控件 × 设置 × 回读 × 不一致时的动作 三态表 + 长度口径定义。
