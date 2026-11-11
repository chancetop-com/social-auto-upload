# 12 — 会话预检、check 判定与身份回读

Status: resolved
Type: grilling
Blocked by: —
Assignee: wayfinder-session (opencode)

## Question

决定“我们怎么知道自己是谁、还能不能发”。需要确认：

1. **创作者会话预检**：是否加 `ensureCreatorSession` 等价物（读 `galaxy_creator_session_id`，缺失则打开 creator 首页等会话建立，超时 15s）？托管模式用 CDP 读 cookie，本地模式从 `storage_state` 读。
2. **`check` 判定标准**：本地宽松（无登录框即通过）与托管严格（必须有上传入口锚点）现在会给同一账号相反答案。统一到哪一个？是否需要两级（`valid` / `valid-but-degraded`）？退出码如何映射。
3. **身份回读**：是否读 `__INITIAL_STATE__.user.userInfo` 输出 nickname / userId（上游做法）。**注意 patchright 的 `evaluate` 默认在 isolated world，读页面全局变量必须 `isolated_context=False`**；读不到时的降级行为。
4. **cookie 刷新时机**：现在每次发布后写回；上游只在登录时写。是否保留、异常路径是否也写。（同一账号不并发，写回无竞争，见 21。）
5. 本地 `cookie_auth` 的“网络故障 = cookie 失效”是否改为与托管一致（故障 != 失效）。

产出：`check` 行为契约（输入 × 观测 × 输出 × 退出码）+ 身份字段与降级 + 预检时序图。

## Comments

- 来自 **07**（2026-11-11）：运行中的登录/验证判定已定为 exit **10**，本地与托管同码同文案；判定器为只读的 `classify_blocked(page)`（主框架 path + 可见 login-box，见 07 §1）。本票需接力的两点：① 本地预检 `cookie_auth` 失败现在抛 `RuntimeError` → **1**（`main.py:509`），按 07 应区分「确定失效 → 10」与「探测失败（网络/5xx/结构异常）→ 1」——正是本票问题 5 的范围；② `check` 是否复用同一分类器（尤其 `/login` 前缀 vs 上传入口锚点的强弱关系）归本票。
- 来自 **14**（2026-11-11，14 已决议；本票随后由另一会话关闭，仅存档）：托管默认改为**有头**，`check` 不再必须显式 `--headed`；`--account` 在托管下**无意义**（输出标签一律 `profile_id`，传了进 ignored 列表）；session 启动日志固定带 `identity=profile:<id>|account_file:<path>`（只作可观测性——本票已定身份回读不做，不据此重开）。

## Answer

**决议**：会话可用性只有**一个权威来源** —— 发布页那一次导航之后的只读观测（07 的 `classify_blocked` + 05 第 15 行的上传入口锚点）。**零网络前置只用于「确定不可能」的情形**；登录态不靠第二次浏览器启动来证明。身份回读不做。

### 0. 总原则

- **一次发布 = 一次浏览器启动、一次发布页访问。** 现在本地是 2 次浏览器 / 2 次发布页 / 4 个 context（`cookie_auth` 一次 + 上传一次，各带一个 `_xhs_user_agent` 探测 context），本票砍掉前一半。
- **网络故障 ≠ 失效。** 探测失败（5xx / 超时 / 离开创作域 / 结构异常）一律 `1`；只有「确定没登录」才是 `10`。
- **不新增退出码、不新增错误类。** 复用 07 的 `LoginRequiredError(reason, publish_attempted)` 与码表。

### 1. 预检（Q1 = A）

| 模式 | 前置 | 失败动作 |
|---|---|---|
| 本地 | ① `account_file` 存在；② `storage_state` 里有 `galaxy_creator_session_id`；③ 该 cookie 的 `expires` 未过（`expires ≤ 0` / `-1` 视为**未知**，放行） | 任一项确定不满足 → **exit 10**，**不启动浏览器**，stderr 给 `sau xiaohongshu login --account …` |
| 托管 | 无前置 | — |

- **删除**发布链路里的独立预检：本地不再跑 `cookie_auth`（`main.py:335-378`），托管不再跑 `is_logged_in`（`main.py:286-332`）。两者都从发布链路移除。
- 真正判定交给 C1：`goto` 发布页之后立刻 `classify_blocked(page)`，命中 → **10**（`publish_attempted=False`）。
- **依据（代码明确）**：`cookies/xiaohongshu_180.json` 含 `galaxy_creator_session_id`（domain `.xiaohongshu.com`，`expires` ≈ 登录后 30 天），且 UI 所需 `a1` / `webId` / `gid` 同在其中 —— 所以「读文件判存在性」不会误杀。
- **为什么不做上游的 `ensureCreatorSession`**：上游每页都要自己建会话，才需要“缺 cookie 就去首页等 15s”；我们每次发布本来就要导航发布页，同样的导航既是发布入口也是会话判定点，多一次只在高频复用时才有意义。
- 本地「文件缺失」也归 **10** 而非 `1`：对机器侧而言唯一动作是「人去做登录」，与托管同语义；`1` 会被调度层当成“重试可能有用”。

