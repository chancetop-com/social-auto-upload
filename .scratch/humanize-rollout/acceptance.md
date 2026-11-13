# 人类化交互层 — 真机验收记录

验收口径（规格 §6.4）：

- **只验本地模式**；托管模式（Multilogin X / AdsPower）一律「未验证」。
- 一律 `--no-publish` 干跑：素材、配文/话题、封面、声明、定时、选项、读回全部照跑，
  **停在发布按钮 / Share 就绪前，不点真实发布、不上真实帖子**。
- 因此**发布点击本身不在本轮验收范围**（规格 §9-28）；发布按钮的 `Humanizer.click`、
  `before_submit` 与提交后行为只由离线测试 + 小红书既有真机证据背书。
- 就绪超时（退出 `1`）视为失败，必须记录目标与 reason。
- 预算上限 15 分钟（900s）；下表墙钟为整条命令耗时。

## 小红书（回归 · 参照实现）

2026-11-12 · 账号 `180`（`cookies/xiaohongshu_180.json`）· 本地模式 · `--headed` · `--debug`

| # | 发布类型 | 触碰字段（规格 §3 以外的小红书既有链路） | HUMANIZE=1 墙钟 | 预算消耗 | 停止点 / 就绪证据 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 视频 | 标题、正文、话题×2、封面（缩略图 + hover 入口）、内容类型「自主拍摄」、定时（C1/C2/C3）、ARM | 56s | 56/900 ≈ 6% | `🧪 ARM 就绪，--no-publish 停在发布按钮前（未点击发布）`，exit 0 | pass（1 处非阻断降级，见下） |
| 2 | 视频（复跑） | 同上（内容类型「自主拍摄」成功写入） | 72s | 72/900 ≈ 8% | 同上，exit 0 | pass |
| 3 | 图文 | 图片×2、标题、正文、话题×2、定时（C1/C2/C3）、ARM | 31s | 31/900 ≈ 3% | 同上，exit 0 | pass |

观察项：

1. **内容类型「自主拍摄」偶发 `point-drift`**（run 1，非阻断：声明步骤按既有契约 warning
   降级，流程继续到 ARM；run 2 同一路径成功）。`point-drift` 来自 `Humanizer.click`
   既有的 ±1px 容差，不是 ticket 01 的共享层修复引入；规格 §2.5.1 的处置是「接受，
   真机出现就在**调用点**先 `Humanizer.hover()`」，属后续平台提交，不是回滚共享层。
   另注：该路径在 ticket 01 之前（11:27 日志）也失败过，当时是 `ambiguous:3`（选择器问题）。
2. **`--original` 目前不可用（账号/平台态，不是人类化回归）**：`div.original-wrapper
   .d-switch` 在视频发布页持续报 `disabled`（2026-11-12 23:28 复核可复现）。
   对照实验：`HUMANIZE=0` 走原生 `locator.click()` 同样等不到 enabled（30s 超时），
   证明与人类化层无关。因此本轮视频验收不带 `--original`；原创声明链路的真机证据仍以
   2026-11-12 01:01 的既有记录为准。
3. 未出现 `covered-by:*`、`zero-box`、`no-bounding-box`；定时 C1/C2/C3 三段读回在 run 1/2/3
   均命中（开关 + 日期输入解析）。
4. 所有失败/成功日志留档：`.local/acceptance/humanize/xhs-*.log`（本机，未入库）。

结论：ticket 01 的共享层修复（几何可见性谓词）在小红书正路上**无回归**；不触发回滚。

## Instagram（W1）

2026-11-13 · 账号 `luke`（`cookies/instagram_luke.json`）· 本地模式 · `--headed` · `--debug`

| # | 发布类型 | 触碰字段 | 墙钟 | 预算消耗 | 停止点 / 就绪证据 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 视频（Reel） | 配文（标题+正文+话题）、封面、地点、关闭评论、AI 标识、Share 就绪 | 63s（H1） | 63/900 ≈ 7% | `Instagram 发布就绪，--no-publish 停在 Share 前（未点击发布）`，exit 0，`status=prepared` | pass |
| 2 | 视频（Reel） | 同上（H0 基线） | 42s（H0） | 42/900 ≈ 5% | 同上 | pass |
| 3 | 图文 carousel | 2 图、配文 1080 码点（>1000 bulk）、alt text ×2、地点、评论、AI、Share 就绪 | 64s（H1） | 64/900 ≈ 7% | 同上 | pass |
| 4 | 图文 carousel | 同上（H0 基线） | 44s（H0） | 44/900 ≈ 5% | 同上 | pass |

双基线：视频 H1 63s / H0 42s（+21s）；carousel H1 64s / H0 44s（+20s）。
`--result` 状态均为 `prepared`，未写 `content_id` / `post_url`；未出现验证码 / 滑块 / 限流提示。

真机暴露并已修复的四处（全部在 Instagram 平台层，未改共享层，未回滚 02）：

1. 首页导航栏 hover 展开 → 导航点击 `point-drift`：`_click_nav` 先 `hover` 再 `click`（§2.5.1）。
2. 逐字输入话题后 hashtag 联想浮层、地点联想浮层盖住右侧选项面板 → 选项点击 `covered-by:button._acmx`：
   配文回读后与地点选中后各点一次弹窗标题栏（`role=heading`）关闭浮层。
3. Lexical 把换行渲染成 `<br>`，`textContent` 读不到换行 → 配文回读改用 `innerText()`（有界轮询）。
4. `role=switch` 原生 input 为 `opacity:0` → 改点其可见父容器（§2.6），回读仍在 input 上。

以上四条均有离线回归测试；发布点击本身仍未验（§9-28）。

## TikTok（W1）

待跑（ticket 06，依赖 ticket 03 合并后）。

## 未验证平台

见 ticket 20 落地的平台表（12 个平台 × 「未验证（无真机环境）」× 离线测试文件）。
