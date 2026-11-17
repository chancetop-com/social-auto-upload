# 20: 完成全入口收口与四平台真实验收

**What to build:** 所有正式本地浏览器动作都使用 Profile，用户能按文档选择并准备浏览器；四个指定平台用已有账号完成真实登录、关闭重开检查和不发布模式验证，交付清晰区分离线、浏览器与平台证据的最终记录。

**Blocked by:** [19：执行一次性旧资料迁移并删除临时实现](./19-one-time-legacy-migration.md)；最终收口还包含已完成的用户追加 [21](./21-browser-kind-first-layout.md)、[22](./22-remove-obsolete-browser-and-stealth.md)、[23](./23-instagram-account-ui-compatibility.md)、[24](./24-clarify-no-publish-output.md)。

**Status:** resolved

**批次：** 最终交付

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [x] 按正式 CLI 注册动作逐一核对全部五批平台及可达启动链，覆盖独立 check、内部预检、视频/图文/文章和已有 verify/delete；确认临时新旧分流、旧 JSON 预检/恢复/导出和旧身份防错配逻辑已退出正式范围。
- [x] 结合 19 的执行与删除记录，确认不再存在本次新增的一次性迁移入口、识别、重启复验、清理/重试或停用分支；用正常 login/check/业务的外部行为验证旧文件重新出现仍被忽略，普通 login 不额外重启。
- [x] 按用户追加的 22 删除指定历史 TikTok Firefox、TencentNote、旧 generic local 分支及无剩余消费者的 stealth helper/资源/包数据/旧测试；保留 Bilibili biliup、正式业务及 managed 契约，不保留本次临时迁移实现。早期历史入口保留结论已被追加授权覆盖。
- [x] 最终基础安装不无条件下载或检查 Chrome/Chromium；本地仅要求实际选定来源，托管两者都不要求。系统 Chrome 缺失时说明由用户依 Google 官方指引安装，项目不自动安装/更新，也不把 Patchright 安装 Chrome 作为默认路线。
- [x] README 与安装指南完整呈现两条独立的按需 CI 安装路线：已有研究中的 Ubuntu 24.04 x64 官方 Chrome amd64 DEB，以及项目固定 Patchright 配套完整 Chromium；说明各自系统依赖、无显示有头运行的 Xvfb、项目版本/缓存一致性及兼容自定义 binary 复用。
- [x] Chromium 文档提供可选的 uv run patchright install --no-shell chromium，说明普通 Chromium 安装可用、仅 headless shell 不满足运行契约；安装示例不冒充已执行结果，不新增 workflow 或 CI 验收系统。
- [x] 收口配置示例、各平台 CLI/skill、登录说明、Agent Bootstrap、运行依赖说明及本地模式术语，使其符合最终已实现状态；安装完成、浏览器能启动和平台已登录分别表述，不覆盖用户既有 headless=True。
- [x] 汇总各批相关离线回归，并补足最终入口清单暴露的实际缺口；除批准 headless 来源及 24 的成功摘要外，托管 provider 路由、所有权、启动/ignored-option 日志和错误契约保持，23 的两种界面业务兼容不改变 provider；无新改动或疑点不无理由重复完整测试矩阵。
- [x] 核对 02 的真实 Chrome/Chromium、有头/无头、自定义路径、持久化与匿名隔离证据；共享能力后续改变时补跑受影响项。未运行的环境明确列出，模拟测试不替代真实浏览器证明。
- [x] 由实施 Agent 在执行时落实用户已有 TikTok、Rednote、Instagram、小红书账号和素材，以默认 Chrome 有头路径分别执行 login、正常关闭后重开 check，以及正式视频/图文发布前流程；不把四平台真实回归交给用户手动完成。
- [x] 真实视频/图文命令全部显式使用 no-publish，并核对参数传递和实际停止点；任何入口保护缺失都先修复并离线证明，再运行真实流程。保留素材上传、编辑和发布就绪检查后停止的语义，不能靠提前跳过这些步骤充当验收。
- [x] 不实际提交发布、不删除真实作品，也不为验证作品管理先发帖；verify/delete、提交后异常和结果观察由相关离线回归覆盖。其他平台与托管不要求新真实账号，不扩展全浏览器配置的真实平台矩阵。
- [x] 最终报告分列离线结果、浏览器实测、四平台不发布模式结果，记录配置、命令、实际停止点和具体失败/阻塞；说明真实素材上传可能留下临时素材或草稿，成功只证明提交前流程，不证明实际发布、not-before 等待、发布后验证或防封禁。
- [x] 只有五批接入、一次性迁移执行与临时代码删除、文档和约定验证都落实才标记实施完成；未执行或阻塞项明确保留，不以离线替身或安装说明代替实际证据。最终独立代码审查仍由 root 后续执行。
- [x] 21 的 kind/platform/account 布局和四份实际资料安全移动、四次正常重开 check、临时搬迁程序删除落实，历史路径不改写。
- [x] 23 的 ordinary/creator × 视频/图文兼容、语义选择器与 Humanizer 验证落实；真实 creator 两次 no-publish 通过，普通号仅受控证据如实标明。
- [x] 24 的三平台本地及适用托管明确停止摘要落实，失败不误报、发布零点击，历史日志不改写。
- [x] 所有追加代码集成后，从隔离工作树完成最终离线回归，真实浏览器用例分列引用其已执行证据。


