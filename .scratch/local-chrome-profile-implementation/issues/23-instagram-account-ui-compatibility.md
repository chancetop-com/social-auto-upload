# 23: 兼容 Instagram 普通号与 creator 的创建界面

**What to build:** 按用户追加说明，普通账号直接打开编辑器、creator 账号先打开创建子菜单的两种界面都可完成视频和图文流程；选择器稳定且保持人类化操作。

**Blocked by:** [19：一次性迁移](./19-one-time-legacy-migration.md)（已完成）。基于 20 已验证基线 `a61628c`；与 21、22、24 并行，真实操作需与 21 搬迁协调。

**Status:** resolved

**依据：** 用户说明当前真实 Instagram 账号为 creator，原来为普通号，要求同时兼容、选择器可靠、尽量不用文本并保留 Humanizer。

- [x] 按实际页面状态支持普通号直接编辑器与 creator 创建子菜单，不永久记录/绑定账号类型或真实身份，不假定所有账号都改变了界面。
- [x] 基于已观察 DOM 的稳定属性、语义、链接和局部结构选择控件，避免 hash class、位置猜测及宽泛文本；缺少可靠结构信号时才使用已观察且严格限定的文本后备，并记录理由。
- [x] 所有目标唯一、可交互；未知或歧义结构安全失败，不点直播/广告或最终发布，不使用 force/JS click 绕过正常交互。
- [x] 两条界面路径沿用现有 Humanizer 的 hover/click/type 节奏，保留 HUMANIZE 开关及现有业务脚本、选项和超时预算。
- [x] TDD 覆盖普通/creator × 视频/图文，以及模糊/缺失控件、发布就绪/no-publish 和人类化事件；保留托管路由、所有权和结果契约。
- [x] 当前真实 creator Profile 的视频和图文显式 no-publish 复验通过；使用原仓库已授权 demo，协调 21 的目录切换后再运行，不额外创建账号或发布/删除作品。
- [x] 普通账号若仅有受控 DOM 证据如实说明，不虚构第二个真实账号验收。当前历史普通界面回归不得被新 creator 修复破坏。
- [x] 同步规格、平台文档和执行记录；新旧真实路径按执行时间记录，不能改写已完成的历史证据。


## Comments

- 2026-11-17：使用 TDD 与已批准公共 CLI / BrowserSession 注入边界。实际 DOM 依据、红→绿、101 项相关离线、19 个受控场景、33 项已有浏览器回归及最终 5 项就绪子集见 [23 验证记录](../research/23-instagram-account-ui.md)。
- 删除无标签时猜导航第二项的分支；图标标签并集计数，creator 仅认实际公开菜单的帖子图标；普通号直接编辑器保留，按当次状态分支，不绑定账号别名或 provider。两条路径用相同 Humanizer hover/click/type。
- 控制夹具暴露两个安全问题并先红后绿：旧推进按钮可匹配提前出现的 Share；旧 no-publish 只看 enabled，可把被遮挡 Share 误记 prepared。现分开推进与提交角色/完整名称，并在原预算内做 shared interactive 检查。该合成缺陷证据不代表此前真实运行点击过 Share。
- 已提交代码 checkpoint `868252b` 并在 `1127e4b` 合并集成 `3455f1f`；21 路径断言与本票行为用例保留并集。当前未操作实际账号，等待 root 确认 21 四份 Profile 搬迁及 check 完毕后才运行获批 demo 的两次显式 no-publish。

- 2026-11-17：21 最终 guard 释放且 root 放行后，使用新原路径的 creator Profile、获批 `demo.mp4/demo.png`、HUMANIZE=1 和显式 headed/no-publish 实际完成视频与图文，均首次退出 0/prepared，Share 前停止、无清理警告。UTC 完成时间分别 12:00:31、12:01:06；原结果无发布字段，进程检查无残留。完整命令与范围限制见验证记录及其 JSONL，不将普通号受控证据称为第二个实际账号验收。

## Answer

已兼容普通账号直接编辑器与 creator 创建子菜单，两种媒体按当次页面状态选择，使用已观察语义、唯一目标和 Humanizer。删除导航位置猜测，分离推进/最终发布，严格检查 no-publish 就绪且保持预算；provider 路由、所有权、日志和结果边界保持。101 项相关离线、19 个新增受控场景、33 项既有浏览器回归和最终 5 项就绪子集通过；当前真实 creator 的视频/图文 no-publish 通过。普通号本次仅受控回归，无剩余本票验收阻塞。

### 2026-11-17 英文 creator 入口补充

