# 07 — 测试与验收策略

Status: resolved
Type: grilling
Blocked by: 05, 06

## Question

在没有稳定真实账号环境的前提下，如何证明实现有效？需要确定：

1. 离线测试覆盖什么：参数解析与映射、页面 fake、选择器/流程快照、退出码。
2. 真实 TikTok Studio 冒烟如何 opt-in（例如环境变量），需要哪些前置条件。
3. 现有 `tests/` 的 fake 与契约测试如何复用。
4. 哪些能力只能靠人工验收，验收清单怎么写。
5. 选择器漂移时测试能给到什么信号。

## Answer

### 0. 总原则

测试框架保持 `unittest`，默认命令 `python -m unittest discover -s tests`；**不引入 pytest、不新增依赖、默认套件不启浏览器、不访问网络**。

证明分三层，真实账号只出现在后两层，**永远不是 CI 门禁**：

| 层 | 是否默认运行 | 证明什么 |
| --- | --- | --- |
| 离线自动化 | 是 | 参数契约、映射、步骤逻辑、流程顺序、退出码、超时常量、旧行为回归 |
| opt-in 表单级冒烟 | 否（`SAU_TIKTOK_SMOKE=1`） | 选择器在真实 TikTok Studio 上确实命中；控件可设置且回读一致 |
| 人工发布验收 | 否 | 设置的实际效果、真实发布/定时/封面/图片帖结果 |

真实页面能证明选择器有效，但证明不了失败分支；失败分支（回读不一致、置灰但已满足、品牌二选一补零）由内存 fake 覆盖，不需要模拟 DOM。

### 1. 默认离线套件：7 组

| # | 组 | 覆盖与断言要点 |
| --- | --- | --- |
| 1 | 参数与校验 | `upload-video` 新 flag 全部出现在 parser；`upload-note` 注册为合法 action；`--images` 1..35、仅 JPG/JPEG/PNG/WebP、单张 ≤50 MB；Title ≤90、Description ≤4000、hashtag ≤50；`--note`/`--notef` 互斥；`--aigc`/`--no-aigc` 互斥；`--privacy` 仅四个枚举；非法值/超限 → 退出 2，且在启动浏览器前失败 |
| 2 | 映射 | CLI → request dataclass；未传 = `None` 三态，不得提前填默认值；隐私枚举 ↔ 页面语义映射；`--your-brand`/`--branded-content` 归一化（未请求的一项显式设为未勾选）；`--disable-reuse` 单开关；`upload-note` 不产生 reuse / thumbnail 字段 |
| 3 | 步骤逻辑 | 内存 fake 上五条分支：未传不操作；显式设置后回读；回读不一致 → 失败并报选项名/请求值/实际值；置灰但目标已满足 → 成功；品牌声明自动打开 + 两个复选框都显式设置 |
| 4 | 流程顺序 | 只做粗粒度断言：设置步骤先于发布；封面步骤后于处理完成；旧 `upload-video` 不带新参数时，操作序列与当前实现一致（不得多出任何设置调用） |
| 5 | 退出码 | `0/1/2/9/10`；`PublishResultUnknownError` 仅在“点击已发出 + 未到成功页 + 未命中登录”时产生；9 的消息必须包含“禁止自动重发”；从未点击发布 → 1 而不是 9 |
| 6 | 超时与登录 | `TIKTOK_LOGIN_CHECK_TIMEOUT_MS == 20_000`、`TIKTOK_PUBLISH_TIMEOUT_SECONDS == 900`；中途 URL 命中 login/captcha/verify/2fa → 10；内嵌验证码不识别 → 1（已知盲区，测试锁现状） |
| 7 | 图片特有 | 先探测 Photos tab 再选文件；探测失败在选文件前退出 1；不调用 reuse/duet/stitch；第 1 张即封面；`--thumbnail` 不存在于 `upload-note` |

不用覆盖率数字判定；上表每组至少一条正向 + 一条负向断言。默认套件失败即阻断合并。

### 2. 页面替身边界

新增能力写成步骤函数，只依赖一个极简控件接口：

```text
set(value) -> None
read() -> value
disabled -> bool
```