### 2. `check` 行为契约（Q2 + Q5 = A）

```
本地: 前置（0 网络）──失败──▶ invalid / exit 10（不起浏览器）
        └─通过─▶ 建 context(storage_state) ─▶ goto 发布页 ─▶ 观测
托管: 建 context(Profile) ───────────────────▶ goto 发布页 ─▶ 观测

观测 = classify_blocked(page)?
  ├─ login / verification ─▶ invalid + reason(stderr) / exit 10
  ├─ None 且 上传入口锚点 attached (count ≥ 1) ─▶ valid / exit 0 ─▶ [本地] 原子写回
  ├─ None 且 一个锚点都没有 ─▶ invalid + "页面结构异常" / exit 1
  └─ 导航 5xx / 超时 / 离开创作域 ─▶ exit 1（探测失败，不是失效）
```

- **页面 = 发布页**，不改轻量页。`check` 的语义是“这个账号现在能不能发”；上传入口是唯一被实机验证过的直接证据。`/explore` 只能证明“这个浏览器有站点的登录态”，creator 首页的登录锚点（上游 `.main-container .user .link-wrapper .channel`）**从未取证**且只证明“登录了”不证明“能发”。
- **锚点用 `attached` 档**，不用 `visible`：`check` 是后台健康检查，页面可能仍在水合；可见性失败会把一次慢加载判成 `1`。`visible` 留给真正要点击的地方（06）。
- **不做两级**（`valid` / `valid-but-degraded`）：调度侧可执行的动作只有「照常发 / 转人工登录 / 别重试」，第三档没有消费者。
- **stdout 契约不变**（`valid` / `invalid`），`reason` 走 stderr，只有**退出码**从 `1` 改为 `10`（与托管当前行为、07 的码表一致）。
- **本地零网络快路（Q5=A）**：文件缺失 / 无 `galaxy_creator_session_id` / 已过期 → 直接 `10`。**不会误报**——浏览器本来就不会发送已过期的 cookie，“已过期”与“不能用”是同一件事。

### 3. 身份回读（Q3 = A）：不做

- 本图不读 `__INITIAL_STATE__.user.userInfo`，不输出 nickname / userId，不引入 `<account>.identity.json`。
- **理由**：① 它不降低任何封禁风险；② 它不解决已观察到的任何故障——本地错号在登录时即被覆盖，托管错号根因在 Profile 配置（Out of scope）。为一个**没有真机证据**的对象（02 的全部快照 grep 不到；patchright 的 `evaluate` 默认 isolated world，读页面全局需 `isolated_context=False`，本仓产品代码零先例）增加一个可抛错步骤，是净负债。
- **将来若要做**，取证首选**不是** `__INITIAL_STATE__`，而是 `cookies/*.json` 里已存在的 `x-user-id-creator.xiaohongshu.com`（24 位值、带 `expires`、零 JS、绕过 isolated world）；范式复用大鱼号 `identity.json`（登录写 / 上传前比对）。这两条归 **15** 判断是否进 shared 层。

### 4. cookie 写回（Q4 = Z：只有成功才写）

| 出口 | 写回 | 备注 |
|---|---|---|
| 发布成功（OBSERVE = 0） | ✅ | 现状 `main.py:1227` / `:1410` 行为不变 |
| `--no-publish` 干跑走完 | ✅ | 结果码同为 0，只是没点发布 |
| 登录成功（同 context 复核通过） | ✅ | 现状 `main.py:437` 语义不变 |
| `check` = `valid`（本地） | ✅ **新增** | 现状 `check` 只读，从不写 |
| `1` / `9` / `10` | ❌ | 按结果码，不按“有没有抛异常” |
| 托管模式 | ❌ | Profile 是唯一真相，不读不写 |

- **这条规则是对现状的显式化，不是变更**：`upload_video_content` / `upload_note_content` 的失败路径全部 `raise`（宽 `except` 只让循环继续，不会让函数正常返回），所以现状的写点本来就等于“只写成功”。改成按结果码表达，只为让它**可断言**（测试能写「9 不写、0 写」），并把 `--no-publish` 从“碰巧正常返回”变成“显式归 0”。
- **不做**「1/9 也写」：封禁风险三维里写盘是平的（纯本地文件）；多写的唯一收益是失败路径上的会话保鲜，而 `1` 的有效场景多是结构性故障（之后必然要人介入），`9` 是稀有路径 —— 换不来可断言性。
- **原子写**：写 `*.tmp` 再 `os.replace`。与 21 的并发结论不冲突：这不是锁，是防 `kill -9` 落在写一半时把唯一一份登录态写坏（成本两行）。
- **代价（诚实记录）**：若长期只跑 `1` / `9`，文件里的 cookie 会比服务端更早过期 → 多一次人工扫码。它**不会**制造假 10（过期 = 浏览器不发 = 真的不能发），也不会让封禁风险上升。

