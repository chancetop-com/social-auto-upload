# 20：累计最终验证记录

## 最终交付完成：合并与工作树清理（2026-11-17）

**当前状态：原 01–20、用户追加 21–24、两轴独立审查、全部修复、原审查者复核、集成合并和最终工作树清理均已完成。** 全部 24 张实施票为 resolved，无剩余实施验收、审查发现、合并或清理待办。本节更新下方历史检查点中的待执行状态，不改写原始测试、实际操作、失败或路径记录。

### 实际集成合并

- 分支：原仓库 `codex/local-chrome-profile`。合并前集成 `cc23b9d3631bfd85980bae4f8885ffadc8233eeb` 和源工作树均干净，源分支以该集成提交为祖先。
- 已复核运行时代码为 `e1ed1b684fc096d5c6f177f643fc38242c2e9fe2`；源分支 `codex/local-profile-review-fixes` 的最终提交 `350960fc755de86587130dfbb2283f4894fc9a57` 只追加原审查者的独立关闭记录。
- 使用 `git merge --no-ff` 完成无冲突合并，提交为 `75cc278a7c90851f60ad461198379c27592eaa8d`，两个父提交分别为上述集成与最终源提交。
- 合并树与源提交树完全一致，均为 `8ef581d51d742d49f516844a8c9bb8b1d981627b`；`git diff --exit-code HEAD codex/local-profile-review-fixes` 和 `git diff --check HEAD^1 HEAD` 通过，合并后集成工作树干净。

### 实际工作树清理与保留范围

root 在上述合并后完成清理，外部执行记录 `/private/tmp/sau-local-profile-notes/cleanup-result.json` 的 `integration_head` 为 `75cc278a7c90851f60ad461198379c27592eaa8d`、`outcome` 为 `removed`，逐项记录了 **25 个已核验并移除的本任务工作树**：`/private/tmp/sau-local-profile-01` 至 `/private/tmp/sau-local-profile-24`，以及 `/private/tmp/sau-local-profile-review-fixes`。这些路径在早期命令中继续作为历史执行位置保留，不再是可用工作目录。

清理后由收口者再次读取 `git worktree list --porcelain`，仅剩以下 3 个工作树；两个既有外部工作树均未移除：

| 保留工作树 | 范围 |
| --- | --- |
| `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload` | 原集成仓库 |
| `/Users/chancetio/.local/share/opencode/worktree/d25f15/playful-meadow` | 既有外部工作树 |
| `/Users/chancetio/.local/share/opencode/worktree/d25f15/quick-meadow` | 既有外部工作树 |

root 清理后独立核对原仓库四个目录仍在：`browser_profiles/chrome/tiktok/lukechen`、`browser_profiles/chrome/rednote/rednote`、`browser_profiles/chrome/instagram/luke`、`browser_profiles/chrome/xiaohongshu/180`。原仓库 Profile、`conf.py` 和 `.local` 历史结果不在工作树清理范围内，均保留；清理及本次文档收口没有操作账号、重建/移动 Profile、改写用户配置或结果，也没有发布或删除真实作品。目录存在核对不冒充新的登录有效性检查。

本次 closeout 仅更新文档，没有运行新测试或浏览器。最终离线证据仍是下节的 **2,031 项：2,029 passed、2 个既有 opt-in skip、0 failures/errors**；98 项浏览器证据、四平台 8 次 no-publish、搬迁后 4 次 check 和 creator 2 次复验继续按各自已执行记录引用，普通 Instagram 的受控证据边界不变。原始历史日志与用户追加要求完整保留，没有 push。

## 独立审查后的修复记录（2026-11-17）

针对固定基线 `47cc1850` 到最终审查快照 `cc23b9d3` 的两轴独立审查已完成：[Spec 报告及处置](./final-review-spec.md)记录 2 项 P2；[Standards 报告及处置](./final-review-standards.md)记录 3 项 P3 与 3 项可选维护性建议。一个新的隔离实施者已处理全部项目，保留原始报告并逐条列出处置与验证。Spec 的 HTTP/认证混合故障和跨站跳转误判先有公共 CLI RED，再修复 GREEN；托管和提交后语义保留。

最终隔离离线回归 **2,031 项 / 126.637s：2,029 passed、2 个既有 opt-in 服务 smoke skip、0 failures/errors**。仍分列相同 98 个先前已验证浏览器用例，没有再操作真实账号或上传。包发现规则包含两个新共享 Python 模块，无需新发行构建。普通 Instagram 仍只有受控证据，原 live/搬迁/用户配置记录均保留。

