# 06 — 页面就绪与元素可用性判定

Status: open
Type: grilling
Blocked by: 05
Assignee: —

## Question

决定“页面可以开始操作”与“元素确实可用”的判定标准。需要确认：

1. **DOM 就绪等待**：上传前是否加稳定等待（参照上游 `WaitLoad` + `WaitDOMStable(1s, 0.1)` + 2s + 1s），还是用更轻的信号（上传 input 可交互 / 发布按钮出现）。
2. **存在 ≠ 可见**：`is_logged_in` 的正向锚点现只做 `count()`（`main.py:326-328`），隐藏元素也算命中。是否把所有 `count()` 判定改为可见性判定？统一 helper 的契约是什么（`is_visible` + bounding box 非零 + opacity 继承 + `aria-hidden`）。
3. **被遮挡**：是否引入 `elementFromPoint` 等价判定，命中则先清障再点，而不是 `click(force=True)`。
4. **与预算的关系**：就绪等待是否用 `clamp_seconds` 收紧。
5. 每个判定函数的签名与返回（bool / 原因字符串），以及失败文案。

产出：判定 helper 契约 + 全部调用点替换清单 + 与 03 预算的接口。

## Evidence from 02（真机取证）

- 常驻覆盖层：`.feature-guide__btn`「我知道了」在空状态与编辑器全程可见；图文编辑器另有 `role="dialog"` 的「图片可以编辑啦」提示弹窗。二者都可能拦截点击。
- 空状态没有任何标题/正文/发布按钮；只有 `div.upload-content` + 隐藏的 `input.upload-input` → 「页面就绪」不能等这些元素。
- 视频：标题框在 t=3s 就出现，但发布按钮仍 `submit-disabled=true` 到 t≈12s → 「元素出现」不等于「可操作」。
