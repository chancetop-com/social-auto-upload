# 02 — 真机 DOM 取证（发布页/图文页）

Status: resolved
Type: task
Blocked by: —
Assignee: wayfinder-session (opencode)

## Question

用真实账号抓取小红书创作后台当前 DOM，确认候选锚点是否存在，产出命中表 + 快照，供 05（选择器基线）、06（可见性判定）、08（话题）、09（上传完成）使用。**不发布**。

清单（逐项记录“存在 / 不存在 / 存在但隐藏 / 属性值”）：

- 入口：`/publish/publish?from=homepage&target=video`、`?target=image`、`?source=official` 三种 URL 落地后的差异。
- 发布按钮：是否同时存在 `xhs-publish-btn`（含 `is-publish` / `submit-disabled` 属性）与 `.publish-page-publish-btn button.bg-red`；是否随图文/视频切换变化。
- 标题：`div.d-input input`、`input[placeholder*="填写标题"]`。
- 正文：`div[role="textbox"][contenteditable="true"]`、`div.tiptap`、`div.ql-editor`、`p[data-placeholder*="输入正文描述"]` 及其父级 `role`。
- 话题：`#creator-editor-topic-container .item .name`、`a[data-topic]` 的 `data-topic` JSON 形状。
- 图文：`div.upload-content`、`.upload-input`、`.img-preview-area .pr`。
- 选项：`.post-time-wrapper .d-switch`、`.custom-switch-card`、`.d-switch-simulator`、`.date-picker-container input`、`.d-datepicker-input-filter input`。
- 浮层：`div.d-popover`、`.feature-guide__btn`。
- 登录/验证：从日志或一次无效会话观察真实 path（`/login`、`/website-login[/captcha]`），只记录路径不含账号信息。

做法建议：`sau xiaohongshu upload-video --no-publish`（本地模式）+ 手动 `page.content()` 保存；或 Playwright trace。产出 `research/02-live-dom-snapshot.md` + 原始片段（**脱敏：不含 cookie、昵称、头像 URL、笔记内容**）。

## Answer

结论落盘：`research/02-live-dom-snapshot.md`。取证方式：复用 `cookies/xiaohongshu_180.json` 的有效登录态，本地模式同参数 headless 跑三个入口 URL + 图文编辑器 + 视频上传时间线，**全程未发布**（脚本 `research/capture_live_dom.py`、`probe_editor_controls.py`、`probe_video_readiness.py`）。

### 对下游最有影响的七条

1. **发布按钮**：`xhs-publish-btn` 存在且可见，属性 `is-publish="true"` / `submit-disabled="false"`；旧版 `.publish-page-publish-btn button.bg-red` **在现网为 0**。元素 `innerText` 为空 → 文字类选择器全部失效。
2. **`submit-disabled` 不是表单完成度**：标题为空时仍为 `false`。它只表达「上传/处理可提交」（视频处理中为 `true`）。03 需自带「已填完」自检。
3. **视频就绪可用 `submit-disabled`**：965KB 视频 t=0 `is-publish=false` → t=3~9 `submit-disabled=true`（标题框已出现）→ t=12+ `false` 稳定。**「标题框出现」与「预览区含*分辨率*」都会提前误判成功**（后者是画质建议警告，处理期间就在）。
4. **正文是 tiptap/ProseMirror**（`div.tiptap`、`role=textbox`），`div.ql-editor` 为 0；`p[data-placeholder*="输入正文描述"]` 命中。
5. **话题一次插入产生 2 个 `a[data-topic]` 同值节点**（`{id, link, name}`，name 不含 `#`）→ 上游「数量严格 +1」判据**不可用**；候选容器 `#creator-editor-topic-container .item .name` 一次 50 个可用。
6. **登录失效 = `/login` 前缀 + `div[class*='login-box']`**：`/login?source=&redirectReason=401&lastUrl=…`。**未观察到** `/website-login[/captcha]`，上游 path 判据不能照搬；验证页 path 仍未取证。
7. **常驻覆盖层**：`.feature-guide__btn`「我知道了」全程可见；图文编辑器另有 `role="dialog"` 的「图片可以编辑啦」弹窗 → 06 需处理点击拦截。

### 其余事实

- `?source=official` 落到**视频**变体；三个入口空状态都只有 `div.upload-content` + 隐藏的 `input.upload-input`（`accept` 区分图文/视频）。
- 标题：`div.d-input input` ≡ `input[placeholder*="填写标题"]`，placeholder `填写标题会有更多赞哦`。
- 图文预览 `.img-preview-area .pr` 上传 1 张后为 1（N>1 未验证）；编辑器内 file input 共 3 个，取 `.first` 有歧义。
- 定时：`.post-time-wrapper .d-switch` + 打开后 `.d-datepicker-input-filter input.d-text`（与现有选择器一致）；开关状态在 `.d-switch-simulator` 的 class（`unchecked`/`checked`）。
- 内容类型声明顶层四项 + 来源声明二级「自主拍摄 / 来源转载」；原创弹窗存在但**不保证** `role=dialog`。

### 未覆盖

`/website-login/captcha` 真实形态、有头/托管模式、多图计数、长视频翻转时长、`**/publish/success?**` 的真实 query。
