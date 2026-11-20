# CLI 使用说明

项目现在提供一个统一的 CLI 入口 `sau`，当前主线已经接入：

- `xiaohongshu`
- `rednote`：小红书国际版的独立适配，保留当前浏览器与站点语言；见 [Rednote 使用说明](./rednote.md)
- `tiktok`：本地持久化 Profile 或托管浏览器模式（MLX / AdsPower）
- `youtube`
- `instagram`：独立网页发布视频/Reels、单图与轮播
- `facebook`：Facebook 个人主页视频/图文立即发布、查询和删除
- `facebook-page`：Meta Business Suite 的 Facebook Page 视频/图文立即或定时发布

文章本地处理命令为 `sau article`，支持主题列表、环境准备和 Markdown/HTML 文件渲染，见 [文章文件与主题渲染](./article.md)。

面向 Agent 的 Skills 包括一个跨平台总入口和各已支持平台的独立入口，完整清单见 [README 的 AI Agent 区域](../README.md#ai-agent)。TikTok 使用 `sau tiktok`，默认走本地持久化 Profile 模式；设置 `MLX_API_TOKEN` 或 `ADSPOWER_API_KEY` 后走[托管浏览器模式](#托管浏览器模式通用)（[Multilogin X 模式](#multilogin-x-模式) / [AdsPower 模式](#adspower-模式)）。见 [TikTok Skill](../skills/tiktok-upload/SKILL.md)。

实现说明：

- `sau_cli.py` 负责组装命令和启动执行；`sau_commands/<平台>.py` 各自维护参数、请求数据和执行逻辑，`sau_commands/arguments.py` 维护共用参数规则
- `sau.exe` 是安装后在 Windows 虚拟环境里自动生成的命令入口，本质上还是调用 `sau_cli.py`
- 如果需要给 OpenClaw、Codex 等 Agent 使用，可安装仓库 `skills/` 下的总入口或任一平台入口；发布渠道和安装方式见 [Skill 分发说明](./skill-distribution.md)。

## 安装 CLI 入口

如果你希望直接使用 `sau` 命令，而不是手动执行 `python sau_cli.py`，先在项目根目录安装一次：

```bash
uv pip install -e .
```

安装后就可以直接使用：

```bash
sau xiaohongshu --help
sau rednote --help
sau tiktok --help
sau youtube --help
sau instagram --help
sau article --help
sau media --help
sau facebook --help
sau facebook-page --help
```

## 网络素材与预下载

七个平台现有的 `upload-video --file`、`upload-note --images` 和自定义封面 `--thumbnail` 都可在支持该参数的入口使用 HTTP(S) 媒体直链。图文可以混排本地路径和 URL，首图、顺序和重复位置按输入保留。

```bash
# 提前入队。收到 accepted 后，调度 App 可以退出。
sau media predownload --task-id post-42 --urls 'https://cdn.example.com/front.jpg'

# 需要本地路径时，加 --wait 并读取 stdout 的 JSON。
sau media predownload --wait --task-id post-42 --urls 'https://cdn.example.com/front.jpg'

# 发布时沿用原 ID 和完整 URL，可复用上一步的下载。
sau tiktok upload-note --account creator --task-id post-42 --images 'https://cdn.example.com/front.jpg' ./back.jpg
```

`--wait` 返回的 `items` 与输入一一对应。成功项含绝对路径 `path`，失败项含 `reason`。整组成功退出 `0`，有项目失败退出 `1`，参数或并发配置无效退出 `2`。同一下载根目录共用后台进程和下载名额，环境变量 `SAU_DOWNLOAD_CONCURRENCY` 接受正整数，默认为 `1`，下次后台进程启动时生效。

发布等待全部素材就绪后才开始计算平台的 15 分钟预算。素材下载失败时，命令指出失败项并以 `1` 退出，此时尚未提交帖子。省略 ID 时，远程文件放在本次发布的临时目录中，命令结束后清理。

指定 ID 时，确认帖子已发布会清理整个 `downloads/<任务ID>/`，包括同一 ID 下未用于这次发布的文件。平台仅确认已排期或正在处理时保留指定目录。失败、中断、结果未知或使用 `--no-publish` 时也保留，之前拿到的路径仍可用于核查。

```bash
# 清除一项，让相同 URL 在下一次请求时获取源站的新内容。
sau media delete --task-id post-42 --url 'https://cdn.example.com/front.jpg'

# 撤销整个任务的下载并删除其目录。
sau media delete --task-id post-42

# 由调度 App 每天运行，回收闲置满七天的任务目录。
sau media cleanup
```

发布正在使用一个任务 ID 时，主动删除该 ID 下任意素材都会退出 `1`。按 URL 删除后，已在等待该项的调用会收到 `item_deleted`。整目录清理会让该 ID 上的等待调用收到 `task_cleared`。

## 按需准备浏览器

所有正式本地浏览器平台默认使用系统 Chrome，由用户按 [Google 官方指引](https://www.google.com/chrome/)安装。显式选择 Chromium 时，在项目环境执行 `uv run patchright install chromium`，可加 `--no-shell` 省去不用的 shell；只有 headless shell 不满足运行要求。兼容自定义 binary 通过 `LOCAL_CHROME_PATH` 选择，只要求实际来源，失败不回退。基础安装和 help 不检查浏览器，托管动作不要求本地 Chrome/Chromium。Linux 系统依赖、Xvfb 与两条独立 CI 路线见[安装说明](./install.md#可选-ci-环境两条独立路线)。

## 重建本地浏览器 Profile（`reset-profile`）

七个平台均提供本地 Profile 重建命令。登录、检查、发布及可用的作品核对和删除动作复用同一平台、浏览器种类、账号别名的持久化资料。

```bash
sau tiktok reset-profile --account "creator" --browser-kind chrome
sau rednote reset-profile --account "creator" --browser-kind chromium
sau instagram reset-profile --account "creator" --browser-kind chrome
sau xiaohongshu reset-profile --account "creator" --browser-kind chrome
```

`--account` 和 `--browser-kind chrome|chromium` 都必须显式提供。目标是 `browser_profiles/<种类>/<平台>/<原始别名>/`，与日常浏览器资料隔离；整个资料根不纳入版本控制。别名保留空格、大小写和 Unicode 原值，拒绝空白、路径分隔符及点目录；文件系统等价路径不能合并不同别名。此命令只按 `--browser-kind` 选择目标，忽略 `LOCAL_BROWSER` / `LOCAL_CHROME_PATH` 与安装状态，不需要安装或启动浏览器。

显式执行即表示清除意图，不另行确认或备份。只清空选定种类/平台下的账号叶子目录及其重建状态，保留外置别名归属、另一种类、其他账号、历史结果和旧 Cookie/身份文件。目标不存在也返回 `0`，显示目标并提示先 login；重建不会自动登录或恢复发布任务，也不是重新提交旧任务的依据。

同一 Profile 被项目进程占用时立即失败；不同别名和同别名的两种浏览器可以并行。目录归属缺失、损坏、冲突、越界/链接，或浏览器 singleton 状态表明占用或无法安全确认时退出 `1`。项目不会自动删 singleton、终止外部浏览器或接管外部会话。归属记录、锁与重建标记位于账号数据外的 `.guards/<kind>/<platform>/<原始别名>/`；账号目录下没有项目必需的内部文件，`.sau-owner.json`、`profile.lock` 等也可作为合法别名。项目锁文件里的 PID/时间只用于诊断，残留文件本身不会阻止使用。

部分删除失败返回 `1` 并标记重建未完成，后续会话拒绝使用残缺资料；修复权限等实际故障后重跑同一显式命令。用法错误返回 `2`。设置 `MLX_API_TOKEN` 或 `ADSPOWER_API_KEY` 时拒绝重建，不调用 provider；两种凭据同时设置仍按原冲突规则返回 `1`。

## 客户端发布闸门（`--not-before`）

所有平台的 `upload-video` / `upload-note` 都支持 `--not-before "YYYY-MM-DDTHH:MM:SSZ"`（UTC 绝对时刻，保留秒级精度，不接受小数秒；`--schedule` 则要求秒/微秒为 0）：

- 上传素材、填写标题/正文、封面、声明、合集等准备工作照常执行；
- 全部准备完成后，如果本地当前时间早于目标时间，保持浏览器打开并等待；
- 只有绝对时刻 **>= `--not-before`** 才执行最后一次「发布/发表」点击；
- 不传该参数时立即发布；目标时间已在过去时也立即发布。

```bash
# 先完成所有准备，东八区 20:00（12:00 UTC）之后才点发布
sau xiaohongshu upload-video --account creator --file videos/demo.mp4 --title "新视频" --not-before "2026-12-01T12:00:00Z"
```

它与平台原生的 `--schedule` 是两套机制，支持原生定时的平台可同时使用：

- `--schedule`：把发布时间交给平台，由平台在目标时间自动发布；
- `--not-before`：在本地等待到目标绝对时刻才点击发布，发布动作仍由当前进程完成，适合需要人工保持登录态、平台不支持原生定时或希望统一控制提交时刻的场景。

两者同时使用时，应让 `--not-before` 早于 `--schedule`；CLI 在 FIRE（点击发布）前复核平台侧的定时开关与时间值，若等待结束时平台侧定时时间已过、或回读不一致，直接退出 `1`（确定未发布），**不会**改成立即发布。

注意事项：

- 等待时间使用 **UTC 绝对时刻**（零偏移，`Z`/`+00:00` 等写法均可；必须用 `T` 分隔日期与时间，保留秒级精度），例如 `2026-12-01T12:00:00Z`；CLI 解析后换算到运行机器的本地时区再等待/打印，非零偏移、无时区或空格分隔会退出 `2`；
- 长时间等待期间浏览器会保持打开；请确保网络、登录态和机器不会在目标时间前中断；
- 主动等待不计入上传/发布超时预算；所有支持客户端发布闸门的平台都会把等待时长从 deadline 中顺延；
- **禁止用 `--not-before` 做发布间隔或节流**：等待发生在填表之后、点击发布之前，本地 Profile 或托管 Profile 中的本平台全程被占用；节流、冷却与排程属于调用方 App（见[调度侧责任](#调度侧责任)）；
- 支持 `--no-publish` 的入口显式使用该参数时不会等待，也不会点击发布；小红书的 `--no-publish` 会跑到 ARM 就绪（见[小红书 CLI 子命令](#小红书-cli-子命令)）；
- Rednote、TikTok、小红书的视频和图文在 `--no-publish` 成功时，本地与托管模式均输出 `素材已上传，发布前检查已通过；已停止，未点击发布按钮。`。它表示媒体上传、编辑及发布就绪检查已完成，可能留下临时素材或草稿；失败或登录失效不会输出此成功摘要。

## 发布超时预算（全平台）

浏览器发布平台统一与 TikTok 对齐：整条上传/发布流程共用一个 **15 分钟总预算**
（`uploader/publish_timeout.py` 的 `PUBLISH_TIMEOUT_SECONDS = 15 * 60`）。TikTok、
小红书与 Instagram 也使用同一 `PublishTimeoutBudget`，仅保留各自更具体的错误文案。

- 预算覆盖打开发布页、上传素材、填写标题/正文/标签、封面、声明、合集、定时设置、点击发布，以及等待平台确认；
- **尚未点击发布**时超时：普通失败，CLI 退出 `1`，确定没有发布任何内容；
- **已经点击发布**后超时：结果未知，CLI 退出 `9`，禁止自动重发；先到平台后台按标题与发布时间核对；
- `--not-before` 的主动等待不计入预算，等待时长会从 deadline 中顺延；**禁止用 `--not-before` 做发布间隔/节流**（等待期间本地 Profile 或托管 Profile 中的本平台被占用，节流属于调用方 App）；
- 从提交视频或图片文件到平台显示素材就绪，使用本次发布的全部剩余时间。多张图片共用同一截止时间。例如，打开发布页已用 2 分钟，上传及后续发布步骤合计还剩 13 分钟。
- 导航、封面编辑和最终发布就绪检查等步骤仍使用各自的等待上限，并受剩余总预算约束。点击后的短轮询可能有秒级收尾开销。

## 人类化交互层（全平台）

浏览器发布平台默认走人类化交互层：文本输入逐字符
键入，可见点击走「移动 → 停顿 → 落点复核 → 按下 → 抬起」。默认开启，不需要任何参数。

- **唯一回滚开关是全局 `HUMANIZE=0`**（按 `strip()` 后比较）。它是语义开关而非限速开关：
  文本退化为一次 `keyboard.insert_text`，点击退化为一次原生 `locator.click()`，所有停顿为零；
  平台代码路径与选择器不变。开关在构造时快照，运行中不读环境变量；不提供
  `HUMANIZE_EXCLUDE`，也不按平台/按字段设例外。关闭时原生 `locator.click()` 失败同样保守
  视为「可能已派发」（浏览器不回报事件是否已触发），发布阶段失败退出 `9`；这是刻意语义。
- **覆盖边界**：只有「文本输入」与「可见点击」被人类化。`set_input_files`、文件选择器弹窗、
  `select_option`、`evaluate`、滚动与读回保持原生；按设计不做坐标点击的控件（隐藏
  checkbox、需 JS 展开的行等）保留原生点击，并在代码内逐条标注原因。
- **失败语义**：候选选择器一个都没出现 → 退出 `1`，属**选择器问题**，改代码而不是重试；
  元素找到但不可用（`ambiguous:N`、`zero-box`、`no-bounding-box`、`point-drift`、
  `covered-by:*`、`disabled`、`pointer-events-none`）→ 退出 `1`，属**页面问题**，只在调用方的
  状态重试循环里按业务重试。`ambiguous:` 首次发现即停止，上传完成等待和发布就绪等待也不重试，
  不取第一个按钮继续。鼠标按下之后才失败时异常带
  `click_dispatched="maybe"`，**禁止再次派发**。没有运行时自动降级：失败不会悄悄退回
  JS 点击或 `force`。
- **与 15 分钟预算的关系**：人类化停顿不是额外预算，只消耗
  [发布超时预算](#发布超时预算全平台) 的剩余额度，并按 `min(采样值, 剩余)` 收紧；预算耗尽后
  停顿收缩到 `0`，暂停本身不抛超时。超时判据仍只在就绪锚点与发布点击。
- **验收口径**：真机验收一律 `--no-publish`，停在发布按钮 / Share 就绪前，不点真实发布、
  不上真实帖子；发布点击与提交后行为不在本轮真机验收范围（规格 §9-28）。
- **托管模式未验证**：Multilogin X / AdsPower 下的人类化交互只做过离线验证，真机行为
  **未验证**。
- 完整契约（公开面、三种清空形态、长期限制、未验证清单）见
  [`.scratch/humanize-rollout/spec.md`](../.scratch/humanize-rollout/spec.md) §2 与 §6.4；
  本节只是对外投影，不存规格副本。

## 发布元数据支持表（八个入口）

下表按命令记录 AI 声明、帖子地点与配文话题三项元数据。每格分别写**网页证据**、**当前 CLI 行为**与**样本**（账号类型、界面语言、观察阶段）。缺样本写「未实测」；网页有控件而命令未接入写「CLI 未接入」；只有页面明确提示资格限制才写「账号不可用」。

| 命令 | AI 声明 | 帖子地点 | 配文话题 |
| --- | --- | --- | --- |
| `xiaohongshu upload-video` | 网页：显式选择 AI 后的终值未实测；CLI：`--content-type ai` 设置失败可告警继续；样本：未实测 | 网页：候选行显示地址，收起后只显示名称；CLI：未接入；样本：中文，`180`，账号类型未核验 | 网页：正文锚点读到 `#coffee`；CLI：`--tags` 追加到正文末尾；样本：中文，`180`，账号类型未核验 |
| `xiaohongshu upload-note` | 网页：下拉可见「笔记含AI合成内容」，选中终值未实测；CLI：`--content-type ai` 设置失败可告警继续；样本：未实测 | 网页：候选行显示地址，收起后只显示名称；CLI：未接入；样本：中文，`180`，账号类型未核验 | 网页：正文锚点读到 `#coffee`；CLI：`--tags` 追加到正文末尾；样本：中文，`180`，账号类型未核验 |
| `rednote upload-video` | 网页：已有回读匹配并到达发布前；CLI：要求回读；样本：中文，`rednote`，账号类型未核验 | 网页：候选行显示地址，收起后只显示名称；CLI：未接入；样本：中文，`rednote`，账号类型未核验 | 网页：正文锚点读到 `#coffee`；CLI：`--tags` 追加到正文末尾；样本：中文，`rednote`，账号类型未核验 |
| `rednote upload-note` | 网页：已有带 AI 声明的双图验收，到达发布前；CLI：要求回读；样本：中文，`rednote`，账号类型未核验 | 网页：候选行显示地址，收起后只显示名称；CLI：未接入；样本：中文，`rednote`，账号类型未核验 | 网页：正文锚点读到 `#coffee`；CLI：`--tags` 追加到正文末尾；样本：中文，`rednote`，账号类型未核验 |
| `instagram upload-video` | 网页：简体中文 Creator Reel 关切到开，分享前读到 `true`；CLI：已接入 `--ai-generated` / `--no-ai-generated`；样本：Creator，简体中文 | 网页：首个同名 `Shanghai`，候选只显示名称；CLI：按候选整行匹配，已接入；样本：Creator，简体中文 | 网页：分享前正文含 `#color #study`；CLI：`--tags` 合并进配文；样本：Creator，简体中文 |
| `instagram upload-note` | 网页：Creator 两图轮播开关原本已关；另有一次确认框遮挡导致回读失败；CLI：已接入 `--ai-generated` / `--no-ai-generated`；样本：Creator，简体中文 | 网页：首个同名 `Shanghai`，选中后名称一致；CLI：按候选整行匹配，已接入；样本：Creator，简体中文 | 网页：分享前正文含 `#color #study`；CLI：`--tags` 合并进配文；样本：Creator，简体中文 |
| `tiktok upload-video` | 网页：仅发布后读到创作者 AI 标识，开关三态未实测；CLI：已接入 `--aigc` / `--no-aigc`，发布前读回，入口缺失且显式关闭按 `default_off`/`entry_missing` 继续；样本：英文 Studio，`lukechen`，账号类型未核验，发布后阶段 + 受控页面离线验收 | 网页：候选行分行显示名称与英国地址，收起后只显示 `London Eye`；CLI：已接入 `--location`，按名称忽略大小写与空白取首个同名行，收起后回读；样本：英文 Studio，`lukechen`，账号类型未核验，发布前候选 + 受控页面离线验收；CLI 实机样本未实测 | 网页：视频配文读到 `#coffee` 关联标记；CLI：`--tags` 追加到 `--title` 配文；样本：英文 Studio，`lukechen` |
| `tiktok upload-note` | 网页：仅公开账号图片帖发布后读到创作者 AI 标识，开关三态未实测；CLI：已接入 `--aigc` / `--no-aigc`，发布前读回，入口缺失且显式关闭按 `default_off`/`entry_missing` 继续；样本：英文 Studio，`lukechen`，账号类型未核验，发布后阶段 + 受控页面离线验收 | 网页：候选行分行显示名称与英国地址，收起后只显示 `London Eye`；CLI：已接入 `--location`，与视频相同的同名匹配与回读；样本：英文 Studio，`lukechen`，账号类型未核验，发布前候选 + 受控页面离线验收；CLI 实机样本未实测 | 网页：图片帖正文读到 `#coffee` 关联标记；CLI：`--tags` 追加到 `--note` 正文；样本：英文 Studio，`lukechen` |

## 日志

日志默认只输出到控制台。需要落盘时设置环境变量 `SAU_LOG_TO_FILES=1`（也接受 `true` /
`yes` / `on`），每个平台写入各自的 `logs/<platform>.log`（如 `logs/tiktok.log`）；单文件
按 **10 MB** 轮转，保留 **10 天**。不设置该变量时不创建、不写入任何日志文件。

该变量在**进程启动时**（`utils/log.py` 导入）读取一次：进程运行中再改环境变量不会切换输出，
需要重启 `sau` 才生效。

## 托管浏览器模式（通用）

设置任一托管模式凭据后，`sau` 进入托管浏览器模式：CLI 通过本机桌面应用打开或加入指定 Profile，经 CDP 接管该 Profile 的浏览器上下文，并复用其中的登录态；不再读写 `cookies/*.json`。两个 provider 子模式是 [Multilogin X 模式](#multilogin-x-模式) 与 [AdsPower 模式](#adspower-模式)。

未设置任一凭据时仍为本地模式；`verify` / `delete` / `article` 在托管模式下仍然本地执行，不受 Profile 影响。

### 激活与优先级

独立的 `sau media predownload`、`sau media delete` 和 `sau media cleanup` 直接管理素材，忽略两种浏览器凭据。其余命令按下表处理，包括接收网络素材的 `upload-video` 和 `upload-note`。

| `MLX_API_TOKEN`（strip 后） | `ADSPOWER_API_KEY`（strip 后） | 模式 |
| --- | --- | --- |
| 空 / 未设置 | 空 / 未设置 | 本地模式 |
| 非空 | 空 / 未设置 | Multilogin X 模式（MLX） |
| 空 / 未设置 | 非空 | AdsPower 模式 |
| 非空 | 非空 | 冲突：退出 `1` |

- 只按环境变量选择，没有 `--browser-provider` 之类的新 flag；空串、纯空白和未设置都视为未激活。
- `ADSPOWER_API_BASE` **不参与激活**；单独设置不会改变模式，也不会告警。
- 同时设置两个凭据时，固定输出 `MLX_API_TOKEN 与 ADSPOWER_API_KEY 不能同时设置；请只保留一个。` 并退出 `1`（不是用法错误 `2`）。该检查在参数解析之后、命令分发之前执行；`--help`、未知子命令和缺参仍保持 argparse 的原有语义。
- 没有 key 的 AdsPower 安装不会被探测或警告，仍按本地 / MLX 的原有逻辑运行。

### 参数矩阵

| 参数 / 行为 | 本地 | MLX | AdsPower |
| --- | --- | --- | --- |
| `--account` | `login` / `check` / `upload-*` 必填；`verify` / `delete` 必填 | 忽略；身份由 `--profile-id` 决定（仅兼容占位） | 忽略；身份由 `--profile-id` 决定（仅兼容占位） |
| `--folder-id` | 静默忽略 | 必填 | 注册但静默忽略；传值不报错、不告警 |
| `--profile-id` | 静默忽略 | 必填 | 必填；strip 后映射 AdsPower `user_id`（V2 请求体字段 `profile_id`） |
| 缺 `--profile-id` | 不适用 | 退出 `2` | 退出 `2` |
| 缺 `--folder-id` | 不适用 | 退出 `2` | 不适用 |
| `--headless` | 读取 LOCAL_CHROME_HEADLESS，缺省 False | 同平台解析结果传给 Launcher | 同平台解析结果，V2 以 `"0"`/`"1"` 编码 |
| `--headed` | False（等价默认） | False（等价默认） | False（等价默认），V2 编码 `"0"` |
| `--debug` | 上传器调试行为 | 上传器调试行为 | 上传器调试行为；不传给 AdsPower |
| `login` | 允许 | 拒绝，退出 `1` | 拒绝，退出 `1` |
| `verify` / `delete` | 本地执行 | 本地执行 | 本地执行 |
| `check` 未登录 | 退出 `10` | 退出 `10` | 退出 `10` |
| `article` | 本地工具 | 本地工具 | 本地工具 |

- `--profile-id` 会去除首尾空白并检查非空；同一 Profile 上本平台已被占用、Profile 不存在或内核未就绪时退出 `1`。
- 托管模式下 `--account` **被忽略**：不读取、不校验、不参与日志/结果标签，也不决定 cookie 文件；身份由 `profile_id` 决定。传了非空 `--account` 只会出现在启动日志的 `ignored=` 列表里。
- 例外不变：`login`、`verify`、`delete` 仍必须 `--account`（`verify` / `delete` 始终本地执行）。
- 注册范围：七个平台的 `check` 与 `upload-*` 都接受 `--profile-id` / `--folder-id`；`login`、`verify`、`delete`、`article` 不注册这组参数。
- 托管模式下 `sau <platform> login` 不带 flag 进入 `run()` 后拒绝并退出 `1`；显式带 `--profile-id` 时因 `login` 解析器未注册该 flag，argparse 退出 `2`。
- 不打印模式 banner；`check` 成功只输出 `valid`，保持 stdout 可解析。

### 退出码

> **母本在规格**：完整契约表（按失败类型切分，含异常类型、`reason`、`publish_attempted` 字段与重跑规则）见 `.scratch/xhs-publish-reliability/spec.md` §4。本节只是派生投影，不能反向定义规格。

| 码 | 含义 | 典型场景 | 调用方动作 |
| --- | --- | --- | --- |
| `0` | 成功 | 发布已提交；`--no-publish` 已准备完成；`check` 已登录；Stop 失败但主操作成功（仅 warning） | 计数 +1、记录时刻 |
| `1` | 运行失败（**确定未发布**） | Local API / Launcher 不可达、key/token 无效、Profile 不存在/被占用、CDP 连不上；双凭证冲突；登录探针结构异常或网络 5xx；ARM 就绪窗/预算耗尽；素材上传失败；话题插错/多插；元数据或定时回读失败；`login` 与平台拒绝 | 修正后可无条件重跑（冷却另议） |
| `2` | 用法错误 | 缺 `--profile-id`、`ADSPOWER_API_BASE` 非法、本地缺 `--account`、静态参数冲突、未知子命令（包括已移除的平台，本地及托管均在解析时退出） | 修正参数 |
| `9` | 发布结果未知 | 发布点击已发出（FIRE 后）但未在观察窗内确认离开发布页，或派发后异常；**帖子可能已存在** | **禁止自动重发**；先到平台后台按标题/素材/时间核对 |
| `10` | 需要登录 / 人机验证 | 登录页、登录表单、验证码、2FA；本地运行前预检失败（本地 Profile 缺失或登录失效）；`check` 确定未登录 | 点击前：排人工登录，登录后可直接重跑。点击后（stderr 另有 `publish_attempted=true`）：**先核对笔记是否存在** |
| `11` | 请求过于频繁（429） | Launcher 或 AdsPower Local API 返回 HTTP 429 | 退避重试；CLI 自身不等待 |
| `130` | 用户中断 | `Ctrl-C`，退出时按共享规则释放平台资格 | — |

七个平台的本地持久化路径不写 JSON、正常关闭 persistent context 即关闭浏览器；关闭失败不覆盖成功、结果未知或主异常。用户中断仍按 `130` 处理。

**stderr 机器信号**：仅当退出码为 `10`、且本次运行**已越过不可回退点**（`publish_attempted=true`，即已派发发布点击）时，CLI 额外向 stderr 打**单独一行** `publish_attempted=true`；固定 token，无前缀、无本地化、无时间戳。点击前的 `10`、以及 `0/1/2/9/11/130` 都**不会**打这一行。该行只证明「可能已提交」，不证明发布成功。

- `11` 是 MLX 与 AdsPower 共用契约。**MLX 的 429 已由 `1` 改为 `11`**；调度层需要同步改为退避重试。
- CLI 不 sleep、不自动重试；429 由调度层处理。已成功的操作仅在 stop 阶段遇到 429 时只 warning，保持原退出码（通常 `0`）。
- HTTP 200 + 业务 `code` 表示限流的情况官方未定义，暂按 `1`；待真实 AdsPower 冒烟（ticket 09）确认后再扩展。

### 平台支持范围

两种托管模式使用同一张平台表。示例中的 `PROFILE_ID` 和 `FOLDER_ID` 须替换为桌面应用中的标识。

| 平台 | 托管模式可用的 action | 说明 |
| --- | --- | --- |
| 小红书、Rednote | `check`、`upload-video`、`upload-note` | 两个独立平台 |
| YouTube | `check`、`upload-video` | |
| Facebook、Facebook Page、Instagram | `check`、`upload-video`、`upload-note` | `verify` / `delete` 仍为本地模式 |
| TikTok | `check`、`upload-video`、`upload-note` | `login` 仅本地模式；图文依赖账号 Photos tab 灰度 |

七个平台共提供 20 个托管入口（7 个登录检查、7 个视频发布和 6 个图文发布）。`sau article` 是本地文件处理命令，不使用 Profile。`verify` / `delete` 始终本地执行，因此在托管模式下仍必须提供 `--account`（缺少时退出 `2`）。

### 共享托管 Profile

同机、同一操作系统用户的兼容 CLI 默认共享同一托管 Profile。不同平台可以同时执行，各自在新标签页工作。同一平台的检查和发布合计限一条命令，冲突者立即退出 `1`。**最后一条已加入的命令离开时会关闭整个 Profile，包括用户从桌面打开的标签页。**

- 从不同目录或虚拟环境运行时也按 provider、Profile 和 CLI 平台判定占用。不同 Profile 可并行运行同一平台。大陆版小红书与 Rednote 分开计数，Facebook 个人与 Page 也分开计数。两条 `facebook-page` 命令即使指定不同 `--page` 也互斥。
- 一条命令在 `--not-before` 等待时，另一平台仍能检查或发布。先离开者清理自己的页面和连接，其他命令继续编辑原页。退出后分别读取各自的退出码和结果。Instagram 与 Facebook Page 默认按命令生成带 UUID 的结果文件。显式传 `--result` 时，为每条命令分配不同路径；使用相同路径时后写入的结果覆盖先前的结果。
- 命令被强杀后，新命令在新页重新开始。若可能已经提交，先到平台核对作品。旧草稿和结果文件可用于核对。混用不支持共享的旧版 CLI 或独立工具时，由调用方串行访问同一 Profile。

### 调度侧责任

- Profile 即身份；传错 `profile_id` 会直接操作另一个账号。CLI 只校验“已登录”，不校验账号是否匹配，调度侧承担该风险。
- 收到 `0`：已发布，或 `--no-publish` 已准备完成；计数 +1 并记录时刻。
- 收到 `1`：确定未发布，可无条件重跑（冷却另议）；不要与登录失效或 429 混淆。
- 收到 `9`：已派发但未确认成功，**帖子可能已存在**；**禁止自动重发**，先到平台后台核对，已存在不要重发，不存在才可人工重试。
- 收到 `10`：
  - stderr **有** `publish_attempted=true`：点击后才落登录/验证页，帖子可能已存在；**先核对**，再排人工登录。
  - stderr **无**该行：点击前登录失效或运行前预检失败，**没有发布**；排人工登录，完成后可直接重跑。
- 收到 `11`（429）：退避重试；CLI 自身不等待。
- 托管模式不提供 CLI 登录。`--not-before` 不是节流手段：禁止用它制造发布间隔，节流/冷却/排程由调度 App 负责。
- Stop 失败只 warning；主操作成功仍返回 `0`，调度侧负责清理可能残留的 Profile。
- 跨机调度应在“桌面应用所在的那台机器”上远程执行 CLI，而不是把 CLI 指向远程 Local API / Launcher。

### 账号一致性风险

托管模式只验证平台页面“已登录”，**Profile 即身份**。本地原作品验证仍会核对历史作者证据；托管发布模式跳过账号一致性比对，CLI 仅打印一条 INFO 说明“账号一致性未校验”。请确保 `profile_id` 与目标账号匹配。

已知限制：命令级 `check` / 上传前登录检测已经是 provider-aware 文案；但部分平台在**上传过程中**遇到登录页、验证码或 2FA 时，uploader 内部错误仍可能提到 Multilogin。这是后续统一文案的已知遗留，不代表 AdsPower 模式需要 Multilogin。

### 安全

- API key / token 只从环境变量读取；不写入命令行、日志、异常文本、`repr` 或测试输出。文档示例只使用 `ADSPOWER_API_KEY="$KEY"`，不把 key 放进命令。
- `Authorization` 永不记录；`AdspowerClient.__repr__` 只输出 `token=<redacted>`。
- `ADSPOWER_API_BASE` 只允许 `http` / `https` + host + 可选端口；禁止 userinfo、path、query、fragment；末尾 `/` 归一化去掉；非法值退出 `2` 且不发出任何请求。
- 默认只连本机；禁止远程/跨机 base。`delete_cache`、`cdp_mask`、`launch_args` 等危险参数不由用户传入，由 provider 固定为安全值。
- 失败诊断脱敏：不含 API key，也不含真实账号或 Profile 名称。

### 明确不支持

- AdsPower 无 key 安装（关闭 API 安全校验）、V1 Local API、旧客户端 fallback / 双栈 / 运行时版本探测。
- AdsPower Firefox Profile；Playwright/CDP 只支持 Chromium。
- Docker、跨机、无桌面 Linux 部署。
- 通过 CLI 在托管模式登录；登录必须在对应桌面应用中完成。
- 在桌面应用中创建/修改 Profile、管理代理或导入/导出 Cookie。

### 与设计规格的差异

设计规格中的部分历史决策与最终实现不同，**实现以 uploader 的 golden 常量和对应测试为准**：

- TikTok：本地持久化 Profile 与托管分支均不注入 stealth。
- 托管分支不应用 `launch_kwargs` / `context_kwargs` / `init_script` / `context_setup`，非空选项继续记录既有忽略警告及启动日志，并使用 `account_file=None`；Profile 的浏览器指纹、代理、时区、定位权限和 UA 由 Profile 自身决定。
- Python 调用方使用 `local_browser_session(..., platform=..., account=...)` 取得本地持久化会话；通用 `browser_session` 必须传入 managed provider，缺少 provider 会在浏览器启动前明确报错。旧临时本地会话、TikTok Firefox 实现及 stealth 资源已移除。

## Multilogin X 模式

设置非空环境变量 `MLX_API_TOKEN` 后，`sau` 进入 Multilogin X（MLX）模式。CLI 通过本机 Multilogin Launcher（`https://launcher.mlx.yt:45001`）打开或加入指定 Profile，经 CDP 接管该 Profile 的浏览器，并复用其中的登录态；不再读写 `cookies/*.json`。

```bash
export MLX_API_TOKEN="<token>"

# check：0=已登录，10=需要人工登录
sau xiaohongshu check --folder-id "FOLDER_ID" --profile-id "PROFILE_ID"

# 上传：--account 被忽略；身份由 --profile-id 决定
sau xiaohongshu upload-video \
  --folder-id "FOLDER_ID" --profile-id "PROFILE_ID" \
  --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags tag1,tag2

# 显式有头（等同默认；保留给调度侧既有传参）
sau xiaohongshu check --folder-id "FOLDER_ID" --profile-id "PROFILE_ID" --headed
```

### MLX 专属参数与行为

- MLX 模式必须同时提供 `--folder-id` 与 `--profile-id`，否则按用法错误退出 `2`。
- `--account` 在 MLX 下**被忽略**：不读取、不校验、不参与日志/结果标签，也不决定 cookie 文件；身份由 `--profile-id` 决定。传了非空值只会出现在启动日志的 `ignored=` 列表里。
- `--headless` / `--headed` 直接映射到 MLX Profile 的有头/无头模式；未传时读取 LOCAL_CHROME_HEADLESS（缺省 False）；`--debug` 语义不变。
- `verify` / `delete` 仍是本地模式操作：即使设置了 `MLX_API_TOKEN` 也不会接管 Profile，因此始终必须提供 `--account`（缺少时退出 `2`）。
- token 只从环境变量读取，不写入命令行、日志或异常文本。Launcher 地址固定，不支持覆盖。
- **429 行为变更**：Launcher 返回 HTTP 429 时，退出码已由 `1` 改为 `11`；调度层应改为退避重试。

### MLX 中断后恢复

Start 响应丢失时，下一条命令使用自己的凭据查询同一 Profile 和 folder。若 Launcher 报告 `browser_running`，CLI 会核对 Mimic 的当前本机 CDP 实例，连接成功后另开页面。若 CLI 已核对过这次运行的实例，后来又观察到 `stopped`，即可确认先前启动已结束，允许一次新的 Start。Launcher 的状态记录只覆盖当前 Agent 会话。单独的 `stopped` 快照、变化的时间戳或空历史都无法确认上一条请求的结果，此时命令退出 `1`。 [Launcher 状态接口](https://documenter.getpostman.com/view/28533318/2s946h9Cv9#0ad3f26d-ae66-459c-8db6-7c5fa5a90198)

Stop 成功响应可能先于浏览器退出。后来者会等待旧实例消失，再按当前状态启动或加入。Stop 响应丢失时，即使桌面出现另一个活动实例，也要等到观察到空闲才能重启。等待超时的命令退出 `1`。若发布过程中进程被强杀，应保留已有结果，先核对平台作品再决定是否重跑。

### MLX 部署前提

1. CLI 与 Multilogin 桌面应用在**同一台 macOS/Windows 机器**上，桌面应用已启动，45001/45003 未被占用。
2. Profile 使用 **Mimic 内核**（Stealthfox 不支持 Playwright）。
3. Profile 已在 Multilogin 应用中人工登录目标平台，且没有待处理验证码或 2FA。
4. TikTok 现有选择器依赖 **English (US)** 页面；本地保留当前语言，托管沿用既有 English 登录探测入口；遇到不支持的布局会报告步骤错误，不自动修改 Profile 偏好。
5. 小红书的托管 Profile 界面语言必须为**中文**；CLI 不切换托管 Profile 的语言，中文选择器依赖中文界面。小红书本地模式保留当前浏览器语言。
6. TikTok 图文（`upload-note`）额外要求账号已被 TikTok Studio 的 Photos tab 灰度覆盖；未覆盖时在选文件前退出 `1`（本地与 MLX 相同）。

**MLX 明确不支持：**

- Docker launcher（CDP 端口默认未映射到宿主机）
- 跨机 launcher（官方只支持 `127.0.0.1`，不引导 SSH 隧道）
- Linux 无桌面部署
- 通过 CLI 在 MLX 中登录（登录必须在 Multilogin 应用中完成；TikTok 本地模式支持 `login`）

Launcher 不可达时请检查桌面应用、同机部署和 45001 端口。连接结果不明确时，先核实对应 Profile 的状态。

## AdsPower 模式

设置非空环境变量 `ADSPOWER_API_KEY` 后，`sau` 进入 AdsPower 模式。CLI 通过 AdsPower Local API（默认 `http://127.0.0.1:50325`）打开或加入 `user_id` 指定的 Chromium Profile，经 `data.ws.puppeteer` 的 CDP WebSocket 接管现有浏览器上下文，并复用 Profile 登录态；不再读写 `cookies/*.json`。

```bash
export ADSPOWER_API_KEY="$KEY"

# check：0=已登录，10=需要人工登录
sau xiaohongshu check --profile-id "PROFILE_ID"

# 上传：--account 被忽略；身份由 --profile-id 决定
sau xiaohongshu upload-video \
  --profile-id "PROFILE_ID" \
  --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags tag1,tag2

# 有头运行，便于人工处理验证码
sau xiaohongshu upload-video --headed \
  --profile-id "PROFILE_ID" \
  --file videos/demo.mp4 --title "示例标题"

# login 拒绝（退出 1）
sau xiaohongshu login --account creator

# 自定义 Local API 地址（仅改端口或使用官方地址时设置）
ADSPOWER_API_KEY="$KEY" ADSPOWER_API_BASE="http://127.0.0.1:50326" \
  sau xiaohongshu check --profile-id "PROFILE_ID"
```

### AdsPower 激活与 `ADSPOWER_API_BASE`

- 仅当 `ADSPOWER_API_KEY` strip 后非空时激活；`ADSPOWER_API_BASE` 不激活模式。
- 默认 `http://127.0.0.1:50325`；仅在改端口或使用 `http://local.adspower.net:50325` 等官方地址时设置。
- 合法值：`http` / `https`、必须有 host、端口可选；禁止 userinfo、path、query、fragment；末尾 `/` 归一化。非法值退出 `2`，且不发出任何请求；合法但连不上属于运行期 `1`。
- 禁止远程/跨机 base。

### AdsPower 参数

- `--profile-id` 必填；strip 后映射 AdsPower 的 `user_id`（V2 请求体字段为 `profile_id`）。
- `--folder-id` 注册但静默忽略；传值不报错、不告警。
- `--account` 在 AdsPower 下**被忽略**：不读取、不校验、不参与日志/结果标签，也不决定 cookie 文件；身份由 `--profile-id` 决定。传了非空值只会出现在启动日志的 `ignored=` 列表里。
- `--headless` 显式无头，V2 编码 `"1"`；`--headed` 为 False，V2 编码 `"0"`；未传时读取 LOCAL_CHROME_HEADLESS（缺省 False）；`--debug` 不传给 AdsPower。
- `login` 拒绝：`AdsPower 模式不支持 CLI 登录；请在 AdsPower 中登录 Profile {profile} 后重试。`
- 只支持 V2 Local API，不做 V1 fallback / 双栈 / 运行时版本探测；AdsPower 客户端请升级到最新 patch。旧客户端 404 会提示“AdsPower 版本过旧或 Local API 未开启”并退出 `1`。
- 启动请求固定 `last_opened_tabs=0`、`proxy_detection=0`、`delete_cache=0`、`cdp_mask=1`，避免继承历史页、触发 IP 检测页或清掉登录态。

### AdsPower 部署前提

1. **AdsPower 付费版**（Local API 仅付费版提供）。
2. AdsPower 桌面应用与 CLI 在**同一台 macOS/Windows 机器**上；应用已启动；Local API 已开启；`50325` 未被占用。
3. `ADSPOWER_API_KEY` 有效；请求带 `Authorization: Bearer`。
4. Profile 为 **Chromium 内核**；Firefox 不支持。
5. Profile 已**人工登录**目标平台，且没有待处理验证码/2FA；TikTok Profile 界面须为 **English (US)**，小红书 Profile 界面须为**中文**。
6. AdsPower 客户端升级到最新 patch（官方未给最低版本）。
7. `ADSPOWER_API_BASE` 默认 `http://127.0.0.1:50325`；仅在改端口或使用官方地址时设置。

### Bearer 与 key 重置

- 请求头为 `Authorization: Bearer <API Key>`（一个空格，key 无首尾空白）。API Key 在 AdsPower 客户端 **Automation → API** 页面生成/重置，不是登录密码。
- 重置后旧 key 立即失效；必须停止调度服务、替换环境变量并重启。
- 普通成员需要被授予 API 权限后才能生成/使用 key。
- key 不写入命令行、日志、异常文本或 `repr`；示例只写 `ADSPOWER_API_KEY="$KEY"`。

### 连不上时排查

依次检查：1) AdsPower 桌面应用是否启动；2) Local API 是否开启；3) `50325` 是否被占用；4) `ADSPOWER_API_BASE` 是否指向本机或官方地址。

### AdsPower 未知项（真实冒烟未执行）

以下是原 AdsPower 接入工单 09 的实测待核对项。共享托管会话的实机范围及记录见[共享 Profile 规格](../.scratch/managed-profile-sharing/spec.md)。

- 已运行 Profile 的 start 返回形状（成功 + 既有 ws，还是错误）。
- 重复 stop / 已停止 Profile 的真实 `code` / `msg`。
- 429 的真实形状（HTTP 429 还是 200 + 业务 `code`）与 `Retry-After`。
- `contexts` 是否恒为 1（含 `last_opened_tabs=0`）。
- 冷启动是否可能超过 30s；超时后不 stop 是否真的留下 Profile。
- V2 在旧客户端上的真实状态码（404 还是 200 + `code != 0`）。
- `/status` 是否要求鉴权、是否返回版本字段。
- V2 最低可用版本；`active` 在 Inactive / 多设备模式下的 `data` 形状。

## 小红书 CLI 子命令

```bash
sau xiaohongshu login --account creator
sau xiaohongshu check --account creator
sau xiaohongshu upload-video --account creator --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags 小红书,视频
sau xiaohongshu upload-note --account creator --images videos/demo1.png videos/demo2.png videos/demo.png --title "图文标题" --note "图文示例" --tags 图文,测试
```

Rednote 使用独立命令 `sau rednote`，持久化 Profile 与小红书隔离，详见 [Rednote 使用说明](./rednote.md)。旧的 `SAU_XHS_CREATOR_BASE_URL` 仍仅覆盖小红书命令的创作中心地址；Rednote 的配置名为 `SAU_REDNOTE_CREATOR_BASE_URL`。

小红书 login/check/视频/图文统一使用 `browser_profiles/<chrome|chromium>/xiaohongshu/<原始别名>/`。默认系统 Chrome、有头；已有 `LOCAL_CHROME_HEADLESS=True` 仍生效。显式 `--headed` / `--headless` 优先于配置；自定义 `LOCAL_CHROME_PATH` 优先于 `--local-browser` / `LOCAL_BROWSER`，无配置默认 Chrome。只要求选定来源，失败不切换。

仅 login 创建资料并引导扫码；check 与发布缺少 Profile 或明确未登录退出 `10`，网络/页面结构故障退出 `1`，验证保留 `reason=verification`。可在同别名重新登录另一真实账号，两种浏览器各自独立。旧 Cookie JSON 不再读取、写回或自动清理。重建使用 `sau xiaohongshu reset-profile --account creator --browser-kind chrome|chromium`。

本地保留当前语言和自然窗口，不设置 locale、Accept-Language、UA、stealth 或固定 viewport。托管保持原有 Profile 语言约定；仅 headless 默认来源采用新优先级，本地 browser/path 完全忽略。`--no-publish` 实际上传素材、编辑并等待 ARM 后停止，可能留下草稿；离线回归不代表真实平台验收。

### 小红书发布声明

`upload-video` / `upload-note` 支持两个独立的声明能力，**默认都不操作页面**，保持平台默认：

| 参数 | 作用 |
| --- | --- |
| `--original` | 开启「原创声明」开关 |
| `--no-original` | 关闭「原创声明」开关 |
| `--content-type fiction` | 虚构演绎，仅供娱乐 |
| `--content-type ai` | 笔记含AI合成内容 |
| `--content-type marketing` | 内容包含营销广告 |
| `--content-type self-shot` | 内容来源声明 → 自主拍摄（必须同时提供 `--shoot-location` 与 `--shoot-date`） |
| `--content-type repost` | 内容来源声明 → 来源转载（必须同时提供 `--repost-source`） |
| `--repost-source <媒体名称>` | 来源转载的媒体名称，仅与 `repost` 搭配 |
| `--shoot-location <地点>` | 自主拍摄的拍摄地点，仅与 `self-shot` 搭配 |
| `--shoot-date <YYYY-MM-DD>` | 自主拍摄的拍摄日期，仅与 `self-shot` 搭配 |
| `--no-publish` | 跑到 **ARM 就绪**（发布按钮存在、可点击且未被禁用/遮挡）后停止，不点击发布；用于回归测试与真机验收 |

```bash
# 开启原创声明
sau xiaohongshu upload-video --account creator \
  --file videos/demo.mp4 --title "原创视频" --original

# 声明 AI 合成内容
sau xiaohongshu upload-note --account creator \
  --images videos/demo1.png videos/demo2.png --title "图文标题" \
  --content-type ai

# 声明自主拍摄（地点和日期必填）
sau xiaohongshu upload-note --account creator \
  --images videos/demo1.png videos/demo2.png --title "图文标题" \
  --content-type self-shot \
  --shoot-location "北京" --shoot-date "2026-11-09"

# 声明来源转载并填写媒体名称
sau xiaohongshu upload-video --account creator \
  --file videos/demo.mp4 --title "转载视频" \
  --content-type repost --repost-source "某某媒体"
```

约束：

- 不传 `--original` / `--no-original` / `--content-type` 时，页面完全保持默认；
- `--original` 与 `--content-type repost` 互斥；
- `--no-original` 不能与 `self-shot` / `repost` 组合；
- `--repost-source` 只能与 `--content-type repost` 一起使用，且不能为空；
- `--shoot-location` / `--shoot-date` 只能与 `--content-type self-shot` 一起使用，两者都必填，日期格式为 `YYYY-MM-DD`；
- 以上组合错误会在启动浏览器前退出 `2`；
- **原创 `--original` 是硬闸**：点前读状态，未开则点击并确认须知；任一步失败退出 `1`（确定未发布）；
- `--no-original` 与内容类型声明失败只记 warning 并继续，不阻断发布；封面设置失败同样 warning 并回退到视频首帧；
- 加 `--no-publish` 时，内容、声明与定时设置完成后继续跑到 ARM 就绪（含 C1/C2/C3 与定时回读），不点击「发布」，也不等待 `--not-before`。

### 小红书元数据与定时校验

- 标题按小红书口径预检（UTF-16 加权：码元 >127 记 2，否则记 1，加总后除 2 向上取整），上限 **20**；显式超限在启动浏览器前退出 `1`，**绝不静默截断**；自动推导标题才会截到 ≤20 并记 warning。
- 正文上限 **1000**，话题锚点按 `#name` 计入；正文 + 话题输入完成后若出现长度错误节点，退出 `1`。
- `--schedule` 使用平台原生定时，时间格式 `YYYY-MM-DDTHH:MM:00Z`（UTC 绝对时刻），填写前按浏览器时区换算；窗口为绝对时刻的 `now + 2h < t <= now + 14d`，越界在启动浏览器前退出 `1`。
- 定时设置分三处回读：C1 点开关后查开关状态与时间输入存在；C2 写入并 `blur()` 后按分钟比对输入值；C3 在 ARM 就绪后、FIRE 前再证开关、值与「请求时间仍晚于本机现在」。任何不一致退出 `1`（确定未发布），不重试、不改成立即发布。
- 回读只证明客户端接受了设置，**不证明服务端受理**；2h/14d 平台边界与定时是否真正生效仍需真机验证。

### 小红书发布超时

小红书的发布预算已与 TikTok 对齐，整条流程使用 **15 分钟总预算**（共享 `PUBLISH_TIMEOUT_SECONDS = 15 * 60`）：

- 预算覆盖打开发布页、上传素材、填写标题/正文/标签、设置声明和封面、定时设置、ARM 就绪等待以及点击发布；
- **尚未点击发布**时超时（含 ARM 就绪窗/预算耗尽）：退出 `1`，确定没有发布任何内容；
- **已经点击发布**后超时：退出 `9`，发布结果未知，禁止自动重发；先到创作服务平台 → 笔记管理按标题和发布时间核对；
- 视频/图文的素材上传等待循环也使用同一个 deadline，不会无限挂起；
- FIRE 之后只按 **URL path** 判定是否离开发布页，并先做登录/人机验证页分类；**不扫描页面文案**、不区分「明确拒绝」与「限流提示」、不做重试；
- 15 秒观察窗内仍未离开 `/publish/publish`（且未命中登录/验证页）：退出 `9`；登录/验证页命中则退出 `10`，派发后带 stderr 行 `publish_attempted=true`；
- `--no-publish` 跑到 ARM 就绪即返回，不进入 FIRE / OBSERVE，不受发布观察窗影响（仍受总预算约束）。

## YouTube CLI 子命令

```bash
sau youtube login --account creator --headed
sau youtube check --account creator
sau youtube upload-video --account creator --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags tag1,tag2 --playlist "我的系列" --visibility public
sau youtube upload-video --account creator --file videos/demo.mp4 --title "示例视频"
```

YouTube 登录需要在浏览器中完成 Google 账号登录，不使用二维码。`--visibility` 可选 `public`、`unlisted` 或 `private`，`--playlist` 可选。当前只支持立即发布；`--schedule` 尚未实现，传入会退出 `2`。

YouTube 本地模式默认系统 Chrome、有头，已有 `LOCAL_CHROME_HEADLESS=True` 保留；显式 `--headed`/`--headless` 优先。`LOCAL_CHROME_PATH` 非空时优先使用并识别实际种类；否则 `--local-browser chrome|chromium` > `LOCAL_BROWSER` > `chrome`。只要求所选浏览器可用，失败不回退；完整 Chromium 可用 `uv run patchright install --no-shell chromium` 准备。

登录、检查和上传只使用 `browser_profiles/<chrome|chromium>/youtube/<原始别名>/`；别名可换号，两种浏览器可分别登录不同账号，上传使用当前频道。旧 JSON 不读取、导出或删除；`YT_PROXY` 对本地三项动作一致生效。保留当前界面语言和自然窗口，不注入 stealth/UA。只有 login 等待人工登录；其他动作缺 Profile、明确未登录/验证退出 `10`，网络、权限和页面故障退出 `1`。

```bash
sau youtube check --account creator --local-browser chromium --headless
sau youtube reset-profile --account creator --browser-kind chrome
```

重建精确清空指定种类，保留另一种类和历史结果，无需浏览器安装；占用或删除故障退出 `1`。上传保留封面、播放列表、可见性、人类化交互和 `--not-before`，没有新增 `--no-publish`。退出 `9` 或 `publish_attempted=true` 时先核查作品，禁止自动重发。MLX/AdsPower 仅采用相同 headless 优先级，继续忽略本地来源和代理，拒绝 CLI login/reset-profile。

## Facebook CLI 子命令

个人主页使用 `facebook`，Page 使用 `facebook-page`。默认不配置代理，浏览器按系统网络直连。需要代理时可在命令中传 `--proxy "代理地址"`，或设置 `SAU_FACEBOOK_PROXY`、`SAU_FACEBOOK_PAGE_PROXY`；传 `--proxy ""` 可忽略环境变量并直连。账号资料分别保存，首次使用先登录对应入口。

```powershell
sau facebook login --account creator
sau facebook check --account creator
sau facebook upload-video --account creator --file videos/demo.mp4 --title "视频标题" --desc "正文"
sau facebook upload-note --account creator --images videos/demo1.png --title "图文标题" --note "正文"
sau facebook-page login --account creator
sau facebook-page upload-note --account creator --page "我的 Page" --images videos/demo1.png --title "图文标题" --note "正文" --schedule "2026-10-21T02:30:00Z" --result .local/page-result.json
sau facebook-page upload-video --account creator --page "我的 Page" --file videos/demo.mp4 --title "视频标题" --desc "正文" --schedule "2026-10-21T02:30:00Z" --result .local/reel-result.json
```

Facebook 全部本地动作复用 `browser_profiles/<chrome|chromium>/facebook/<原始别名>`，与 `facebook-page` 隔离。默认系统 Chrome、有头；显式 `--local-browser chromium` 使用配套完整 Chromium，`LOCAL_CHROME_PATH` 优先于种类选择。显式 headed/headless > `LOCAL_CHROME_HEADLESS` > False，保留已有配置。启动失败不回退，不固定 viewport、不修改语言；只需安装所选来源。先 `sau facebook login --account creator --headed`，正常关闭后同配置 check；旧 JSON 不读取、导入或导出。别名可重新登录其他账号，两类浏览器可登录不同账号。缺少 Profile 或明确未登录退出 10，验证挑战保留 verification 提示；页面/权限/网络异常退出 1。重建用 `sau facebook reset-profile --account creator --browser-kind chrome`，无需浏览器 binary，只清空指定资料；重建不是重发旧任务的许可。

个人主页支持视频、图片及正文立即发布，目前未接入个人主页定时。Page 视频和图文支持 `--schedule "YYYY-MM-DDTHH:MM:00Z"`：UTC 绝对时刻，填写前按浏览器时区换算，要求至少提前 2 小时；不传即立即提交。当前实现核对页面日期/时间及原作品列表安排。`--page` 应填写准确 Page 名称。

Page 发布结果默认保存在 `.local/meta-results/`，也可用 `--result` 指定 JSON 文件。结果包含 `page_id`、`page_name`、`content_id`（视频处理中可能暂时没有）和状态。`scheduled` 表示平台已确认排期并核对原记录；`published` 表示图文已发布并核对原记录；立即发布视频在创建响应无错误且完成弹窗出现后返回 `processing`，表示平台已受理并正在处理，不能当成已经公开播放，后续作品编号由平台生成时再查询。`submission_unknown` 仅表示提交响应或完成证据没有确认，必须先查原记录，禁止直接重发。

### 查询与删除

```powershell
sau facebook verify --account creator --post-url "https://www.facebook.com/reel/作品编号/" --owner-id "作者数字ID" --expected-text "原作品正文"
sau facebook delete --account creator --post-url "原作品链接" --owner-id "作者数字ID" --expected-text "原作品正文"
sau facebook delete --account creator --post-url "原作品链接" --owner-id "作者数字ID" --expected-text "原作品正文" --from-trash --permanent
sau facebook-page verify --account creator --page "我的 Page" --page-id "Page数字ID" --content-id "内容编号" --expected-text "原作品正文" --scheduled
sau facebook-page delete --account creator --page "我的 Page" --page-id "Page数字ID" --content-id "内容编号" --expected-text "原作品正文" --scheduled --result .local/delete-result.json
```

Facebook 的 verify/delete 即使存在托管环境变量仍使用原始本地 `--account`、所选浏览器及代理。换号不改写历史作品证据，owner-id、原作品编号、作者链接和 expected-text 仍须同时匹配。

个人主页删除默认移至垃圾箱；加 `--permanent` 可永久删除，已经在垃圾箱中的作品再加 `--from-trash`。查询垃圾箱同样使用 `verify --from-trash`。`verify --deleted` 仅查询原编号是否已不在垃圾箱，返回 `absent_from_trash`，不凭“没找到”证明曾经永久删除。

Page 的 `--scheduled` 选择定时列表，删除会取消排期并永久移除。已发布作品不加该参数，当前平台执行移至垃圾箱，返回 `trashed`，30 天后由平台删除；CLI 尚未接入 Page 垃圾箱的提前永久删除。定时作品发布后编号可能变化，管理已发布作品请使用已发布列表中的编号。

所有删除动作先核对作者或 Page、原作品编号和正文。正文相同且无法唯一定位时明确失败。当前查询覆盖列表已加载的近期作品，不保证自动翻页检索全部历史作品。删除之后重新查询服务器列表；若结果未知，先查询，不自动重删。删除远端作品不会删除本地素材。

Facebook Page 的 login/check/视频/图文/verify/delete 和直接 uploader 已使用 `browser_profiles/<chrome|chromium>/facebook-page/<原始别名>/`。多个 `--page` 目标复用同一登录 Profile，与 `facebook` 隔离。仅 login 创建资料并等待人工登录；别名可以换号，历史结果不会因此改写，作品查询仍须匹配原 Page、内容编号和配文。

默认 Chrome 有头；显式 headed/headless > `LOCAL_CHROME_HEADLESS` > False。`LOCAL_CHROME_PATH` 优先并按实际产品种类选资料，否则 `--local-browser` > `LOCAL_BROWSER` > chrome；只要求选定来源，使用 no_viewport、保留当前语言和代理，失败不回退。旧 JSON 不再读写或自动迁移。缺少 Profile、未登录/验证退出 `10`，网络、权限和页面结构故障退出 `1`；提交后仍保留 `publish_attempted=true`，结果未知 `9` 不重发。verify/delete 在有托管凭据时仍用原始本地别名。重建：`sau facebook-page reset-profile --account creator --browser-kind chrome`。

该平台本次仅完成离线和受控浏览器验证；没有真实登录、发布或删除。当前未提供 `--no-publish`，示例上传会提交。

## Instagram 独立网页发布

Instagram 使用 Patchright 与项目专用持久化 Profile，不依赖 Facebook Page 或 Business Suite 绑定。默认系统 Chrome、有头（已有 `LOCAL_CHROME_HEADLESS=True` 保留，显式 headed/headless 优先），未配置代理时按系统网络直连；需要代理时可使用 `--proxy` 或 `SAU_INSTAGRAM_PROXY`。传 `--proxy ""` 可忽略环境变量并直连。首次使用按安装指南准备所选来源：系统 Chrome、显式 `--local-browser chromium` 或 `LOCAL_CHROME_PATH` 自定义路径；只检查所选来源，失败不回退。

```powershell
sau instagram login --account creator
sau instagram check --account creator
sau instagram upload-video --account creator --file videos/demo.mp4 --thumbnail videos/demo.png --title "视频标题" --desc "正文" --tags 生活,分享 --result .local/instagram-video.json
sau instagram upload-note --account creator --images videos/demo1.png --title "单图标题" --note "正文"
sau instagram upload-note --account creator --images videos/demo1.png videos/demo2.png --title "轮播标题" --note "正文" --result .local/instagram-carousel.json
```

视频/Reel 可用 `--thumbnail` 指定 JPG/JPEG/PNG 封面；省略时使用 Instagram 默认封面。指定图片后会检查主预览确实使用该图片，失败则停止提交。封面按当前视频画幅居中裁剪，图片边缘的重要文字应留出安全区域。图文发布不接受此参数。

`--no-publish`：素材上传、配文/话题、全部发布选项完成后，等待 Share 可点击（窗口 `min(60s, 剩余预算)`）即停止，不点击 Share、不等待 `--not-before`、不进入结果观察；成功退出 `0`，就绪超时退出 `1`。若使用 `--result`，结果文件状态为 `prepared`，只记录平台/标题/选项，不写 `content_id`/`post_id`/`post_url`。

`login` 在同一个持久化 context 中等待人工登录和必要验证，资料由浏览器保存在 `browser_profiles/<chrome|chromium>/instagram/<原始别名>/`；`check`、视频/图文和作品操作复用同目录。当前会话须有正向登录证据和有效 `ds_user_id`，别名不绑定真实账号，两种浏览器可以登录不同账号。正常命令不读取、导出、迁移或删除旧 Cookie JSON。只有 login 引导登录；其他动作缺少 Profile、明确未登录/验证退出 `10`，探测、网络、页面和必需字段故障退出 `1`。`check` 不代替发布权限检查。

所有本地入口和直接 uploader 统一采用 `LOCAL_CHROME_PATH` > 显式 `--local-browser` > `LOCAL_BROWSER` > Chrome；headless 为显式参数/布尔值 > `LOCAL_CHROME_HEADLESS` > False。注入的 session 由调用方关闭。`reset-profile --account creator --browser-kind chrome` 只清空指定种类且无需 binary；之后重新 login。

视频和图文回归都显式传 `--no-publish`：完成素材上传、编辑及 Share 就绪检查后停止，结果 `prepared`，不等待 not-before 或提交。它可能留下临时素材/草稿；本轮离线验证不代表真实账号验收。

视频输入为 MP4/MOV；照片为 JPG/JPEG/PNG/AVIF/HEIC/HEIF，实际解码与处理受平台限制。多个图片路径按传入顺序创建轮播；当前已实测单张照片及两张不同照片。标题、正文、标签合并为配文，合计最多 2200 字符。`--headless` 可切换无头运行，人工登录使用默认可见模式。

配文超过 2200 字符、视频与图片同时传入或都未传入、`--thumbnail` 与图片同传、替代文字条数或长度不合法、`--location` 为空等静态错误，都在启动浏览器或托管 Profile **之前**校验并退出 `2`。**注意**：配文超长此前退出 `1`（`ValueError`），现在改为退出 `2`（用法错误），与 TikTok、小红书对齐；调度层若按 `1` 判断需同步调整。

当前账号的照片/Reels 发布页及高级设置中没有定时入口，因此此独立网页实现只支持立即发布，不提供 `--schedule`；这不代表所有 Instagram 账号和客户端都没有定时能力。首次通知提示会自动选择稍后，视频上传时的 Reels 介绍会自动确认；没有提示则继续。登录、验证仍由用户在工程浏览器完成，未知弹窗或操作失败会明确报错。

创建入口兼容普通账号直接打开编辑器，以及 creator 的英文 `Create → Post`、中文“创建 → 帖子”子菜单。菜单按 SVG 的 `aria-label` 属性识别，不匹配页面中的可见 `Post` 文本；多个候选（包括中英文同时出现）会停止，菜单项或外层容器仍被禁用时不会派发点击。开启人类化时，由 Humanizer 完成滚动、移动与最终校验，不额外 hover；`HUMANIZE=0` 时先原生 hover 完成滚动和移入，再校验并原生点击。未派发的暂时失败在原预算内重试，可能已派发的点击不重试。此入口支持不扩大下述发布选项的真实账号验收范围。

### Instagram 发布选项

`upload-video` / `upload-note` 已接入四项网页发布选项，全部可选；**不传即完全不动页面默认**，也不会读取任何相关控件。

| 参数 | 命令 | 行为 |
|---|---|---|
| `--location TEXT` | `upload-video`、`upload-note` | 在 Instagram 的联想列表里按**忽略大小写与多余空白的精确匹配**选择；无精确匹配则退出 `1`、不发布，错误信息列出观察到的候选 |
| `--no-comments` | `upload-video`、`upload-note` | 请求关闭评论；入口不存在或不可用视为已满足（`default_off`，退出 `0`） |
| `--ai-generated` | `upload-video`、`upload-note` | 请求打开 AI 生成标识；入口不存在或不可用时退出 `1` |
| `--no-ai-generated` | `upload-video`、`upload-note` | 请求关闭 AI 生成标识；已是关闭或入口缺失时退出 `0` |
| `--alt-text TEXT` | 仅 `upload-note` | 每张图片一条替代文字，可重复；条数必须为 0 或正好等于 `--images` 张数，每条 1–1000 字符，不会截断 |

- `--ai-generated` 与 `--no-ai-generated` 互斥，同时传入由 argparse 退出 `2`；没有 `--aigc` 别名。
- 没有 `--comments`：评论只有“请求关闭”一个方向，想保持开启就不传 `--no-comments`。
- `--alt-text` 按 `--images` 顺序逐张填写；`upload-video --alt-text` 由 argparse 拒绝，退出 `2`。
- 选项动作与回读（set-then-readback）在点击 Share **之前**完成。任何一项未生效都退出 `1`、不点击发布，也不会用到 `9`；结果文件仍会记录每项状态和失败证据。

```powershell
sau instagram upload-note --account creator --images videos/demo1.png videos/demo2.png --title "轮播标题" --note "正文" --location "Shanghai, China" --no-comments --ai-generated --alt-text "第一张的替代文字" --alt-text "第二张的替代文字" --result .local/instagram-carousel.json
sau instagram upload-video --account creator --file videos/demo.mp4 --title "视频标题" --desc "正文" --no-comments --result .local/instagram-video.json
```

示例中的 `--location` 必须与 Instagram 当时给出的候选完全一致（忽略大小写与多余空白）；候选名称随账号和地区变化，建议先用 `--headed` 观察一次再固定。

其余网页选填能力仍保留页面默认，CLI 不读取也不修改：协作者、Stories、定时发布、配乐/曲库、选帧封面、用户标签、滤镜、隐藏点赞/播放数。上述四项之外的元数据仍不做发布后回读对账；已知平台会在个别情况下降级元数据（等同官方 API 的 `config_issue`），本轮不检测。

结果 JSON 新增顶层 `options` 对象，固定包含 `location`、`alt_text`、`comments`、`ai_generated` 四个键，每项为 `{requested, applied, status[, reason]}`：`status` 取 `not_requested` / `set` / `default_off` / `unsupported` / `mismatch`，`reason` 取 `entry_missing` / `account_ineligible`（无归因时省略）。`options` 是新增字段，旧消费方可直接忽略。

本地模式保持浏览器/Profile/站点原有语言，不设置 locale、请求头、固定 viewport 或最大化；托管模式不应用该设置，MLX / AdsPower 的 Instagram Profile 必须人工保持 **English** 界面。若 Instagram 账号自身把语言设为中文，页面仍可能按账号设置渲染中文——先用 `--headed` 观察一次；入口缺失时日志会打印 `html[lang]` 便于判断。

> 选择器证据只来自 **English 界面 + Personal 账号**；中文标签与专业账号均未验证，可能以 `entry_missing` 结束。本节不承诺中文或专业账号可用。
>
> 四项能力已在真实账号真发验收通过（2026-11-10，English UI、Personal 账号、本地 cookie 模式）：单条两图轮播同时设置地点、两条替代文字、关闭评论与 AI 标识，发布后回读一致（地点显示、`img[alt]` 逐张对应、无评论输入框、`AI content` 标签）；同日另以 `upload-video` 发布 Reel，验证 `--file` / `--thumbnail`（字节校验）/ `--desc` / `--tags` 与关闭评论、AI 标识，发布后 `#话题` 与 `AI content` 均正确。证据见 `.scratch/instagram-browser-parity/research/08-acceptance-evidence.md`。中文界面、专业账号与托管模式（MLX / AdsPower）仍未验收。

成功返回 `published`、`content_id`、`post_id`、`post_url` 和 `media_count`。Reels 可能先处于 `processing`，程序会等待本次提交的最终创建结果；超时后保留已观察状态。`submission_unknown` 表示已进入提交但未确认平台结果，`processing` 表示平台已受理且尚未取得最终作品，均不可直接重复上传。默认结果保存在 `.local/instagram-results/`；建议用 `--result` 指定路径。

### Instagram 发布超时

Instagram 的发布预算已与 TikTok 对齐，整条流程使用 **15 分钟总预算**（共享 `PUBLISH_TIMEOUT_SECONDS = 15 * 60`）：

- 预算覆盖打开首页、身份核验、上传素材、裁剪/编辑、填写配文、封面设置以及点击发布；
- **尚未点击发布**时超时：退出 `1`，确定没有发布任何内容；
- **已经点击发布**后超时：退出 `9`，发布结果未知，禁止自动重发；先到 Instagram 个人主页按配文和发布时间核对；
- 等待 Reels 最终创建响应也受同一 deadline 约束；仍为 `submission_unknown` 或 `processing` 时不能当成已发布，也不能直接重传；
- `--not-before` 的主动等待不计入预算，等待时长会从 deadline 中顺延；
- 封面、裁剪和配文等长等待会按剩余预算收紧，不会因单个等待超时后继续无限挂起。

如果已取得原作品链接：

```powershell
sau instagram verify --account creator --post-url "https://www.instagram.com/p/作品编号/" --expected-text "原作品中的准确文字" --result .local/instagram-verify.json
sau instagram delete --account creator --post-url "https://www.instagram.com/reel/作品编号/" --expected-text "原作品中的准确文字" --result .local/instagram-delete.json
```

`verify` / `delete` 在 MLX/AdsPower 环境下仍走本地路径，要求原始 `--account`，保留本地来源/headless/代理。接受 `/p/编号/`、`/reel/编号/` 以及带作者名的原作品链接。操作前读取当前会话用户并核对原作品作者、作品编号和正文，换号后仍拒绝删除其他作者的作品。`delete` 将作品移至 Instagram 的“最近删除”，最终返回 `deleted`；不实现批量删除或提前永久清空。“最近删除”的保留规则由平台决定，本地素材不会被删除。

结果未知且没有链接时，先在同一账号主页按配文、素材和发布时间查找原作品，复制原作品链接再运行 `verify`；找不到不能证明提交失败，也不要直接重发。删除出现 `deletion_unknown` 时同样先查原作品和“最近删除”，不要重复删除。失败结果会包含阶段/错误和本地证据目录；账号状态、截图及页面记录均放在 Git 忽略目录，不应提交到仓库。

## TikTok CLI 子命令（本地模式或托管浏览器模式）

TikTok 支持本地与两种托管子模式：

- **本地模式**（默认）：不设置托管凭据，使用 `browser_profiles/<chrome|chromium>/tiktok/<原始别名>` 的专用持久化 Profile；`--account` 必填，`--folder-id` / `--profile-id` 忽略。默认系统 Chrome、有头，保留当前语言与自然窗口尺寸。
- **Multilogin X 模式**：设置非空 `MLX_API_TOKEN`，并要求 `--folder-id` / `--profile-id`；Profile 界面须为 **English (US)**（小红书须为中文）。
- **AdsPower 模式**：设置非空 `ADSPOWER_API_KEY`，只要求 `--profile-id`；`--folder-id` 忽略；Profile 界面须为 **English (US)**（小红书须为中文）。

```bash
# 本地模式：先交互式登录一次（打开有头浏览器，登录后回终端按 Enter）
sau tiktok login --account creator --headed
sau tiktok check --account creator
sau tiktok upload-video --account creator --file videos/demo.mp4 --title "示例标题"
sau tiktok upload-note --account creator --images videos/demo1.png videos/demo2.png

# Multilogin 模式
export MLX_API_TOKEN="<token>"

sau tiktok check --folder-id "FOLDER_ID" --profile-id "PROFILE_ID"

# 视频：发布选项均可选，不传时保持页面默认
sau tiktok upload-video \
  --folder-id "FOLDER_ID" --profile-id "PROFILE_ID" \
  --file videos/demo.mp4 --title "示例标题" --tags tag1,tag2 \
  --location "London Eye" \
  --privacy public --no-comments --disable-reuse --aigc --your-brand \
  --schedule "2026-10-21T02:30:00Z" --thumbnail videos/demo.png

# 图文：1–35 张本地图片，按传入顺序展示，第 1 张即封面
sau tiktok upload-note \
  --folder-id "FOLDER_ID" --profile-id "PROFILE_ID" \
  --images videos/demo1.png videos/demo2.png \
  --title "图文标题" --note "图文正文" --tags 图文,测试 \
  --location "London Eye" \
  --privacy friends --no-comments --aigc

# AdsPower 模式（--folder-id 可省略）
unset MLX_API_TOKEN
export ADSPOWER_API_KEY="$KEY"

sau tiktok check --profile-id "PROFILE_ID"

sau tiktok upload-video \
  --profile-id "PROFILE_ID" \
  --file videos/demo.mp4 --title "示例标题" --tags tag1,tag2 \
  --privacy public --no-comments --schedule "2026-10-21T02:30:00Z"
```

- 支持 `login`、`check`、`upload-video`、`upload-note`、`reset-profile`；login/reset-profile 仅本地模式，托管登录仍在对应桌面应用完成。
- `LOCAL_CHROME_PATH` 非空时优先。否则显式 `--local-browser chrome|chromium` > `LOCAL_BROWSER` > `chrome`；Chrome 使用系统 channel，Chromium 使用项目固定 Patchright 配套完整 channel，两种模式均不改用 headless shell。只要求选定来源；失败不回退。
- `--headed`/`--headless` 或直接调用显式布尔值 > `LOCAL_CHROME_HEADLESS` > `False`；未传与显式 False 不同。已有 True 保留，示例默认 False。同一动作预检与业务共用同次配置和 session。
- 自定义路径必须先根据产品信息识别种类；无法识别/证据冲突退出 `1`。生效配置非法退出 `2`；托管完全忽略本地路径与种类配置，仅应用同一 headless 优先级。
- Profile 是唯一登录态来源，旧 JSON 不参与读写或自动清理。只有 login 引导人工登录；缺少 Profile、明确未登录或验证挑战退出 `10`，网络、页面结构、权限或浏览器故障退出 `1`。check 成功返回 `0`，目录存在本身不证明登录。
- 别名是管理名称，可登录不同真实账号；Chrome / Chromium 隔离，同种类改路径、版本或 headless 复用资料。跨种类不复制凭据；另一个种类未登录需单独 login。
- 本地模式持有 Profile 独占权直到业务和关闭结束；占用时立即失败，不抢占外部浏览器。正常关闭只关闭 persistent context；关闭故障独立告警，保持成功/未知/主异常，取消继续传播。重建不恢复任务或自动重发。
- TikTok 本地持久化路径不再注入 stealth、UA、请求头、语言参数或固定 viewport。现有选择器仍依赖支持的页面布局；自动化不会切换语言。
- 本地与托管共用 15 分钟发布预算；提交后登录/验证错误保留 `publish_attempted=true`。离线、隔离浏览器矩阵与四平台真实 login/no-publish 的证据分列于[最终验收记录](../.scratch/local-chrome-profile-implementation/research/20-final-validation.md)。此前 Cookie 路径验收不作为当前 Profile 的登录证据。
- `--no-publish`：上传、标题/正文/话题、全部发布选项、封面与 `--schedule` 完成后，等待发布按钮可点击（`post_video_button` / `Post` / `Schedule`，窗口 `min(60s, 剩余预算)`）即停止，不点击发布，也不等待 `--not-before`；成功退出 `0`，就绪超时退出 `1`。
- 未注册的子命令仍由 argparse 退出 `2`。

### 视频发布选项

`upload-video` 的原有位置参数和行为不变；以下选项均为可选，不传时不操作对应控件，保持页面默认：

| 参数 | 取值 | 含义 |
| --- | --- | --- |
| `--privacy` | `public` / `friends` / `followers` / `only-me` | 设置隐私级别；账号类型不匹配时回读失败并退出 `1` |
| `--location TEXT` | 文本 | 按完整地点名称选择：忽略大小写、去首尾空白并合并连续空白，按页面顺序点击第一个同名候选。成功须候选列表收起且控件读回所点名称；终端报告请求值、所点行名称与可见地址、最终值。无同名候选、入口缺失、列表未收起、读值为空或不符均退出 `1`；空白值退出 `2` |
| `--no-comments` | 开关 | 关闭评论 |
| `--disable-reuse` | 开关 | 关闭内容复用；同时影响 Duet、Stitch、Stickers 和 Story |
| `--aigc` / `--no-aigc` | 互斥 | 三态 AI 生成内容标识：省略时完全不读取、不点击、不展开 AI 入口，保留页面当前值；`--aigc` 须读到开：入口缺失、仍为关且可见禁用、或回读失败退出 `1`；`--no-aigc` 已关记 `default_off`，从开切关并读回记 `set`，入口确实缺失记 `default_off`/`entry_missing`（终值未知）并继续，可见但禁用且仍为开或无法读值退出 `1` |
| `--your-brand` | 开关 | 声明为自家品牌推广，会自动打开品牌声明总开关 |
| `--branded-content` | 开关 | 声明为付费品牌内容；不能与 `--privacy only-me` 同时使用（本地退出 `2`） |
| `--thumbnail` | 文件路径 | 自定义视频封面，语义不变 |

视频标题仍为必填；视频 caption 不新增长度校验。`--your-brand` 与 `--branded-content` 可同时使用；只请求其中一项时，另一项会被显式取消勾选。`--branded-content` 与 `--privacy friends` 允许组合，但仍以页面回读为准。

### 图文发布参数

| 参数 | 必填 | 含义 |
| --- | --- | --- |
| `--images` | 是 | 1–35 张本地图片，按传入顺序展示，第 1 张即封面 |
| `--title` | 否 | 页面 Title，≤90 字符；不传则不改动页面输入 |
| `--note` | 否 | Description，≤4000 字符（含 tags 展开后的文本）；不传且无 tags 时不改动页面输入 |
| `--notef` | 否 | 从本地 txt/md 读取 Description；与 `--note` 互斥 |
| `--tags` | 否 | 逗号分隔，规范化后追加到 Description；最多 50 个 |
| `--location` | 否 | 与视频相同：按完整名称选择地点，忽略大小写与空白，取首个同名行；省略时保留页面原值 |
| `--schedule` | 否 | 与视频相同的 `YYYY-MM-DDTHH:MM:00Z` |
| `--privacy` / `--no-comments` / `--aigc` / `--no-aigc` / `--your-brand` / `--branded-content` | 否 | 与视频相同语义；AI 三态与终端 `requested` / `applied` / `status` / `reason` / `continue` 诊断相同 |

`upload-note` 没有 `--disable-reuse`、`--thumbnail` 或 `--cover-index`：图片帖没有内容复用设置，第 1 张即封面。

### TikTok 限制与错误语义

- 图片仅支持 JPG / JPEG / PNG / WEBP（扩展名大小写不敏感），单张 ≤50 MB。
- 图片数量、格式、大小，以及 Title/Description/hashtag 超限、`--note`/`--notef` 冲突、`--branded-content --privacy only-me` 都在启动浏览器前校验失败并退出 `2`，不会截断后继续。
- 显式设置的发布选项会写入页面后回读；回读不一致退出 `1`，且不会点击发布。
- 帖子地点按三态处理：省略 `--location` 时不读取、不搜索、不点击地点控件，保留页面原值；显式请求时终端打印一行 `TikTok 帖子地点: option=location requested=... candidate=... address=... final=... status=... reason=... continue=...`。成功须候选列表收起且控件读回所点行的名称。无同名候选（含空列表或仅近似名称）记 `no_match`/`no_same_name_candidate`；入口缺失记 `unsupported`/`entry_missing`；只有页面明确提示资格限制才记 `account_ineligible`；列表未收起、读值为空或不符分别记 `list_not_collapsed`、`final_empty`、`final_mismatch`。以上失败均退出 `1`，发布按钮零点击。空白 `--location` 在启动浏览器前退出 `2`。
- AI 声明按三态报告：省略 `--aigc` / `--no-aigc` 时不读取、不点击 AI 开关，保留页面原值，结果记 `not_requested` 且不打印 AI 行；显式请求时终端打印一行 `TikTok AI 声明: option=aigc requested=... applied=... status=... reason=... continue=...`。`status=set` 和 `default_off` 可继续；`default_off` + `reason=entry_missing` 表示入口缺失、终值未知；`unsupported`、`mismatch` 或 `continue=no` 退出 `1`，发布按钮零点击。开关可见但禁用且仍为开、可见但无法读值（`reason=read_error`）或首次运行的 `Turn on` 对话框失败（`reason=dialog_error`）都按 `mismatch` 停止。
- 账号没有 Photos tab（未在图文灰度内）时，`upload-note` 在选文件前退出 `1`，不会把图片送进视频 input。
- 退出码 `9` 表示发布结果未知：发布点击已发出但未确认成功；**禁止自动重发**，先到 TikTok Studio → Content/Posts 按标题与发布时间核对。
- 不提供 `--cover-ms`、`--cover-index`、`--bgm`、`--json`，也不提供独立的 Duet / Stitch 开关；机器信号只有退出码与 stderr。

## 登录二维码说明

- 小红书和 Rednote 登录过程中，CLI 可能会输出二维码图片。
- 对普通用户来说，可以直接打开该图片扫码
- 对可操作本地文件的 agent 来说，不要只把图片路径告诉用户
- 这类二维码图片本身就是给用户扫码的，agent 应优先直接展示/发送本地图片给用户
- YouTube 当前不走这套本地二维码图片托管链路，登录按上面的平台说明处理即可
- 托管浏览器模式不提供 CLI 登录链路，也不会生成登录二维码；请在对应桌面应用（Multilogin / AdsPower）中登录 Profile，收到退出码 `10` 时转人工处理

## 定时发布

小红书、Rednote、TikTok 和 Facebook Page 的视频与图文支持原生 `--schedule`。使用 UTC 绝对时刻（`YYYY-MM-DDTHH:MM:00Z`），浏览器按其时区填写平台控件。TikTok 精确到 5 分钟。请将下方示例时间替换为目标平台允许的未来时刻。

```bash
sau xiaohongshu upload-video --account creator --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --schedule "2026-03-24T13:30:00Z"
sau xiaohongshu upload-note --account creator --images videos/demo1.png videos/demo2.png videos/demo.png --title "图文标题" --note "图文示例" --schedule "2026-03-24T13:30:00Z"
sau tiktok upload-video --account creator --file videos/demo.mp4 --title "示例标题" --schedule "2026-03-24T13:30:00Z"
sau tiktok upload-note --account creator --images videos/demo1.png videos/demo2.png --title "图文标题" --note "图文示例" --schedule "2026-03-24T13:30:00Z"
sau tiktok upload-video --folder-id "FOLDER_ID" --profile-id "PROFILE_ID" --file videos/demo.mp4 --title "示例标题" --schedule "2026-03-24T13:30:00Z"
sau tiktok upload-note --folder-id "FOLDER_ID" --profile-id "PROFILE_ID" --images videos/demo1.png videos/demo2.png --title "图文标题" --note "图文示例" --schedule "2026-03-24T13:30:00Z"
```

## 运行时参数

CLI 将 `debug` 和 `headless` 拆成了两个独立维度：

```bash
--debug
--headless
--headed
```

- `--debug`: 打开调试行为，例如失败时保留更多调试信息（默认关闭，唯一来源是该 flag）
- `--headless`: 无头模式运行
- `--headed`: 有头模式运行（等价默认，保留给既有调度侧显式传参）

七个平台未显式指定有头或无头模式时，读取 `LOCAL_CHROME_HEADLESS`，未配置则为 `False`。

补充：

- `--headless` 只在确实不需要界面时显式传；默认可见窗口更便于人工处理验证码和核对发布结果
- 正式浏览器平台的 CLI 和直接调用均读取 `conf.LOCAL_CHROME_HEADLESS`；显式参数优先，升级保留已有 True

## 视频上传参数

```bash
--file videos/demo.mp4
--title "示例标题"
--desc "示例简介"
--tags 运动,训练
```

封面与其他可选参数见目标平台的 `upload-video --help`。

## 图片笔记上传参数

```bash
--images videos/demo1.png videos/demo2.png videos/demo.png
--title "图文标题"
--note "图文内容"
--tags 图文,测试
```

图片笔记上传当前限制：

- 小红书：支持多张图片，正文 `--note` 可选，但 `--title` 建议始终显式传入
- TikTok：1–35 张，仅 JPG/JPEG/PNG/WEBP，单张 ≤50 MB；Title ≤90 字符，Description ≤4000 字符（含 tags），最多 50 个 hashtag；第 1 张即封面；本地与托管浏览器模式均支持