原两轴审查者已独立复核候选 `e1ed1b684fc096d5c6f177f643fc38242c2e9fe2`，全部发现关闭。Spec 独立隔离快照执行 13 个公共边界方法，1.470s 全部通过；Standards 独立核对 17 个适配器的 2,210 个别名组合，0 差异，并确认 14 个私有 builder 转换等价、26 个公共构造签名未变。完整复核记录追加在上述两个报告中；未重复累计/真实浏览器测试或账号操作。

**独立审查、全部修复、实施者验证和原审查者复核均完成；集成合并及 root 负责的最终工作树清理仍待执行。** 以下是票 20 原始累计记录，保留当时的时间、路径和状态表述。

## 最终收口：包含用户追加的 21–24

2026-11-17，集成代码 `91d2cc03`。原定 01–20 及追加 21–24 的实现和约定验收已完成；本票、实施索引及父规格可标 resolved。**最终独立两轴代码审查仍由 root 后续执行，本记录不是独立审查结果，也不声称审查或最终工作树清理已完成。** 本轮只做隔离离线回归、公共 parser 核对和文档收口，没有再次启动实际账号或上传素材。

当前运行契约与追加证据：

| 追加票 | 当前结果 | 离线/包证据 | 真实浏览器或平台证据 |
| --- | --- | --- | --- |
| [21：新布局](./21-layout-validation.md) | `browser_profiles/<chrome|chromium>/<platform>/<raw_account>`；外置归属、guard 与重建标记；无旧布局回退 | 30 项共享、post-merge 121 项等通过，真实进程占用/碰撞/重建保护保留 | 相同 Profile 测试集合 sandbox 外 352/352；新布局 8 配置完整持久化/匿名隔离矩阵通过；四个原 Profile 同 inode 移动并各自正常 Chrome 有头 check valid/0 |
| [22：废弃实现删除](./22-obsolete-browser-removal.md) | 旧 TikTok Firefox、TencentNote、generic `_local_session`、stealth helper/资源/包数据和专属旧测试已删除；通用会话无 provider 明确拒绝 | 897 项（2 skip）、合并后 165 项及解压 wheel 检查通过，wheel/sdist 内容检查保留 Bilibili 与 article renderer | 无账号操作，不把包检查当浏览器实测 |
| [23：两种 Instagram 界面](./23-instagram-account-ui.md) | ordinary 直接编辑器、creator 帖子子菜单均由当次 DOM 判断；保留 Humanizer、阶段分离与可交互 Share 检查 | 合并后 101 项通过；保留 local/managed 生命周期与结果契约 | 新受控 Chrome 6 测试/19 场景、既有 33 项及最终就绪 5 项通过；新布局真实 creator 视频/图文 no-publish 均通过。普通号只有受控证据 |
| [24：明确停止摘要](../issues/24-clarify-no-publish-output.md) | TikTok、Rednote、小红书六个媒体动作的适用 local/managed no-publish 成功摘要为“素材已上传，发布前检查已通过；已停止，未点击发布按钮。” | 305 项离线通过，成功/失败/登录失效和零点击均覆盖 | 18 项既有 Rednote 真实浏览器合成 DOM 通过；文案改动没有额外上传 |

21 的实际移动保留四个原资料的 inode、原 conf.py 和历史结果；四个精确旧叶子已不存在，未知旧 Instagram `.DS_Store` 与父目录保留。每个新 Profile 正常 check 后又取得/释放占用；无 reset、重新登录、覆盖/合并目录、跨浏览器复制、读取 Cookie/History 内容、清 singleton 或杀外部进程。一次性搬迁程序已删除。详细旧/新路径与执行事实仅追加在 [21 搬迁事件](./21-relocation-events.jsonl)，下方原 19/20 执行路径不改写。

23 在 21 搬迁/check/guard 释放后，当前真实 creator 账号以 HUMANIZE=1、默认系统 Chrome 有头分别完成视频（12:00:31 UTC）及图文（12:01:06 UTC），均退出 0，结果 prepared，日志明确停在 Share 前；没有发布字段或清理警告。获批素材、完整参数与新路径见 [23 实际事件](./23-live-events.jsonl)。因此实际证据是原四平台 8 个 no-publish 流程，另加受影响 Instagram creator 2 次复验；不是两个真实 Instagram 账号，不证明真正发布、等待定时、发布后核验或风控。素材仍可能留作临时素材/草稿。

