# 41 — 文档回写与全量验收

**What to build:** 规格的行为、退出码与文案全部投影到用户能看到的 CLI 文档；退出码镜像覆盖全集且没有"待覆盖"项；真机清单逐条执行并把实际结果写回；全量测试绿。同时把"下一批平台迁移"的硬前置登记成待办，而不是当成已完成。

**Blocked by:** 29–40（全部）.

**Status:** ready-for-agent

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

- 详细待办见 [`follow-ups.md`](../follow-ups.md)：TikTok / Instagram 的 `--no-publish` 必须先升级为「跑到 ARM 就绪」，再做 U11 步 2/3 真机验收。
- 同文件登记了规格 §8.3 中值得在硬件上复检的项（真实验证页 path、login-box 假阳性、定时 2h/14d 边界、慢成功观察窗、定时成功后跳转等）。

## Comments

- 真机验收 §9.3 第 1–9 项全部**未执行**：当前环境没有账号、cookie 与桌面浏览器。`spec.md` §9.3「实际结果」列统一填 `未验证（无真机环境）`，不得当成通过证据。
- 离线验收：`python -m unittest tests.test_xiaohongshu_uploader tests.test_xhs_exit_contract tests.test_mlx_xhs_kuaishou tests.test_publish_timeout -v` → `Ran 76 tests ... OK`；全量 `python -m unittest discover -s tests -t .` → `Ran 1447 tests ... OK (skipped=2)`。集成分支基线为 1451 条；本轮按票删除 5 条（XHS 登录探针 4 + 验证码跳转 1）、新增 1 条 `PENDING` 守卫，故净减 4。
- 机制消失用例核对：拒绝词 3 条与 `cookie_auth` 1 条已不存在；`test_mlx_xhs_kuaishou.py` 中 XHS 登录探针 4 条与 `test_xhs_note_captcha_redirect_raises_login_required` 已删除（探针行为由 `tests/test_xhs_session.py` 的 `Decision12SessionProbeTests` 覆盖）；Kuaishou 用例与 `tests/test_publish_timeout.py` 未改动。
