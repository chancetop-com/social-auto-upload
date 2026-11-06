# 04 — 视频与图片封面

Status: resolved
Type: research
Blocked by:

## Question

网页端如何选择封面？具体要回答：

1. 视频封面帧选择：是否存在时间轴/帧选择器，如何定位到指定毫秒对应的帧。
2. 自定义封面上传：入口、支持格式与尺寸、与现有 `thumbnail_path` 流程的关系。
3. 图片帖封面：是否通过选择第 N 张图作为封面，页面表现是什么。
4. 封面操作与定时发布、AI 标识、品牌声明的先后顺序是否有限制。
5. 上传完成前是否可以设置封面。

输出：UI 路径、候选选择器、与现有 `upload_thumbnails` 的差异，并逐条标注置信度。

## Answer

详见 [研究文档](../research/04-covers.md)。

- **视频自定义封面可行**：`Edit cover` → `Upload cover`，JPEG/PNG/JPG，≥324×432，≤50 MB，按 3:4 裁剪；与现有 `thumbnail_path` 语义一致，但现有 `upload_thumbnails` 的 `.cover-container` / `Confirm` 等选择器很可能已过期，当前 UI 更像 `Edit cover` / `Upload cover` / `Save`。
- **视频按毫秒选帧部分可行**：11 帧胶片 + 可拖拽指示器，点击胶片按 `x = target_ms / duration_ms * canvasWidth` 映射；精度约 `duration/429` 毫秒/像素（1 分钟约 ±140 ms，10 分钟约 ±1.4 s），无毫秒输入框。若要求精确毫秒，建议本地 ffmpeg 抽帧后走自定义封面上传。
- **图片帖封面只能第 1 张**：没有“第 N 张作封面”控件；换封面等于拖到第 1 位，会改变图片顺序。网页端无法“保持顺序同时换封面”。
- 封面与定时/AI/品牌无硬性顺序依赖，但必须在最终 `Schedule`/`Post` 前完成；视频需等 Processing 完成。
- 风险：预览变化不等于服务端接受封面（上游 issue #228），需要发布后核验或页面状态断言。
- 待复核 11 项已列在文档末尾（真实 DOM、帧步长、Save/Confirm、裁剪行为、图片帖入口等）。

## Comments
