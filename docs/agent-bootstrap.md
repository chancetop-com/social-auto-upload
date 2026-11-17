# Agent Bootstrap Prompt

这份文档是写给 `OpenClaw`、`Codex`、`Claude Code / cc` 这类 agent 客户端用户的。

目标不是让 agent 先通读整个仓库，而是先把 `social-auto-upload` 安装到可运行、可验证、可继续执行任务的状态。

当前主线已接入的平台：

- `bilibili`
- `douyin`
- `kuaishou`
- `xiaohongshu`
- `dayu`
- `tiktok`

## 这份文档解决什么问题

现在仓库里已经有：

- 安装说明
- CLI 文档
- 平台 skill

但这些内容更偏向“agent 进入仓库之后怎么执行”。

这份文档补的是“用户第一次把仓库交给 agent 客户端时，应该怎么说”。

## 推荐使用方式

1. 把整个仓库给你的 agent 客户端。
2. 把下面这段启动提示词完整发给它。
3. 等 agent 完成安装和 CLI 验证后，再继续给它下达登录、上传、定时发布等任务。

## 通用启动提示词

复制下面整段，发给你的 agent：

```text
你现在在一个名为 `social-auto-upload` 的仓库中工作。

这是一个多平台社交媒体自动发布项目。当前主线已经接入：

- bilibili
- douyin
- kuaishou
- xiaohongshu
- dayu
- tiktok

你的第一目标不是通读全部源码，也不是优先运行历史 examples，而是先把项目安装到“可运行、可验证、可继续执行任务”的状态。

请遵守以下规则：

1. 默认把仓库根目录视为当前工作目录。
2. 优先使用 `uv` 管理 Python 环境（`uv pip install -e .`）。
3. 优先使用当前主线 CLI：`sau`。
4. 优先参考这些文档：
   - `docs/install.md`
   - `docs/CLI.md`
   - `docs/update.md`
5. 如果需要平台级操作，优先参考这些 skill：
   - `skills/douyin-upload/`
   - `skills/kuaishou-upload/`
   - `skills/xiaohongshu-upload/`
   - `skills/bilibili-upload/`
   - `skills/dayu-upload/`
   - `skills/tiktok-upload/`
6. `examples/` 仅保留文章示例素材，不包含可执行脚本；统一使用当前 CLI 主线。
7. 如果登录流程生成二维码图片，不要只返回图片路径；请直接展示图片，或者明确告诉我该打开哪个本地图片文件扫码。
8. 如果是 Bilibili 登录，不要在非交互环境里强行代跑；应改为指导我在本地真实终端执行。
9. 安装完成后，请优先验证以下命令：
   - `sau --help`
   - `sau douyin --help`
   - `sau kuaishou --help`
   - `sau xiaohongshu --help`
   - `sau bilibili --help`
10. TikTok、Rednote、Instagram、小红书已使用持久化 Profile：默认系统 Chrome；先确认选择来源。Chrome 由用户按官方方式安装；显式 Chromium 使用项目固定 Patchright 的完整浏览器（`uv run patchright install --no-shell chromium`）。保留已有 conf.py；显式 headed/headless 优先于 LOCAL_CHROME_HEADLESS，未配置默认有头。登录使用 `sau tiktok login --account <alias> --headed` 或 `sau rednote login --account <alias> --headed`，交互完成后同配置 check；Profile/明确未登录退出 10，运行故障退出 1。仅 login 引导登录，真实发布前回归显式传 --no-publish；不要导入旧 Cookie 或自动重发。小红书也已接入相同 Profile/来源/headless 契约：使用 `sau xiaohongshu login --account <alias> --headed` 扫码，正常关闭后同配置 check；视频和图文回归都显式传 `--no-publish`，到 ARM 就绪后、最终提交前停止。小红书保留当前语言、二维码和人类化交互，不读写旧 JSON。其他平台保留各自现有运行方式。
11. YouTube 的 login/check/upload-video 已使用持久化 Profile，遵循上述浏览器来源与 headless 优先级；执行 `sau youtube login --account <alias> --headed` 完成人工 Google 登录，然后同配置 check。`YT_PROXY` 对本地登录/检查/上传一致生效，托管忽略。重建用 `sau youtube reset-profile --account <alias> --browser-kind chrome`。YouTube 没有 `--no-publish`，环境验收只做 login/check 或隔离合成测试，不能以实际提交视频验收；旧 JSON 不导入。
12. Facebook Page 使用 `skills/meta-upload/SKILL.md`：`sau facebook-page login --account <alias> --headed` 后同配置 check，登录 Profile 与 Facebook 隔离，多个 Page 目标共用该别名。verify/delete 仍是本地动作，保持原 Page/编号/配文核验。仅准备浏览器和查看 help 不代表已登录；该平台没有 --no-publish，未获真实发布/删除任务时只用离线或受控页面验证。
13. 完成后，请明确输出：
   - 你实际执行了哪些命令
   - 哪些验证通过了
   - 当前项目是否已经进入“可继续登录/上传”的状态
   - 推荐我下一步执行什么

如果过程中遇到错误，不要跳过，请先说明错误，再给出你准备采取的下一步动作。
```