### 最后集成离线回归

共享路径、旧会话删除及 Instagram 业务选择器均已变化，因此本轮完整离线重跑有必要。执行前确认 `/private/tmp/sau-local-profile-20` 的忽略配置 `BASE_DIR` 指向工作树、`LOCAL_CHROME_HEADLESS=True`、`LOCAL_BROWSER` 缺省、无自定义路径，与原用户可选设置等价；文章依赖通过 ignored node_modules symlink 复用。原仓库配置/账号资料不参与离线测试。

```sh
# cwd: /private/tmp/sau-local-profile-20
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python /private/tmp/sau-local-profile-notes/run20-final-offline.py
```

外部 runner 复用前述 unittest discover 选择方式：分列基线 80 个已识别真实浏览器用例和 12 个 `*_profile_dom` 用例，再明确分列票 23 新增 `tests.test_instagram_account_ui` 的全部 6 个方法。共收集 **2,123 项**，选择 **2,025 项离线**，分列 **98 项真实浏览器**；没有通过忽略新失败改变选择。manifest 确认新模块 6 项均在 deferred、0 项在 selected。真实浏览器项由各票的已执行记录证明，本轮未重跑无变化的浏览器矩阵或实际账号。

**实际结果：2,025 tests / 124.370s；2,023 passed、2 个既有 MLX/AdsPower opt-in 实际服务 smoke skipped；0 failures、0 errors。** 原始日志 `/private/tmp/sau-local-profile-notes/20-cumulative-offline.log`；完整选择清单 `/private/tmp/sau-local-profile-notes/20-cumulative-offline-manifest.json`。无需代码修复。不同阶段与受影响子集存在重叠，不相加声称唯一测试总数；本轮数量变化包含旧测试删除及新回归加入。

当前公共 `sau_cli.build_parser()` 再核对仍是 **17 浏览器平台 / 87 浏览器动作 / 93 总动作**，所有普通动作具备 account/local-browser/headless/headed，reset 具备 account/browser-kind，与[原入口清单](./20-cli-inventory.json)一致。文档提供两条按需 CI 安装路线；仍未执行 Linux CI/Windows 原生实测，未新增 workflow、未自动安装/更新 Chrome。原实现验收与追加要求均无剩余阻塞；下一步是 root 的独立审查。

## 原定范围历史记录（af47cf4，以下事实按执行当时保留）

日期：2026-11-17，Darwin arm64。实施基线：`1c8220b`，工作分支 `codex/local-profile-20`。本记录分别列出离线替身、真实浏览器合成页面和真实平台证据。

**交付状态：原定 20 票范围的实现、文档及实际验收已落实；整体任务尚未完成。** 实测结束后，用户新增要求把 Profile 改为 `browser_profiles/<chrome|chromium>/<platform>/<account>`，并删除历史 TikTok Firefox 入口、未注册 TencentNote、旧 generic local session 及无剩余依赖的 stealth 资源/打包/测试。这两项由后续实施处理；本提交未移动任何真实 Profile、未改变布局、未实施这些删除，也不把原方案的资源保留结论当作新要求的完成证据。新布局仍须安全移动四份真实 Profile 并重开检查，最后再进行独立代码审查。父规格保留未完成状态。

## 正式入口与资源审计

由实际 `sau_cli.build_parser()` 导出的 [入口清单](./20-cli-inventory.json) 包含 17 个浏览器平台、87 个注册浏览器动作（含 17 个 reset），另有 Bilibili/article 的 6 个动作，共 93 个。所有普通浏览器动作都有 account/local-browser/headless/headed，所有 reset 都有 account/browser-kind。清单证明注册覆盖，不代表真实平台执行。

逐个追踪 login、独立 check、内部预检、视频/图文/文章、已注册 verify/delete 到共享 `local_browser_session`：所有正式本地获取均为持久化 context，真实 local 模式，不导入/恢复/导出旧 storage-state JSON；业务沿用当前 session，托管分支仍由原 provider 管理。覆盖平台为 TikTok、Rednote、Instagram、小红书、YouTube、Facebook、Facebook Page、抖音、快手、视频号、百家号、微博、虎扑、支付宝生活号、大鱼号、知乎、雪球。

审计保留的边界：