- 默认套件用内存 fake 实现该接口：记录调用、维护当前值、可模拟 `disabled=True` 但目标已满足、可模拟 set 后 read 返回不一致。
- **不模拟 TikTok 的 DOM 标签、`Show more` 折叠、label 文案、层级结构**；这些属于真实页面。
- 测试只断言“步骤函数对控件做了什么、回读后如何判定”，不断言 CSS 字符串。
- 生产接线（谁把控件接口映射到真实 locator）由 09 设计；07 只要求步骤函数不直接吃 DOM 字符串，否则无法在内存中测失败分支。

### 3. 选择器组织与漂移信号

按仓库现状，**不引入 manifest、不做源码扫描**。TikTok 现有 `tk_config.py::Tk_Locator` 只有 `tk_iframe` / `default`，其余内联；新控件沿用同一风格（`tk_config.py` 命名常量，或就地候选列表）。

漂移信号分两类：

1. **真实页面信号（唯一能发现 TikTok 改版的信号）**：冒烟失败信息必须包含控件名、已尝试的候选选择器、当前页面 URL、所处阶段（进页/选文件/表单/设置/封面）。
2. **运行期信号**：新增步骤抛错时写明控件/阶段；回读不一致的 stderr 含选项名、请求值、实际值（与 06 一致）。

离线套件只能发现“我们改代码时改坏了行为”，不能发现 TikTok 改版。刷新流程写进 08：跑冒烟 → 按失败控件更新选择器 → 重跑。

### 4. opt-in 表单级冒烟

文件：`tests/test_tiktok_smoke.py`。

**开关与配置**

- 开关：`SAU_TIKTOK_SMOKE=1`；关闭时整模块 skip。
- 复用 `MLX_API_TOKEN`、`SAU_MLX_FOLDER_ID`、`SAU_MLX_PROFILE_ID`。
- 样本：`videos/demo.mp4`、`videos/demo.png`，不新增二进制。
- 前置条件：
  1. Multilogin 桌面应用在本机运行，Profile 使用 Mimic 内核。
  2. Profile 界面语言 English (US)，已登录一个可发布的公开 TikTok 账号。
  3. 与 `SAU_MLX_SMOKE` 共用 Profile 时**串行运行**，不得并行。

**视频用例**

1. 打开 `TIKTOK_UPLOAD_URL`，断言上传入口存在。
2. 选 `videos/demo.mp4`，等待表单出现（标题编辑器可见）。
3. 展开 Settings / Show more。
4. 逐控件定位 → 设置一个安全值 → 回读并断言；覆盖隐私、评论、reuse、AIGC、Your brand、Branded content。
5. 打开封面编辑器并验证 `Upload cover` 入口（覆盖 04 指出的旧选择器更新）。
6. **绝不点击 Post / Schedule**。

**图片用例**

1. 探测 Photos tab；缺失 → **只 skip 本用例**并输出原因（rollout 未覆盖，属账号能力，不是代码失败）。
2. 有则选 `videos/demo.png`，验证 title/description/tags 输入与隐私/评论/AIGC/品牌控件（图片帖不测 reuse）。
3. 第 1 张即封面；**绝不点击 Post / Schedule**。

**失败与跳过矩阵**

| 情况 | 行为 |
| --- | --- |
| `SAU_TIKTOK_SMOKE` 未设置 | 整模块 skip |
| 开关打开但变量缺失 | **fail**，消息指出缺哪个变量 |
| 未登录 / 登录页 / 验证码跳转 | **fail**，消息要求先在 Multilogin 登录 |
| 上传页打不开 / 视频路径控件缺失 | **fail**，报控件名 + 候选 + URL |
| 账号没有 Photos tab | **只 skip 图片用例**，视频用例仍须通过 |
| 设置后回读不一致 | **fail**，报选项/请求值/实际值 |

**副作用**：不发布，但可能留下未发布草稿。冒烟不自动删除；08 写清理步骤（TikTok Studio → Content/Drafts 手动删除）。设置不跨表单记忆（03 已确认每次重置），冒烟不会污染后续运行。

