# macOS 桌面发布节点

使用平时打开浏览器的 macOS 普通用户安装。桌面节点通过出站 HTTPS 连接 Gateway，登录桌面后才能接单。准备可写目录、可访问的开发环境 Gateway 和桌面端 Token。默认引导按本机芯片取得 Gateway 批准的包（Apple 芯片为 `macos-arm64`，Intel 为 `macos-x86_64`）。包内含 Python、worker 和配套 CLI。

## 准备浏览器、窗口和安装包

1. 用该用户安装比特浏览器或 AdsPower，打开 Local API 和 Token 鉴权。比特浏览器使用“复制 ID”取得窗口 ID，AdsPower 使用 Profile 的用户 ID。打开目标窗口，登录平台，核对头像、账号标识及商家归属，再关闭窗口。平台可选 `rednote`、`xiaohongshu`、`tiktok`、`instagram`。
2. 从发布负责人取得引导脚本所属的完整 Git SHA（下面的 `REVISION`）。通过有读取权限的账号获取仓库脚本，例如 `git clone git@github.com:chancetop-com/social-auto-upload.git`，在该仓库执行 `git checkout --detach "$REVISION"`。也可以取得负责人分发的同一提交的 `desktop` 目录。
3. 在浏览器用户的终端设置安装参数。以下示例使用 zsh；替换示例值。省略安装根目录参数时默认使用 `~/Library/Application Support/social-auto-upload`。

```zsh
REVISION='替换为40位提交SHA'
INSTALL_ROOT="$HOME/Library/Application Support/social-auto-upload"
export SAU_PROVIDERS=bitbrowser
read -rs 'SAU_DESKTOP_TOKEN?桌面 Token：'; echo
export SAU_DESKTOP_TOKEN
# 同时使用两个浏览器时设置 SAU_PROVIDERS=bitbrowser,adspower
export SAU_RELEASE_CHECK_PROVIDER=bitbrowser SAU_RELEASE_CHECK_PLATFORM=tiktok
export SAU_RELEASE_CHECK_PROFILE='复制的窗口ID'
./desktop/bootstrap.sh --approved "$INSTALL_ROOT"
```

省略全部命令行参数使用默认目录从 Gateway 安装。发布负责人使用本地制品做离线包核验时，可另外指定完整固定参数 `./desktop/bootstrap.sh "$REVISION" "$SHA256" "$ARTIFACT_DIR" "$INSTALL_ROOT"`。

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

### 从 Gateway 首装和滚动升级

在首次安装前选定一个已登录、允许运维自检的窗口。以下变量与 Gateway 地址、桌面 Token 和提供方 Key 一起由安装器保存。也可在已装节点成功运行上面的 `check` 命令，记住本次自检目标。

```zsh
export SAU_RELEASE_CHECK_PROVIDER=bitbrowser SAU_RELEASE_CHECK_PLATFORM=tiktok
export SAU_RELEASE_CHECK_PROFILE='复制的窗口ID'
./desktop/bootstrap.sh --approved "$INSTALL_ROOT"
"$INSTALL_ROOT/cli-service" status
```

已装旧版且没有 `release-host.sh` 的节点，需由原浏览器用户执行一次上面的 `--approved` 引导，让旧监督进程排空并迁入分批流程。支持自动更新的版本随后在登录或重连时自行查版本。

首次安装从所连 Gateway 取本机芯片已批准的 ZIP 并验证 SHA-256。全新环境首台可取得验证批次。根目录的 `state/machine-id` 自动生成，关机返场、重启和升级沿用同一标识。不要把此文件复制到另一台桌面。以后每次登录或网络恢复会重新查询；收到批次后停止领新工作，等子进程退出并尝试原会话回执，然后核验、切换整包。新的 worker 会话与单独的检查会话均上报实际安装的摘要，Gateway 收到该窗口的成功回执后继续下一台。

发布负责人在有内网 Gateway 访问权的终端运行以下命令。先设置 `SAU_RELEASE_GATEWAY_URL` 为内网 HTTPS 地址或本地端口转发地址，安全注入 `GATEWAY_INTERNAL_TOKEN`。制品目录放置相同提交的各目标 ZIP 及配套 `.sha256`。

```zsh
ARTIFACT_DIR='/Volumes/Release Share/dev'
python3 desktop/release.py worker --env dev --ref main --artifacts "$ARTIFACT_DIR" --watch
python3 desktop/release.py status --env dev --release-id "$RELEASE_ID" --watch
```

把第一条输出的 `releaseId` 保存为 `RELEASE_ID`。关闭终端后第二条仍能查到目标 `revision`、各节点实际 SHA、`batches[].phase`、`validationDeadline` 和 `replacementFor`。失联超过期限后，即使只剩一台忙机，也先排空再接替。迟到回执进入原批次。包内 CLI 不能运行时，查看 `pauseReason`，修复并发布新的提交。`onlineReady=true` 表示当前在线节点全部通过。

下载断网时保留现有程序并重试。切换遇断电，恢复后用原用户登录，稳定登录脚本会根据 `.versions` 中的提交记录启动完整镜像；已切换镜像不能启动时，恢复上一套并报告失败。等 `status` 的 `revision` 与目标一致、`upgrade` 为空并核对 Gateway 回执；确认后会删除 `.versions` 和旧程序。切换中请保留这些文件。若窗口登录失效，先在选定窗口恢复账号，若无回执请按既有工作流核对原发布结果。
