# 本地浏览器 Profile 迁移实施票

批准日期：2026-11-17。

依据：[原始规格](../local-chrome-profile/spec.md)与用户确认的 20 票拆分。实施票独立编号，原规格、决策地图及五张已解决决策票保留原位。每张票是独立 Markdown 文件，验收复选框表示待完成工作，不表示实施或验证已执行。

## 票据与阻塞关系

| 编号 | 标题 | 交付阶段 | Blocked by |
| --- | --- | --- | --- |
| [01](./issues/01-profile-ownership-and-reset.md) | 安全定位、占用与重建本地 Profile | 第一批 | 无 |
| [02](./issues/02-tiktok-persistent-profile.md) | TikTok 全流程接入持久化 Profile | 第一批 | 01 |
| [03](./issues/03-rednote-persistent-profile.md) | Rednote 全流程接入 | 第一批 | 02 |
| [04](./issues/04-instagram-persistent-profile.md) | Instagram 全流程与作品管理接入 | 第一批 | 02 |
| [05](./issues/05-xiaohongshu-persistent-profile.md) | 小红书全流程接入 | 第一批 | 02 |
| [06](./issues/06-youtube-persistent-profile.md) | YouTube 全流程接入 | 第二批 | 03、04、05 |
| [07](./issues/07-facebook-persistent-profile.md) | Facebook 全流程与作品管理接入 | 第二批 | 03、04、05 |
| [08](./issues/08-facebook-page-persistent-profile.md) | Facebook Page 全流程接入 | 第二批 | 03、04、05 |
| [09](./issues/09-douyin-persistent-profile.md) | 抖音全流程接入 | 第三批 | 06、07、08 |
| [10](./issues/10-kuaishou-persistent-profile.md) | 快手全流程接入 | 第三批 | 06、07、08 |
| [11](./issues/11-tencent-persistent-profile.md) | 视频号正式流程接入 | 第三批 | 06、07、08 |
| [12](./issues/12-baijiahao-persistent-profile.md) | 百家号正式流程接入 | 第三批 | 06、07、08 |
| [13](./issues/13-weibo-persistent-profile.md) | 微博全流程与窗口交互适配 | 第四批 | 09、10、11、12 |
| [14](./issues/14-hupu-persistent-profile.md) | 虎扑全流程接入 | 第四批 | 09、10、11、12 |
| [15](./issues/15-alipay-persistent-profile.md) | 支付宝生活号全流程接入 | 第四批 | 09、10、11、12 |
| [16](./issues/16-dayu-persistent-profile.md) | 大鱼号接入及匿名公开验证 | 第五批 | 13、14、15 |
| [17](./issues/17-zhihu-persistent-profile.md) | 知乎全流程与当次身份接入 | 第五批 | 13、14、15 |
| [18](./issues/18-xueqiu-persistent-profile.md) | 雪球全流程与当次身份接入 | 第五批 | 13、14、15 |
| [19](./issues/19-one-time-legacy-migration.md) | 执行一次性旧资料迁移并删除临时实现 | 五批接入后的一次性作业 | 16、17、18 |
| [20](./issues/20-final-convergence-and-no-publish-validation.md) | 完成全入口收口与四平台真实验收 | 最终交付 | 19 |
| [21](./issues/21-browser-kind-first-layout.md) | 浏览器种类首层布局与现有资料安全搬迁 | 用户追加 | 19，20 已验证基线 |
| [22](./issues/22-remove-obsolete-browser-and-stealth.md) | 删除废弃浏览器入口与 stealth 资源 | 用户追加收口 | 19（已完成） |
| [24](./issues/24-clarify-no-publish-output.md) | 明确三个平台 no-publish 成功摘要 | 用户追加要求 | 19（基于 20 已验证基线） |

## 执行顺序

第一批包含 01–05，第二批 06–08，第三批 09–12，第四批 13–15，第五批 16–18。跨批阻塞落实已批准的交付顺序；同批独立平台不附加相互阻塞。01 先通过显式重建交付安全定位和 Profile 占用，02 通过 TikTok 完整流程交付持久化会话与浏览器实测，再由 03–05 分别接入其余第一批平台。第一批以共享能力和四个平台全部完成为交付边界。

19 在五批平台接入后执行一次性旧资料迁移并移除临时代码；20 完成最终入口、文档与验证收口。新旧入口并存期间，未迁移平台仍按旧行为运行；平台接入票须一次覆盖该平台全部正式动作、内部预检及读写清理。

