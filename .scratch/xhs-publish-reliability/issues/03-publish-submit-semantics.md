# 03 — 发布提交语义：预算底座 + 单次点击

Status: open
Type: grilling
Blocked by: 01
Assignee: —

## Question

决定发布提交的语义，使“点一次发布最多只发一次”成立。需要确认：

1. **预算底座**：是否先把小红书迁到 `uploader/publish_timeout.py` 的 `PublishTimeoutBudget`（预算、`--not-before` 顺延、`clamp_ms`/`clamp_seconds`、`pre_click_error`、`timeout_error`、exit 1/9）？现为自建 `_new_publish_deadline` + 手写顺延，且**没有 clamp**，固定超时会超支预算。
2. **点击策略**：单次点击。观察窗多长（现 3s，上游 15s）？
3. **成功信号**：`publish/success` 字样，还是“URL 离开 `/publish/publish`”（上游）？两者关系是取代还是并集？
4. **唯一允许重试的条件**：页面未变 + 按钮仍可点 + 未命中拒绝词？最多几次？
5. **exit 9 边界**：观察窗耗尽 → `PublishResultUnknownError`；预算耗尽（点击后）→ 同上；预算耗尽（点击前）→ exit 1。是否保留这一三分。
6. `--no-publish` 干跑是否复用同一预算（且不进入提交循环）。

产出：判定表（事件 × 观测信号 × 结论 × 退出码 × 是否可重试），可直接进 spec。

## Evidence from 02（真机取证）

- `xhs-publish-btn[submit-disabled]` 在**标题为空**时为 `false` → 该属性只表达「上传/处理可提交」，不能当「表单已填完」的判据；点击前自检需另行定义。
- 元素 `innerText` 为空，任何基于「发布」文字的等待/点击在现网都不会命中。
