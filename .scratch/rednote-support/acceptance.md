# Rednote 第一版验收

日期：2026-11-16，时间为 Asia/Shanghai。账号标签 `rednote`；会话保存在 git 忽略的 cookies 目录。所有素材仅包含中性测试文字，存于 git 忽略的 `.local/rednote-acceptance/`。

| 检查 | 结果 |
| --- | --- |
| 官方创作入口 | `https://creator.rednote.com`，官网 Post 链接已核实 |
| 本地有头登录 | 17:08:49 成功保存会话；用户人工登录 |
| 新进程无头 `check` | 17:09:44 返回 `valid`，退出 `0` |
| 双图 `upload-note --no-publish` | 17:12:14 到达 ARM，标题/正文已填写，退出 `0` |
| 视频 `upload-video --no-publish` | 17:13:22 到达 ARM，标题/正文已填写，退出 `0` |
| 实际发布 | 未执行；用户仅授权 `--no-publish` |

两次干跑使用 `Rednote setup check` 和 `Integration check. Draft only.`；没有标签、声明、定时、自定义封面。浏览器 context 配置为 `en-US`，平台可能返回中文 UI。

## 已修正的真实差异

- 会话不是小红书的 `galaxy_creator_session_id`，而是 Rednote `web_session` / `id_token`；快路验证前者，线上可用性以发布页探测为准。
- 登录页等待 `load` 会被外部资源拖到超时，改为等待 `domcontentloaded`。
- 有头登录允许人工短信或扫码，二维码准备不再成为有头登录的前置条件。
- 保留 DOM 原名 `xhs-publish-btn`，不能将网站的自定义元素机械改名为 Rednote。

## 自动化检查

- 小红书相关回归与首批 Rednote 测试：437 项通过；唯一 Chromium 沙箱启动失败的测试在沙箱外单独重跑通过。
- Rednote、MLX、AdsPower 与通用浏览器 CLI：108 项通过，391 个子测试通过。
- 最终 Rednote 定向测试（含真实 cookie 差异回归）：14 项通过，25 个子测试通过。
- Ruff 基础错误检查（E4/E7/E9/F）与 `git diff --check` 通过。

## 未验证范围

最终提交、无头二维码登录、托管模式真实 Profile、标签候选、自定义封面、声明与定时发布的真实页面能力未作线上验收；它们保留小红书基线或共享托管逻辑。不会把离线通过等同为线上能力已验证。

## 高级选项续验（2026-11-16）

以小红书现有 `Humanizer` 和提交契约为基线，只按真实差异调整。字段填写、悬停和点击继续走人类化层；声明入口受固定发布栏遮挡时先居中滚动，再执行原有命中检查。

| 检查 | 结果 |
| --- | --- |
| 视频封面 + AI 声明 + 关闭原创 + 定时 | 17:42:18 到 ARM，退出 `0`；封面 modal 关闭、主预览改变，声明回读匹配，时间回读 `2026-11-17 17:17` |
| 双图 + travel + AI 声明 + 关闭原创 + 定时 | 17:48:42 `topic-match:travel`，17:48:53 到 ARM，退出 `0`；最终 `data-topic` 确认名称与非空平台 id |
| 无头二维码 | 17:23:47 已提取非空图片并回调；未扫码，超时后清理临时 QR，没有创建新账号状态 |
| 自主拍摄/转载弹窗 | 实际打开并读取结构；取消和确认都含 `custom-button`，已收窄到确认按钮 `bg-red`；没有填写或确认来源信息 |
| 原创开启（当时观察） | 3 秒视频控件 disabled；当时误归因于账号。图文实际可用，后续已更正并完成开启验证，见下节 |
| 语言 | `navigator.language=en-US`，实际后台中文；官方当前 bundle 同样使用中文文案，未编造英文别名 |

封面/声明设置失败不再 warning 后继续；关闭原创必须能确认关闭。标签回读覆盖平台自动转换，不把「没有点候选」误判为「没有插入话题」。只有确无稳定标识的语义选项保留实际文案；其余结构可用的控件不设置文本候选。

详细结构证据见 [高级选项证据](research/advanced-evidence.md)。最终提交、真实英文后台、托管 Profile、其余声明完整闭环和扫码闭环仍未验收；上述第一版「未验证范围」以本节更新为准。