## Comments

- 2026-11-17：原定范围的全入口/资源审计、文档收口和四平台实际验收已完成。详细配置、命令、停止点、失败修复、证据边界见 [20 验证记录](../research/20-final-validation.md)，实际命令见 [JSONL](../research/20-live-events.jsonl)，注册覆盖见 [CLI 清单](../research/20-cli-inventory.json)。
- TDD：公共最小配置强制 import 缺陷先红后绿；三个配置 fixture 先复现 2 failures/1 error 后 3 项通过；小红书已认证重定向、Instagram 实际帖子子菜单/继续按钮、TikTok/小红书本地 prepared 文案均先复现再修复。托管原行为与输出有对应回归。
- 离线：首次 live 前停止保护 124 项通过；集成集合 2,030 项（2,028 通过、2 个原有 opt-in skip），真实浏览器项分列；最后受影响 274 项全部通过。工作树文章依赖未准备导致的首轮失败已明确修复后全量重跑。
- 真实浏览器合成页面：Instagram 33 项通过，最后修改的 6 项再次通过。沿用 02 的 Chrome/Chromium、channel/custom、有头/无头 8 组合实测；本票未改变共享来源/会话能力，未执行 Linux CI 安装示例。
- 真实平台：原仓库 TikTok/lukechen、Rednote/rednote、Instagram/luke、小红书/180 均默认 Chrome 显式有头普通 login、正常关闭后独立 check、视频/图文显式 no-publish 通过。共 8 个实际上传/编辑/发布就绪流程均停在最终发布按钮之前；无真实发布或删除。小红书一次 login、Instagram 两次 video 的初始失败和修复后成功记录全部保留。原配置未改，真实 Profile/结果留在原仓库。
- **用户追加要求，整体尚未完成：** 实测完成后要求改为 `browser_profiles/<chrome|chromium>/<platform>/<account>`，并明确授权移除历史 TikTok Firefox、未注册 TencentNote、旧 generic local session 和无剩余依赖的 stealth 资源/打包/旧测试。停止所有实际账号操作，将本票已验证基线交给后续实施；本提交不移动数据或实施新增删除。最后整体完成复选框与 Status 保持待完成，父规格未标完成。后续必须安全迁移四个真实 Profile、重开 check、完成删除和最终独立审查后再收口。

- 2026-11-17 最终收口：21–24 全部 resolved 并集成到 `91d2cc03`，本工作树 fast-forward 后逐项核对新布局/同 inode 移动/四次 check、历史代码和资源删除/发行物、Instagram 两种页面/Humanizer/真实 creator 两次复验、三平台停止摘要。以上历史 Comments 保留当时状态，当前以本条及 Answer 为准；没有再次账号操作或上传。
- 最后隔离离线回归收集 2,123、选择 2,025、分列 98 个已单独实测的真实浏览器用例（含 23 新模块全部 6 项）；实际 124.370s，2,023 passed / 2 个既有 opt-in provider smoke skipped，0 failures/errors，无新代码修复。公共 parser 仍为 17 平台 / 87 浏览器动作 / 93 总动作，所需 flags 全部存在。完整命令、manifest/log 与各项证据见 [累计最终记录](../research/20-final-validation.md)。

## Answer

原定迁移及用户追加 21–24 的实施和约定验收均已完成，17 平台正式本地入口使用当前 kind-first 持久化 Profile；旧资料/旧布局临时作业已执行并退出，授权废弃代码及 stealth 已删除，文档与按需浏览器安装路线已收口。原四平台八个真实 no-publish 结果、后续四份资料移动/check 及两次受影响 creator no-publish 复验均有分层证据，用户配置/实际 Profile/历史结果保留。普通 Instagram 只报告受控验证，未实际发布或删除作品。

本票和父规格 resolved 表示实施与约定验收落实；**最终独立两轴代码审查、必要后续修复和工作树清理由 root 继续执行，本票不冒充独立审查结果**。没有剩余实现验收阻塞。