## 安装完成后，你可以继续怎么说

下面这些是你可以继续发给 agent 的任务示例。

### 做一次平台登录

```text
请继续帮我登录小红书账号，使用有头模式，账号名用 `creator`。
```

```text
请继续帮我登录抖音账号，使用无头模式，账号名用 `creator`。
```

### 做一次 CLI 可用性检查

```text
请检查 bilibili、douyin、kuaishou、xiaohongshu 四个平台的 CLI 入口是否都可用，并告诉我缺什么依赖。
```

### 做一次真实上传

```text
请使用 xiaohongshu CLI，帮我上传一个图文草稿，使用定时发布，不要立即发布。
```

```text
请使用 douyin CLI，帮我上传一个视频，优先走当前主线，不要走历史 example。
```

## OpenClaw / Codex / Claude Code 使用建议

### OpenClaw

- 适合直接粘贴上面的完整启动提示词
- 如果支持把仓库作为工作目录挂载进去，优先先挂载仓库，再发提示词
- 如果支持本地文件展示，登录二维码应让 agent 直接展示图片

### Codex

- 建议先让它完成 bootstrap，再继续发平台任务
- 让它优先使用 `docs/install.md`、`docs/CLI.md` 和 `skills/`
- 不要让它一开始自由探索整个仓库，否则容易走到历史路径

### Claude Code / cc

- 建议先让仓库成为当前 workspace
- 再发完整启动提示词
- 后续按“安装 -> 验证 -> 登录 -> 上传”顺序继续给任务

## 为什么不按平台拆四套提示词

因为这个项目现在已经有统一的 CLI 主线。

用户第一次把仓库交给 agent 时，更需要的是：

- agent 知道主入口是什么
- agent 知道应该优先走哪条路径
- agent 知道哪些是历史路径
- agent 安装完成后先给出明确验收结果

等进入执行阶段，再让 agent 根据你的实际目标去选择：

- `bilibili`
- `douyin`
- `kuaishou`
- `xiaohongshu`

这样比给用户准备四套平台 prompt 更稳，也更容易维护。

Instagram 已迁移全部本地动作：按安装说明准备所选 Chrome/Chromium，保留已有 conf.py。先 `sau instagram login --account <alias> --headed`，等待消息入口与当前身份验证完成，再同配置 check；浏览器自动保存 Profile，无旧 Cookie 导入/导出。视频/图文回归显式 `--no-publish`，只有结果 prepared 表示到达 Share 前。verify/delete 在托管环境下仍要求原始本地账号并保留代理；原作者核验有效，不执行真实删除来验收。需要清空时显式 reset-profile 指定种类；安装成功、浏览器可启动和账号已登录分别报告。

Facebook 已迁移 login/check/视频/图文/verify/delete：使用项目专用 `browser_profiles/facebook/<原始别名>/<chrome|chromium>`，与 Facebook Page 完全隔离。保留 conf.py；按所选 Chrome/完整 Chromium/自定义路径安装，显式 headed/headless 覆盖配置，未配置默认有头。先 `sau facebook login --account <alias> --headed`，正常关闭后同配置 check；旧 JSON 不读写。verify/delete 在托管环境下仍用本地原始别名，继续核对 owner-id、原作者、作品 ID 和正文；验证使用离线替身，不执行真实删除。Facebook 没有 no-publish 开关，受控 DOM 回归不等于真实账号发布验收。只有 login 引导登录；退出 10 安排人工登录/验证，提交后先核对作品，退出 9 禁止自动重发。显式 reset-profile 只重建指定资料，不能据此重新提交旧任务。

快手环境准备：读取 `skills/kuaishou-upload/SKILL.md` 的本地 Profile 契约，按所选来源安装浏览器，保留已有配置；执行 `sau kuaishou login --account <alias> --headed` 扫码后同配置 check。只有 login 引导登录，旧 JSON 不参与；快手没有 --no-publish，未有真实发布任务时用离线/受控页面验证。重建明确指定 --browser-kind，不借重建重新提交旧任务。

视频号的 login/check/upload-video 已迁移：按 `skills/tencent-upload/SKILL.md` 准备所选 Chrome/完整 Chromium，保留 conf.py。先 `sau tencent login --account <alias> --headed` 扫码，正常关闭后同配置 check；仅 login 引导登录，旧 JSON 不导入。视频预检和业务共用 Profile。明确未登录/验证退出 10，运行故障退出 1，提交后先核查作品；退出 9 禁止自动重发。该平台无 --no-publish，不以真实发布或保存草稿验收，使用离线替身/受控 DOM。需要重建时显式指定 reset-profile 的 browser-kind。

