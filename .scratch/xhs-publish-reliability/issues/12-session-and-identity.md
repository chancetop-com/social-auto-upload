# 12 — 会话预检、check 判定与身份回读

Status: open
Type: grilling
Blocked by: —
Assignee: —

## Question

决定“我们怎么知道自己是谁、还能不能发”。需要确认：

1. **创作者会话预检**：是否加 `ensureCreatorSession` 等价物（读 `galaxy_creator_session_id`，缺失则打开 creator 首页等会话建立，超时 15s）？托管模式用 CDP 读 cookie，本地模式从 `storage_state` 读。
2. **`check` 判定标准**：本地宽松（无登录框即通过）与托管严格（必须有上传入口锚点）现在会给同一账号相反答案。统一到哪一个？是否需要两级（`valid` / `valid-but-degraded`）？退出码如何映射。
3. **身份回读**：是否读 `__INITIAL_STATE__.user.userInfo` 输出 nickname / userId（上游做法）。**注意 patchright 的 `evaluate` 默认在 isolated world，读页面全局变量必须 `isolated_context=False`**；读不到时的降级行为。
4. **cookie 刷新时机**：现在每次发布后写回；上游只在登录时写。是否保留、异常路径是否也写。
5. 本地 `cookie_auth` 的“网络故障 = cookie 失效”是否改为与托管一致（故障 != 失效）。

产出：`check` 行为契约（输入 × 观测 × 输出 × 退出码）+ 身份字段与降级 + 预检时序图。
