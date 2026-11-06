# GLOSSARY

本项目在 Multilogin X 接入语境下的统一术语。只记录“是什么”，不记录实现细节。

## Multilogin X

用于多账号隔离的浏览器 Profile 管理产品。本项目中它只负责提供“每个账号独立的浏览器身份、Cookie 存储与代理出口”，不承担上传业务逻辑。

## Profile

Multilogin X 中的一个浏览器身份容器：独立的 Cookie、localStorage、指纹与代理配置。一个 Profile 对应一个平台账号的登录态。Profile 是 Multilogin 模式下 Cookie 的唯一真相源。

## Folder

Multilogin X 中用于组织 Profile 的文件夹。启动 Profile 时必须同时提供 `folder_id` 与 `profile_id`。

## Launcher

运行在本机的 Multilogin 服务（桌面应用或 Docker 容器），默认监听 `45001`，负责启动/停止 Profile 并分配 CDP 端口。Launcher 不是 Multilogin 云端 API。

## Automation Token

用于 Launcher 与自动化接口的长期凭据，通过 Multilogin 云端用普通 API token 换取。与 30 分钟过期的普通 API token、只能换 token 的 refresh token 区分。

## Multilogin 模式（MLX 模式）

由环境变量 `MLX_API_TOKEN` 激活的可选模式：CLI 通过 Launcher 启动指定 Profile，经 CDP 接管其现有浏览器上下文，复用 Profile 登录态完成上传，结束后停止由本次调用启动的 Profile。

## 本地模式（Local 模式）

项目原有的默认模式：上传器自行启动浏览器，从 `cookies/<platform>_<account>.json` 读取 `storage_state`，上传后写回。Multilogin 模式下该文件完全不参与。

## Owned session（所有权）

“谁启动谁停止”的判定：CLI 自己调用 Start 启动的 Profile，才由该 CLI 在结束时 Stop；已在运行、非本次启动的 Profile 不由 CLI 停止。

## Login required（登录失效）

平台侧的登录态无效（登录页、登录表单、未登录锚点）。Multilogin 模式下 upload 与 check 以退出码 `10` 表达，交由调度 App 安排人工登录；它不是 Launcher 的 token 失效或 Profile 占用。

## Account label

用于日志与上报的业务标识。本地模式下同时决定 cookie 文件名；Multilogin 模式下 `--account` 可省略，缺省以 `profile_id` 作为标签，不代表额外的身份校验。

## Browser session

一次“取得浏览器并交还”的生命周期单元。本地模式下它启动并关闭自己的浏览器；Multilogin 模式下它连接一个已存在的 Profile 上下文，只断开 CDP，不销毁浏览器。

## 设置后回读（set-then-readback）

显式传参后操作页面控件，再从页面读取最终状态并与请求值比较；不一致即视为失败。未传参的选项不参与设置或回读，保持页面默认。

## 发布结果未知

发布动作已经发出，但没有观察到成功页面，也没有命中登录或验证码跳转的状态。帖子可能已经发布，对应退出码 `9`；禁止自动重发，必须先人工核查。

## Photos tab / 图片帖

Photos tab 是 TikTok Studio 上传页的图片帖模式入口，按账号或地区灰度开放。图片帖（note）是多图帖子，对应 API 的 Photo post，本仓命令为 `upload-note`；第 1 张图片即封面。
