# CLI 使用说明

项目现在提供一个统一的 CLI 入口 `sau`，当前主线已经接入：

- `douyin`
- `kuaishou`
- `xiaohongshu`
- `bilibili`
- `tencent`
- `baijiahao`
- `alipay`
- `weibo`
- `hupu`
- `tiktok`：本地 cookie 模式或托管浏览器模式（MLX / AdsPower）
- `youtube`
- `facebook`：Facebook 个人主页视频/图文立即发布、查询和删除
- `facebook-page`：Meta Business Suite 的 Facebook Page 视频/图文立即或定时发布
- `dayu`
- `xueqiu`：HTML/Markdown/TXT 长文、原位置配图及封面，默认实际发表，支持按原作品 ID 查询结果；见 [雪球使用说明](./xueqiu.md)，已实测正式 CLI 发表及后台核验
- `zhihu`：文章、视频和定时发布；见仓库内 [知乎 Skill](../skills/zhihu-upload/SKILL.md)

文章本地处理命令为 `sau article`，支持主题列表、环境准备和 Markdown/HTML 文件渲染，见 [文章文件与主题渲染](./article.md)。

面向 Agent 的 Skills 包括一个跨平台总入口和各已支持平台的独立入口，完整清单见 [README 的 AI Agent 区域](../README.md#ai-agent)。TikTok 使用 `sau tiktok`，默认走本地 cookie 模式；设置 `MLX_API_TOKEN` 或 `ADSPOWER_API_KEY` 后走[托管浏览器模式](#托管浏览器模式通用)（[Multilogin X 模式](#multilogin-x-模式) / [AdsPower 模式](#adspower-模式)）。见 [TikTok Skill](../skills/tiktok-upload/SKILL.md)。

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
sau douyin --help
sau kuaishou --help
sau xiaohongshu --help
sau bilibili --help
sau tencent --help
sau baijiahao --help
sau alipay --help
sau weibo --help
sau hupu --help
sau tiktok --help
sau youtube --help
sau facebook --help
sau facebook-page --help
sau dayu --help
sau xueqiu --help
sau zhihu --help
```

## 安装 patchright 浏览器

Windows 下推荐先指定镜像，再安装 Chromium：

```powershell
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright"; patchright install chromium
```

## 托管浏览器模式（通用）

设置任一托管模式凭据后，`sau` 进入托管浏览器模式：CLI 通过本机桌面应用启动指定 Profile，经 CDP 接管该 Profile 的浏览器上下文，并复用其中的登录态；不再读写 `cookies/*.json`。两个 provider 子模式是 [Multilogin X 模式](#multilogin-x-模式) 与 [AdsPower 模式](#adspower-模式)。

未设置任一凭据时仍为本地模式；`verify` / `delete` / `article` 在托管模式下仍然本地执行，不受 Profile 影响。

### 激活与优先级

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
| `--account` | `login` / `check` / `upload-*` 必填；`verify` / `delete` 必填 | 可选；仅日志/结果标签，无身份或 cookie 语义 | 可选；纯兼容占位，仅日志/结果标签 |
| `--folder-id` | 静默忽略 | 必填 | 注册但静默忽略；传值不报错、不告警 |
| `--profile-id` | 静默忽略 | 必填 | 必填；strip 后映射 AdsPower `user_id`（V2 请求体字段 `profile_id`） |
| 缺 `--profile-id` | 不适用 | 退出 `2` | 退出 `2` |
| 缺 `--folder-id` | 不适用 | 退出 `2` | 不适用 |
| `--headless` | 默认 True | 默认 True，传给 Launcher | 默认 True，V2 编码 `"1"` |
| `--headed` | False | False | False，V2 编码 `"0"` |
| `--debug` | 上传器调试行为 | 上传器调试行为 | 上传器调试行为；不传给 AdsPower |
| `login` | 允许 | 拒绝，退出 `1` | 拒绝，退出 `1` |
| `verify` / `delete` | 本地执行 | 本地执行 | 本地执行 |
| `check` 未登录 | `invalid` + 退出 `1` | 退出 `10` | 退出 `10` |
| Bilibili | 允许 | 拒绝，退出 `1` | 拒绝，退出 `1` |
| `article` | 本地工具 | 本地工具 | 本地工具 |

- `--profile-id` 只校验 strip 后非空，不猜格式；Profile 不存在、被占用或内核未就绪交给服务端，按运行失败退出 `1`。
- 托管模式下 `--account` 缺省取 `profile_id`，不会变成 cookie 文件名；它不参与登录或身份校验。
- 注册范围：除 `bilibili` 外，所有平台的 `check` 与 `upload-*` 都接受 `--profile-id` / `--folder-id`；`login`、`verify`、`delete`、`article` 不注册这组参数。
- 托管模式下 `sau <platform> login` 不带 flag 进入 `run()` 后拒绝并退出 `1`；显式带 `--profile-id` 时因 `login` 解析器未注册该 flag，argparse 退出 `2`。
- 不打印模式 banner；`check` 成功只输出 `valid`，保持 stdout 可解析。

### 退出码

| 码 | 含义 | 典型场景 |
| --- | --- | --- |
| `0` | 成功 | 上传已提交；check 已登录；Stop 失败但主操作成功（仅 warning） |
| `1` | 运行失败 | Local API / Launcher 不可达、key 或 token 无效、Profile 不存在/被占用、CDP 连不上、上传失败、网络错误、双模式冲突、login/平台拒绝 |
| `2` | 用法错误 | 缺 `--profile-id`、`ADSPOWER_API_BASE` 非法、本地缺 `--account`、未知子命令 |
| `9` | 发布结果未知 | 发布点击已发出但未观察到成功页；**禁止自动重发**，需先人工核验 |
| `10` | 需要登录 | 登录页、登录表单、验证码、2FA |
| `11` | 请求过于频繁（429） | Launcher 或 AdsPower Local API 返回 HTTP 429；调度层退避重试 |
| `130` | 用户中断 | `Ctrl-C`；Stop 仍会执行，不属于调度契约 |

- `11` 是 MLX 与 AdsPower 共用契约。**MLX 的 429 已由 `1` 改为 `11`**，这是本次改动中唯一改变 MLX 可观察行为的地方；调度层需要同步改为退避重试。
- CLI 不 sleep、不自动重试；429 由调度层处理。已成功的操作仅在 stop 阶段遇到 429 时只 warning，保持原退出码（通常 `0`）。
- HTTP 200 + 业务 `code` 表示限流的情况官方未定义，暂按 `1`；待真实 AdsPower 冒烟（ticket 09）确认后再扩展。

### 平台支持范围

两种托管模式使用同一张平台表：

| 平台 | 托管模式可用的 action | 说明 |
| --- | --- | --- |
| 抖音、快手、小红书 | `check`、`upload-video`、`upload-note` | |
| 视频号、百家号、支付宝生活号、微博、虎扑、YouTube | `check`、`upload-video` | |
| Facebook、Facebook Page、Instagram | `check`、`upload-video`、`upload-note` | `verify` / `delete` 仍为本地模式 |
| 大鱼号 | `check`、`upload-video`、`upload-article` | `verify` 仍为本地模式 |
| 知乎 | `check`、`upload-video`、`upload-article` | `verify` 仍为本地模式 |
| 雪球 | `check`、`upload-article` | `verify` 仍为本地模式 |
| TikTok | `check`、`upload-video`、`upload-note` | `login` 仅本地模式；图文依赖账号 Photos tab 灰度 |
| Bilibili | 不支持 | `biliup` 没有浏览器上下文；托管模式下退出 `1` |

共 16 个平台可走托管浏览器模式。`sau article` 是本地文件处理命令，不使用 Profile。`verify` / `delete` 始终本地执行，因此在托管模式下仍必须提供 `--account`（缺少时退出 `2`）。

### 调度侧责任

- 保证同一 Profile **不并发**；CLI 不加锁，也不做 active 预检。同一 Profile 的串行由调度 App 负责。
- Profile 即身份；传错 `profile_id` 会直接操作另一个账号。CLI 只校验“已登录”，不校验账号是否匹配，调度侧承担该风险。
- 收到退出码 `10` 时安排人工登录；托管模式不提供 CLI 登录。
- 收到退出码 `9`（发布结果未知）时**禁止自动重发**；先到平台后台按标题、素材与发布时间核对原作品，已存在不要重发，不存在才可人工重试。
- 收到退出码 `11`（429）时退避重试；CLI 自身不等待。
- 收到退出码 `1` 时按运行失败处理，不要与登录失效或 429 混淆。
- Stop 失败只 warning；主操作成功仍返回 `0`，调度侧负责清理可能残留的 Profile。
- 跨机调度应在“桌面应用所在的那台机器”上远程执行 CLI，而不是把 CLI 指向远程 Local API / Launcher。

### 账号一致性风险

托管模式只验证平台页面“已登录”，**Profile 即身份**。知乎、雪球、大鱼号和 Instagram 在本地模式下会比对 `.identity.json` / 用户 ID；托管模式下这些比对会跳过，CLI 仅打印一条 INFO 说明“账号一致性未校验”。请确保 `profile_id` 与目标账号匹配。

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
- Bilibili（`biliup` 子进程，无浏览器上下文）。
- 通过 CLI 在托管模式登录；登录必须在对应桌面应用中完成。
- 在桌面应用中创建/修改 Profile、管理代理或导入/导出 Cookie。

### 与设计规格的差异

设计规格中的部分历史决策与最终实现不同，**实现以 uploader 的 golden 常量和对应测试为准**：

- 视频号：视频上传的 `init_script` 实际为 `False`，图文上传仍为 `True`（`TENCENT_INIT_SCRIPT=False`、`TENCENT_NOTE_INIT_SCRIPT=True`）。
- TikTok：legacy 本地路径的 `set_init_script` 原本就未启用，`TIKTOK_INIT_SCRIPT=False`；托管分支同样不注入。
- 托管分支会静默忽略 `launch_kwargs` / `context_kwargs` / `init_script` / `context_setup`，并使用 `account_file=None`；Profile 的浏览器指纹、代理、时区、定位权限和 UA 由 Profile 自身决定。

## Multilogin X 模式

设置非空环境变量 `MLX_API_TOKEN` 后，`sau` 进入 Multilogin X（MLX）模式。CLI 通过本机 Multilogin Launcher（`https://launcher.mlx.yt:45001`）启动指定 Profile，经 CDP 接管该 Profile 的浏览器，并复用其中的登录态；不再读写 `cookies/*.json`。

```bash
export MLX_API_TOKEN="<token>"

# check：0=已登录，10=需要人工登录
sau douyin check --folder-id <folder_id> --profile-id <profile_id>

# 上传：--account 可省略，缺省用 profile_id 作为日志标签
sau douyin upload-video \
  --folder-id <folder_id> --profile-id <profile_id> \
  --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags tag1,tag2

# 有头运行，便于人工处理验证码
sau xiaohongshu check --folder-id <folder_id> --profile-id <profile_id> --headed
```

### MLX 专属参数与行为

- MLX 模式必须同时提供 `--folder-id` 与 `--profile-id`，否则按用法错误退出 `2`。
- `--account` 在 MLX 下可选，只是日志/结果标签；缺省值为 `profile_id`。它不参与登录或身份校验，也不决定 cookie 文件。
- `--headless` / `--headed` 直接映射到 MLX Profile 的有头/无头模式；`--debug` 语义不变。
- `verify` / `delete` 仍是本地模式操作：即使设置了 `MLX_API_TOKEN` 也不会接管 Profile，因此始终必须提供 `--account`（缺少时退出 `2`）。
- token 只从环境变量读取，不写入命令行、日志或异常文本。Launcher 地址固定，不支持覆盖。
- **429 行为变更**：Launcher 返回 HTTP 429 时，退出码已由 `1` 改为 `11`；调度层应改为退避重试。

### MLX 部署前提

1. CLI 与 Multilogin 桌面应用在**同一台 macOS/Windows 机器**上，桌面应用已启动，45001/45003 未被占用。
2. Profile 使用 **Mimic 内核**（Stealthfox 不支持 Playwright）。
3. Profile 已在 Multilogin 应用中人工登录目标平台，且没有待处理验证码或 2FA。
4. TikTok 的 MLX 模式额外要求 Profile 界面语言为 **English (US)**；MLX 模式会跳过 CLI 内的语言切换。本地模式会自动切换页面语言。
5. TikTok 图文（`upload-note`）额外要求账号已被 TikTok Studio 的 Photos tab 灰度覆盖；未覆盖时在选文件前退出 `1`（本地与 MLX 相同）。

**MLX 明确不支持：**

- Docker launcher（CDP 端口默认未映射到宿主机）
- 跨机 launcher（官方只支持 `127.0.0.1`，不引导 SSH 隧道）
- Linux 无桌面部署
- Bilibili
- 通过 CLI 在 MLX 中登录（登录必须在 Multilogin 应用中完成；TikTok 本地模式支持 `login`）

启动前 CLI 会探活 `GET /api/v1/version`；失败退出 `1`，并提示确认桌面应用、同机部署和 45001 端口。Start 成功但 CDP 连接连续 3 次失败时，错误信息会附带 Docker launcher 提示，并在退出前停止本次启动的 Profile。

## AdsPower 模式

设置非空环境变量 `ADSPOWER_API_KEY` 后，`sau` 进入 AdsPower 模式。CLI 通过 AdsPower Local API（默认 `http://127.0.0.1:50325`）启动 `user_id` 指定的 Chromium Profile，经 `data.ws.puppeteer` 的 CDP WebSocket 接管现有浏览器上下文，并复用 Profile 登录态；不再读写 `cookies/*.json`。

```bash
export ADSPOWER_API_KEY="$KEY"

# check：0=已登录，10=需要人工登录
sau douyin check --profile-id <profile_id>

# 上传：--account 可省略，缺省用 profile_id 作为日志标签
sau douyin upload-video \
  --profile-id <profile_id> \
  --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags tag1,tag2

# 有头运行，便于人工处理验证码
sau douyin upload-video --headed \
  --profile-id <profile_id> \
  --file videos/demo.mp4 --title "示例标题"

# login 拒绝（退出 1）
sau douyin login --account creator

# Bilibili 拒绝（退出 1）
sau bilibili check --account creator

# 自定义 Local API 地址（仅改端口或使用官方地址时设置）
ADSPOWER_API_KEY="$KEY" ADSPOWER_API_BASE="http://127.0.0.1:50326" \
  sau douyin check --profile-id <profile_id>
```

### AdsPower 激活与 `ADSPOWER_API_BASE`

- 仅当 `ADSPOWER_API_KEY` strip 后非空时激活；`ADSPOWER_API_BASE` 不激活模式。
- 默认 `http://127.0.0.1:50325`；仅在改端口或使用 `http://local.adspower.net:50325` 等官方地址时设置。
- 合法值：`http` / `https`、必须有 host、端口可选；禁止 userinfo、path、query、fragment；末尾 `/` 归一化。非法值退出 `2`，且不发出任何请求；合法但连不上属于运行期 `1`。
- 禁止远程/跨机 base。

### AdsPower 参数

- `--profile-id` 必填；strip 后映射 AdsPower 的 `user_id`（V2 请求体字段为 `profile_id`）。
- `--folder-id` 注册但静默忽略；传值不报错、不告警。
- `--account` 可选，仅日志/结果标签，缺省为 `profile_id`；它不会决定 cookie 文件。
- `--headless` 默认 True，V2 编码 `"1"`；`--headed` 为 False，V2 编码 `"0"`；`--debug` 不传给 AdsPower。
- `login` 拒绝：`AdsPower 模式不支持 CLI 登录；请在 AdsPower 中登录 Profile {profile} 后重试。`
- 只支持 V2 Local API，不做 V1 fallback / 双栈 / 运行时版本探测；AdsPower 客户端请升级到最新 patch。旧客户端 404 会提示“AdsPower 版本过旧或 Local API 未开启”并退出 `1`。
- 启动请求固定 `last_opened_tabs=0`、`proxy_detection=0`、`delete_cache=0`、`cdp_mask=1`，避免继承历史页、触发 IP 检测页或清掉登录态。

### AdsPower 部署前提

1. **AdsPower 付费版**（Local API 仅付费版提供）。
2. AdsPower 桌面应用与 CLI 在**同一台 macOS/Windows 机器**上；应用已启动；Local API 已开启；`50325` 未被占用。
3. `ADSPOWER_API_KEY` 有效；请求带 `Authorization: Bearer`。
4. Profile 为 **Chromium 内核**；Firefox 不支持。
5. Profile 已**人工登录**目标平台，且没有待处理验证码/2FA；TikTok Profile 界面须为 **English (US)**。
6. AdsPower 客户端升级到最新 patch（官方未给最低版本）。
7. `ADSPOWER_API_BASE` 默认 `http://127.0.0.1:50325`；仅在改端口或使用官方地址时设置。
8. 同一 Profile **串行使用**；CLI 不加锁、不做 active 预检。

### Bearer 与 key 重置

- 请求头为 `Authorization: Bearer <API Key>`（一个空格，key 无首尾空白）。API Key 在 AdsPower 客户端 **Automation → API** 页面生成/重置，不是登录密码。
- 重置后旧 key 立即失效；必须停止调度服务、替换环境变量并重启。
- 普通成员需要被授予 API 权限后才能生成/使用 key。
- key 不写入命令行、日志、异常文本或 `repr`；示例只写 `ADSPOWER_API_KEY="$KEY"`。

### 连不上时排查

依次检查：1) AdsPower 桌面应用是否启动；2) Local API 是否开启；3) `50325` 是否被占用；4) `ADSPOWER_API_BASE` 是否指向本机或官方地址。

### AdsPower 未知项（真实冒烟未执行）

本机未安装 AdsPower，**真实 AdsPower 冒烟未执行（ticket 09）**。以下行为只有离线测试和设计依据，仍需真实设备验证：

- 已运行 Profile 的 start 返回形状（成功 + 既有 ws，还是错误）。
- 重复 stop / 已停止 Profile 的真实 `code` / `msg`。
- 429 的真实形状（HTTP 429 还是 200 + 业务 `code`）与 `Retry-After`。
- `contexts` 是否恒为 1（含 `last_opened_tabs=0`）。
- 冷启动是否可能超过 30s；超时后不 stop 是否真的留下 Profile。
- V2 在旧客户端上的真实状态码（404 还是 200 + `code != 0`）。
- `/status` 是否要求鉴权、是否返回版本字段。
- V2 最低可用版本；`active` 在 Inactive / 多设备模式下的 `data` 形状。

## 大鱼号 CLI 子命令

登录、分类和来源选项见 [视频发布](./dayu.md)；正文文件、格式和图片路径见 [图文发布](./dayu-article.md)。Markdown 主题及独立本地渲染命令见 [文章文件与主题渲染](./article.md)。

```powershell
sau dayu upload-article --account creator --title "如何阅读作品数据面板" --content-file examples/dayu_article.html --source "无需标注" --cover-indices 1

# Markdown 首次使用需要 Node.js 22+，先安装渲染依赖
sau article setup
sau dayu upload-article --account creator --title "如何阅读作品数据面板" --content-file examples/article.md --theme modern --source "无需标注" --cover-indices 1
```

Markdown 默认主题为 `default`，可选 `default/grace/simple/modern/plain`；HTML/TXT 不使用 `--theme`。主题会自动转换为大鱼号兼容排版，保留文字颜色、背景和近似字号，圆角、字体和间距等效果可能与本地预览不同。确认发表前会检查服务端预览；平台确认最终发表后即返回成功，不等待审核。

视频和文章均支持 `--schedule "YYYY-MM-DD HH:MM"`：北京时间 2 小时后至 7 天内，分钟为 5 的倍数。平台确认原作品和定时安排后即成功，不等待到点。使用结果文件执行 `sau dayu verify --account creator --result "本次结果文件.json"` 可只读核对原作品与时间，勿重新上传。Agent 可使用仓库的 [大鱼号 Skill](../skills/dayu-upload/SKILL.md)。

## 知乎 CLI 子命令

知乎提供文章和视频发布。文章使用 HTML/Markdown/TXT 原稿，正文图片按原稿位置导入；视频文件须大于 100KB（102400 字节）、最大 20GB、最长 4 小时。

```powershell
sau zhihu login --account creator
sau zhihu check --account creator
sau zhihu upload-article --account creator --title "知乎文章标题" --content-file examples/article.md
sau zhihu upload-video --account creator --file videos/demo.mp4 --title "知乎视频标题" --desc "视频简介" --originality original --category "教育" --video-mark "含 AI 生成内容"
# 上传素材后导出该表单的全部领域和视频标记；不发表，但可能留下草稿。
sau zhihu upload-video --account creator --file videos/demo.mp4 --title "知乎视频标题" --originality original --show-options
```

`--account` 是本地会话别名，与知乎展示名无须相同。登录命令读取页面当前身份并保存本地会话。

`--category` 与 `--video-mark` 使用 CLI 可选值，完整领域清单见 `sau zhihu upload-video --help`。省略时在交互终端按编号选择；非交互调用必须指定。程序提交前仍核对实时菜单，`--show-options` 将候选写入结果 JSON 的 `options`。

`--originality` 可选 `original`（原创）、`reprint`（转载）。`--video-mark` 可选 `内容无需标注`、`含 AI 生成内容`、`含虚构演绎内容`、`内容含营销信息`、`内容为转载`、`个人观点仅供参考`，须按实际内容选择。视频标题 5–50 字，简介最多 300 字；暂不支持自动选择话题、自定义封面、专栏和内容来源。

文章标题最多 100 字。图片写在原稿里，例如 `![配图](images/1.png)`，相对路径从原稿目录解析。提交前核对文字、图片位置、基本格式和链接；恢复非空草稿时停止以保护原文。Markdown 首次使用先执行 `sau article setup`。暂不支持自定义主题 CSS、手动封面、专栏收录和文档导入。

文章和视频加 `--prepare-only` 可只填写检查，平台仍可能自动保存草稿。`published` 表示平台确认发表；结果为 `submission_unknown` 时先检查创作中心原作品，勿重复上传。已有链接时用 `sau zhihu verify --account creator --result "本次结果.json"` 核对，视频详情地址可为 `/pin/<作品ID>`。

`--schedule "YYYY-MM-DD HH:MM"` 为实验性选项，按北京时间限制在 30 分钟后至 48 小时内，尚不保证完整排期流程可用。更多用法见 [知乎 Skill](../skills/zhihu-upload/SKILL.md)。

## 抖音 CLI 子命令

```bash
sau douyin login --account <account_name>
sau douyin login --account <account_name> --headless
sau douyin check --account <account_name>
sau douyin upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags 运动,训练
sau douyin upload-note --account <account_name> --images videos/1.png videos/2.png --title "图文标题" --note "图文示例" --tags 图文,测试
```

抖音短信验证码补充说明：

- 视频发布过程中如果触发短信二次验证，CLI 会优先读取项目根目录下的 `verify_code.txt`
- 如果未找到 `verify_code.txt`，并且当前命令是在交互式终端中手动运行，CLI 会直接在终端提示输入验证码
- 对 agent、自动任务、远程桥接这类场景，仍然可以继续用写入 `verify_code.txt` 的方式喂验证码
- 验证通过后，程序会自动清理 `verify_code.txt`

## 快手 CLI 子命令

```bash
sau kuaishou login --account <account_name>
sau kuaishou check --account <account_name>
sau kuaishou upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags 运动,训练
sau kuaishou upload-note --account <account_name> --images videos/1.png videos/2.png videos/3.png --title "图文标题" --note "图文示例" --tags 图文,测试
```

## 小红书 CLI 子命令

```bash
sau xiaohongshu login --account <account_name>
sau xiaohongshu check --account <account_name>
sau xiaohongshu upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags 小红书,视频
sau xiaohongshu upload-note --account <account_name> --images videos/1.png videos/2.png videos/3.png --title "图文标题" --note "图文示例" --tags 图文,测试
```

海外环境如果无法登录默认创作者后台，可以通过环境变量切换到 RedNote 域名。该设置同时作用于登录、cookie 校验、视频发布和图文发布：

```bash
SAU_XHS_CREATOR_BASE_URL=https://creator.rednote.com sau xiaohongshu login --account <account_name>
```

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
| `--no-publish` | 填完内容并设置声明后停止，不点击发布，用于回归测试 |

```bash
# 开启原创声明
sau xiaohongshu upload-video --account <account_name> \
  --file videos/demo.mp4 --title "原创视频" --original

# 声明 AI 合成内容
sau xiaohongshu upload-note --account <account_name> \
  --images videos/1.png videos/2.png --title "图文标题" \
  --content-type ai

# 声明自主拍摄（地点和日期必填）
sau xiaohongshu upload-note --account <account_name> \
  --images videos/1.png videos/2.png --title "图文标题" \
  --content-type self-shot \
  --shoot-location "北京" --shoot-date "2026-11-09"

# 声明来源转载并填写媒体名称
sau xiaohongshu upload-video --account <account_name> \
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
- 声明设置失败只记 warning 并继续发布，不阻断上传；
- 加 `--no-publish` 时，内容与声明设置完成后直接结束，不点击「发布」，适合有头回归验证。

### 小红书发布超时

小红书的发布预算已与 TikTok 对齐，整条流程使用 **15 分钟总预算**（`XHS_PUBLISH_TIMEOUT_SECONDS = 15 * 60`）：

- 预算覆盖打开发布页、上传素材、填写标题/正文/标签、设置声明和封面、定时设置以及点击发布；
- **尚未点击发布**时超时：退出 `1`，确定没有发布任何内容；
- **已经点击发布**后超时：退出 `9`，发布结果未知，禁止自动重发；先到创作服务平台 → 笔记管理按标题和发布时间核对；
- 视频/图文的素材上传等待循环也使用同一个 deadline，不会无限挂起；
- `--no-publish` 在发布循环之前返回，不受该超时影响。

## Bilibili CLI 子命令

```bash
sau bilibili login --account <account_name>
sau bilibili check --account <account_name>
sau bilibili upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tid 249 --tags 足球,测试 --thumbnail covers/demo.png
```

补充说明：

- `creator` 之类的名字只是示例值，真正传的是用户自定义的 `account_name`
- 一个 `account_name` 对应一个账号文件，可以准备多个账号并发使用
- 浏览器平台统一元数据约定：
- 视频使用 `title + desc + tags`
- 抖音、快手、小红书的图片笔记使用 `title + note + tags`
- 大鱼号文章使用 `title + content-file + source`，正文从 UTF-8 文件读取
- `sau bilibili ...` 会自动准备 `biliup`
- 如果本地没有 `biliup`，第一次运行会自动下载
- 如果上游 GitHub Release 有更新，运行时会先自动更新
- `sau bilibili login --account <name>` 建议由用户自己在本地真实终端里执行；如果终端里的二维码显示不完整，可直接打开当前目录下的 `qrcode.png` 扫码

## 视频号 CLI 子命令

```bash
sau tencent login --account <account_name>
sau tencent check --account <account_name>
sau tencent upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags 视频号,测试
```

视频号支持定时发布、草稿、合集和双比例封面：

```bash
sau tencent upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --schedule "2026-03-24 21:30" --thumbnail-landscape covers/landscape.png --thumbnail-portrait covers/portrait.png --collection "我的合集"
sau tencent upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --draft
```

视频号登录和上传依赖浏览器中的登录态。无头模式下如果需要扫码，CLI 会生成临时二维码；需要人工查看页面时可以加 `--headed`。

## 百家号 CLI 子命令

```bash
sau baijiahao login --account <account_name>
sau baijiahao check --account <account_name>
sau baijiahao upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags 百家号,测试
```

百家号当前支持登录、账号检查和视频上传；支持 `--thumbnail` 与 `--collection`，暂不支持 `--schedule`。上传前需要先完成百度账号登录并保存账号文件。

## 支付宝生活号 CLI 子命令

```bash
sau alipay login --account <account_name>
sau alipay check --account <account_name>
sau alipay upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags 生活号,测试
```

支付宝生活号当前支持登录、账号检查和视频上传；支持 `--thumbnail` 与 `--collection`，暂不支持图文上传和 `--schedule`。首次使用前需要在支付宝内容创作后台完成登录，并确认账号已开通生活号内容创作权限。

## YouTube CLI 子命令

```bash
sau youtube login --account <account_name>
sau youtube check --account <account_name>
sau youtube upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags tag1,tag2 --playlist "我的系列" --visibility public
sau youtube upload-video --account <account_name> --file videos/demo.mp4 --title "定时视频" --schedule "2026-10-21 10:30"
```

YouTube 登录需要在浏览器中完成 Google 账号登录，不使用二维码。`--visibility` 可选 `public`、`unlisted` 或 `private`，`--playlist` 可选；传 `--schedule` 时使用 YouTube Studio 的 Schedule 状态并核对日期/时间控件，不传则立即按 `--visibility` 发布。

## Facebook CLI 子命令

个人主页使用 `facebook`，Page 使用 `facebook-page`。默认不配置代理，浏览器按系统网络直连。需要代理时可在命令中传 `--proxy "代理地址"`，或设置 `SAU_FACEBOOK_PROXY`、`SAU_FACEBOOK_PAGE_PROXY`；传 `--proxy ""` 可忽略环境变量并直连。账号文件分别保存，首次使用先登录对应入口。

```powershell
sau facebook login --account creator
sau facebook check --account creator
sau facebook upload-video --account creator --file videos/demo.mp4 --title "视频标题" --desc "正文"
sau facebook upload-note --account creator --images images/1.jpg --title "图文标题" --note "正文"
sau facebook-page login --account creator
sau facebook-page upload-note --account creator --page "我的 Page" --images images/1.jpg --title "图文标题" --note "正文" --schedule "2026-10-21 10:30" --result .local/page-result.json
sau facebook-page upload-video --account creator --page "我的 Page" --file videos/demo.mp4 --title "视频标题" --desc "正文" --schedule "2026-10-21 10:30" --result .local/reel-result.json
```

个人主页支持视频、图片及正文立即发布，目前未接入个人主页定时。Page 视频和图文支持 `--schedule "YYYY-MM-DD HH:MM"`，使用北京时间，要求至少提前 2 小时；不传即立即提交。当前实现核对 `Asia/Shanghai` 浏览器时区、页面日期/时间及原作品列表安排。`--page` 应填写准确 Page 名称。

Page 发布结果默认保存在 `.local/meta-results/`，也可用 `--result` 指定 JSON 文件。结果包含 `page_id`、`page_name`、`content_id`（视频处理中可能暂时没有）和状态。`scheduled` 表示平台已确认排期并核对原记录；`published` 表示图文已发布并核对原记录；立即发布视频在创建响应无错误且完成弹窗出现后返回 `processing`，表示平台已受理并正在处理，不能当成已经公开播放，后续作品编号由平台生成时再查询。`submission_unknown` 仅表示提交响应或完成证据没有确认，必须先查原记录，禁止直接重发。

### 查询与删除

```powershell
sau facebook verify --account creator --post-url "https://www.facebook.com/reel/作品编号/" --owner-id "作者数字ID" --expected-text "原作品正文"
sau facebook delete --account creator --post-url "原作品链接" --owner-id "作者数字ID" --expected-text "原作品正文"
sau facebook delete --account creator --post-url "原作品链接" --owner-id "作者数字ID" --expected-text "原作品正文" --from-trash --permanent
sau facebook-page verify --account creator --page "我的 Page" --page-id "Page数字ID" --content-id "内容编号" --expected-text "原作品正文" --scheduled
sau facebook-page delete --account creator --page "我的 Page" --page-id "Page数字ID" --content-id "内容编号" --expected-text "原作品正文" --scheduled --result .local/delete-result.json
```

个人主页删除默认移至垃圾箱；加 `--permanent` 可永久删除，已经在垃圾箱中的作品再加 `--from-trash`。查询垃圾箱同样使用 `verify --from-trash`。`verify --deleted` 仅查询原编号是否已不在垃圾箱，返回 `absent_from_trash`，不凭“没找到”证明曾经永久删除。

Page 的 `--scheduled` 选择定时列表，删除会取消排期并永久移除。已发布作品不加该参数，当前平台执行移至垃圾箱，返回 `trashed`，30 天后由平台删除；CLI 尚未接入 Page 垃圾箱的提前永久删除。定时作品发布后编号可能变化，管理已发布作品请使用已发布列表中的编号。

所有删除动作先核对作者或 Page、原作品编号和正文。正文相同且无法唯一定位时明确失败。当前查询覆盖列表已加载的近期作品，不保证自动翻页检索全部历史作品。删除之后重新查询服务器列表；若结果未知，先查询，不自动重删。删除远端作品不会删除本地素材。

## Instagram 独立网页发布

Instagram 使用工程的 Patchright Chrome，不依赖 Facebook Page 或 Business Suite 绑定。默认可见浏览器，未配置代理时按系统网络直连；需要代理时可使用 `--proxy` 或 `SAU_INSTAGRAM_PROXY`。传 `--proxy ""` 可忽略环境变量并直连。首次使用先安装依赖和 Chrome，按本文的项目环境准备步骤执行。

```powershell
sau instagram login --account creator
sau instagram check --account creator
sau instagram upload-video --account creator --file videos/demo.mp4 --thumbnail covers/demo.png --title "视频标题" --desc "正文" --tags 生活,分享 --result .local/instagram-video.json
sau instagram upload-note --account creator --images images/1.jpg --title "单图标题" --note "正文"
sau instagram upload-note --account creator --images images/1.jpg images/2.jpg --title "轮播标题" --note "正文" --result .local/instagram-carousel.json
```

视频/Reel 可用 `--thumbnail` 指定 JPG/JPEG/PNG 封面；省略时使用 Instagram 默认封面。指定图片后会检查主预览确实使用该图片，失败则停止提交。封面按当前视频画幅居中裁剪，图片边缘的重要文字应留出安全区域。图文发布不接受此参数。

`login` 在工程浏览器中等待人工登录和必要验证，将状态保存为 `cookies/instagram_creator.json`，并通过新会话验证。`check` 检查该账号的登录状态和用户绑定，不能代替发布权限检查；网络或未知页面超时会报告错误，不会直接视为 Cookie 失效。

视频输入为 MP4/MOV；照片为 JPG/JPEG/PNG/AVIF/HEIC/HEIF，实际解码与处理受平台限制。多个图片路径按传入顺序创建轮播；当前已实测单张照片及两张不同照片。标题、正文、标签合并为配文，合计最多 2200 字符。`--headless` 可切换无头运行，人工登录使用默认可见模式。

当前账号的照片/Reels 发布页及高级设置中没有定时入口，因此此独立网页实现只支持立即发布，不提供 `--schedule`；这不代表所有 Instagram 账号和客户端都没有定时能力。页面还提供地点、协作者、AI 标签、隐藏点赞/播放数、关闭评论，照片提供替代文字与滤镜，视频提供裁剪和声音；上述选填功能当前未接入 CLI，保留页面默认设置。首次通知提示会自动选择稍后，视频上传时的 Reels 介绍会自动确认；没有提示则继续。登录、验证仍由用户在工程浏览器完成，未知弹窗或操作失败会明确报错。

成功返回 `published`、`content_id`、`post_id`、`post_url` 和 `media_count`。Reels 可能先处于 `processing`，程序会等待本次提交的最终创建结果；超时后保留已观察状态。`submission_unknown` 表示已进入提交但未确认平台结果，`processing` 表示平台已受理且尚未取得最终作品，均不可直接重复上传。默认结果保存在 `.local/instagram-results/`；建议用 `--result` 指定路径。

如果已取得原作品链接：

```powershell
sau instagram verify --account creator --post-url "https://www.instagram.com/p/作品编号/" --expected-text "原作品中的准确文字" --result .local/instagram-verify.json
sau instagram delete --account creator --post-url "https://www.instagram.com/reel/作品编号/" --expected-text "原作品中的准确文字" --result .local/instagram-delete.json
```

接受 `/p/编号/`、`/reel/编号/` 以及带作者名的原作品链接。操作前核对账号绑定、作者、作品编号和正文，拒绝删除其他作者的作品。`delete` 将作品移至 Instagram 的“最近删除”，最终返回 `deleted`；不实现批量删除或提前永久清空。“最近删除”的保留规则由平台决定，本地素材不会被删除。

结果未知且没有链接时，先在同一账号主页按配文、素材和发布时间查找原作品，复制原作品链接再运行 `verify`；找不到不能证明提交失败，也不要直接重发。删除出现 `deletion_unknown` 时同样先查原作品和“最近删除”，不要重复删除。失败结果会包含阶段/错误和本地证据目录；账号状态、截图及页面记录均放在 Git 忽略目录，不应提交到仓库。

## 微博 CLI 子命令

```bash
sau weibo login --account <account_name>
sau weibo check --account <account_name>
sau weibo upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags 微博,测试 --thumbnail covers/demo.png
```

微博当前支持登录、账号检查和视频上传；标题最多 30 个字，封面图建议小于 5 MB，暂不支持图文上传和 `--schedule`。

## 虎扑 CLI 子命令

```bash
sau hupu login --account <account_name>
sau hupu check --account <account_name>
sau hupu upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags 虎扑,测试 --thumbnail covers/demo.png
```

虎扑当前支持登录、账号检查和视频上传；标题长度要求为 4–40 个字，暂不支持图文上传和 `--schedule`。虎扑登录可能需要在浏览器中完成 QQ 或手机号登录，需要人工查看页面时可以加 `--headed`。

## TikTok CLI 子命令（本地模式或托管浏览器模式）

TikTok 支持本地与两种托管子模式：

- **本地模式**（默认）：不设置任一托管凭据，使用本地 Chromium 与 `cookies/tiktok_<account>.json`；`--account` 必填，`--folder-id` / `--profile-id` 忽略。本地 context 固定 `en-US`，不需要改系统语言。
- **Multilogin X 模式**：设置非空 `MLX_API_TOKEN`，并要求 `--folder-id` / `--profile-id`；Profile 界面须为 **English (US)**。
- **AdsPower 模式**：设置非空 `ADSPOWER_API_KEY`，只要求 `--profile-id`；`--folder-id` 忽略；Profile 界面须为 **English (US)**。

```bash
# 本地模式：先交互式登录一次（打开有头浏览器，登录后回终端按 Enter）
sau tiktok login --account creator
sau tiktok check --account creator
sau tiktok upload-video --account creator --file videos/demo.mp4 --title "示例标题"
sau tiktok upload-note --account creator --images images/1.jpg images/2.png

# Multilogin 模式
export MLX_API_TOKEN="<token>"

sau tiktok check --folder-id <folder_id> --profile-id <profile_id>

# 视频：发布选项均可选，不传时保持页面默认
sau tiktok upload-video \
  --folder-id <folder_id> --profile-id <profile_id> \
  --file videos/demo.mp4 --title "示例标题" --tags tag1,tag2 \
  --privacy public --no-comments --disable-reuse --aigc --your-brand \
  --schedule "2026-10-21 10:30" --thumbnail covers/demo.png

# 图文：1–35 张本地图片，按传入顺序展示，第 1 张即封面
sau tiktok upload-note \
  --folder-id <folder_id> --profile-id <profile_id> \
  --images images/1.jpg images/2.png \
  --title "图文标题" --note "图文正文" --tags 图文,测试 \
  --privacy friends --no-comments --aigc

# AdsPower 模式（--folder-id 可省略）
export ADSPOWER_API_KEY="$KEY"

sau tiktok check --profile-id <profile_id>

sau tiktok upload-video \
  --profile-id <profile_id> \
  --file videos/demo.mp4 --title "示例标题" --tags tag1,tag2 \
  --privacy public --no-comments --schedule "2026-10-21 10:30"
```

- 支持 `check`、`upload-video`、`upload-note`；`login` 仅本地模式，托管模式下退出 `1`，请先在对应桌面应用中登录 Profile。
- 本地 `check` 返回 `0`（有效）/ `1`（无效）；托管模式 `check` 返回 `0/10/1/2`。
- 本地模式读写 `cookies/tiktok_<account>.json`；托管模式不读写 cookie 文件。
- 托管分支跳过页面语言切换，因此 Profile 界面必须为 **English (US)**；本地模式会自动切换页面语言。
- 本地模式与托管模式共用 15 分钟上传预算；登录页、验证码或 2FA 在托管模式下退出 `10`，本地模式按运行失败退出 `1`。
- 真实账号的本地登录与发布**待验收**；未在真实账号验证前，不要把“命令已支持”当成“发布效果已验证”。
- 未注册的子命令仍由 argparse 退出 `2`。

### 视频发布选项

`upload-video` 的原有位置参数和行为不变；以下选项均为可选，不传时不操作对应控件，保持页面默认：

| 参数 | 取值 | 含义 |
| --- | --- | --- |
| `--privacy` | `public` / `friends` / `followers` / `only-me` | 设置隐私级别；账号类型不匹配时回读失败并退出 `1` |
| `--no-comments` | 开关 | 关闭评论 |
| `--disable-reuse` | 开关 | 关闭内容复用；同时影响 Duet、Stitch、Stickers 和 Story |
| `--aigc` / `--no-aigc` | 互斥 | 开启/关闭 AI 生成内容标识；不传则保持页面默认 |
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
| `--schedule` | 否 | 与视频相同的 `YYYY-MM-DD HH:MM` |
| `--privacy` / `--no-comments` / `--aigc` / `--no-aigc` / `--your-brand` / `--branded-content` | 否 | 与视频相同语义 |

`upload-note` 没有 `--disable-reuse`、`--thumbnail` 或 `--cover-index`：图片帖没有内容复用设置，第 1 张即封面。

### TikTok 限制与错误语义

- 图片仅支持 JPG / JPEG / PNG / WEBP（扩展名大小写不敏感），单张 ≤50 MB。
- 图片数量、格式、大小，以及 Title/Description/hashtag 超限、`--note`/`--notef` 冲突、`--branded-content --privacy only-me` 都在启动浏览器前校验失败并退出 `2`，不会截断后继续。
- 显式设置的发布选项会写入页面后回读；回读不一致退出 `1`，且不会点击发布。
- 账号没有 Photos tab（未在图文灰度内）时，`upload-note` 在选文件前退出 `1`，不会把图片送进视频 input。
- 退出码 `9` 表示发布结果未知：发布点击已发出但未确认成功；**禁止自动重发**，先到 TikTok Studio → Content/Posts 按标题与发布时间核对。
- 不提供 `--cover-ms`、`--cover-index`、`--bgm`、`--json`，也不提供独立的 Duet / Stitch 开关；机器信号只有退出码与 stderr。

## 登录二维码说明

- 抖音、快手、小红书、视频号、百家号、支付宝生活号、微博和虎扑登录过程中，CLI / uploader 可能会生成临时二维码图片
- 对普通用户来说，可以直接打开该图片扫码
- 对可操作本地文件的 agent 来说，不要只把图片路径告诉用户
- 这类二维码图片本身就是给用户扫码的，agent 应优先直接展示/发送本地图片给用户
- Bilibili 和 YouTube 当前不走这套本地二维码图片托管链路，登录按上面的平台说明处理即可
- 托管浏览器模式不提供 CLI 登录链路，也不会生成登录二维码；请在对应桌面应用（Multilogin / AdsPower）中登录 Profile，收到退出码 `10` 时转人工处理

## 定时发布

抖音、快手、小红书、视频号的图文或视频上传，TikTok（本地或托管浏览器模式）的视频与图文上传，Bilibili 的视频上传，以及大鱼号的视频和文章上传支持 `--schedule`。只要传了 `--schedule`，CLI 就会自动切换到对应平台的定时发布策略；不传则默认立即发布。大鱼号时间固定为北京时间，范围为 2 小时后至 7 天内、5 分钟一档。百家号、支付宝生活号、微博和虎扑当前不支持 `--schedule`。

```bash
sau douyin upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --schedule "2026-03-24 21:30"
sau douyin upload-note --account <account_name> --images videos/1.png videos/2.png --title "图文标题" --note "图文示例" --schedule "2026-03-24 21:30"
sau kuaishou upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --schedule "2026-03-24 21:30"
sau kuaishou upload-note --account <account_name> --images videos/1.png videos/2.png videos/3.png --title "图文标题" --note "图文示例" --schedule "2026-03-24 21:30"
sau xiaohongshu upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --schedule "2026-03-24 21:30"
sau xiaohongshu upload-note --account <account_name> --images videos/1.png videos/2.png videos/3.png --title "图文标题" --note "图文示例" --schedule "2026-03-24 21:30"
sau bilibili upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tid 249 --schedule "2026-03-24 21:30"
sau tencent upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --schedule "2026-03-24 21:30"
sau tiktok upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --schedule "2026-03-24 21:30"
sau tiktok upload-note --account <account_name> --images videos/1.png videos/2.png --title "图文标题" --note "图文示例" --schedule "2026-03-24 21:30"
sau tiktok upload-video --folder-id <folder_id> --profile-id <profile_id> --file videos/demo.mp4 --title "示例标题" --schedule "2026-03-24 21:30"
sau tiktok upload-note --folder-id <folder_id> --profile-id <profile_id> --images videos/1.png videos/2.png --title "图文标题" --note "图文示例" --schedule "2026-03-24 21:30"
```

## 运行时参数

CLI 将 `debug` 和 `headless` 拆成了两个独立维度：

```bash
--debug
--headless
--headed
```

- `--debug`: 打开调试行为，例如失败时保留更多调试信息
- `--headless`: 无头模式运行
- `--headed`: 有头模式运行

如果都不传，CLI 当前默认按 `headless=True` 运行。

补充：

- 抖音和快手的 CLI 默认都是无头模式
- 如果用户明确要求可见浏览器窗口，或确实需要人工看页面，再显式传 `--headed`

## 视频上传参数

```bash
--file videos/demo.mp4
--title "示例标题"
--desc "示例简介"
--tags 运动,训练
--thumbnail videos/demo.png
--thumbnail-landscape videos/cover-4x3.png
--thumbnail-portrait videos/cover-3x4.png
```

抖音和视频号支持同时设置两种比例的封面图：

- `--thumbnail-landscape`: 4:3 横版封面
- `--thumbnail-portrait`: 3:4 竖版封面
- `--thumbnail`: 兼容旧参数，等同于 3:4 竖版封面

视频号、百家号和支付宝生活号支持使用 `--collection` 指定已有合集；百家号和支付宝生活号还支持 `--thumbnail` 指定封面图。

抖音额外支持：

```bash
--product-link https://example.com/item
--product-title 示例商品
```

Bilibili 额外要求：

```bash
--tid 249
```

- `--tid` 第一版是必填
- `--tags` 会映射到 `biliup upload --tag`
- `--schedule` 会映射到 Bilibili 所需的时间戳参数

## 图片笔记上传参数

```bash
--images videos/1.png videos/2.png videos/3.png
--title "图文标题"
--note "图文内容"
--tags 图文,测试
```

图片笔记上传当前限制：

- 抖音：最多 35 张图片，不支持 GIF
- 快手：支持多张图片，建议传真实不同文件，不要把同一路径重复多次
- 小红书：支持多张图片，正文 `--note` 可选，但 `--title` 建议始终显式传入
- TikTok：1–35 张，仅 JPG/JPEG/PNG/WEBP，单张 ≤50 MB；Title ≤90 字符，Description ≤4000 字符（含 tags），最多 50 个 hashtag；第 1 张即封面；本地与托管浏览器模式均支持

大鱼号文章使用 `--content-file` 提供 HTML、Markdown 或 TXT 正文文件，支持本地图片和图文混排，正文最多 2 万字；来源与封面等参数见 [大鱼号图文发布](./dayu-article.md)。
