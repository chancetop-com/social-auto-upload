# GLOSSARY

本项目在浏览器身份与上传语境下的统一术语。只记录“是什么”，不记录实现细节。

## 托管浏览器模式（managed browser mode）

由环境变量激活、通过桌面应用提供的 Profile 启动并接管浏览器的可选模式；本地模式的对立面。它由 `Managed browser provider` 抽象出两个子模式：`Multilogin X 模式（MLX）` 与 `AdsPower 模式`。两种子模式共享参数矩阵、退出码、登录失效契约与平台覆盖。

## Managed browser provider

把一个 Provider 的 Profile 身份与 HTTP client 原语组合起来的抽象。Multilogin X 与 AdsPower 各有一份实现；上传器只依赖 `BrowserSession`，不直接依赖具体 provider。

## Profile

浏览器身份容器：独立的 Cookie、localStorage、指纹，以及可选的代理配置。一个 Profile 通常对应一个平台账号的登录态。Profile 是托管模式下 Cookie 的唯一真相源。定位方式因 provider 而异：MLX 用 `folder_id + profile_id`，AdsPower 用 `user_id`（V2 请求体字段为 `profile_id`）。

## 本地模式（Local 模式）

项目原有的默认模式：不设置任一托管模式环境变量时，上传器自行启动浏览器，从 `cookies/<platform>_<account>.json` 读取 `storage_state`，上传后写回。托管模式下该文件完全不参与。

## 客户端发布闸门（not-before）

与平台原生定时发布并列的本地等待机制：内容上传和表单填写全部完成后，进程保持浏览器打开，直到本地时间不早于指定时间才点击发布。它不把发布时间交给平台，语义是“不早于”，对应 CLI 参数 `--not-before`。

## Browser session

一次“取得浏览器并交还”的生命周期单元。本地模式下它启动并关闭自己的浏览器；托管模式下它连接一个已存在的 Profile 上下文，只断开 CDP，不销毁浏览器。

## Owned session（所有权）

“谁启动谁停止”的判定：CLI 自己调用 Start 启动的 Profile，才由该 CLI 在结束时 Stop；已在运行、非本次启动的 Profile 不由 CLI 停止。Start 失败不会触发 Stop；Start 返回 2xx 但响应不完整时做一次 best-effort Stop。

## Login required（登录失效）

平台侧的登录态无效（登录页、登录表单、未登录锚点）。托管模式下 upload 与 check 以退出码 `10` 表达，交由调度 App 安排人工登录；它不是桌面应用的 API Key / token 失效，也不是 Profile 占用。

## 请求过于频繁（429）

桌面应用或 Local API 返回 HTTP 429 的状态。托管模式下以退出码 `11` 表达，CLI 不等待、不自动重试；MLX 与 AdsPower 共用该契约，MLX 的 429 已由退出码 `1` 改为 `11`，调度层应改为退避重试。

## Account label

用于日志与上报的业务标识。本地模式下同时决定 cookie 文件名；托管模式下 `--account` 可省略，缺省以 `profile_id` 作为标签，不代表额外的身份校验。

## Multilogin X（MLX）

用于多账号隔离的浏览器 Profile 管理产品。本项目中它只负责提供“每个账号独立的浏览器身份、Cookie 存储与代理出口”，不承担上传业务逻辑。

## Folder（MLX 专属）

Multilogin X 中用于组织 Profile 的文件夹。启动 Profile 时必须同时提供 `folder_id` 与 `profile_id`。AdsPower 模式不要求该字段，传入也会被静默忽略。

## Launcher（MLX 专属）

运行在本机的 Multilogin 服务（桌面应用或 Docker 容器），默认监听 `45001`，负责启动/停止 Profile 并分配 CDP 端口。Launcher 不是 Multilogin 云端 API。Docker launcher 与跨机部署不在支持范围内。

## Automation Token（MLX 专属）

用于 Launcher 与自动化接口的长期凭据，通过 Multilogin 云端用普通 API token 换取。与 30 分钟过期的普通 API token、只能换 token 的 refresh token 区分。请求以环境变量 `MLX_API_TOKEN` 提供。

## Multilogin X 模式（MLX 模式；MLX 专属）

由环境变量 `MLX_API_TOKEN` 激活的托管模式子模式：CLI 通过 Launcher 启动指定 Profile，经 CDP 接管其现有浏览器上下文，复用 Profile 登录态完成上传，结束后停止由本次调用启动的 Profile。

## AdsPower

多账号隔离的浏览器 Profile 管理产品。与 MLX 一样，它只提供浏览器身份、Cookie 存储与代理出口；Local API 仅付费版提供。

## AdsPower Local API

AdsPower 桌面应用在本机暴露的 HTTP 接口，默认地址为 `http://127.0.0.1:50325`。本项目只使用 V2 API，不做 V1 fallback、双栈或运行时版本探测。地址可用 `ADSPOWER_API_BASE` 覆盖；默认且推荐只使用本机或官方地址，禁止跨机部署。

## API Key（`ADSPOWER_API_KEY`）

在 AdsPower 客户端 **Automation → API** 页面生成或重置的 Local API 凭据，通过环境变量 `ADSPOWER_API_KEY` 提供；请求以 `Authorization: Bearer <API Key>` 发送。它不是 AdsPower 登录密码，也不会写入命令行、日志、异常文本或 `repr`。重置后旧 key 立即失效，需要停服务、替换环境变量并重启。

## AdsPower 模式

由环境变量 `ADSPOWER_API_KEY` 激活的托管模式子模式：CLI 通过 AdsPower Local API 启动 `user_id` 指定的 Profile，经 `data.ws.puppeteer` 的 CDP WebSocket 接管上下文，复用 Profile 登录态完成上传，结束后停止由本次调用启动的 Profile。

## user_id（AdsPower Profile 标识）

AdsPower 的 Profile 标识。CLI 通过 `--profile-id` 传入；AdsPower V2 请求体字段名为 `profile_id`。本项目中不存在 `--user-id` 参数。

## 设置后回读（set-then-readback）

显式传参后操作页面控件，再从页面读取最终状态并与请求值比较；不一致即视为失败。未传参的选项不参与设置或回读，保持页面默认。

## 发布结果未知

发布动作已经发出，但没有观察到成功页面，也没有命中登录或验证码跳转的状态。帖子可能已经发布，对应退出码 `9`；禁止自动重发，必须先人工核查。

## Photos tab / 图片帖

Photos tab 是 TikTok Studio 上传页的图片帖模式入口，按账号或地区灰度开放。图片帖（note）是多图帖子，对应 API 的 Photo post，本仓命令为 `upload-note`；第 1 张图片即封面。