### 5. 登录链路

- 扫码完成判定继续用 `_is_xhs_login_completed`，但**判据换成 07 的分类器**（`classify_blocked` 返回 `None` 即已离开登录页），删掉现在同时存在的 `/login` 前缀判断与 login-box 可见判断两套。
- **删除登录后的第二次浏览器复核**（`main.py:438` 的 `cookie_auth`）：改为**同一 context 内导航一次发布页**，跑第 2 节的 `probe_session()`。一次导航、零新浏览器，判据与 `check` 完全同一套。
  - 通过 → 原子写回 → `success`；
  - 未通过 → **exit 1**（文案：登录流程结束但发布页未就绪），**不判 10** —— 刚扫码成功就判失效会把人推进扫码循环。
- `xiaohongshu_cookie_gen` 其余部分（二维码抓取、轮询间隔、超时）不动。

### 6. 检查点与时序

```
[本地发布]
前置(0网络) ─✗─▶ exit 10
   └─✓─▶ launch → new_context(storage_state) → goto 发布页
            → C1 classify_blocked? ─命中─▶ exit 10 (publish_attempted=False)
            → 上传 → 填写 → ARM(C3 必查) → FIRE → OBSERVE(C4 轮询)
            → 0 ─▶ 原子写回 ─▶ exit 0
            → 1 / 9 / 10 ─▶ 不写 ─▶ 对应退出码

[托管发布]
connect Profile → goto 发布页 → C1 …（同上，全程不读写 storage_state）

[check]
本地前置 ─✗─▶ invalid/10
   └─✓─▶ 建 context → goto → C1/锚点 → 0(写回) / 10 / 1
托管          → 建 context → goto → C1/锚点 → 0 / 10 / 1（不写）
```

- C1/C3/C4 的位置、`publish_attempted` 的取值、以及「页面状态压过同点超时/异常」全部照 **07 §0**，本票不重复定义。
- 本票只补一条 07 未覆盖的：**前置失败（本地快路）发生在任何导航之前**，因此 `publish_attempted=False`、可无条件重跑。

### 7. 对其它工单的约束

- **13**（两端一致性）：`check` 的 `invalid` 文案与「探测失败」文案由 13 统一，本票只定码。
- **14**：托管模式不再有 `is_logged_in` 预检，14 讨论“参数静默丢弃”时不必再为预检留分支。
- **15**：身份范式（大鱼号 `identity.json`）是否进 shared 层由 15 判断；本票只声明 xhs 不启用。
- **16**：可断言的最小集合 —— ① 前置三态（有/缺/过期）；② `check` 四出口；③ 写回矩阵（0/9/10 各一条）；④ 登录复核走同 context（断言只 `new_page` 一次）。全部可用 `RecordingPage.url` + `FakeLocator` + `FakeContext.storage_state`。
- **17**：把 §1/§2/§4/§5 并入规格，并更新 `GLOSSARY.md` 的 `Login required`（补“本地与托管同码 10；探测失败是 1”）。
- **19**：若 19 改用 `launch_persistent_context(user_data_dir=…)`，则本票的「写回 / 过期快路 / 快照文件」需重定 —— 已在其票内留注释。
- **22**：与文案无关，无影响。

### 8. 置信度

- **代码明确**：现状两个写点及代码位置；失败路径全部 `raise`（宽 `except` 不产生正常返回）；`cookie_auth` 任意异常 → `False`（网络故障 = 失效）；`_xhs_user_agent` 每次多开一个 context；`galaxy_creator_session_id` 存在于本地快照且带过期时间；`check` 现在完全不写。
- **仅推断**：服务端是否在会话进行中轮换 / 续期 cookie（决定“只写成功”的保鲜代价有多大）；托管 Profile 内是否会有我们看不见的自动续期。
- **需真机验证**：登录扫码完成 → 发布页锚点出现的时延（决定 §5 的等待上限）；`/website-login*` 是否会出现（沿用 07 §8）。

### 9. 残余风险

1. 本地只写成功 → 长期失败时多一次重登（可恢复，不是事故）。
2. 托管没有前置 → 会话死亡唯一途径是 C1；若某次 C1 误判为未命中，代价是走完流程后在 ARM/FIRE 处失败（07 已把 C1 放在必查点）。
3. 登录后同 context 复核若页面未就绪 → `1`：比误判 `10` 好（不会逼人反复扫码），但运维需要知道“扫码成功也可能 exit 1”。
4. 原子写只防半个文件，不防“写了一个语义上更旧的快照”——后者由“只写成功”覆盖。

