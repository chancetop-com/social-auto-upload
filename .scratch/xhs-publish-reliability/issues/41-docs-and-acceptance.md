# 41 — 文档回写与全量验收

**What to build:** 规格的行为、退出码与文案全部投影到用户能看到的 CLI 文档；退出码镜像覆盖全集且没有"待覆盖"项；真机清单逐条执行并把实际结果写回；全量测试绿。同时把"下一批平台迁移"的硬前置登记成待办，而不是当成已完成。

**Blocked by:** 29–40（全部）.

Status: resolved

**文档回写（派生投影，母本是规格 §4）**

- [x] 定时发布段落改为"CLI 在 FIRE 前复核，不一致 `exit 1`"，删掉"拒绝或立即发布"
- [x] `--account` 在托管下改为"忽略；身份由 profile 决定"
- [x] 三列默认值改为有头
- [x] 退出码表与规格 §4 对齐，写明 `publish_attempted` stderr 行；注明母本在规格
- [x] `--not-before` 与 15 分钟预算语义保留，补"禁止用 `--not-before` 做节流"
- [x] 并发与调用方动作段落补齐 `1/9/10/11` 的可执行语义
- [x] `check --headed` 示例同步默认值
- [x] 小红书子命令段：`--no-publish` 措辞改为"跑到 ARM 就绪"；声明/定时/超时/立即拒绝段落按规格改写；删"限流保留重试"条款
- [x] 平台字符上限事实修正（TikTok 4000；2200 是 Instagram）
- [x] 技能文档里的 CLI 契约镜像同步同一段

**测试收尾**

- [x] 删除机制已消失的用例：拒绝词 3 条、`cookie_auth` 1 条、xhs 登录探针与验证码相关用例
- [x] 改写 3 条（观察判据、填元数据键盘动作、ARM 截止）+ 默认 headless 断言
- [x] 退出码镜像覆盖 `{0,1,2,9,10,11,130}`，"待覆盖"清单为空
- [x] 快手及其余平台、预算模块用例零改动作为回归基线
- [x] 按决策分段组织用例（`Decision03SubmitTests` … `Decision13ParityTests`），不新增 runner
- [x] `python -m unittest discover -s tests -t .` 全绿

**真机验收（本地强制，托管可选）**

- [ ] 视频正路 `--no-publish` → `0`，日志含 ARM 就绪行与发布按钮命中日志
- [ ] 图文 2 张正路 → `0`，第 2 张经"+"瓦片/文件选择器，逐瓦片完成 + 静默复检通过
- [ ] 定时正路（2h–14d）→ 到 ARM 就绪 `0`；**不验证**定时是否生效
- [ ] 注入①移走账号文件 → `10`，**无**启动日志
- [ ] 注入②改坏会话 cookie → 启浏览器 → 分类命中 → `10`，stderr 不含 `publish_attempted=true`
- [ ] 注入③假 mp4 → 失败态 → 点击前 `1`，stderr 不含该行
- [ ] 注入④（可选）20MB PNG → 逐瓦片完成正常，60s 不误杀
- [ ] 真实发布最小验收：1 篇图文 → `0`，URL 离开发布页；人工删除该笔记
- [x] 结果回写到规格 §9.3 的"实际结果"列，不新建目录

**后续待办（不实施）**

- [x] 把平台迁移顺序与硬前置写进后续 effort 待办：TikTok / Instagram 需先补"跑到 ARM 就绪"的 `--no-publish`，否则它们的真机验收退化为"填表完成"

## Follow-ups

### 硬前置：TikTok / Instagram 的 `--no-publish` 语义

- **现状**：TikTok 与 Instagram 的 `--no-publish` 仍是「填表完成即返回」，没有「跑到 ARM 就绪」。
- **要求**：升级为与小红书相同语义——完成上传、元数据、声明/选项与定时设置后，等待发布按钮存在、可交互（hit-test）且未被禁用/遮挡，再返回成功；不进入 FIRE/OBSERVE。
- **原因**：U11 步 2/3 的真机验收若只到「填表完成」，无法证明选择器、就绪判据与上传完成判定在真实页面上成立，验收会退化为假阳性。
- **连带**：升级后同步改写各自 `docs/CLI.md` 段落与 skill 契约镜像（`--no-publish` 措辞、超时/观察窗语义）。

### 真机复检：规格 §8.3 中仍有价值、但本轮无环境验证的项

以下编号沿用 `spec.md` §8.3；本轮全部为「未验证（无真机环境）」。