所有票的初始 Status 为 ready-for-agent。它表示规格已足够清楚，不表示阻塞票已经完成。只选择所有阻塞票均已完成的票；初始可开始的票只有 [01：安全定位、占用与重建本地 Profile](./issues/01-profile-ownership-and-reset.md)。同批依赖满足后可以分别领取，避免将编号先后误当作额外依赖。

## 每张票都要遵守的范围

- 采用术语表中的本地浏览器 Profile、Profile 占用、Profile 重建、账号别名、发布目标、Browser session、不发布模式和发布结果未知。原始规格给出完整契约；票据补充可验证交付边界，不放宽规格。
- 默认 Chrome 有头，支持显式 Chromium、自定义路径和 headless；只要求选定来源，失败不回退。Profile 按 `browser_profiles/<chrome|chromium>/<platform>/<raw_account>` 隔离；21 将守护资料置于账号数据之外，保留 01 的归属、锁与重建语义。
- 平台接入覆盖正式 CLI 可达的全部本地动作及直接支撑它们的 uploader；保持真实 local 模式及既有 session 注入边界。Bilibili biliup 保持原流程。用户追加授权删除指定的历史 TikTok Firefox、TencentNote、旧通用本地会话及无剩余消费者的 stealth 资源，见票 22；其他历史入口不扩大范围。
- 只有 login 引导登录；业务登录失效即结束。使用当前会话所需身份，别名可以换号；显式发布目标和历史作品核验仍有效。正常流程不读取旧登录态，也不承担一次性迁移。
- 保持提交至多一次、发布预算、not-before、结果文件、publish_attempted 和禁止自动重发。用法错误为 2，运行/探测故障为 1，登录/验证为 10，发布结果未知为 9，托管限流为 11；提交后异常保留既有阶段信息和恢复指导。
- 本地退出指纹、语言及固定窗口覆盖，保留 Patchright 默认和业务所需脚本、权限、代理及交互能力。MLX/AdsPower 只改变批准的 headless 来源，其他路由、参数、日志和所有权行为保持。
- 每票运行与其改动相关的行为回归并同步文档，提交记录包含覆盖入口、命令、实际结果、尚未迁移平台和阻塞。测试以正式 CLI 和外部边界为主，不锁定私有拆分，不用模拟冒充实测。
- 01 的跨进程证据和 02 的浏览器实测由实施 Agent 执行。第五批平台不要求新真实账号；20 仅对四个指定平台做已有账号的不发布模式回归，真实发布与作品删除不在验收范围。

## 验收覆盖定位

| 规格契约 | 主要落实票 |
| --- | --- |
| Profile 目录、别名、归属、跨进程占用、显式重建 | 01；02 贯穿会话；03–18 各平台开放 |
| 浏览器来源识别、headless、持久化生命周期、错误与主结果 | 02；03–18 验证接入与平台例外 |
| 登录分类、别名换号、当前身份、显式目标及历史作品 | 02–18；04、07、08、16–18 覆盖作品与身份特例 |
| 五批隔离、托管 headless 与所有权契约 | 02–18；20 最终核对 |
| 参数清理、窗口/剪贴板/代理/匿名 context 例外 | 02–18；16 覆盖大鱼号匿名验证 |
| 一次性旧资料迁移、失败处理、临时代码实际删除 | 19；20 验证最终旧文件被忽略 |
| 安装说明、配置、CLI/skill、Bootstrap 与术语 | 各接入票随实现更新；20 最终收口及两条 CI 安装路线 |
| 离线、跨进程、真实浏览器、四平台不发布模式证据 | 各票离线；01 跨进程；02 浏览器；20 平台实测和总报告 |

## 记录约定

按本地 tracker 约定更新票据 Status，实施讨论与结果追加到相应票的 Comments。不得以存在测试、已准备命令或文档示例替代真实执行结果；未完成验收保持可见。迁移专用代码和测试在 19 完成使命后删除，正常 Profile 回归及执行记录保留。


## 交付记录

- 2026-11-17：[01 已解决](./issues/01-profile-ownership-and-reset.md)。第一批四平台开放显式重建，共享 Profile 归属/跨进程占用已交付；20 项所有权/重建测试和 213 项相关回归通过。当前只改变重建入口，浏览器持久化会话及其实际浏览器验证由 02 继续交付，其余平台按上述阻塞关系接入。