- Bilibili biliup 与其独立账号 JSON、二进制运行/下载链仍有正式调用；article renderer 资源仍服务正式文章处理。
- 托管调用的既有 hint dictionaries、ignored-option 日志和 TikTok managed `?lang=en` 探测 URL 保留；本地不向 context 注入 viewport、UA、locale、headers、geolocation 或 stealth。原有业务代理和限定 origin 的剪贴板授权仍保留。
- Dayu/Xueqiu 的 cookie-shaped 路径仅定位历史结果文件，不恢复账号。当前身份与历史作品作者核验保留。
- Dayu 匿名公开验证从当前 browser 创建无 storage-state 的独立 context，以有界清理结束，主 Profile/锁仍属于外层。
- Dayu preview.close 仅走 managed 分支；Xueqiu auxiliary.close 也仅走 managed 分支。替身边界设为永不返回时，本地完整路径仍正常返回和清理；托管相同等待风险已存在于基线 `47cc185`，未在本票扩大修改范围。
- 在**原定审计范围**中，历史 Firefox TikTok、未注册 TencentNote 和 generic local compatibility 分支仍调用旧资源，因此当时未删除 stealth。用户随后已明确授权移除这些调用方与资源，此项现为后续待办，不能再据此宣称它们需要永久保留。

[19 实际迁移/移除记录](./19-migration-execution.md) 已落实四份旧资料迁移、8 次正向探测、8 次严格正常关闭、四份精确旧 JSON 删除及全部临时代码/测试移除。当前正式代码没有新增一次性迁移入口、重启复验、清理重试或停用分支。相关公共入口测试证明旧 JSON 再出现也被忽略、普通 login 只获取一次 session。四份真实 Profile 一直保留于原仓库。

## 原定范围的修复与文档

1. 公共 `sau_cli --help` 在仅有 `BASE_DIR` 的配置下曾因 optional browser constants 的强制 import 失败。百家号、快手、微博、视频号改用兼容缺省；不改变已有 managed 默认值。
2. 三个集成 fixture 分别依赖不存在的 LOCAL_BROWSER、用户 HEADLESS=False 假设；改为明确隔离配置，生产配置未改。
3. 小红书已登录 Profile 会把 `/login` 重定向到工作台；原实现无条件等待 QR 导致真实登录验收失败。现在仅识别为登录页时取 QR，但仍须实际正向 publish-page probe 才返回成功。缺少 QR 本身不代表成功，未知页面与验证页仍分别保持故障/登录所需分类；新 QR 登录回调与清理仍有覆盖。
4. Instagram 本机实际中文界面在 Create 后出现“帖子/直播视频/广告”子菜单，裁剪步骤主动作是“继续”。依据实际截图/DOM，为 local 添加明确的帖子 icon 入口和继续名称；保留原 managed 选择器与路由。素材上传、配文、编辑和 no-publish 停止点完整执行。
5. TikTok/小红书 local no-publish 的 CLI 曾输出 submitted；现在明确输出 prepared (not published)。Rednote 已如此，Instagram 结果已是 prepared。managed 与真正提交时的既有输出及 exit/result 契约不变。

README、CLI、安装/更新、agent bootstrap、配置样例、术语、技能分发和受影响独立 skill 已收口为 17 平台 Profile 模式。基础安装无浏览器下载/检查 hook。浏览器仅按实际来源准备；保留已有 `HEADLESS=True`，显式 CLI 可以覆盖。文档依据既有研究完整列出 Ubuntu 24.04 x64 Google 官方 amd64 DEB 与固定 Patchright 配套完整 Chromium 两条可选 CI 路线，包含系统依赖、Xvfb、缓存/版本一致性、自定义 binary 复用和可选 `--no-shell`。**未执行这些 Linux 安装示例，没有新增 workflow 或 CI 系统，也没有自动安装/更新 Google Chrome。**

## 离线证据

测试使用原仓库 `.venv/bin/python`，cwd/源码为工作树，测试临时根与真实账号数据隔离。完整集成第一次因工作树缺 article renderer 的 npm 依赖出现 1 failure/12 errors；随后用 ignored node_modules symlink 复用已有原仓库依赖，重新完整运行通过。未以跳过受影响测试消除该故障。