| # | 项 | 下一次真机复检动作 |
| --- | --- | --- |
| 1 | `/website-login*` 与真实验证页 path 未观察到 | 制造一次登录失效，记录真实跳转 path；确认 `/website-login/captcha` 分支是否死代码 |
| 2 | 正常发布页上 `login-box` 的 count/可见性未单验 | 正常发布页观察一次，确认不会产生假 `10` |
| 3 | 定时回读只证客户端接受，不证服务端受理；2h/14d 边界未真机验证 | 用 2h、14d 边界各发一次定时，到点核对平台是否按设定时间发布 |
| 4 | C3 时效是粗判，不保证平台最小提前量 | 接近最小提前量时观察平台是否拒绝或回滚 |
| 6 | 观察窗 15s 对「慢成功」是否够用 | 真机记录发布成功实际离开 `/publish/publish` 的耗时分布 |
| 7 | 定时发布成功后是否跳转 `publish/success` | 真机确认；若不跳转，每次定时发布都会等到预算/窗口耗尽 → `9` |
| 8 | `--no-publish` 升级到 ARM 是前置改动 | 先完成上方「硬前置」，再做 §9.3 第 1–3 项 |
| 10 | 点击后落登录页的真实频率 | 统计派发后 `publish_attempted=true` 的实际发生率 |
| 12 | 登录后同 context 复核若页面未就绪 → `1` | 扫码成功后立刻重跑一次，确认运维可解释该 `1` |
| 15 | `type_horizon_chars=1000` 对部分编辑器可能被截断 | 用长正文真机确认编辑器不截断，或截断即按点击前 `1` 处理 |

§8.3 #5（`9` 与限流不可区分）、#9（humanize 效果不设断言）、#13（本地只写成功）属于设计/残留风险，不做真机断言；#11 已有实机证据；#14 托管为可选项。

### 文档与验收遗留

- 本轮 `spec.md` §9.3 九行全部标记 `未验证（无真机环境）`，不得当作通过证据。
- 小红书 `--account` 在托管下已改为「忽略、身份由 profile 决定」；若其它平台文档仍写「仅日志标签」，迁移时一并修正。

## Comments

- 真机验收 §9.3 第 1–9 项全部**未执行**：当前环境没有账号、cookie 与桌面浏览器。`spec.md` §9.3「实际结果」列统一填 `未验证（无真机环境）`，不得当成通过证据。
- 离线验收：`python -m unittest tests.test_xiaohongshu_uploader tests.test_xhs_exit_contract tests.test_mlx_xhs_kuaishou tests.test_publish_timeout -v` → `Ran 76 tests ... OK`；全量 `python -m unittest discover -s tests -t .` → `Ran 1447 tests ... OK (skipped=2)`。集成分支基线为 1451 条；本轮按票删除 5 条（XHS 登录探针 4 + 验证码跳转 1）、新增 1 条 `PENDING` 守卫，故净减 4。
- 机制消失用例核对：拒绝词 3 条与 `cookie_auth` 1 条已不存在；`test_mlx_xhs_kuaishou.py` 中 XHS 登录探针 4 条与 `test_xhs_note_captcha_redirect_raises_login_required` 已删除（探针行为由 `tests/test_xhs_session.py` 的 `Decision12SessionProbeTests` 覆盖）；Kuaishou 用例与 `tests/test_publish_timeout.py` 未改动。
- 代码评审已判定**不修**的项（judgement call，登记理由而非隐式忽略）：
  - `upload_video_content` / `upload_note_content` 末尾重复的 ARM→FIRE→OBSERVE 尾段：规格定义了两条独立流程，二者共用已测试的 helper；抽取会改变错误归属与 C3 时序，收益不足以抵消回归风险，延后为独立重构。
  - 轮询循环形状重复、请求 dataclass 字段块重复、测试内 fixture 重复、`_wait_ms` 包装、`_page_path`/`_current_path`、`_PROVIDER_LABELS` 重复：均属可读性整理；当前实现有真实回归风险而收益有限。
  - `BlockedKind` / `classify_blocked` 命名：规格 U10/U11 明确使用这两个名字；用户可见术语仍是 glossary 的 `Login required`，不改。

## Comments

- **2026-11-12 真机验收结果**已回写规格 §9.3「实际结果」列：视频/图文/定时正路 0；注入①/②/③ 均符合预期（10/10/1）。未执行项：20MB PNG（可选）、真实发布（会产生真实笔记，待确认）、托管（本机无凭证）。
- 真机复测暴露的 5 个问题（probe 轮询、滚动、focus、loading-text、定时全选）已修复并记录在规格 §9.3 末尾。
- **2026-11-12 真实发布最小验收**：`upload-note --account 180 --images videos/demo1.png --title "SAU真实发布验收"` → 退出 `0`，日志 `图文发布成功`，OBSERVE 确认 URL 离开 `/publish/publish`。该测试笔记待人工删除。
