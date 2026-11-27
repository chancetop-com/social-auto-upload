# macOS 桌面发布节点

使用平时打开浏览器的 macOS 普通用户安装。桌面节点通过出站 HTTPS 连接 Gateway，登录桌面后才能接单。准备可写目录、可访问的开发环境 Gateway、桌面端 Token，以及与本机芯片匹配的程序包（Apple 芯片选 `macos-arm64`，Intel 选 `macos-x86_64`）。包内含 Python、worker 和配套 CLI。

## 准备浏览器、窗口和安装包

1. 用该用户安装比特浏览器或 AdsPower，打开 Local API 和 Token 鉴权。比特浏览器使用“复制 ID”取得窗口 ID，AdsPower 使用 Profile 的用户 ID。打开目标窗口，登录平台，核对头像、账号标识及商家归属，再关闭窗口。平台可选 `rednote`、`xiaohongshu`、`tiktok`、`instagram`。
2. 从发布负责人取得批准的完整 Git SHA、该芯片 ZIP 的 SHA-256 和制品目录读权限。ZIP 文件名为 `sau-desktop-完整SHA-目标.zip`。通过有读取权限的账号获取仓库脚本，例如 `git clone git@github.com:chancetop-com/social-auto-upload.git`，在该仓库执行 `git checkout --detach "$REVISION"`。也可以取得负责人分发的同一提交的 `desktop` 目录。
3. 在浏览器用户的终端设置安装参数。以下示例使用 zsh；替换示例值。省略安装根目录参数时默认使用 `~/Library/Application Support/social-auto-upload`。

```zsh
REVISION='替换为40位提交SHA'
SHA256='替换为该ZIP的64位SHA256'
ARTIFACT_DIR='/Volumes/Release Share/dev'
INSTALL_ROOT="$HOME/Library/Application Support/social-auto-upload"
export SAU_PROVIDERS=bitbrowser
read -rs 'SAU_DESKTOP_TOKEN?桌面 Token：'; echo
export SAU_DESKTOP_TOKEN
# 同时使用两个浏览器时设置 SAU_PROVIDERS=bitbrowser,adspower
./desktop/bootstrap.sh "$REVISION" "$SHA256" "$ARTIFACT_DIR" "$INSTALL_ROOT"
```

缺少选定提供方的 API Key 时，安装器在终端隐式输入。可预先导出 `BITBROWSER_API_KEY` 或 `ADSPOWER_API_KEY`。默认 Gateway 为 `https://social-media-web-api.connexup-dev.net`；需要覆盖时在安装或重启前导出 `SAU_GATEWAY_URL`。两个 Local API 默认分别为本机 54345、50325 端口，可用 `BITBROWSER_API_BASE`、`ADSPOWER_API_BASE` 指定回环地址。容量默认 1，按机器实际能力设置 `WORKER_MAX_CONCURRENCY`。应用位于非标准位置时，把 `BITBROWSER_APP_PATH` 或 `ADSPOWER_APP_PATH` 设置为对应的绝对 `.app` 路径。

## 启动、状态和不发布自检

安装命令验证摘要并打印根目录和监督进程 PID。相同包重复安装沿用同一服务。启动项位于 `~/Library/LaunchAgents/net.connexup.social-auto-upload.*.plist`，绑定当前图形登录会话。锁屏后节点继续工作；睡眠期间暂停，唤醒、联网后重新枚举窗口、上报容量，进程持续运行时沿用原会话。某个提供方晚启动时，其他已就绪的提供方可以先接单。

```zsh
ctl="$INSTALL_ROOT/cli-service"
"$ctl" status
"$ctl" check --provider bitbrowser --profile-id '复制的窗口ID' --platform tiktok
```

`status` 输出 `release`、`revision`、`running`、`claimReady`、`activeCount`、`capacity`、`sessionId`、`lastExit` 和 `nextAttempt`。时间为 Unix 秒。自检调用配套 CLI 检查现有登录态，无素材和发布步骤。回执中确认 `cloudConnected=true`、`profileVisible=true`、`cliInvoked=true`、`platformLogin="valid"`。更换 AdsPower 时使用 `--provider adspower`。若 Local API 不可用，检查客户端、回环端口和 Key；若窗口不可见，核对所复制的 ID；若为 `login-required`，在目标窗口手动登录后重新自检。

## 维护、升级和异常恢复

```zsh
"$ctl" stop           # 排空并退出；下次图形登录自动启动
"$ctl" start          # 在本次已登录会话启动
"$ctl" restart        # 排空，保存本次配置，开启新会话
"$ctl" disable        # 排空，持续禁用登录启动
"$ctl" enable         # 恢复登录启动并立即启动
"$ctl" restart --force
"$ctl" uninstall
```

这些是分别使用的维护命令。正常停止、重启和卸载会停止领取，等待当前 CLI 结束并尝试上报结果。上传时间较长时等待命令返回。强制重启会终止本安装的 worker 和受管 CLI；随后按原云端截止时间核对未确认的发布。请勿手工重跑该发布。

空闲 worker 意外退出后，监督进程第一次立即重启，连续退出依次等待 10、20、40、80、160 秒，随后每次 300 秒；运行满 10 分钟重置。忙时崩溃留下的可识别 CLI 继续占用容量，结束后才释放。新会话只领取新的工作。可查看 `state/worker.log` 及 `status` 的最后退出原因和下次时间。网络或浏览器暂时不可用时，worker 原地重试。

安装根目录中的 `program` 存放配套运行时和版本清单，`cli-service` 是稳定入口；`state` 存放用户私有配置、日志和 `cli` 数据。更换版本走发布负责人的分批升级流程，等待排空、切换、无发布自检及 Gateway 确认。原安装器拒绝覆盖另一摘要。卸载删除本安装的程序、入口及登录项，保留 `state` 以便保管浏览器资料和配置。用户单独安装的 CLI 可继续使用。
