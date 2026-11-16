# Rednote（第一版）

Rednote 使用独立的 `sau rednote` 命令，默认访问 [Rednote 创作中心](https://creator.rednote.com/publish/publish)。2026-11-16 已从 [Rednote 官网](https://www.rednote.com/) 的 Post 链接核实此入口，并在登录态下观察到视频和图文上传页。

本版按小红书上传器初始化独立模块；上传、标题/正文/话题、封面、声明、定时及 ARM / FIRE / OBSERVE 提交机制沿用小红书基线。保留独立实现是为了继续根据 Rednote 实际页面调整，不改变现有小红书行为。**这不代表所有小红书功能已经通过 Rednote 真账号验收。**

## 登录与检查

```bash
sau rednote login --account creator --headed
sau rednote check --account creator
```

有头登录保留网页默认的短信入口，用户也可以切到扫码；等待命令显示登录成功后再关闭窗口。无头登录 `--headless` 输出二维码。CLI 的测试浏览器和日常 Chrome 是不同会话，日常 Chrome 已登录不代表 CLI 已登录。

本地会话保存到 `cookies/rednote_creator.json`；与同名 `xiaohongshu` 账号隔离，二维码与日志也使用 Rednote 命名。实测 Rednote 使用 `.rednote.com` 下的 `web_session` / `id_token`，没有小红书的 `galaxy_creator_session_id`。本地预检要求目标创作域存在未过期、非空的 `web_session`；通过发布页上传入口确认有效后才原子写回会话。

## 英文环境

本地浏览器使用 `locale=en-US` 和 `Accept-Language: en-US,en;q=0.9`。这控制网页语言环境，不改变操作系统或浏览器菜单的语言，也不保证服务器返回英文页面。

实际 `en-US` context 仍返回中文后台；所检查的官方发布资源也直接使用这些中文文案。标题、正文、登录、声明入口、原创开关、定时和确认按钮采用结构定位，删除无必要的文本兜底。当前只有缺少稳定标识的声明选项和封面上传页签使用已观察的中文名称。若出现实际英文页面，先取证；确需文本才按真实英文、中文排序，不自行翻译或添加猜测候选。

## 发布前验证

```bash
sau rednote upload-video --account creator \
  --file videos/demo.mp4 --title "Hello rednote" \
  --desc "Video description" --tags travel,life --no-publish

sau rednote upload-note --account creator \
  --images videos/1.png videos/2.png --title "Hello rednote" \
  --note "Photo description" --tags travel,life --no-publish
```

`--no-publish` 仍会向 Rednote 上传素材并填写内容，到发布按钮就绪后停止，不点击发布。去掉它才会实际提交。准备成功时 CLI 输出 `prepared (not published)`。

第一版参数与小红书一致：视频 `--thumbnail`、原创/内容类型声明、`--schedule`（UTC、精确到分钟）、`--not-before`（UTC、可精确到秒）等。完整参数以 `sau rednote upload-video --help` / `upload-note --help` 为准。显式封面和声明必须设置、回读成功，否则停止在发布前；不静默换用首帧或省略声明。来源声明还要核对确认后显示的媒体名称或拍摄日期/地点，不能只检查类型名称。`--shoot-location` 使用候选中的完整地点名称；只匹配名称，不把地址或名称前缀的包含关系当成匹配，重名时停止。定时在填写后及发布前检查开关和分钟值。话题以最终 `data-topic` 回读为准，包括页面自动转换；错词或重复插入会停止。标题长度、正文长度、标签数及定时窗口仍沿用小红书限制。

## 托管浏览器模式

设置 `MLX_API_TOKEN` 后，`check` 和两种上传命令使用 `--folder-id <folder> --profile-id <profile>`。设置 `ADSPOWER_API_KEY` 后只需 `--profile-id <profile>`。两种凭据不能同时设置。

托管模式沿用 Profile 自身语言和登录态，不覆盖指纹、不读写本地 cookie；请在 Profile 中使用英文环境登录 Rednote 后运行。`login` 命令仅用于本地模式。

## 域名与退出码

调试时可用 `SAU_REDNOTE_CREATOR_BASE_URL` 覆盖创作中心地址，作用于登录、检查、视频和图文路径。`SAU_XHS_CREATOR_BASE_URL` 不影响 Rednote；不要用它切换 Rednote 账号。

退出码沿用项目契约：`0` 成功或干跑准备完成，`1` 普通故障，`2` 参数错误，`9` 发布结果未知，`10` 需登录或人机验证，`11` 托管服务限流。`9` 或 `publish_attempted=true` 时先人工核对帖子，禁止自动重发。

## 验收进度

- 已核实官方域名、登录后视频/图文入口及 `input.upload-input` 结构。
- 离线测试覆盖命令分发、账号/域名隔离、英文 context、托管会话、干跑不派发发布、发布结果的创作域检查。
- 已完成真实账号的本地有头登录，并在新的无头英文 context 中执行 `check` 返回 `valid`。
- 两张中性测试图片已完成真实 `upload-note --no-publish`：逐张上传、英文标题/正文、发布按钮就绪，退出 `0`，没有点击发布。
- 3 秒中性测试视频已完成真实 `upload-video --no-publish`：上传处理、英文标题/正文、发布按钮就绪，退出 `0`，没有点击发布。
- 真实视频干跑已通过自定义封面、AI 声明、`--no-original` 和定时回读；图文干跑已通过话题 `travel`、AI 声明、`--no-original` 和定时回读。均为 `en-US` context 下的实际中文界面，未发布。
- 无头二维码提取、用户扫码、保存会话及新浏览器 `probe_session=valid` 已通过。自主拍摄（地点、日期、确认后明细）、转载（媒体名称及确认后明细）、虚构和营销声明也已通过真实页面干跑。图文及 12 秒视频均已开启原创并回读成功。3 秒视频禁用是时长限制，不能据此判断账号无原创能力；当前官方组件在视频不足 10 秒或来源转载时禁用原创。
- 纯英文服务端界面、真实托管 Profile 和最终提交仍未验收；用户当前选择先完成本地账号验收。详见 [验收记录](../.scratch/rednote-support/acceptance.md) 和 [接入地图](../.scratch/rednote-support/map.md)。
