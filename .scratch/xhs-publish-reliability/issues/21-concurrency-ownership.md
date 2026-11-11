# 21 — 同一账号的并发与 Profile 生命周期所有权

Status: resolved
Type: grilling
Blocked by: —
Assignee: wayfinder-session (opencode)

## Question

调度 App 可以对同一个账号同时起两个 `upload` 进程。现在没有任何互斥机制，两条链路会互相踩。本票决定：**同一账号被并发调用时，我们的行为是什么，以及在哪一层实现。**

> 范围的界定：**多账号**并发隔离仍归 Out of scope（由 Profile 承担，且**已明确支持**）；本票只管**同一账号 / 同一 Profile 的两个实例**。

### 已有契约（不是空白，是「故意不管」）

`docs/CLI.md:195` 写得很清楚：

> 保证同一 Profile **不并发**；CLI 不加锁，也不做 active 预检。同一 Profile 的串行由调度 App 负责。

同时多账号并发是**被支持的**：`README.md:322`「可以按账号名并发执行任务」、`docs/install.md:158`「可以准备多个账号并发使用」。

所以本票真正要决定的是：**这条「把串行责任推给调度 App」的契约要不要保留**；如果要保留，就得保证**违反契约时的伤害是局部的**——而现在的 `_stop_profile` 是无条件的，违反契约会直接把别人的浏览器杀掉。多账号并发本身不是问题：不同账号 → 不同 Profile / 不同 cookie 文件 → 互不共享可变状态。

### 代码事实（置信度：代码明确）

1. **全仓没有任何进程间互斥**：`flock` / `fcntl` / `FileLock` / `O_EXCL` 均 0 处；CLI 每次进程独立、无共享状态。
2. **本地模式的 cookie 文件是「启动读、干净退出写」**（`utils/browser_session.py:174` 读、`:194-196` 写）：
   - 两个进程从同一快照起步 → 先退出的写入刷新后的状态 → 后退出的用旧状态**覆盖**它 → 下一次运行拿着过期快照，表现为「登录失效」。
   - `context.storage_state(path=...)` 直接写目标文件，不是「临时文件 + rename」；并发写有概率写坏 JSON（**仅推断**，未复现）。
3. **托管模式的所有权规则只覆盖了一半**（`utils/browser_session.py:210-220` 注释）：
   - 已有规则：`Start` 失败 ⇒ 不属于本进程 ⇒ **绝不 Stop**。
   - 缺失的逆命题：**`Start` 成功 ≠ 这个 Profile 是本进程启动的**。
   - `provider.status()` 存在，但 docstring 明确写着 *"never used for control flow"*（`utils/managed_browser.py:32-33`）。
   - `_managed_session` 的 `finally` 无条件 `_stop_profile`（`:257-262`）。若第二个进程也 `Start` 成功，**先退出的那个会杀掉还在跑的那个的浏览器**。
4. **两个托管进程会共享同一个 context**：`_managed_session` 取 `browser.contexts[0]`（`:239-251`），后连上来的进程拿到的是前者那个 context —— cookie、localStorage、登录态全部共享。
5. **`provider.start()` 在「Profile 已在运行」时的响应未定义**：MLX 是 `GET .../start?automation_type=playwright`（`utils/multilogin.py:134`），AdsPower 是 `POST /api/v2/browser-profile/start`（`utils/adspower.py:213`）。两者对「已运行」是返回既有端口还是业务错误，**需真机验证**。

### 必须确认