最终定向回归：`tests/test_rednote.py`、`test_rednote_options.py`、小红书 `selectors/topics/submit` 共 **105 项通过，73 个子测试通过**。包含真实 Chromium DOM 夹具、自动话题转换/错词拒绝、封面关闭与预览回读、声明不生效拒绝、原创禁用、来源确认与取消按钮区分。新增/修改的 Rednote Python 文件 Ruff E4/E7/E9/F 通过，`git diff --check` 通过。扩大到整个 `sau_cli.py` 的 Ruff 检查有既存 F401（`resolve_account_file` 导入），HEAD 中同样存在，本轮未改动该兼容导入。

## 本地剩余验收（2026-11-16）

用户本轮明确「暂无，先完成本地账号验收」。继续使用原中性测试图及 `Rednote setup check` / `Integration check. Draft only.`，所有上传均 `--no-publish`，没有发布。

| 检查 | 结果 |
| --- | --- |
| 转载声明初次完整流程 | 17:58:35 ARM 就绪，退出 `0`；实际显示 `信息转载于Rednote integration fixture` |
| 自主拍摄 | 18:02:13 ARM 就绪，退出 `0`；地点为候选实际名称 `人民公园-睡莲池`，日期 `2026-11-16`，确认后明细完整匹配 |
| 无头扫码登录 | 用户人工扫码确认；18:03:02 返回 success，会话保存、二维码清理完成 |
| 扫码会话新进程复核 | 新 Chromium context 恢复临时会话，预检通过，`probe_session` 返回 `valid` |
| 虚构声明 | 18:04:16 回读 `虚构演绎，仅供娱乐` |
| 营销声明 | 18:04:21 回读 `内容包含营销广告` |
| 转载明细增强回读 | 18:04:33 回读类型和媒体名称均匹配，ARM 就绪，退出 `0` |

虚构/营销/转载的最后一轮在同一测试草稿内依次调用正式 `apply_declarations`，最后由正式上传器完成 `--no-publish` ARM 检查；没有跳过人类化层。自主拍摄的地点/日期是干跑测试值，不是对测试卡片拍摄事实的描述。

实际来源控件会在打开弹窗时先改变类型，取消弹窗也可能留下类型名称，因此新增确认后 `.notation` 明细回读。地点列表实际把名称与地址拆为 `.name` / `.subname`；`上海市人民公园` 查询返回名称 `人民公园` 等多个结果，不能按任意包含关系或第一项猜地点。现仅接受完整名称唯一命中；用实际候选名称完成验证。

测试：Rednote 路由/会话与真实 Chromium DOM 定向回归 **29 项通过、40 个子测试通过**，包括来源类型已选但明细缺失/错误、地址或名称前缀干扰、同名候选拒绝、日期输入和确认。既有小红书实现和共享 Humanizer 未修改。

原始证据继续保存在忽略目录：`self-shot-acceptance/`、`source-variants-acceptance/`，位于 `.local/rednote-acceptance/` 下；二维码临时会话在新进程复核后清理，仅保留结果记录。

仍未验收：纯英文后台、真实托管 Profile 及最终公开提交。原创开启随后复核通过，见下节；本节更新前面历史记录中的相关待验证项。

## 原创开关纠正与补验（2026-11-16）

用户追问原创是否真的不可用后，重新对照原始 DOM 与官方组件：先前 3 秒视频的禁用状态被错误泛化为账号限制。普通图文历史 DOM 实际没有 disabled；转载图文则有 disabled。当前官方组件禁用条件为「来源转载」或「视频 duration < 10」，与账号是否有原创能力不能等同。

| 检查 | 结果 |
| --- | --- |
| 普通图文开启原创 | 18:12:09 确认成功、弹窗关闭、开关 checked，ARM 就绪，退出 `0` |
| 12 秒视频开启原创 | 同一中性卡片生成 12 秒视频；18:13:43 开启成功，18:13:44 ARM 就绪，退出 `0` |
| 结构与人类化 | `.original-wrapper .d-switch`、`div.d-modal.creator-modal-style`、弹窗内 `.d-checkbox` 与 `button.custom-button` 均实测命中；继续沿用小红书结构，无文本选择器 |
| 真实差异修复 | 图文开关曾被固定 `xhs-publish-btn` 遮挡；点击前居中滚动，再走 Humanizer 和正常命中检查，没有强制点击 |

所有运行保持 `--no-publish`，未点击发布。`original-note-acceptance/` 和 `original-video-acceptance/` 保存此轮实际截图与 DOM。代码错误提示不再把禁用归为账号能力缺失。

