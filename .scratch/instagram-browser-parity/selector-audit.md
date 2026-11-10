# Instagram 选择器可靠性审计（2026-11-10）

审查范围：`uploader/meta_uploader/insgraph_uploader/` 与 `posts.py` 中所有浏览器选择器。
评分：**高** = 依赖 hash 类名/固定下标/固定数量，DOM 一改即失效；**中** = 结构假设或单一文案；
**低** = ARIA role、语义属性、URL/接口或 meta 字段。

## 主流程（main.py）

| 位置 | 选择器 | 评分 | 问题 | 本轮处理 |
|---|---|---|---|---|
| 素材入口 | `input[type=file][accept*="video/mp4"]` | 中 | 只认 mp4；accept 变更/仅 quicktime 时失效 | 改 `accept*="video/"`，补 `[multiple]` 与任意 file input |
| 向导主动作 | `._ac76 [role=button]:not(:has(svg))` | 高 | hash 类名，改版即失效 | 保留实测首选，补 aria 名称回退（Next/Share/中文） |
| 向导标题 | `._ac76 [role=heading]` | 高 | hash 类名 | 保留实测首选，补 `role=heading` 回退 |
| 创建入口 | `a._a6hd[href="#"]` + count=4 + nth(1) | 高 | hash 类名 + 固定数量/下标 | 优先 `svg[aria-label=New post]` 语义定位，保留旧回退 |
| 通知图标 | `img[src^="/images/instagram/xig/ico/xxhdpi_launcher.png"]` | 中 | 精确路径 | 改 `src*="launcher"` |
| 通知关闭 | `._a9-z > button` nth(1) | 高 | hash 类名 + 固定下标 | 改“对话框最后一个 button”，角色级且在通知/Reels 均成立 |
| Reels 图标 | `img[src^="/images/instagram/clips/reels_nux_icon.png"]` | 中 | 精确路径 | 改 `src*="reels_nux"` |
| Reels 关闭 | `._a9-z div > button` | 高 | hash 类名 + 结构 | 复用“最后一个 button” |
| 封面入口 | `input[type=file][accept="image/jpeg,image/png"]` | 中 | accept 顺序固定 | 改“含 image/jpeg 且不含 video”，保留精确回退 |
| 配文编辑器 | `[contenteditable][role=textbox][data-lexical-editor]` | 低 | 语义属性 | 补 `[contenteditable][role=textbox]` 回退 |
| 自己主页 | `a[href]` + `[aria-selected] img` | 中 | 依赖导航选中容器 | 补头像 alt 文本回退 |
| 登录态 | 收件箱/用户名输入/登录链接 | 低 | 语义 URL/字段 | 保持 |
| 创建响应 | `/api/v1/media/configure` + 作品/作者/配文校验 | 低 | 业务接口 + 响应校验 | 保持 |

## 发布选项（controls/）

| 位置 | 选择器 | 评分 | 问题 | 本轮处理 |
|---|---|---|---|---|
| 地点入口 | placeholder / aria-label | 低 | 语义属性 | 补 `input[name="creation-location-input"]` |
| 地点联想 | 几何 + 精确文本（无 ARIA role） | 中 | 依赖尺寸/位置常量 | 保持（实测无 role；已用输入框锚点） |
| 地点 chip | `._abgh` 祖先 | 中 | 旧语义类名 | 仅防御性兜底，保持 |
| Alt 入口 | `Accessibility` 精确文本 + role=button 祖先 | 低 | 文本 + 结构 | 保持 |
| Alt 输入 | 精确 aria-label/placeholder | 中 | 文案变体 | 扩为大小写不敏感子串 + textarea |
| 开关 | `[role=switch] / [role=checkbox]` + 标签文本 | 低 | ARIA role + 文本 | 保持 |
| 折叠 chevron | `[aria-label="Up chevron icon"]` | 中 | 单一英文文案 | 补大小写不敏感 chevron/up 组合与中文 |
| 折叠行 | 文本 + `ancestor::*[@role=button]` | 中 | 只认 role=button | 补原生 `button` |

## 原作品删除（posts.py）

| 位置 | 选择器 | 评分 | 问题 | 本轮处理 |
|---|---|---|---|---|
| 菜单按钮 | `[role=button][aria-haspopup=dialog]` + `svg circle` | 中 | 依赖 SVG 形状 | 补 More options/更多选项 文案回退 |
| 菜单删除项 | 精确文案 `Delete/删除` | 低 | 文本 | 保持 |
| 确认框 | `aria-modal` + heading | 低 | 语义 | 保持 |
| 确认删除按钮 | `buttons.nth(0)` | 高 | 固定下标，若 Cancel 在前会误点取消 | 只按 `Delete/删除` 文案点击；文案缺失直接失败关闭，绝不猜下标 |

## 第二轮 code-review 后的修正

第一轮加固后，两个独立 review agent 又发现并已修正：

1. **创建入口恢复 spec §4.4 优先级**：先结构（4 个导航弹出入口），组内用
   `aria-label` 消歧，最后才用实测下标；只有结构组数量变化时才走页面级标签。
2. **素材入口保留 accept 哨兵**：不再直接把 `input[type=file]` 当唯一主选择器；
   按 `accept*="video/"` → `[multiple]` → 任意 file input 的优先级，在弹窗挂载后
   逐轮解析，返回具体选择器，`to_have_count(1)` 仍是真实哨兵。
3. **删除确认失败关闭**：确认框只按 `Delete/删除` 文案点击；文案缺失直接失败，
   绝不回退 `nth(0)`，避免按钮重排后误点 Cancel。
4. **提示关闭不再赌“最后一个按钮”**：优先明确文案（Not Now/OK/中文），未命中才
   退回最后一个按钮；并保留 `_dismiss_optional_prompt` 的迟到挂载等待窗口。
5. **自己主页回退收窄**：头像 alt 回退只在 `nav` / `role=navigation` 内生效，
   不再匹配动态流里其他用户。
6. **Alt text 保留精确优先**：精确文案先命中；完全缺席时才用宽松子串 + 中文回退。
7. **测试证据修正**：删除流程分开记录菜单点击与确认框点击，新增“Cancel 在前”
   与“确认框无精确 Delete 时失败关闭”用例。

## 结论（加固后）

| 风险级 | 剩余项 | 处理 |
|---|---|---|
| 高 | 无（无真机条件下可安全消除的项已消除） | — |
| 中 | 地点联想列表无 ARIA role，仍靠几何 + 精确文本 | 实测 DOM 限制；输入框锚点 + 精确匹配，永不点模糊项 |
| 中 | 通知/Reels 提示仍靠特定图标文件名识别 | 图标名片段 + 文案优先关闭；图标改名会被真实 DOM 哨兵捕获 |
| 中 | `_ac76` / `_a6hd` / `_abgh` 等 hash 类名仍作为首选 | 均已有语义回退，hash 变化时可继续 |
| 低 | 登录态、meta、API 路径、ARIA role、可见文案 | 语义选择器，保持 |

选择器已从“单点 hash/下标”改为“实测首选 + 语义回退 + 失败关闭”，在无真机
回归的条件下已达到相对可靠。
