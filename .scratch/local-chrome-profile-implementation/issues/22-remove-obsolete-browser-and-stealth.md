# 22: 删除无业务依据的历史启动代码及 stealth 资源

**What to build:** 按用户 2026-11-17 的明确授权，删除被替代的 TikTok Firefox 实现、未完成的 TencentNote、旧通用本地会话分支及不再需要的 stealth 资源，保留托管会话。

**Blocked by:** [19：一次性迁移](./19-one-time-legacy-migration.md)（已完成）。基于 20 已验证基线 `a61628c`；与 21、23、24 并行。

**Status:** resolved

**依据：** 最新用户指令覆盖原规格关于这些历史调用方/资源的保留要求；历史引用本身不证明实际业务用途。

- [x] 删除 `uploader/tk_uploader/main.py` 旧 Firefox 实现及其失效引用，正式 `main_chrome.py` 保持完整。
- [x] 删除未注册且未完成的 `TencentNote` 及包导出、骨架/旧行为测试和相关死代码；保留 TencentVideo 正式功能。
- [x] 删除 `utils.browser_session._local_session` 旧本地分支，保持托管 provider 路由、配置、日志、参数、所有权、错误和断开/停止契约；不把缺少平台/别名的旧调用偷偷路由到新 Profile。
- [x] 审核引用闭包后删除不再使用的 stealth 注入 helper/import、`stealth.min.js`、打包项及旧测试；保留业务脚本、剪贴板、人类化交互和仍需要的 Bilibili biliup。
- [x] 管理模式的 ignored-option 日志契约继续保持，必要参数不能仅因旧本地分支移除而误删。
- [x] 采用 TDD/相关离线 provider、正式入口和打包检查证明旧入口退出、托管功能未改变；不执行真实账号操作。
- [x] 同步当前规格、CLI/安装/skill/打包文档及索引，说明用户追加决定；历史执行证据不改写。清理范围外的无关功能不扩大。

## Comments

- 2026-11-17：先读取协议、最新用户修正、规格和测试边界；集成分支为工作树祖先。按批准 TDD 接缝先取得 generic 无 provider 与包表面 Red，再完成删除闭包和 Green。相关 897 tests（2 项实际 provider smoke 默认 skip）通过；交互门禁/发行资源补充 4 项通过，解压 wheel 表面 3 项通过；wheel/sdist 离线构建与内容检查通过。完整命令、初始失败和修正见[22 验证记录](../research/22-obsolete-browser-removal.md)。
- 没有真实账号操作；17 平台/Bilibili 与 managed hints、忽略日志、所有权和错误契约保留。历史记录不改写。本票不涉及 21 的目录/资料移动、23 的 Instagram 选择器或 24 的成功文案。

- 源实现 `470ca5f` 后合并最新集成 `05ee329`（含 24）；规格/索引相邻追加冲突保留双方修正。合并后核心会话/包/交互及三平台 no-publish 公共流程 **165 tests 通过**，没有运行真实账号。

## Answer

用户指定的旧 Firefox、未完成 TencentNote、generic 旧 local branch 和无剩余消费者的 stealth 已从运行代码/发行物移除。无 provider 的 generic 调用明确失败；正式本地流程使用显式平台/别名的持久化入口，托管契约完整保留。相关回归与包验证通过，无本票遗留阻塞。