- 用户复核 `main` 后要求同时支持英文。基线 `0a5df82` 的子菜单仅匹配中文 `帖子`；`adspower` 提交 `7ee8380` 中的 `09-creator-entry-evidence.md` 已记录英文 `Post` 图标外层为普通 div，没有中文布局的链接结构。
- 选择器合并中文链接与英文 `svg[aria-label="Post"]`，统一检查唯一性（包括混合语言候选），不使用可见文本。展开的子菜单直接 Humanizer 点击，不额外 hover；仅未派发的暂时不可用在原 deadline 内重试，多义或可能已派发的错误直接停止。
- 新增英文视频/图文的本地与 AdsPower 受控页面、漂移恢复、重复/混合/缺失菜单，以及已点击后不再重复点击的回归。原普通号、中文 creator 与 MLX 受控回归继续保留；无真实账号操作。
- 修复前的新英文用例先复现只点击 Create、没有点击 Post；修复后的现有离线集合 101 项通过。浏览器首轮发现测试夹具把编辑器的 Next 误计入菜单误点，已将该事件监听限定为 Post/直播/广告与文本干扰项；该首轮不作为通过证据。
- 最终 `tests.test_instagram_account_ui`：10 tests / 28 个受控场景全部通过（264.024s），含英文 creator 本地/AdsPower × 视频/图文；真实指针引起的 `point-drift` 先失败后恢复，最终仅一次 Post 点击，Share/直播/广告零点击。命令：`.venv/bin/python -m unittest tests.test_instagram_account_ui -v`；日志 `/private/tmp/instagram-english-account-ui-fixed.log`。
- 现有离线命令：`.venv/bin/python -m unittest tests.test_instagram_profile_cli tests.test_mlx_meta tests.test_instagram_humanize tests.test_publish_ambiguity -q`，101 tests / OK（9.267s），日志 `/private/tmp/instagram-english-offline.log`。这些结果仅为当前修改的受控回归，不是新的真实账号或真实发布验收。

### 英文菜单禁用状态 P2 修复与复核

- 独立审查复现：英文选择器返回 SVG，外层普通 div 的 `aria-disabled=true` 未被共享交互检查识别，会向禁用菜单派发点击。用户授权修复。
- 共享 DOM 探测在原祖先遍历中合并父层 `aria-disabled=true` 到 disabled；保留可见性，阻止 interactive/editable。Instagram 点击前复用 `check(..., 'interactive')`，覆盖 HUMANIZE=0；Humanizer 最终落点复核使用同一规则，阻止移动过程中才被禁用的菜单。未猜测父容器层数，未改点击派发标记或重试边界。
- 新增三种英文公开上传场景（Humanizer 关闭/开启的静态禁用、鼠标移入时禁用）和 DOM 嵌套 SVG/input 禁用/恢复回归，修复前全部失败，修复后零 Post/Share/直播/广告点击、无素材上传。`tests.test_xhs_dom` 加新增 Instagram 用例共 77 tests / OK（50.290s），日志 `/private/tmp/instagram-disabled-green.log`。
- `tests.test_humanize tests.test_instagram_profile_cli tests.test_mlx_meta tests.test_instagram_humanize tests.test_publish_ambiguity` 共 149 tests / OK（10.260s），日志 `/private/tmp/instagram-disabled-offline.log`。受影响既有浏览器子集 5 tests / 11 场景全部通过（91.234s），覆盖英文视频/图文 local/AdsPower、普通/中文快速路径、漂移恢复、多义/缺失菜单及不重复点击；日志 `/private/tmp/instagram-disabled-existing.log`。
- 原 Spec 审查者确认 P2 闭环；Standards 增量复核未发现新增问题。`git diff --check` 通过。本次仍仅使用替身与隔离合成页面，没有真实账号或发布操作。

### 再次审查后的点击顺序修复

- 新一轮完整审查补出两个边界：HUMANIZE=0 的原生点击在前置检查之后才移动指针，移入时禁用仍会派发；完整交互检查又发生在滚动之前，导致屏外菜单一直报 covered-by:unknown，无法进入原有自动滚动。上一轮通过的测试未覆盖这两个组合，其历史结果不作为这两个边界的通过证据。
- 用户要求修复后再审查。开启人类化时移除额外前置检查，保持 Humanizer 原有滚动、移动、最终落点/禁用校验和派发顺序；关闭人类化时先通过 Humanizer 的原生 hover 完成滚动及移入，再检查交互状态并原生点击。共享 Humanizer 实现、派发标记与原有预算不变。
- 禁用回归补齐原生移入时禁用，形成两种 Humanizer 设置 × 静态/动态禁用四个场景；新增中文/英文 × 两种 Humanizer 设置的屏外菜单完整 no-publish 流程，并断言实际发生滚动。
- 最终 `.venv/bin/python -m unittest tests.test_instagram_account_ui -v`：12 tests / 36 场景全部通过（326.298s），日志 `/private/tmp/instagram-menu-final-browser.log`。四种禁用场景均无 Post 点击/素材上传；四种屏外场景均滚入视口并完成 prepared，所有 no-publish 场景均无 Share/直播/广告点击。
- 最终离线集合 `tests.test_humanize tests.test_instagram_profile_cli tests.test_mlx_meta tests.test_instagram_humanize tests.test_publish_ambiguity tests.test_mlx_tencent_baijiahao tests.test_tencent_profiles`：216 tests / OK（17.560s），日志 `/private/tmp/instagram-menu-final-offline.log`。未重复计入前轮已通过且源码未改变的共享 DOM 测试。
- 修复后以新的独立上下文审查相对 `0a5df82` 的全部八个工作树文件：Standards 0 项、Spec 0 项，无新增可操作发现。`git diff --check` 通过。没有真实账号、发布或删除操作。