- 2026-11-17：[03 已解决](./issues/03-rednote-persistent-profile.md)。Rednote 的 login/check/视频/图文和直接 uploader/setup 已接入持久化 Profile；152 项相关离线测试及 18 项完整 Chromium 自然 viewport 合成 DOM 测试通过。[验证记录](./research/03-rednote-validation.md) 区分新路径离线证据与留待 20 的真实账号验收。

- 2026-11-17：[04 已解决](./issues/04-instagram-persistent-profile.md)。Instagram 六项动作及直接调用接入持久化 Profile，包含本地 proxy、provider 环境下仍本地的 verify/delete、当前会话身份和原作品作者核验。219 项最终离线/所有权回归及 62 项受影响浏览器夹具回归通过；另完成 141 项 Instagram 功能/受控 DOM 回归。本票未操作真实账号，真实 no-publish 与旧资料作业仍由 20/19 执行。
- 2026-11-17：[05 已解决](./issues/05-xiaohongshu-persistent-profile.md)。小红书全部正式本地动作与直接 uploader 已接入持久化 Profile；324 项平台回归、165 项相关/跨平台回归、7 项真实动态 DOM 测试通过，另有 4/4 受控 no_viewport 浏览器流程。证据见 [05 记录](./research/05-browser-validation.md)。未操作真实账号，平台真实 no-publish 留给 20。

- 2026-11-17：[06 已解决](./issues/06-youtube-persistent-profile.md)。YouTube login/check/upload-video/reset-profile 与直接调用使用持久化 Profile；合入 04 测试修复后 273 项相关回归及完整 Chromium 自然窗口合成 DOM 实测通过，保留托管与上传结果契约。[06 验证记录](./research/06-youtube-validation.md) 区分实际合成浏览器检查与未执行的真实账号动作。

- 2026-11-17：[07 已解决](./issues/07-facebook-persistent-profile.md)。Facebook全部正式本地动作、直接调用与独立作品操作接入持久化Profile，与Facebook Page隔离；保留作者/原作品/正文核验及原有托管路由。合并YouTube06后365项相关离线/共享回归、13项受控浏览器/DOM回归通过；未操作真实账号或作品。见 [07验证记录](./research/07-facebook-validation.md)。

- 2026-11-17：[08 已解决](./issues/08-facebook-page-persistent-profile.md)。Facebook Page 全部正式本地动作和直接调用使用独立持久化 Profile，多个 Page 目标共用同一登录容器，保持显式目标和原作品证据核验。合入 YouTube 06 与 Facebook 07 后 270 项相关离线回归通过，另有 10 项受控 Chrome/DOM 回归通过；未操作真实账号或发布/删除作品。[08 验证记录](./research/08-facebook-page-validation.md)。

- 2026-11-17：[10 已解决](./issues/10-kuaishou-persistent-profile.md)。快手 login/check/视频/图文/reset-profile 与全部可达直接调用使用持久化 Profile；219 项相关离线回归及真实 Chrome 小窗口的两个合成内容流程通过。保留封面、合集、定时、QR 和提交后保护，未操作真实账号。见 [10 验证记录](./research/10-kuaishou-validation.md)。

- 2026-11-17：[12 已解决](./issues/12-baijiahao-persistent-profile.md)。百家号 login/check/视频/reset-profile 与直接调用使用持久化 Profile，严格区分登录/验证与运行故障，保护提交结果及清理所有权。372 项相关离线回归通过，Chrome 有头/完整 Chromium 无头两条受控 DOM 合成流程通过；未操作真实账号或发布作品。见 [12 验证记录](./research/12-baijiahao-validation.md)。

- 2026-11-17：[14 已解决](./issues/14-hupu-persistent-profile.md)。虎扑 login/check/视频/reset-profile 与直接 setup/uploader 复用持久化 Profile；移除 UA/viewport/webdriver context 重建和旧 JSON 流程，保留 QQ popup/二维码、文件选择器、专区弹窗与提交保护。合入微博 13 后 364 项相关回归通过；Chrome 有头与完整 Chromium 无头两条受控 DOM 流程通过，未操作真实账号或发布作品。见 [14 验证记录](./research/14-hupu-validation.md)。

- 2026-11-17：[15 已解决](./issues/15-alipay-persistent-profile.md)。支付宝生活号 login/check/视频/reset-profile 和直接调用接入持久化 Profile，QR 回调与 qiankun 无 stealth 保留，登录分类与提交结果保护完整。合入微博、虎扑和 TikTok 生命周期补丁后 340 项相关离线检查通过；Chrome 有头/完整 Chromium 无头两条自然窗口受控 DOM 流程通过，未操作真实账号或作品。见 [15 验证记录](./research/15-alipay-validation.md)。

