# TikTok 浏览器能力对齐 — 路线图

> **实施状态（2026-11-06）**：ticket 10–18 已实现、通过 code review 并合入 `integration/tiktok-browser-parity`；ticket 19 的真实账号冒烟与发布验收未执行（本机无 MLX token / Launcher / 真实账号），保持“待验收”。
> **后续扩展**：TikTok 本地 cookie 模式已实现并合入（见 [`../tiktok-local-mode/spec.md`](../tiktok-local-mode/spec.md)）；本地私有账号真实验收证据见 [`acceptance-local.md`](./acceptance-local.md)。

## Destination

一份可交给后续会话实施的规格：在不引入 TikTok 官方 API 的前提下，用现有 MLX 浏览器流程补齐 Content Posting API 的作者侧能力（隐私级别、评论/合拍/拼接开关、AI 生成标识、品牌内容声明、封面、图片帖），并给出参数契约、默认值、失败语义、测试策略与“API 能力 ↔ 浏览器实现”对照矩阵。

## Notes

### 已确认约束（charter）

- 通道固定：继续用浏览器 + Multilogin X Profile；不注册开发者 App、不接 OAuth、不走 Content Posting API。
- 图片按本地文件处理，与视频相同；不使用 `PULL_FROM_URL`，不要求图床或域名验证。
- 新增图片帖命令名 `upload-note`，与抖音/小红书/快手/Facebook 对齐；支持标题、正文、tags。
- 尽可能补齐 API 作者侧能力；每项先确认浏览器 UI 是否可做，再由用户判断取舍。
- 实现基线：以当前 `main_chrome.py` 的视频发布流程为起点扩展，不另起一套架构；新能力作为可选步骤插入现有流程。
- 现有 `upload-video` 的参数、行为、退出码保持向后兼容。
- MLX Profile 界面语言固定 English (US)；不新增本地模式。

### 代码事实

- 入口：`sau_cli.py` → `sau_commands/tiktok.py` → `uploader/tk_uploader/main_chrome.py`。
- 现有能力：视频本地文件、标题、tags、定时、缩略图、登录检测、15 分钟发布超时。
- 现有定位器集中在 `uploader/tk_uploader/tk_config.py` 与 `main_chrome.py`；使用 patchright locator。
- 测试用 `unittest`，位于 `tests/`；MLX 相关已有 fake 与契约测试。
- 新增参数落点：`sau_commands/tiktok.py` 的 `TiktokVideoUploadRequest`；`TiktokVideo.__init__` 的 legacy positional 顺序不能动。
- 其他平台图文实现可参考：`sau_commands/douyin.py` 的 `upload-note` 与 `uploader/xiaohongshu_uploader` 的图文路径。

### 参考

- TikTok Content Posting API（2026-10 文档）：Direct Post、Upload、Photo、Query Creator Info、Media Transfer Guide。
- 研究结论必须标注置信度：官方文档 / 开源实现实测 / 仅推断。

## Decisions so far

<!-- 一条已关闭工单一行，格式：- [标题](链接) — 一句话结论 -->

