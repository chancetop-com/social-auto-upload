# Windows 桌面发布节点

在使用浏览器的 Windows x64 普通用户会话中运行 PowerShell 5.1 或更新版本。准备可写目录、开发环境 Gateway 的出站 HTTPS、桌面端 Token、目标平台的现有登录态及 `windows-x86_64` 私有运行时包。

## 准备窗口和安装来源

1. 在该用户下安装比特浏览器或 AdsPower，打开 Local API 和 Token 鉴权。比特浏览器在目标窗口选择“复制 ID”；AdsPower 记录 Profile 的用户 ID。打开该窗口，登录目标平台，核对账号标识、头像及商家归属，再关闭窗口。
2. 向发布负责人取得获批版本的完整 Git SHA、Windows ZIP 的 SHA-256 和制品目录读权限。如果从私有仓库取脚本，先用有读取权限的 SSH 账号执行 `git clone git@github.com:chancetop-com/social-auto-upload.git`，进入仓库并执行 `git checkout --detach $Revision`。也可以使用该提交分发的完整 `desktop` 目录，其中应同时包含 `bootstrap.ps1` 和 `expand-package.ps1`。制品目录应有 `sau-desktop-完整SHA-windows-x86_64.zip`。
3. 从仓库根目录运行以下 PowerShell 命令，替换占位值。省略 `-InstallRoot` 时默认使用 `%LOCALAPPDATA%\social-auto-upload`。

```powershell
$Revision = '替换为40位提交SHA'
$Digest = '替换为Windows包的64位SHA256'
$ArtifactDir = '\\fileserver\releases\dev'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'social-auto-upload'
$env:SAU_PROVIDERS = 'bitbrowser'
$token = Read-Host '桌面 Token' -AsSecureString
$env:SAU_DESKTOP_TOKEN = ([pscredential]::new('desktop', $token)).GetNetworkCredential().Password
& .\desktop\bootstrap.ps1 -Revision $Revision -Sha256 $Digest -ArtifactDir $ArtifactDir -InstallRoot $InstallRoot
```

也可选择 `adspower` 或 `bitbrowser,adspower`。需要时设置 `BITBROWSER_API_KEY`、`ADSPOWER_API_KEY`；缺少已选提供方的 Key 时安装器会在本机提示输入。Local API 默认使用回环地址上的 54345（比特浏览器）和 50325（AdsPower）端口，覆盖变量分别为 `BITBROWSER_API_BASE`、`ADSPOWER_API_BASE`。若客户端安装在自定义路径，设置 `BITBROWSER_APP_PATH` 或 `ADSPOWER_APP_PATH` 为实际 EXE 的完整路径，例如 `$env:BITBROWSER_APP_PATH = 'D:\Apps\BitBrowser\BitBrowser.exe'`。默认 Gateway 是 `https://social-media-web-api.connexup-dev.net`，通过 `SAU_GATEWAY_URL` 覆盖；默认容量 1，通过 `WORKER_MAX_CONCURRENCY` 调整。安装及重启保存本用户设置。

## 登录、自检和状态

安装器打印根目录和监督进程 PID，注册当前用户的登录触发任务（任务计划程序中名称以 `net.connexup.social-auto-upload.` 开头）。任务使用交互式令牌和普通权限，登录前等待，登录后启动所选客户端并轮询 Local API。锁屏期间继续运行。睡眠期间暂停，唤醒和网络重连后重新盘点窗口与占用，每个已就绪提供方都可独立接单。

```powershell
$Ctl = Join-Path $InstallRoot 'cli-service.cmd'
& $Ctl status
& $Ctl check --provider bitbrowser --profile-id '复制的窗口ID' --platform tiktok
```

`status` 返回版本和提交（`release`、`revision`）、`running`、`claimReady`、`activeCount`、`capacity`、`sessionId`、`lastExit`、`nextAttempt`。时间是 Unix 秒。自检只检查登录态，不上传、不发布。确认回执中的 `cloudConnected=true`、`profileVisible=true`、`cliInvoked=true`、`platformLogin="valid"`。可换用 `--provider adspower`，或将平台换为 `rednote`、`xiaohongshu`、`instagram`。未连云端时检查 Gateway 地址和 Token；窗口不可见时核对 Local API、密钥及窗口 ID；`login-required` 时打开该窗口手动登录并重试自检。

## 日常维护和恢复

| 命令 | 操作及完成条件 |
| --- | --- |
| `& $Ctl stop` | 停止领取，等待当前命令和结果上报尝试，下一次登录仍会启动。 |
| `& $Ctl start` | 在已登录的当前用户会话启动；禁用状态由 enable 恢复。 |
| `& $Ctl restart` | 排空后读取新的配置，在新会话领取。 |
| `& $Ctl disable` | 排空并注销登录任务；重启系统后仍保持禁用。 |
| `& $Ctl enable` | 恢复注册并立即启动。 |
| `& $Ctl restart --force` | 终止本安装的 worker 和受管 CLI，留下未确认的操作按原云端结果截止时间对账。 |
| `& $Ctl uninstall` | 排空，解除注册，删除本安装的入口和程序，保留独立的 `state` 目录。 |

空闲 worker 崩溃第一次立即重启，连续故障依次退避 10、20、40、80、160 秒，之后每次 300 秒。稳定运行满 10 分钟后重置。忙时崩溃仍在执行的可识别 CLI 继续占用一个名额。新 worker 创建新会话，既不重跑旧发布，也不重发旧回执。云端未确认时，请先到目标平台核对账号和内容。浏览器或网络暂时不可用时，worker 保持运行，恢复后重新上报。

根目录的 `program\runtime` 是配套 Python、worker 及 CLI，`program\release.json` 记录版本，`state\worker.log` 记录运行日志，`state\settings.json` 存放该用户的私有设置，`state\cli` 存放工作资料。相同包可重复安装。跨版本升级由发布负责人分批安排，排空后切换整包，执行不发布自检并等待 Gateway 确认。原安装器会拒绝在已占用的目录覆盖其他摘要。单独安装的 CLI 使用自己的路径。