- 2026-11-17：[17 已解决](./issues/17-zhihu-persistent-profile.md)。知乎 login/check/文章/视频/verify/reset-profile 和直接调用接入持久化 Profile，支持同别名换号并保留当前字段、历史作品证据和文章编辑链。合入大鱼号 16 和雪球 18 后 376 项相关离线回归及 6 项已有测试通过（含 1 项真实 Chrome 合成 DOM 文章完整性测试）；未操作真实账号或作品。见 [17 验证记录](./research/17-zhihu-validation.md)。

- 2026-11-17：[16 已解决](./issues/16-dayu-persistent-profile.md)。大鱼号 login/check/视频/文章/verify/reset-profile 与直接调用接入持久化 Profile，当前身份替代旧绑定，公开核验保持匿名隔离和主锁。合入雪球 18 后 157 项相关离线检查、15 项真实浏览器合成 DOM/内容回归及 Chrome 有头/完整 Chromium 无头 2 条受控匿名流程通过；未操作真实账号或作品。见 [16 验证记录](./research/16-dayu-validation.md)。

- 2026-11-17：[18 已解决](./issues/18-xueqiu-persistent-profile.md)。雪球 login/check/文章/verify/reset-profile 与直接入口使用持久化 Profile，移除旧身份旁文件约束，保留当次主体和历史作者核验及结果路径。299 项相关离线检查、16 项浏览器/内容检查通过，完整文章合成流程在 Chrome 有头和 Chromium 无头通过；未操作真实账号或作品。见 [18 验证记录](./research/18-xueqiu-validation.md)。

- 2026-11-17：[19 已解决](./issues/19-one-time-legacy-migration.md)。实际完成 TikTok/lukechen、Rednote/rednote、Instagram/luke、小红书/180 原仓库 Chrome 有头迁移；每项持续占用至两次正向探测与两次严格正常关闭后定向删除旧 Cookie。四个 Profile 保留，四个旧文件均已清理，临时迁移代码/入口/专用测试已实际删除；11 项临时合成验证、移除后97项正常Profile回归通过。见[实际执行与移除记录](./research/19-migration-execution.md)。剩余目标0、阻塞无，20可开始真实no-publish验收。


- 2026-11-17：[20 原定范围验收已完成，整体仍待追加要求](./issues/20-final-convergence-and-no-publish-validation.md)。17 个浏览器平台、87 个正式动作完成最终审计；最小配置导入、小红书已认证 login、Instagram 实际中文入口及本地 no-publish 输出修复。集成离线 2,030 项（2 skip）、最后相关 274 项、受控浏览器 33 项及最后 6 项通过；原仓库四平台普通 login/重开 check 与全部 8 个真实 no-publish 流程通过，无实际发布或删除。用户随后要求改为 kind/platform/account 目录并移除明确废弃的旧入口与 stealth 资源；本基线不宣称这些追加工作已完成，父规格保持未完成。见 [20 分层验证记录](./research/20-final-validation.md)。

- 2026-11-17：[22 已解决](./issues/22-remove-obsolete-browser-and-stealth.md)。按追加授权删除旧 TikTok Firefox、TencentNote、generic local branch 和 stealth helper/资源/打包/旧测试；保留正式业务与完整 provider 契约。897 项相关回归（2 skip）、交互/资源门禁 4 项、解压 wheel 3 项及 wheel/sdist 检查通过；未操作真实账号。见 [22 验证记录](./research/22-obsolete-browser-removal.md)。
- 2026-11-17：[24 已解决](./issues/24-clarify-no-publish-output.md) 明确 Rednote、TikTok、小红书视频/图文 no-publish 成功摘要；本地及托管统一说明素材上传、检查完成且未点击发布，历史日志原文保留。305 项离线与 18 项真实浏览器受控 DOM 检查通过；未操作真实账号或额外上传。验证结果见票据 Comments。

- 2026-11-17：[23：Instagram 普通号/creator 界面兼容](./issues/23-instagram-account-ui-compatibility.md) 承接用户账号类型更正。保留普通号直接编辑器，按实际 DOM 识别 creator 帖子子菜单，覆盖两种媒体、人类化交互与发布前停止；真实 creator 复验须等待 21 完成 Profile 搬迁并释放账号。