- [01 — 图文（Photo）帖的浏览器入口与能力边界](./issues/01-photo-post-feasibility.md) — 条件可行：`?tab=photo` + 先切 tab 再选本地文件；最多 35 张、JPG/PNG/WebP/50MB；Title≤90、Description≤4000；第 1 张即封面；支持排序/定时/选曲，但 Photos tab 按账号灰度，需先探测。
- [04 — 视频与图片封面](./issues/04-covers.md) — 视频自定义封面可行（`Edit cover` → `Upload cover` → `Save`，旧选择器需更新）；按毫秒选帧精度约 `duration/429` ms/px，硬精确需本地抽帧；图片帖只能第 1 张作封面，换封面会改顺序。
- [03 — 隐私级别与互动开关](./issues/03-privacy-interactions.md) — `privacy_level` 与 `disable_comment` 可用浏览器表达；`disable_duet`/`disable_stitch` 已合并为 `Allow reuse of content`，只能同开同关；发布前必须回读，私有账号第一项变 `Followers`。
- [02 — AI 生成标识与品牌内容声明](./issues/02-aigc-brand-disclosure.md) — 三项都在 `Show more` 高级设置；AI 标识默认关、首次开启需点 `Turn on`；Your brand / Branded content 可同选但至少选一个；Branded content 不能配 Private，campaign 关联仍需移动端完成。
- [05 — CLI 参数契约与默认值](./issues/05-cli-parameter-contract.md) — `upload-video` 新增 `--privacy` / `--no-comments` / `--disable-reuse` / `--aigc|--no-aigc` / `--your-brand` / `--branded-content`；`upload-note` 用 `--images` + 可选 `--title` / `--note|--notef` / `--tags` / `--schedule`；未传就不动，显式传则设置并回读；超长/超限直接报错；不做 `--cover-ms`、`--bgm`、`--cover-index`。
- [06 — 能力预检与失败语义](./issues/06-preflight-failure-semantics.md) — 不做能力预检，只用“设置后回读最终状态”（置灰但目标已满足算成功）；账号能力不支持仍退出 1；新增退出码 `9` 表示“发布结果未知”（点击已发出、未到成功页、未跳登录），禁止自动重发；超时沿用现状常量；验证码/2FA 仅靠 URL 标记判 10。
- [07 — 测试与验收策略](./issues/07-test-strategy.md) — 三层证明：默认离线 `unittest`（7 组契约，逻辑用内存控件 fake，不模拟 DOM）+ `SAU_TIKTOK_SMOKE=1` 表单级冒烟（复用 MLX 变量，设置/回读但不发布，缺 Photos tab 只 skip 图片用例）+ 人工发布验收（公开账号必做，私有/灰度有条件）；不引入 manifest，漂移靠冒烟命名失败；旧 `test_mlx_tiktok.py` 只改两条冲突断言。
- [09 — 视频/图片共用流程与扩展点](./issues/09-shared-flow-extension-points.md) — 视频号式模板方法：`TiktokBaseUploader` 持 9 步骨架与发布循环，`TiktokVideo` / `TiktokNote` 只实现钩子；分叉点提前到进页（URL / Photos tab），表单填写不是唯一；选项打包 `TiktokPublishOptions` + 构造器 keyword-only；选择器内联、`tk_config` 只放常量；登录 / 15 分钟 deadline / 映射完全复用；全量改名到骨架词汇，测试仅 2 条断言 + 2 行调用。
- [08 — 汇总实施规格](./issues/08-assemble-spec.md) — 规格已产出（[spec.md](./spec.md)）：能力矩阵、命令/参数契约、视频与图片两条 UI 路径及候选选择器、设置后回读、退出码 `9`、三层测试、部署/阶段/回滚齐全；选择器降级改为每步有序候选、`--json` 明确为非目标。

## Implementation status

- [10–18] 已实现并合入 `integration/tiktok-browser-parity`：共用骨架、退出码 `9`、视频隐私/互动、AIGC/品牌、封面刷新、`upload-note` 核心与文案/选项、文档/Skill/术语表、opt-in 冒烟。
- 验证：TikTok 专项 188 tests 全绿；默认离线套件 726 tests，基线 5 failures + 1 error + 2 skips 均为既有、非 TikTok 问题；`git diff --check` 干净。两轴 code review 已完成，spec 缺口已修复。
- [19 — 真实账号冒烟与发布验收](./issues/19-real-account-acceptance.md) — **未执行**：本机无 `MLX_API_TOKEN`、Launcher 不可达、无真实账号；所有发布效果项保持“待验收”。

## Not yet specified

<!-- 无。规格已覆盖原先的 4 项雾；事实性不确定项转为 spec §11.1「实施时必须先实测」，且已给出兜底行为。 -->

- 无。目的地已到达；剩余项是实施期实测事实（见 [spec.md](./spec.md) §11.1），不再是待决策问题。

## Out of scope

- 官方 Content Posting API、OAuth、开发者 App 审核、`PULL_FROM_URL`、图床、`MEDIA_UPLOAD` 收件箱、取消拉取、分片上传。
- Flask 后端 `sau_backend.py`、Vue 前端、调度 App 本身。
- 账号↔Profile 映射与身份校验。