| 范围 | 实际结果 |
| --- | --- |
| optional config 公共 CLI 回归 | 先复现 ImportError，修复后 1/1 通过 |
| 三个 integrated fixture | 先复现 2 failures/1 error，修复后 3/3 通过 |
| 首次实际上传前的四平台停止保护回归 | 124/124 通过，3.213s；逐条核对 8 个动作参数传递和停止分支 |
| 集成离线集合 | 收集 2,122；选中 2,030，2,028 通过、2 个原有 opt-in provider smoke 跳过，153.855s；另 92 项真实浏览器测试按已有记录单独验证 |
| 小红书已认证 login | 先复现 QR 等待失败，17 项通过；补充无 QR 但无正向证据不能成功及验证分类 |
| local 停止输出 | 先复现误报 submitted，34 项通过；最终集合还断言 managed 原输出不变 |
| Instagram 子菜单与继续 | 各先有视频/图文失败，再分别 16 项、51 项通过 |
| 最后受影响集合 | 274/274 通过，18.825s，包含上述新用例、TikTok no-publish/选项、XHS probe/submit/blocked、Instagram 与 managed Meta，以及公共最小配置 |

最后集合曾因把 managed upload 输出断言放在 managed check 用例中产生一次测试自身失败（check 实际输出 valid），移到真实 upload 用例后完整 274 项通过。该修复没有改生产代码。

集成命令使用机器上的 `/private/tmp/sau-local-profile-notes/run-integrated-offline.py`：标准 unittest discover，仅分离基线 80 个已识别的真实浏览器测试和 12 个新增 `*_profile_dom` 测试，写明 selected/deferred manifest，不替换会话或 skip 失败。它不是项目运行入口。最后受影响命令为：

```sh
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest \
  tests.test_tiktok_profile_cli tests.test_tiktok_no_publish tests.test_tiktok_note_cli tests.test_mlx_tiktok \
  tests.test_xhs_profile_cli tests.test_xhs_session tests.test_xhs_submit tests.test_xhs_blocked \
  tests.test_instagram_profile_cli tests.test_mlx_meta tests.test_cli_minimal_config -q
```

集成全量在本票最后四个真实问题回归用例加入前完成；后续修改由上面的最终受影响集合覆盖，没有将不同运行次数简单相加成唯一测试总数。verify/delete、提交后异常、结果未知、提交次数和 cleanup 结果保留由相应离线测试覆盖，未用真实作品验证。

各批原始证据仍分别保留，相关平台用例也进入本次集成集合：第一批 [01](../issues/01-profile-ownership-and-reset.md)、[02](./02-browser-validation.md)、[03](./03-rednote-validation.md)、[04](../issues/04-instagram-persistent-profile.md)、[05](./05-browser-validation.md)；第二批 [06](./06-youtube-validation.md)、[07](./07-facebook-validation.md)、[08](./08-facebook-page-validation.md)；第三批 [09](./09-douyin-validation.md)、[10](./10-kuaishou-validation.md)、[11](./11-tencent-validation.md)、[12](./12-baijiahao-validation.md)；第四批 [13](./13-browser-validation.md)、[14](./14-hupu-validation.md)、[15](./15-alipay-validation.md)；第五批 [16](./16-dayu-validation.md)、[17](./17-zhihu-validation.md)、[18](./18-xueqiu-validation.md)。

## 真实浏览器、受控页面

[02 的 8 组合实测](./02-browser-validation.md) 已覆盖系统 Chrome 157.0.8103.79、Patchright 1.64.4 对应完整 Chromium revision 1248 / Chrome for Testing 156.0.8078.4：channel/custom 各有头与无头，正常关闭重开后 Cookie/localStorage 持久化、匿名 context 隔离、匿名关闭后主页面仍可用全部通过。本票没有修改共享浏览器来源/会话/占用能力，未无理由重跑全矩阵。Windows/Linux 原生实测仍未执行。

本票额外执行真实 Chrome、合成 DOM 的 Instagram 回归：`tests.test_instagram_uploader tests.test_instagram_no_publish` 共 33 项通过，163.403s。最后 local 继续修复后又执行受影响的 composer/media-input 和全部 no-publish 用例，共 6 项通过，50.661s。它们使用隔离测试页面，不是实际账号成功证据。浏览器启动经本机 sandbox escalation；没有安装新浏览器。

## 四平台实际验收

数据根为原仓库 `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload`，源码为工作树 `/private/tmp/sau-local-profile-20`。机器外部 harness `/private/tmp/sau-local-profile-notes/run20_live.py` 只做源码/原配置/数据根绑定和命令 allowlist，然后调用真实 `sau_cli.main(argv)`；它未提交到项目、不是永久迁移入口。原 `conf.py` 未修改，已有 `HEADLESS=True` 被每条命令的 `--headed` 显式覆盖；LOCAL_BROWSER 缺省且无 custom path，实际为 `channel=chrome`、157.0.8103.79、headless=False、no_viewport=True。没有 provider 环境。