最终 Rednote 定向回归 **30 项通过、42 个子测试通过**，新增固定发布栏遮挡下开启/关闭原创与确认回读测试。Rednote 修改文件 Ruff E4/E7/E9/F 与 `git diff --check` 通过。

## 第一版交付核对（2026-11-16）

README 主能力表补上 Rednote 实验性入口，许可证说明与实际 19 个 Skill 保持一致。独立 Rednote Skill 随包提供 `references/runtime-requirements.md` 和 `references/cli-contract.md`，所有相对引用验证可解析；slug 无重复。

`uv build --wheel --offline` 成功。wheel 包含 `sau_commands/rednote.py`、`uploader/rednote_uploader/` 和 `sau` 入口；在临时目录解包后，从包内加载的 `login`、`check`、`upload-video`、`upload-note` 帮助命令全部成功。上传命令确认有 `--no-publish`、原创/内容声明、平台定时与客户端等待选项。wheel 不含 cookies、原始验收素材或研究目录；仅在本地验证，未分发。

本轮只补文档和交付记录，没有修改上传器或重复线上上传。构建与检查记录位于 `.local/rednote-acceptance/`；剩余真实英文后台和托管 Profile 的验证范围不变。

## 动态候选偶发停顿修复（2026-11-16）

用户的 `自动化,小红书` 标签组合在真实账号复现：候选列表按旧数量遍历，第二个 `.name` 消失后 `text_content()` 等待 30.008 秒，单条标签耗时 33.000 秒。修复使用真实节点快照与编辑器批量回读，保持结构选择器、精确匹配和 Humanizer。

| 真实复验 | 标签耗时 | 结果 |
| --- | --- | --- |
| 中性双图，原创 + AI，`--no-publish` | 2.989 秒 / 2.984 秒 | 18:45:35 发布前就绪，退出 0 |
| 实际 `upload-video` CLI，12 秒中性视频，原创 + AI，`--no-publish` | 2.037 秒 / 2.753 秒 | 18:52:28 发布前就绪，`prepared (not published)`，退出 0 |

用户要求扩大排查后，离线 Chromium 同时复现并修正小红书和 TikTok 的话题候选、百家号合集搜索；还覆盖 Rednote / 小红书编辑器话题回读的同类等待。没有对其他平台新增线上上传。

最终扩展回归 **457 项通过、177 个子测试通过**。TikTok / 百家号 / 小红书话题专项另有 **157 项通过、24 个子测试通过**，与扩展组有重叠，不累加。修改文件 Ruff 对比 HEAD 无新增诊断，保留 9 条既有问题；`git diff --check` 通过。全部日志与诊断脚本位于 `.local/rednote-debug/`，未点击发布。具体范围见 [修正动态候选刷新时的偶发长停顿](issues/08-topic-refresh-stall.md)。

## 发布结果与歧义契约修复（2026-11-16）

针对两项审查结论补回归后修复：本地浏览器 context/browser 关闭分别保护，cookie 写回与已发现的其他清理错误只记 warning；CLI 故障注入保持 `0/9/10` 和 `publish_attempted=true` 信号。Rednote / 小红书在滚动前先确认发布按钮数量，ARM 与视频完成闸首次出现 `ambiguous:N` 即停止。

检查其他 CLI 平台后，同步修正清理路径与实际存在的发布按钮取首项/吞歧义重试路径。快手首次发布点击成功后的确认按钮歧义保留结果未知；抖音和快手关闭人类化时仍先检查数量。托管浏览器的所有权与 Stop 规则保持不变。

新增专项 **17 项、245 个子用例通过**；跨平台边界组 **149 项、30 个子用例通过**；Instagram / YouTube 浏览器与清理组 **53 项、14 个子用例通过**。全仓分组完成：前段 1335 项通过，修正并复跑 3 个旧测试替身签名问题；剩余 24 个文件 621 项通过。各组重叠，不累加；完整运行口径见 [ticket 09](issues/09-publish-result-contracts.md)。

本地 Chromium 双按钮页面中，Rednote / 小红书四个等待入口在 **6–37 毫秒**内停止，Instagram Share 同样拒绝歧义，点击计数为 **0**。本次没有真实账号上传或发布。新增文件完整 Ruff、修改文件 Ruff 对比 HEAD 无新增诊断及 `git diff --check` 均通过。
