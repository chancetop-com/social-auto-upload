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

与平台原生定时发布并列的本地等待机制：内容准备完成后，进程保持浏览器打开，直到到达指定时刻才点击发布。它不把发布时间交给平台，语义是“不早于”。

## 绝对时刻（absolute instant）

带时区偏移、能唯一确定某一瞬间的时间点。它与“浏览器墙上时间”相对：前者是瞬间，后者是某个时区里显示的日期与时分。

## 浏览器墙上时间（browser wall clock）

平台日期/时间控件显示的本地日期与时分。同一个绝对时刻在不同浏览器时区会显示成不同的墙上时间。

## Browser session

一次“取得浏览器并交还”的生命周期单元。本地模式下它启动并关闭自己的浏览器；托管模式下它连接一个已存在的 Profile 上下文，只断开 CDP，不销毁浏览器。

## Owned session（所有权）

“谁启动谁停止”的判定：CLI 自己调用 Start 启动的 Profile，才由该 CLI 在结束时 Stop；已在运行、非本次启动的 Profile 不由 CLI 停止。Start 失败不会触发 Stop；Start 返回 2xx 但响应不完整时做一次 best-effort Stop。

## Login required（登录失效）

平台侧的登录态无效（登录页、登录表单、未登录锚点）。本地模式与托管模式**同码 `10`**，交由调度 App 安排人工登录；它不是桌面应用的 API Key / token 失效，也不是 Profile 占用。探测本身失败（网络错误、5xx、页面结构异常）属于故障而非失效，退出码是 `1`。发布点击之后才检出登录失效时，异常带 `publish_attempted=true`，表示帖子可能已经提交，必须先核对再决定是否重跑。

## 人机验证（verification）

平台要求通过验证码或滑块等交互才能继续的状态，异常字段为 `reason="verification"`。它与登录失效同码 `10`，区别只在补救动作：登录失效先恢复会话，人机验证先完成验证（通过后通常不必重新扫码）。派发前检出记 `publish_attempted=False`；派发后检出记 `True`，后者同样要先核对帖子是否已存在。

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

## 元素角色（attached/visible/interactive/editable）

判定元素能否用于当前动作的四档递进语义。**attached**：元素确实存在于页面结构中，且指向唯一目标。**visible**：用户能看到它。**interactive**：用户能点到它，没有被遮挡或禁用。**editable**：用户能向它输入。后一档以前一档为前提；任何一档不成立都按“不可用”处理，而不是退回上一档。

## 入口缺失（entry_missing）

请求的发布选项在页面上找不到对应控件：未开放、未渲染或被账号门控。结果文件以 `status=unsupported` 记录；若请求的是“关闭”类开关（关闭评论、关闭 AI 标识），则视为已满足，记 `default_off` 并退出 `0`。它不代表页面改版或发布流程故障，只说明本次请求无法在该账号落地；若请求的是“开启”类状态，则按失败处理，退出 `1` 且不点击发布。

## 账号不合格（account_ineligible）

控件存在但当前账号无权使用该能力（例如没有对应内测资格或地区开放）。处理方式与入口缺失相同，结果文件的 `reason` 记为 `account_ineligible`，用于区分“账号问题”与“页面改版”。

## 发布超时预算

一次上传/发布流程共享的 15 分钟 deadline，由 `PublishTimeoutBudget` 表示。预算覆盖打开发布页、上传素材、填写元数据、点击发布和等待平台确认；`--not-before` 的主动等待会从 deadline 中顺延。点击发布前耗尽预算按普通失败处理（退出码 `1`，确定未发布）；点击发布后耗尽预算按发布结果未知处理（退出码 `9`，禁止自动重发）。

## 发布结果未知

发布动作已经发出，但没有观察到成功页面，也没有命中登录或验证码跳转的状态。帖子可能已经发布，对应退出码 `9`；禁止自动重发，必须先人工核查。

## publish_attempted

本次运行是否已经越过不可回退点（提交动作已派发）。`True` 只证明“可能已提交”，不证明成功；它决定调用方必须先核对帖子是否存在，而不是直接重跑。派发前的失败为 `False`。

## ARM / FIRE / OBSERVE（发布提交三段）

一次发布运行拆成三段。**ARM**：反复检查发布按钮的就绪谓词（存在、`interactive`、`is-publish`、`submit-disabled`），是唯一允许重试的阶段；就绪窗用尽即确定未发布（退出码 `1`）。**FIRE**：先置位 `publish_attempted`，再做落点复核与人类化点击，单次运行至多派发一次；派发后不再触碰按钮，任何异常都视为可能已发布（退出码 `9`）。**OBSERVE**：只按 URL 判断结果，离开 `/publish/publish` 且未命中登录/验证页为成功（退出码 `0`），窗口内仍未离开为结果未知（退出码 `9`）。

## Photos tab / 图片帖

Photos tab 是 TikTok Studio 上传页的图片帖模式入口，按账号或地区灰度开放。图片帖（note）是多图帖子，对应 API 的 Photo post，本仓命令为 `upload-note`；第 1 张图片即封面。