本轮**实际使用的历史路径**相对于原仓库分别为 `browser_profiles/tiktok/lukechen/chrome`、`browser_profiles/rednote/rednote/chrome`、`browser_profiles/instagram/luke/chrome`、`browser_profiles/xiaohongshu/180/chrome`。后续 kind-first 搬迁须另附执行记录，不改写这些已发生的路径。

每个平台普通 login 正常退出后，独立进程重开相同 Profile 执行 check；然后视频、图文分别通过正式 CLI。账号别名和获批素材是用户已有数据。每条上传显式 `--no-publish`，所有阶段完整命令、开始/结束 UTC 与退出码在 [实际事件记录](./20-live-events.jsonl)。命令模板（对下表四个平台/别名逐个运行）：

```text
<python> <harness> <platform> login --account <alias> --headed
<python> <harness> <platform> check --account <alias> --headed
<python> <harness> <platform> upload-video --account <alias> --headed --file <original>/videos/demo.mp4 --title Profile验收 --no-publish
<python> <harness> <platform> upload-note --account <alias> --headed --images <original>/videos/demo.png --title Profile验收 --no-publish
```

| 平台/别名 | login 成功 UTC | 独立 check 成功 UTC | 视频成功 UTC | 图文成功 UTC | 实际停止点 |
| --- | --- | --- | --- | --- | --- |
| TikTok / lukechen | 11:04:54 | 11:05:38 | 11:06:23 | 11:06:56 | 素材/内容及发布就绪检查完成，发布按钮前停止，未点击发布 |
| Rednote / rednote | 11:06:41 | 11:07:15 | 11:08:07 | 11:09:12 | ARM 就绪，发布按钮前停止，未点击发布 |
| Instagram / luke | 11:07:59 | 11:08:26 | 11:15:42 | 11:16:31 | 素材/裁剪/编辑/配文完成，Share 前停止，结果 prepared |
| 小红书 / 180 | 11:10:43 | 11:11:26 | 11:12:08 | 11:13:24 | ARM 就绪，发布按钮前停止，未点击发布 |

表中全部退出码 0，正常关闭，没有 cleanup 警告。TikTok 普通 login 在已有认证状态下由 Agent 向 TTY 输入 Enter 触发真实正向探测；没有伪造探测结果或要求用户重复登录。

保留的实际失败及其处理：

- 小红书首次 login 于 11:07:47 退出 1，已登录重定向后仍等 login-box。修复与离线证明后，普通 login/reopen check 和两次 no-publish 全部通过。
- Instagram 首次 video 于 11:09:37 退出 1，Create 的帖子子菜单未进入；第二次于 11:13:58 退出 1，素材已上传但裁剪继续按钮未匹配。两次均在提交前，保留 not_submitted 结果和实际截图/DOM，先 TDD 修复后第三次 video 与 note 成功。
- 首次 Instagram 失败的结果最初因 cwd 相对路径写进工作树 `.local`；harness 随后绑定 cwd 到原仓库，并把这一条结果及其引用证据无覆盖移回原仓库。Profile 从未创建在工作树；所有实测结果现在位于原仓库 `.local`。
- TikTok 两次成功运行发生在 truthful stdout 修复之前，实际日志已有“发布就绪，--no-publish 停在发布按钮前（未点击发布）”，末行旧文案仍是 submitted。记录保留原样，未把旧文案伪装成重跑后的输出；修复后的 prepared 与 managed 原输出均由最终公共 CLI 测试证明。

真实页面截图/HTML与账号结果保留在原仓库 ignored `.local`，未提交个人页面或凭据。原始机器日志在 `/private/tmp/sau-local-profile-notes/20-*.log`；本记录与 JSONL 保留可审阅的命令、失败原因与最终结果。未实际提交发布、未删除作品、未为验证作品管理创建帖子。

**证据边界：** 素材确实上传，平台可能保留临时素材或草稿。成功只证明提交前流程，不证明真正发布、not-before 等待、发布后验证或防封禁。其他平台/托管不新增真实账号验收。实测完成且新要求到达后停止了所有账号操作；进程检查没有剩余 live harness 或使用 browser_profiles 的 Chrome。四份原仓库 Profile 必须在后续布局迁移和工作树删除后继续保留。