抖音已迁移 login/check/视频/图文：保留 conf.py，准备所选系统 Chrome、完整 Chromium 或自定义路径；先 `sau douyin login --account <alias> --headed`，正常关闭后同配置 check。Profile 路径为 `browser_profiles/douyin/<原始别名>/<chrome|chromium>`，旧 JSON 不参与，默认/显式 headless 与其他已迁移平台一致。只有 login 处理扫码/验证，发布中退出 10 安排人工恢复；提交后先核对作品，9 禁止自动重发。没有 no-publish 开关，未获真实发布任务时只做离线/受控 DOM 验证。显式 reset-profile 仅清空选定种类，无需浏览器安装。

百家号已接入本地持久化 Profile：保留已有 conf.py，按实际选择准备系统 Chrome、完整 Chromium（`uv run patchright install --no-shell chromium`）或自定义路径。显式 headed/headless 优先于配置，未配置默认有头。先 `sau baijiahao login --account <alias> --headed` 完成扫码或验证，正常关闭后同配置 check；只认后台业务控件，旧 JSON 不导入/导出。视频必须提供 `--thumbnail`，可选合集和 not-before；无 `--no-publish` 或 `--schedule`，验收使用离线/受控 DOM，不提交真实视频。缺少 Profile/登录或验证退出 10，其他运行故障退出 1；提交后保留 publish_attempted，退出 9 先核对作品，不自动重发。重建必须显式 `reset-profile --account <alias> --browser-kind chrome|chromium`，只清空该种类，不影响历史作品证据。

微博 login/check/upload-video 与直接 uploader 已接入持久化 Profile。保留 conf.py，按 `skills/weibo-upload/SKILL.md` 准备所选 Chrome/完整 Chromium；先 `sau weibo login --account <alias> --headed`，正常关闭后同配置 check。默认有头，显式运行参数优先；旧 JSON 不导入/导出，别名可换号，只有 login 引导登录。发布必需封面，自然窗口下滚动和落点校验完成交互。缺少 Profile/未登录或验证退出 10，其他故障退出 1；提交后保留 publish_attempted，9 或已提交标记都先核对作品，不自动重发。重建显式指定 browser-kind；微博无 no-publish，未获真实发布任务时只做离线/受控页面验证。

虎扑 login/check/upload-video 与直接调用已接入本地持久化 Profile。保留 conf.py；默认系统 Chrome 有头，只准备所选系统 Chrome、完整 Chromium（`uv run patchright install --no-shell chromium`）或自定义路径。显式 headed/headless 优先于配置，未配置 False；路径优先于浏览器选择。执行 `sau hupu login --account <alias> --headed` 完成 QQ 扫码/验证，关闭后同配置 check；旧 JSON 不读写，账号别名可换号。浏览器自然窗口内保留二维码、文件选择器和专区弹窗；不替换 context 或覆盖语言/指纹。缺少 Profile/登录/验证退出 10，故障退出 1；提交后保留 publish_attempted，结果未知 9 禁止自动重发。Hupu 没有 no-publish，不用真实视频提交验收；测试用隔离合成 DOM。重建须明确 `reset-profile --account <alias> --browser-kind chrome|chromium`。

支付宝生活号已迁移 login/check/upload-video/reset-profile 和直接 uploader：保留 conf.py，只准备所选 Chrome、完整 Chromium 或自定义路径；默认 Chrome 有头，显式 headed/headless 覆盖配置。先 `sau alipay login --account <alias> --headed` 扫码，正常关闭后同配置 check；二维码可展示或通过回调交付，内容创作入口才是成功证据。旧 JSON 不读写，浏览器自动持久化独立 Profile；别名允许换号，勿新增账号绑定。保持 qiankun 微应用无 stealth。缺少 Profile/登录或验证退出 10，其他故障退出 1；提交后保留 publish_attempted，退出 9 先核对作品、禁止自动重发。支付宝无 no-publish，只用离线/受控 DOM 验收，不提交真实视频；显式 reset-profile 仅重建指定种类，不影响其他资料或历史结果。

雪球 login/check/文章/verify/reset-profile 已接入独立持久化 Profile。保留 conf.py，只准备所选系统 Chrome、完整 Chromium（`uv run patchright install --no-shell chromium`）或自定义路径；默认 Chrome 有头，显式运行参数优先，路径覆盖来源。先 `sau xueqiu login --account <alias> --headed`，正常关闭后同配置 check；别名可换号，只有 login 引导登录，旧 JSON/身份旁文件不参与。`--expected-name` 与历史作品作者继续核对；verify 在托管环境下仍本地。文章验收显式 `--prepare-only` 停在预览，可能保存远端草稿，不以真实提交验收。缺少 Profile/登录/验证退出 10，运行故障 1，提交后标记或结果未知 9 先核查作品、禁止自动重发。重建明确指定 browser-kind，保留另一种类与 `cookies/xueqiu_results/`；完整使用流程见 `skills/xueqiu-upload/SKILL.md`。
