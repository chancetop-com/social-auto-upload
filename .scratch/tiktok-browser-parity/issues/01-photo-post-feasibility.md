# 01 — 图文（Photo）帖的浏览器入口与能力边界

Status: resolved
Type: research
Blocked by:

## Question

TikTok Studio 网页端是否支持发布图片帖？具体要回答：

1. 入口在哪里：上传页的 Photo/Images 切换、独立 URL，还是只能走 App？
2. 本地文件选择是否可行，最多多少张，支持哪些格式与大小限制？
3. 标题、正文（description）分别对应页面上的哪个输入框，各自长度上限是多少？
4. 配乐：是否有自动配乐/选择音乐，网页端能否控制？
5. 封面：是否可选第几张图作为封面？
6. 是否支持定时发布、草稿、多图排序？
7. 与视频上传模式相比，哪些字段存在、哪些缺失？

输出：可执行的 UI 流程、候选选择器、限制与风险，并逐条标注置信度（官方文档 / 开源实现实测 / 仅推断）。

## Answer

**条件可行**。详见 [研究文档](../research/01-photo-post-feasibility.md)。

- 网页端有独立 `Photos` tab 与 `/tiktokstudio/upload?tab=photo` / `/upload/post/photo` 路由；必须先切 tab 再操作 `input[type=file][accept*="image"]`，否则会落到视频 input 静默失败。
- 本地上传最多 35 张；网页接受 JPG/JPEG/PNG/WebP，单张 50 MB（与 API 的 20 MB/1080p 限制不同）。
- Title（≤90）与 Description（Draft.js，≤4000）分离；话题计入 description，最多 50 个。
- 有 “Add sound” 官方曲库，可搜索/收藏/推荐后点 `Use`；没有自动配乐开关。
- 没有独立封面控件：**第 1 张图即封面**，只能拖拽重排。
- 支持多图排序与定时（需账号 `schedule_enable`）；草稿机制存在但手动按钮待复核。
- 图片帖没有 Duet/Stitch、商品链接/合集等视频字段。
- 最大风险：Photos tab 2026-07 才放量，目标 Profile 可能没有入口；需先探测并明确报错。
- 待真人复核 12 项，已列在文档末尾（入口、accept、Title 必填性、Add sound DOM、Schedule、成功 URL、图片 ID 形态等）。

## Comments
