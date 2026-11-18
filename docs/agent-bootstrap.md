# Agent Bootstrap Prompt

这份文档是写给 `OpenClaw`、`Codex`、`Claude Code / cc` 这类 agent 客户端用户的。

目标不是让 agent 先通读整个仓库，而是先把 `social-auto-upload` 安装到可运行、可验证、可继续执行任务的状态。

当前 CLI 提供七个平台和本地工具 `article`。平台和内容类型见[CLI 使用说明](./CLI.md)。

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

这是一个多平台社交媒体自动发布项目。使用 sau --help 获取当前安装的平台与本地工具列表。

你的第一目标不是通读全部源码，也不是优先运行历史 examples，而是先把项目安装到“可运行、可验证、可继续执行任务”的状态。

请遵守以下规则：

1. 默认把仓库根目录视为当前工作目录。
2. 优先使用 `uv` 管理 Python 环境（`uv pip install -e .`）。
3. 优先使用当前主线 CLI：`sau`。
4. 优先参考这些文档：
   - `docs/install.md`
   - `docs/CLI.md`
   - `docs/update.md`
5. 平台级操作先查 skills/social-auto-upload/SKILL.md 中的平台映射，再读取目标平台 Skill。
6. 使用 sau article themes 和 sau article render 在本地预览文章；发布走目标平台的 CLI。
7. 如果登录流程生成二维码图片，不要只返回图片路径；请直接展示图片，或者明确告诉我该打开哪个本地图片文件扫码。
8. 安装后运行 sau --help，逐一验证 instagram、tiktok、xiaohongshu、rednote、facebook、facebook-page、youtube 的 --help，以及 sau article themes。
9. 七个平台的本地模式都使用持久化 Profile，默认系统 Chrome。先确认选择来源。Chrome 由用户按官方方式安装；显式 Chromium 使用项目固定 Patchright 的完整浏览器（`uv run patchright install --no-shell chromium`）。保留已有 conf.py；显式 headed/headless 优先于 LOCAL_CHROME_HEADLESS，未配置默认有头。登录使用 `sau tiktok login --account <alias> --headed` 或 `sau rednote login --account <alias> --headed`，交互完成后同配置 check；Profile/明确未登录退出 10，运行故障退出 1。仅 login 引导登录，真实发布前回归显式传 --no-publish；不要导入旧 Cookie 或自动重发。小红书也已接入相同 Profile/来源/headless 契约：使用 `sau xiaohongshu login --account <alias> --headed` 扫码，正常关闭后同配置 check；视频和图文回归都显式传 `--no-publish`，到 ARM 就绪后、最终提交前停止。小红书保留当前语言、二维码和人类化交互，不读写旧 JSON。所有浏览器平台按相同来源/headless 契约运行；托管动作无需安装本地浏览器。基础安装、浏览器启动和平台登录分别报告。Linux/CI 按 docs/install.md 的两条独立路线准备，不自动安装或更新系统 Chrome。
10. YouTube 的 login/check/upload-video 已使用持久化 Profile，遵循上述浏览器来源与 headless 优先级；执行 `sau youtube login --account <alias> --headed` 完成人工 Google 登录，然后同配置 check。`YT_PROXY` 对本地登录/检查/上传一致生效，托管忽略。重建用 `sau youtube reset-profile --account <alias> --browser-kind chrome`。YouTube 没有 `--no-publish`，环境验收只做 login/check 或隔离合成测试，不能以实际提交视频验收；旧 JSON 不导入。
11. Facebook Page 使用 `skills/meta-upload/SKILL.md`：`sau facebook-page login --account <alias> --headed` 后同配置 check，登录 Profile 与 Facebook 隔离，多个 Page 目标共用该别名。verify/delete 仍是本地动作，保持原 Page/编号/配文核验。仅准备浏览器和查看 help 不代表已登录；该平台没有 --no-publish，未获真实发布/删除任务时只用离线或受控页面验证。
12. 完成后，请明确输出：
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
请继续帮我登录 Rednote 账号，使用无头模式，账号名用 `creator`。
```

### 做一次 CLI 可用性检查

```text
请核对 sau --help 的七个平台和本地 article 工具，检查目标平台的帮助是否可用。
```

### 做一次真实上传

```text
请使用 xiaohongshu CLI，帮我上传一个图文草稿，使用定时发布，不要立即发布。
```

```text
请使用 instagram CLI，帮我上传一个视频，优先走当前主线，不要走历史 example。
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

## 安装后的平台操作

可根据用户指定的平台，从[技能目录](./skill-distribution.md)选择发布流程。

Instagram 已迁移全部本地动作：按安装说明准备所选 Chrome/Chromium，保留已有 conf.py。先 `sau instagram login --account <alias> --headed`，等待消息入口与当前身份验证完成，再同配置 check；浏览器自动保存 Profile，无旧 Cookie 导入/导出。视频/图文回归显式 `--no-publish`，只有结果 prepared 表示到达 Share 前。verify/delete 在托管环境下仍要求原始本地账号并保留代理；原作者核验有效，不执行真实删除来验收。需要清空时显式 reset-profile 指定种类；安装成功、浏览器可启动和账号已登录分别报告。

Facebook 已迁移 login/check/视频/图文/verify/delete：使用项目专用 `browser_profiles/<chrome|chromium>/facebook/<原始别名>`，与 Facebook Page 完全隔离。保留 conf.py；按所选 Chrome/完整 Chromium/自定义路径安装，显式 headed/headless 覆盖配置，未配置默认有头。先 `sau facebook login --account <alias> --headed`，正常关闭后同配置 check；旧 JSON 不读写。verify/delete 在托管环境下仍用本地原始别名，继续核对 owner-id、原作者、作品 ID 和正文；验证使用离线替身，不执行真实删除。Facebook 没有 no-publish 开关，受控 DOM 回归不等于真实账号发布验收。只有 login 引导登录；退出 10 安排人工登录/验证，提交后先核对作品，退出 9 禁止自动重发。显式 reset-profile 只重建指定资料，不能据此重新提交旧任务。