### 5. 人工发布验收清单

一份逐项清单，证据 = 退出码 + 帖子 URL/截图，记录日期与账号类型。

| 项 | 必做/条件 | 核对方式 |
| --- | --- | --- |
| 视频无新参数发布 | 必做（公开账号） | 退出 0；Content 列表出现新帖 |
| `--privacy only-me` | 必做 | 帖子仅自己可见 |
| `--no-comments` | 必做 | 评论入口关闭 |
| `--disable-reuse` | 必做 | 合拍/拼接/贴纸复用关闭 |
| `--aigc` | 必做 | 帖子显示 AI-generated 标识 |
| `--your-brand` / `--branded-content` | 必做 | 声明出现在帖子/审核态 |
| 视频自定义封面 | 必做 | 封面为上传图 |
| `--schedule` | 必做 | 到点发布，时间正确 |
| `upload-note` 多图 | 必做 | 顺序正确，第 1 张为封面，标题/正文/tags 正确 |
| 图片帖设置项 | 必做 | 页面若渲染 AIGC/品牌则核对；未渲染则记为“页面不支持” |
| 私有账号首项文案、friends+品牌组合 | 有条件（有第二个账号才做） | 首项显示 Followers；组合可用性记录为置信度 |
| Photos tab 灰度 | 有条件 | 无入口时记录账号未覆盖 |
| 账号能力不支持时退出 1 | 有条件 | 用不匹配的账号组合触发，stderr 含请求值/实际值 |
| 退出码 9 的破坏性复现 | **不要求** | 离线已锁映射；人工不制造“结果未知” |

私有账号 / Photos 灰度 / friends+品牌组合未实测时，08 的对照矩阵必须标为“条件可行 / 未验证”，不得写成已验证。

### 6. 现有测试如何复用

- `tests/test_mlx_tiktok.py` 保留为旧 `upload-video` 的回归基线，**直接改两条必然冲突的断言**：
  - `test_actions_are_check_upload_video_login_only`：action 集合加入 `upload-note`（并改名去掉 `_only` 语义）。
  - `test_unknown_subcommand_still_exits_2`：未知子命令样本换成真正不存在的名字（如 `upload-audio`），不再用 `upload-note`。
- 复用现有 `_run`、`_AsyncCM`、`_subparser`、`_option_strings` 与 `tests/fakes.py`；不重写旧文件、不拆文件、不 skip。
- 新增按主题拆分：
  - `tests/test_tiktok_settings.py`：内存 fake + 步骤逻辑（第 1 节第 3 组）。
  - `tests/test_tiktok_note_cli.py`：`upload-note` 参数、校验、映射、图片特有流程（第 1、2、7 组）。
  - `tests/test_tiktok_smoke.py`：第 4 节的 opt-in 冒烟。
- 新增一条回归断言：`upload-video` 不传任何新参数时，fake 记录的操作序列中**没有任何设置类调用**。

### 7. 明确不测

- 离线不测真实选择器匹配、账号级能力可用性、设置的实际效果。
- 不自动化真实发布、风控、扫码、短信 2FA、内嵌验证码、地区跳转；内嵌验证码是 06 已记录的盲区。
- 不自动化封面渲染、定时真实到点、AIGC 标识实际展示、品牌政策审核。
- 不测 Profile 指纹、代理出口、Mimic 内核版本、MLX 云端 API、Docker/跨机。
- 不测 `sau_backend.py`、Vue 前端、账号↔Profile 映射（charter 已排除）。

### 8. 对下游工单的约束

- **08 汇总规格**：必须包含第 1 节测试矩阵、第 4 节冒烟运行手册（开关/前置/失败矩阵/草稿清理/串行说明）、第 5 节人工清单、第 3 节漂移刷新流程；不得把真实账号写成默认验收前提。
- **09 共用流程**：步骤函数必须可被内存控件 fake 驱动；发布阶段需暴露 `publish_clicked` 状态；新增步骤不得吞异常；`PublishResultUnknownError` 只能由发布阶段抛出。
- **实现阶段**：只改上述两条旧断言；不新增测试依赖；默认套件保持离线。

## Comments