1. **策略**：同一账号并发时，是「拒绝后到者」、「排队串行」、「按分钟合并」，还是允许（只在日志里警告）？三个选项分别对应什么退出码？
1b. **要不要保留 CLI.md:195 的契约**（调度 App 负责串行、CLI 不加锁）？若保留，最低要求是「不误伤」：`Stop` 前证明 Profile 是本进程启动的；若不保留，则 1 的答案变成「CLI 自己拒绝或串行」。
1c. **多账号并发的边界**：不同账号并发时共享的资源只有——日志文件（`logs/<platform>.log`，loguru `rotation="10 MB"` 跨进程不安全）、本机 CPU/带宽，以及 provider 的并发 Profile 上限（MLX 按套餐、AdsPower 按订阅，**需外部核实**）。这些要不要进契约？
2. **互斥的实现层**：CLI 本地文件锁（`.local/locks/<platform>_<account>.lock`？），还是交给调度 App？若本地锁，是否两把（账号级 + Profile 级）？
3. **锁的生命周期**：`--not-before` 会让进程挂几小时——等待期间持锁还是放锁？放锁则两个进程可能同时进入提交段。
4. **陈旧锁回收**：进程被 `kill -9` 后锁怎么失效？PID 存活探测、启动时间戳、心跳、还是租约（TTL）？
5. **托管 Profile 所有权**：`Start` 前是否查 `status` 并在「已在运行」时**拒绝启动**（推荐？）还是接管但**不 Stop**？这会把 `status()` 从 diagnostic-only 提升为 control-flow，需要显式改契约。
6. **同 context 并发是否允许**：即便不 Stop，两个 page 在同一 context 里同时发布是否可接受？还是「一个 Profile 同时只允许一个 session」？
7. **本地 cookie 写回**：加锁后自然串行，还是同时要做原子写（tmp + rename）+ 「只写更新的一方」？
8. **退出码**：并发冲突用什么码——`UsageError`(2)、新增专用错误、还是复用 `RateLimitedError`(11)？调度侧需要能区分「稍后重试」与「配置错误」。
9. **与 18 的分工**：18 管时间维度（最小间隔、失败冷却、熔断），其「连续失败计数 / 频次上限」**依赖本票的锁**才能跨进程生效；本票管空间维度（同一时刻只有一个实例）。两票不得互相覆盖。

### 产出

锁的粒度 × 持有区间 × 陈旧回收 × 冲突出口 的判定表；改动点清单（`browser_session` / `sau_commands` / 锁模块）；以及「两个进程同账号同时启动」的验收脚本形态。

## Comments

- 2026-11-11 由 03 的会话暴露：讨论「先置位再派发」时确认了**单进程内**的重复点击裂缝（demo S5），随后延伸到**跨进程**——同一账号两个 `upload` 时，上述 5 条代码事实没有任何一条被处理。

## Answer

**前提（用户确认，2026-11-11）：同一账号不会并发。** 调度侧保证一个账号同一时刻只有一个 `upload` 进程。这与 `docs/CLI.md:195` 的既有契约一致：同一 Profile 的串行由调度 App 负责，CLI 不加锁、不做 active 预检。

**因此本票不做任何改动：**

- **不引入进程间锁**，不引入账号级互斥，不把 `provider.status()` 从 diagnostic-only 提升为 control-flow。
- **本地 cookie 的写回竞态不成立**：同一账号只有一个写入者，「后退出覆盖先退出」不会发生。
- **托管 Profile 的 `Stop` 误伤不成立**：同一 Profile 不会被第二个进程启动，`_stop_profile` 的无条件 Stop 只作用在自己启动的那个实例上。
- **退出码不变**：不存在新的并发冲突出口。

**多账号并发依然成立且被支持**（`README.md:322`、`docs/install.md:158`）：不同账号 → 不同 Profile / 不同 cookie 文件 → 没有共享的可变状态。仅有的共享点是日志文件轮转（loguru 的 `rotation` 是进程内语义）、本机资源、以及 provider 的并发 Profile 上限——都属于部署约束，不进入本规格。

**这条保证是部署前提，不是代码保证。** 若将来允许多实例（例如调度 App 改成并行、或 CLI 被手工并发调用），本票必须重开，且届时至少需要三件事：账号级锁、`Stop` 前的所有权证明、cookie 写回的原子化（tmp + rename）。

## Comments

- 2026-11-11 由 03 的会话暴露：讨论「先置位再派发」时确认了**单进程内**的重复点击裂缝（demo S5），随后延伸到**跨进程**。
- 同日收口：用户确认调度侧不会对同一账号并发，本票无待决事项，仅记录该前提与重开条件。
