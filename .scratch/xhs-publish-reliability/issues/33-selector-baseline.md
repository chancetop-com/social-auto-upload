# 33 — 选择器基线收敛

**What to build:** 小红书发布主链路（上传 → 标题 → 正文 → 话题 → 发布）在现网稳定命中结构锚点，不再依赖中文按钮文案；三条早已零命中的死锚点被删掉；文件输入不再靠 `.first` 猜。每次解析都能从日志看出走的是主候选还是兜底。

**Blocked by:** 31（接线处的等待要 clamp）、32（统一解析器与角色判定）.

Status: resolved

- [x] 发布按钮只保留 `xhs-publish-btn`（配合 `is-publish` / `submit-disabled`）；三条中文 `has-text` 与旧版按钮分支**本票直接删除**，过渡期常量断言同批删除
- [x] 图文与视频上传入口、标题、正文、话题候选、话题回读、定时开关、定时时间、原创开关、原创确认弹窗、内容类型声明、封面入口与弹窗、登录二维码、登录态正向锚点逐项按矩阵落位
- [x] 主链路零中文依赖；文本兜底只在结构分支失败后启用，且**只保留中文**
- [x] 内容类型声明里被误写成 id 的 class 已修正，主路径不再恒为 0
- [x] 封面入口从两个零命中选择器改为新结构主候选，文本兜底降为次级
- [x] 文件输入类（图文/视频/封面）命中数必须为 1；多义且无法用容器收窄 → 判为不可用，**禁止** `.first`
- [x] 每次解析打一条命中日志（环节、候选种类、选择器、URL）：首选结构分支为 debug，任何非结构分支额外打 info
- [x] 删除清单与矩阵"删旧条件"一致：新分支稳定命中且旧分支零命中就删旧分支，不留双路径
- [ ] 真机 `--no-publish` 正路日志显示首选结构分支（不靠兜底）

## Comments

- 矩阵第 1–17 行已落位为 `main.py` 模块级候选元组；解析统一经 `_resolve_anchor` → `utils.dom.wait_resolved/resolve`，命中日志固定格式 `锚点命中｜环节=…｜种类=…｜选择器=…｜URL=…`（结构 `debug`，非结构额外 `info`）。
- 删除：`button:has-text("发布")` / `button:has-text("定时发布")` 四条分支、`#publish-container div`、`div.upload-cover`、`div.cover-plugin-preview div.default.pointer`、`XHS_LOGIN_POSITIVE_SELECTORS` 里的中文发布按钮、旧 `div[class^='upload-content'] input[class='upload-input']`、定时开关的中文卡片过滤、原创开关的 `_js_click_by_text` 兜底。
- 保留的兜底（矩阵明确保留）：标题中文 placeholder、正文 ProseMirror / 中文 placeholder 上溯、定时时间 `.date-picker-container input`、原创中文卡片、原创弹窗 `role=dialog`、封面文本 `编辑封面`/`设置封面`/`上传`/`完成`、二维码文本容器、声明下拉精确文案。
- 机械保障：`tests/test_xhs_selectors.py`（候选顺序、结构无中文、文件输入多义 → `ElementUnusableError`、命中日志级别、死锚点静态断言）；`tests/test_xhs_budget.py` 的附件 input 等待改为 `wait_resolved` 后在虚拟时钟里仍受预算 clamp（10 秒）。
- `xhs-publish-btn` 的 `is-publish` / `submit-disabled` 谓词留给 ticket 36（ARM），本票只定义选择器与 65% 落点；封面/多图按 `set_input_files` 批量分发的语义保持不变（ticket 38 接管上传完成）。
- 真机项：`未验证（无真机环境）` —— ① `--no-publish` 正路日志只需出现 `种类=structure`；② 封面入口/弹窗与「上传」/「完成」按钮需真机跑通一次后才能删文本兜底；③ 原创声明弹窗 `[role=dialog]` 需两个账号各出现一次后再删。
