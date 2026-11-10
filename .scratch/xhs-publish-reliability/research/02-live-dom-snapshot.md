# 02 — 真机 DOM 取证（发布页 / 图文编辑器 / 视频就绪）

- 取证时间：2026-11-10（本机，headless Chromium 156.0.8078.4，patchright）
- 账号：复用 `cookies/xiaohongshu_180.json`（登录态有效），**未发布任何内容**；产生的草稿未提交
- 环境：与本地模式同参数——`channel="chromium"`、`locale=zh-CN`、`Accept-Language: zh-CN,zh;q=0.9`、`stealth.min.js` init script、UA 把 `HeadlessChrome` 换成 `Chrome`
- 脚本：`research/capture_live_dom.py`、`research/probe_editor_controls.py`、`research/probe_video_readiness.py`
- 原始数据（本地，未脱敏，勿入 git）：`research/raw/probes.json`、`raw/controls-report.json`、`raw/video-readiness.json`、`raw/*.html|png`
- 置信度口径：**真机取证** = 本次实际观察到；**未验证** = 本次未覆盖

## 1. 入口 URL 的落地差异

| URL | 落地 | 首屏形态 |
|---|---|---|
| `?from=homepage&target=video` | 同 URL，HTTP 200 | 视频上传区（`accept=.mp4,…`） |
| `?from=homepage&target=image` | 同 URL，HTTP 200 | 图文上传区（`accept=.jpg,.jpeg,.png,.webp`） |
| `?source=official` | 同 URL，HTTP 200 | **落到视频变体**（上传区文案是「拖拽视频…上传视频」） |

三种入口在空状态下都**没有**标题框、正文编辑器、发布按钮——这些只在有内容后渲染。

空状态共同锚点：

- `div.upload-content`：1 个、可见，文案区分图文/视频。
- `input.upload-input`：1 个、**不可见**（`type=file`，`accept` 区分模式）；这也是现有登录态判定用的正向锚点。

## 2. 发布按钮

| 选择器 | 空状态 | 图文编辑器 | 视频编辑器 |
|---|---|---|---|
| `xhs-publish-btn` | 0 | **1、可见**，`is-publish="true"`、`submit-disabled="false"` | 见 §6 时间线 |
| `.publish-page-publish-btn button.bg-red` | 0 | **0（已不存在）** | 0 |
| `button:has-text("发布")` | 0 | 0（发布按钮是无文字的 `<xhs-publish-btn>`） | 0 |

结论（真机取证）：

1. 上游的**新版**选择器与属性口径在现网成立：`is-publish` / `submit-disabled` 两个属性都在，且**零中文依赖**。
2. 上游的**旧版**选择器在现网**已死**。双代并存的必要性下降为「容错旧账号/灰度页面」，不是当前页面事实。
3. `submit-disabled="false"` 在**标题为空**时也成立 → 该属性只表达「上传/处理是否可提交」，**不表达「表单是否填完」**。03 不能把它当「可以发布」的完整判据。
4. `xhs-publish-btn` 的 `innerText` 为空 → 任何基于文字的点击/等待都会失效。

## 3. 标题 / 正文

| 环节 | 选择器 | 结果 | 属性 |
|---|---|---|---|
| 标题 | `div.d-input input` | 1、可见 | `class=d-text`、`placeholder=填写标题会有更多赞哦` |
| 标题 | `input[placeholder*="填写标题"]` | 1、可见 | 与上面同一个节点 |
| 正文 | `div[role="textbox"][contenteditable="true"]` | 1、可见 | `class="tiptap ProseMirror"` |
| 正文 | `div.tiptap` | 1、可见 | 同上 |
| 正文 | `div.ql-editor` | 0 | — |
| 正文占位 | `p[data-placeholder*="输入正文描述"]` | 1、可见 | `class="is-empty is-editor-empty"`、`data-placeholder=输入正文描述，真诚有价值的分享予人温暖` |

结论：正文是 **ProseMirror（tiptap）**，不是 Quill；`data-placeholder` 的完整文案与现有选择器前缀一致。

## 4. 话题（图文编辑器内实测）

1. 在正文键入 `#旅行` 后：`#creator-editor-topic-container` = 1 个、可见，含 **50** 个 `.item .name`（如 `#旅行pov`、`#旅行中的非遗体验`、`#旅行`）。
2. 点击第一个候选后：正文出现话题词，`a[data-topic]` = **2 个节点**，两者 `data-topic` 完全相同：

```json
{"id":"697b3a24000000002500dad4","link":"xhsdiscover://topic/v2/697b3a240253000000000001","name":"旅行pov"}
```

- 锚点可见文本形如 `#旅行pov[话题]#`；第二个锚点文本为 `#旅行pov`。
- **上游「数量必须严格 +1」的判据在现网会误判**：插入 1 个话题得到 2 个 `a[data-topic]`。
- `data-topic.name` 与请求值大小写不敏感比较仍可行（name 不含 `#`）。

## 5. 上传与选项控件

