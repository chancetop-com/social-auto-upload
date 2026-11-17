# 02 浏览器与离线验证记录

日期：2026-11-17，Darwin arm64。范围：TikTok 全正式入口及新共享本地会话。无真实平台登录、素材上传、发布或删除；旧账号资料与用户 conf.py 未修改。

## 真实浏览器

执行脚本：[browser-smoke.py](./browser-smoke.py)。从隔离 worktree 执行：

```sh
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python .scratch/local-chrome-profile-implementation/research/browser-smoke.py
```

浏览器启动经 sandbox escalation 执行。脚本只创建随机临时根、合成账号别名和 `127.0.0.1` HTTP origin；每一组合都正常关闭再重开，验证 Cookie / localStorage 保存，并验证同一 browser 的匿名 context 初始没有登录 context 的状态、匿名写入不污染主 Profile、关闭匿名 context 后主页面仍可用。

| 已选来源 | 实际浏览器版本 | 有头 | 无头 | 重开存储复用 | 匿名隔离 |
| --- | --- | --- | --- | --- | --- |
| `channel=chrome`，系统 Chrome | 157.0.8103.79 | 通过 | 通过 | 两种模式通过 | 两种模式通过 |
| `channel=chromium`，Patchright 1.64.4 配套完整 revision 1248（Chrome for Testing） | 156.0.8078.4 | 通过 | 通过 | 两种模式通过 | 两种模式通过 |
| 自定义 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` | 157.0.8103.79 | 通过 | 通过 | 两种模式通过 | 两种模式通过 |
| 自定义 Patchright `chromium.executable_path`，本机缓存中的完整 Chrome for Testing | 156.0.8078.4 | 通过 | 通过 | 两种模式通过 | 两种模式通过 |

最终输出 `PASS 8 configurations`。同一浏览器种类在 channel/custom、有头/无头间复用同一个临时叶子；两种类分开。自定义种类依据 macOS 产品元数据的可执行文件、显示名/名称、bundle identifier 交叉校验，未依据路径名或 UA/CDP Chrome 字样。

首次 smoke 在四项 channel 组合成功后发现系统 Chrome 的 `CFBundleName=Chrome`、`CFBundleDisplayName=Google Chrome`；原识别仅接受产品全名因此安全拒绝，尚未打开 custom 的账号 Profile。修复交叉校验后完整八项通过。标准 channel 的已知种类不通过产品 UA 猜测，启动日志记录 browser.version 的实际值；可靠路径未知则标 unknown。

本机未进行 Windows/Linux 原生浏览器实测，相关产品信息分支有明确失败/超时语义。此结果不能证明平台登录、风控、发布成功或完整多语言支持。真实 TikTok / Rednote / Instagram / 小红书 login 与 no-publish 仍属票 20。

## 离线行为

主要入口是正式 CLI dispatch → 真实配置 → Profile 文件系统/占用 → persistent session → 真实 TikTok uploader。仅浏览器 DOM、provider、交互输入和系统边界使用替身；不替换整个本地 session。新测试包括：

- 配置缺省/显式 False/True、两种 channel、自定义路径优先于无关非法选择、未知/冲突产品在 Profile 创建前拒绝、所选来源失败不回退；托管完全绕开本地来源与目录。
- 旧 JSON 损坏/不存在不影响新 Profile；缺少 Profile 和未登录为 10，网络/未知页面为 1，验证 reason 保留；login 使用同次模式一次浏览器，别名可以再次登录。
- 视频及图文完整表单流程以 DOM fixture 到达真正 no-publish 停止点；视频成功/未知/提交后登录/验证时仅一次提交，关闭故障保持 0/9/10 与 publish_attempted；登录表单出现时提交次数为零。
- setup、业务与 close 都保持占用；setup 失败、正常完成、异常、取消、cleanup 超时和 cleanup 期间新取消均释放项目锁并保留主结果；正常不重复 browser.close。Profile 核心真实跨进程回归另外通过。
- 原 Cookie restore/writeback/双关闭测试已由上述公开行为替代；保留其他平台旧行为、托管所有权、TikTok 发布预算、选项、人类化、覆盖层及封面回归。

实际命令与结果见 [票 02](../issues/02-tiktok-persistent-profile.md) Comments。浏览器日志在本次机器 `/private/tmp/sau-local-profile-notes/02-browser-smoke.log`，离线日志在同目录 `02-targeted.log`、`02-final-local.log`；本文件记录可长期阅读的结论。
