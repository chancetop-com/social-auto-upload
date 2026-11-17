# Rednote 高级选项页面证据

2026-11-16，真实本地账号；浏览器 `navigator.language=en-US`，时区 `Asia/Shanghai`，页面仍显示中文。所有上传均显式 `--no-publish`。

| 环节 | 实际证据 | 调整 |
| --- | --- | --- |
| 封面 | `.d-modal` 包含 `.d-tabs` 和 `.d-modal-footer .btn-confirm`，没有小红书封面 modal 的那些专用 class | 新 modal 作用域；确认关闭且主预览背景改变才成功；失败停止 |
| 封面上传页签 | `.d-tabs-header` 只有显示文字，没有 id、name、role；当前文字「上传封面」 | 仅在 modal 内用已观察的精确文字；没有编造英文别名 |
| 声明入口 | wrapper 实际是 `lass="declaration-wrapper"`，不是 `class`；固定发布栏会遮挡贴底入口 | 以实际属性定位，滚到中心再点击 |
| 声明选项 | `.d-popover.d-dropdown .d-option` 没有稳定 value/id，名称有 AI、虚构、营销与来源二级选项 | 仅在下拉内按真实完整名称定位；选择后读取 wrapper 中 `.d-select-description`，不能用菜单中的文字冒充选中状态 |
| 原创 | 3 秒视频禁用，普通图文开关可用；先前将视频状态泛化为账号限制不准确 | 图文及 12 秒视频均已开启成功；居中滚动避开固定发布栏；其余开关和确认弹窗结构与小红书一致 |
| 定时 | `.post-time-wrapper .d-switch` 与 `.d-datepicker-input-filter input.d-text` | `2026-11-17T09:17:00Z` 回读为 `2026-11-17 17:17`，C2/C3 通过 |
| 标签 | `travel` 一度只有 `.newTopic` 新建项；Space 会接受候选 | 排除新建项；输入前记录基线，回退后也回读新增 data-topic，实际已插入 travel 就报告匹配，不再仅按点击次数报告纯文本 |
| 无头 QR | QR 图片有 `img.css-1lhmg90`；回调拿到非空图片 | 提取已验证；没有进行扫码闭环，也没有写入新账号文件 |

## 公开资源交叉核对

英文 Accept-Language 请求返回的官方发布页引用 [project-publish-vue.371d26b5.js](https://fe-platform-s10.rednotecdn.com/formula-static/ugc/public/resource/js/project-publish-vue.371d26b5.js)。该版本中声明选项与封面页签直接使用中文字符串，`lass` 拼写也与真实 DOM 一致。所检查的发布入口/组件资源没有找到这些控件的英文语言表；这不是对所有 Rednote 部署的断言。

不使用自行翻译的英文别名，不用列表索引猜测选项。若以后获得实际英文页面，先记录结构与文案；确需文本时才按已验证英文、中文的顺序添加。

原始 DOM、截图和资源保存在 git 忽略的 `.local/rednote-acceptance/`，不把账号页面、签名素材 URL 或大体积 bundle 加入仓库。2026-11-17 清理了本轮本地验收使用的三个一次性脚本（`capture_dry_run.py`、`inspect_source_dialogs.py`、`verify_declaration_variants.py`）；脚本可从 Git 历史恢复。本记录和正式回归测试保留，后续验收通过正式 CLI 的 `--no-publish` 入口执行。

自主拍摄和转载弹窗均已在实际账号打开取证：`.d-modal.self-shooting-contain`、`.address-input input`、`.date-picker input`，确认按钮使用 `.dialog-footer button.bg-red`。取消和确认都带 `custom-button`，不能仅用这个公共 class。只检查弹窗，没有填写或确认虚构来源。

## 本地来源声明续验

2026-11-16 18:02 完成自主拍摄的真实填写/确认；18:04 完成转载明细回读。当前页面会在打开来源弹窗前先设置类型，因此类型名称本身不能证明来源值已保存；采用已观察到的 `.wrapper:has([lass="declaration-wrapper"]) > .notation` 读取确认后明细。精确比较使用页面实际格式：`拍摄于日期，地点名称` / `信息转载于媒体名称`，这些是读值验证，不是文本选择器。

实际地点建议使用 `li .name` 与 `li .subname` 分别展示名称、地址。名称必须完整匹配用户参数，重复名称拒绝，不选择仅地址包含关键词的项，也不回退第一条。成功测试采用页面实际返回的 `人民公园-睡莲池`，不推测地点别名。输入、点击、日期键入和确认仍走原有 Humanizer。

五种内容类型已逐项通过真实中文后台的回读；无头扫码登录由用户确认后，在新浏览器中复核 `valid`。

## 原创条件与真实开启

2026-11-16 18:12 图文、18:13 的 12 秒视频均完成原创确认和 checked 回读，随后 ARM 就绪，未发布。原先仅据 3 秒视频禁用就推断账号不可用，结论不成立。上方官方资源中的 OriginalPlugin 组件明确以 `origin === SourceMedia` 或视频 `duration < 10` 决定 disabled；普通图文、3 秒视频、转载图文的实际 DOM 与之吻合。

确认弹窗结构与小红书基线一致，不新增文本候选。实际调整仅为点击原创开关前居中滚动，避开固定发布栏；Humanizer 的命中检查仍保留。原始证据归档在 `.local/rednote-acceptance/original-note-acceptance/`、`original-video-acceptance/`，官方组件摘录为同目录的 `original-component-evidence.txt`。