| 环节 | 选择器 | 空状态 | 编辑器 | 备注 |
|---|---|---|---|---|
| 图文上传框 | `div.upload-content` | 1 可见 | 存在 | 视频/图文共用类名，靠 `accept` 区分 |
| 上传 input | `.upload-input` / `input[type=file]` | 1（隐藏） | 3 个 file input | 编辑器里另有封面等 input，取 `.first` 有歧义风险 |
| 图文预览计数 | `.img-preview-area .pr` | 0 | 1（上传 1 张后） | 单张已验证；N 张未验证 |
| 定时发布卡片 | `.custom-switch-card` | 0 | 3 个（原创声明 / 定时发布 / …） | 用 `filter(has_text="定时发布")` 可定位 |
| 定时开关 | `.post-time-wrapper .d-switch` | 0 | 1 可见 | — |
| 开关状态 | `.d-switch-simulator` | 0 | 3 个 | 状态在 class：`unchecked` / `checked`（现有 `_switch_is_on` 口径成立） |
| 定时时间 | `.d-datepicker-input-filter input.d-text` | 0 | 打开开关后 1 可见 | `.date-picker-container input` 也命中 1 |

## 6. 视频上传 / 就绪时间线（`videos/demo.mp4`，965KB）

每 3 秒采样一次：

| t(s) | `is-publish` | `submit-disabled` | 标题框出现 | 预览文本 |
|---|---|---|---|---|
| 0 | `false` | `false` | 否 | 空 |
| 3 | `true` | **`true`** | **是** | 空 |
| 6–9 | `true` | `true` | 是 | 「…视频分辨率较低，建议上传1080P…」 |
| 12+ | `true` | **`false`** | 是 | 同上，稳定到 87s 采样结束 |

结论（真机取证，单次 965KB 视频、本机网络）：

1. **`xhs-publish-btn[submit-disabled]` 是视频就绪信号**：处理中为 `true`，可发布时 `false`，零中文依赖。
2. **标题框出现 ≠ 就绪**：t=3s 标题框已在，但按钮仍禁用 9 秒。
3. **预览区文本里出现「分辨率」≠ 上传成功**：该文案是画质建议警告，处理期间就有；现有视频完成判定按关键词命中 `分辨率` 会**提前**认为成功。
4. 视频页的 `is-publish` 在 0s 时为 `false`（尚未渲染完），随后转 `true`——与上游「`is-publish == "false"` 跳过该 widget」的语义一致。

## 7. 声明与浮层

| 环节 | 事实 |
|---|---|
| 内容类型声明入口 | 文字「添加内容类型声明」可点 |
| 下拉项（顶层） | `虚构演绎，仅供娱乐` / `笔记含AI合成内容` / `内容包含营销广告` / `内容来源声明` |
| 二级（来源声明） | `自主拍摄` / `来源转载` |
| 原创声明弹窗 | 点击「原创声明」开关后出现，含「…获得以下权益…」「声明原创」；是 `div.d-modal` 一类，**不保证带 `role=dialog`** |
| 图文 AI 提示弹窗 | **存在并可见**：`role="dialog"`，文案「图片可以编辑啦，快来试试吧…」 |
| 引导浮层 | `.feature-guide__btn`「我知道了」在空状态、编辑器、各阶段**一直可见** |

→ 06 必须把「AI 图片提示弹窗」「引导按钮」列为可拦截点击的覆盖层。

## 8. 登录 / 验证页的真实 path（无会话探测）

清空 storage_state 后访问：

| 入口 | 落地 |
|---|---|
| `/publish/publish?…target=video` | `https://creator.xiaohongshu.com/login?source=&redirectReason=401&lastUrl=%252Fpublish%252Fpublish%253F…` |
| `/publish/publish?…target=image` | 同上（`lastUrl` 不同） |
| `/`（创作者首页） | `https://creator.xiaohongshu.com/login` |

- 共同特征：path 以 **`/login`** 开头，且页面存在 `div[class*='login-box']`（1 个）。
- **未观察到** `/website-login` 或 `/website-login/captcha`（本次未触发验证码，无法验证验证页 path）。
- 上游的 `/website-login` 分支来自其网页端场景，**不能照搬到 creator 后台**；07 的 path 判据应以 `/login` 为基线。

## 9. 对下游工单的直接含义

- **03**：`submit-disabled=false` 只代表「可提交」，不代表「已填完」；点击前的自检与成功判据要另行定义。
- **05**：`xhs-publish-btn` 可采用为基线；旧版 `.publish-page-publish-btn` 在现网为 0，作为兜底而非主路径；正文用 `div.tiptap`（非 Quill）。
- **06**：`feature-guide__btn` 与图片 AI 弹窗是常驻覆盖层，需要「先关闭覆盖层再操作」或点击穿透策略。
- **07**：登录失效 = path 前缀 `/login` + `div[class*='login-box']`；验证页 path 未取证。
- **08**：`a[data-topic]` 一次插入出现 2 个同值节点，「数量 +1」不可用；应改为「按 `name` 集合变化」或「正文出现话题锚点」。
- **09**：图文 `.pr` 单张已验证；视频就绪用 `submit-disabled`，不要用「标题框出现」或「预览区含 `分辨率`」。

## 10. 未覆盖 / 需真机补充

- `/website-login/captcha` 的真实形态（未主动触发风控，不拿账号冒险）。
- 有头模式与托管模式（Multilogin/AdsPower）下的同一组锚点。
- 多图（N>1）逐张上传时 `.pr` 的计数行为、单张上限时间。
- 视频长文件 / 慢网络下的 `submit-disabled` 翻转时长（本次 965KB 约 12s）。
- 发布成功页 `**/publish/success?**` 的真实 query 形状（本次不发布，未取证）。
