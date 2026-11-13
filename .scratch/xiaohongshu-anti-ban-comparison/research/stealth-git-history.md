# stealth.js 注入的 Git 历史与原仓库证据

核查日期：2026-11-13（Asia/Shanghai）。检查本地 Git 对象，并通过 GitHub 公共 API 核验 fork 来源、原始提交、关联 PR 与讨论。没有修改业务代码，没有进行账号登录或发布。

## 结论

注入最早来自原项目使用普通 Playwright 时的反自动化检测方案。小红书早期签名流程已使用该脚本；后来抽成跨平台公共工具，新版小红书登录/发布流程继续复用。迁移到 Patchright 时仍然保留，并未找到证明“Patchright 必须同时注入这份 JS”的实验或详细设计论证。2026-11-11 本 fork 的文档又明确决定本轮不改本地浏览器配置。

“当初为什么加入”已有明确提交证据；“今天继续注入是否仍有净收益”没有因此得到证明。

## 仓库关系

本地 origin 为 `chancetop-com/social-auto-upload`。GitHub 仓库 API 返回 `fork=true`，`parent.full_name` 和 `source.full_name` 均为 `dreammis/social-auto-upload`。原仓库为 [dreammis/social-auto-upload](https://github.com/dreammis/social-auto-upload)，不是此前用于比较的 `xpzouying/xiaohongshu-mcp`。

## 时间线

### 2023-12-08：小红书早期签名流程已经注入

提交 [`eec0a68`](https://github.com/dreammis/social-auto-upload/commit/eec0a68e3a342700613ab619e52af5fa3ef25523) 新增 `xhs_uploader/main.py`。当时使用 `playwright.sync_api`，`sign_local()` 启动无头 Chromium，在新 context 上调用 `add_init_script`，随后打开小红书页面，调用页面签名函数。

脚本文件名是 `xhs_uploader/cdn.jsdelivr.net_gh_requireCool_stealth.min.js_stealth.min.js`，说明其最早作为已有 stealth 文件被纳入；仅凭文件名不能证明该外部项目的具体版本或所有技术来源。提交只写增加小红书功能，没有独立的反检测效果对照。该时期的签名方案也不是当前的创作者中心 UI 发布链路。

### 2024-06-14：明确以“避免检测”为由公共化

提交 [`096f5f8`](https://github.com/dreammis/social-auto-upload/commit/096f5f87c23ce49acfadaa0944809ab16c6b1022) 的原始说明：

> 1. add stealth to avoid detect

这个提交新增 `utils/stealth.min.js` 和公共函数 `set_init_script(context)`；抖音、视频号、TikTok 的登录/会话检查/上传调用接入该函数，旧小红书签名代码改为读取公共脚本路径。当时这些实现使用普通 Playwright，Patchright 尚未出现在这些调用中。

GitHub API 对该提交返回的关联 PR 与 commit comments 都为空，所以没有找到更详细的“具体平台拦截样例、移除对照或封禁率”讨论。可确定的是维护者明确的反检测意图，不能把该意图当作效果验证。

### 2025-06-03：当前小红书 UI 上传器继承注入

提交 [`86fb7f6`](https://github.com/dreammis/social-auto-upload/commit/86fb7f65635fb76a90dec27210e3aeb3c24ccd02) 新增 `uploader/xiaohongshu_uploader/main.py`，使用 `playwright.async_api`。`cookie_auth`、扫码登录和视频上传都调用公共 `set_init_script`。提交说明只描述新增小红书登录/发布相关脚本，没有额外的 stealth 效果证据。

### 2026-03-25：迁移到 Patchright，但保留注入

提交 [`2277a5f`](https://github.com/dreammis/social-auto-upload/commit/2277a5fdf9651ac737a5f88e4a78b26dfdf7766c) 将小红书模块的导入从 Playwright 改成 Patchright；重写后的会话检查、登录、视频与图文上传依然调用 `set_init_script`。该提交说明仅为“临时留档”，关联 PR 查询为空，没有找到为什么需要“Patchright + stealth.js”叠加的解释。

### 2026-11-11：本 fork 明确暂不改配置

本地提交 `8a098e7852dc00e8aa993c7454d13b783c19827c` 收口本地浏览器配置决议，明确不删除 `_xhs_user_agent()`、不删除 stealth 注入，也不改用持久 context。该决议是变更范围选择，并没有声称现状防检测效果更好。[决议正文](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.scratch/xhs-publish-reliability/issues/19-local-browser-hygiene.md:37)

## 文件是否被持续调整

执行 Git blob 对比：

```text
HEAD:utils/stealth.min.js       166d1d746c99557fc4dc13d7a227fa62a602861a
096f5f8:utils/stealth.min.js    166d1d746c99557fc4dc13d7a227fa62a602861a
```

本地当前文件与 2024-06-14 公共化时的文件逐字节一致。期间目录迁移没有改变这个事实。2023 年最早文件的 blob 为 `d53498cdffbda9d80e8e41f722ba10b564a75d59`，与 2024 年版本不同，不能把“完全未变”的起点延伸到 2023 年。

## 原仓库后续反馈

- [PR #287：修复不要伪造 CPU 和显卡信息](https://github.com/dreammis/social-auto-upload/pull/287)，创建于 2026-09-12。贡献者报告在 macOS ARM64、Patchright 1.58.2、有头 Chromium 下，原 bundle 将 `hardwareConcurrency` 固定为 4，WebGL 固定为 Intel；移除两段覆盖后，页面和 iframe 恢复浏览器原生硬件信息。其说明提供本地浏览器 fixture 的前后验证，明确没有平台账号或上传测试。截至本次查询，状态为 **closed，merged=false**，comments/reviews 均为空，不能推断维护者关闭原因，也不能当作已经进入当前代码的修复。
- [Issue #307](https://github.com/dreammis/social-auto-upload/issues/307) / [PR #308](https://github.com/dreammis/social-auto-upload/pull/308)，2026-11-06。报告旧 Patchright 1.58.2 在注入 init script 时改写 CSP，意外阻止抖音 blob Worker，导致上传失败；方案是升级依赖。报告者后续更正 Python 首个带修复版本为 1.61.2。本项目当前已用 1.64.4，因此不能把这个旧版本问题说成当前仍然存在。它只说明额外注入有可能带来功能副作用，不是小红书封禁证据。
- [PR #241](https://github.com/dreammis/social-auto-upload/pull/241) 提出额外的指纹随机化与行为延时；截至查询仍 open、未合并。这类未合并提案不能反过来证明现有 stealth 已有效，也不能算当前实现。

因此，历史支持把当前注入称为“从普通 Playwright 时期继承、迁移后继续保留的反检测层”。是否继续保留、缩减或删除，应重新比较当前浏览器实际输出与流程兼容性，不能仅凭原提交意图决定。
