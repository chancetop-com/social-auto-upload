# 01: 安全定位、占用与重建本地 Profile

**What to build:** 用户可以通过明确指定平台、账号别名和浏览器种类的 reset-profile 安全清空一个本地浏览器 Profile，无需安装或启动浏览器；安全定位和 Profile 占用能力也供后续登录与业务会话复用。

**Blocked by:** None (can start immediately)

**Status:** resolved

**批次：** 第一批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [x] 提供 sau <平台> reset-profile --account <别名> --browser-kind chrome|chromium 的完整 CLI 行为；本票先为第一批平台开放，后续平台随各自接入票开放，Bilibili 不提供入口。未迁移平台的已有动作继续按原行为运行。
- [x] Profile 使用项目专用根，依正式平台、原始账号别名、实际浏览器种类隔离，以浏览器种类叶子目录作为 user data directory；不使用日常浏览器资料、父账号目录或浏览器内部 Default 目录，整个资料根排除版本控制。
- [x] 别名保持原值与可读性，不裁剪、改大小写、Unicode 归一化、哈希化或转义；拒绝空白名称、路径分隔符、点目录及越界输入，文件系统不支持时明确失败。大小写或 Unicode 等价路径碰撞不得合并账号资料。
- [x] 在互斥保护下安全创建、读取和校验平台、原始别名及种类归属；已有目录元数据缺失、损坏或冲突时拒绝认领。元数据不包含凭据副本或永久真实账号绑定，父级别名归属可供两种浏览器安全共用。
- [x] 针对实际解析目录建立非等待式跨进程互斥；同 Profile 占用立即以 1 退出，不同 Profile（包括同别名两种浏览器）可并行，等价路径不能绕过占用。PID、时间戳和诊断文件存在不代替活锁判定。
- [x] 锁与可重建资料分离，重建不删除自身互斥保护；残留诊断文件不永久阻断使用。检测到外部浏览器占用或无法安全确认时给出有依据的故障，不删除 singleton 锁、不终止或接管外部浏览器。
- [x] 重建目标仅由显式 browser-kind 决定，不读取浏览器选择、可执行文件配置或安装状态来推导，不启动浏览器、不执行产品识别；托管模式拒绝此动作，且不调用 provider。
- [x] 归属、路径与占用检查通过后，只删除目标种类叶子目录和专属状态；保留父级别名归属、另一种类、其他别名、历史发布结果及旧 Cookie/身份资料。
- [x] 显式命令即清除意图，不增加交互确认或备份；显示目标和结果。目标不存在视为已清空，成功退出 0 并提示 login，不启动登录、不续跑业务、不创建看似有效的 Profile。
- [x] 部分删除失败退出 1，报告未完成状态；残缺资料不能被后续会话当作有效 Profile，修复后可重跑同一显式命令。重建不构成重新发布旧任务的依据。
- [x] 从正式 CLI 验证目标选择、非法参数、路径/归属冲突、无需 binary、托管拒绝、已不存在、部分失败和保留范围；使用临时目录及两个真实子进程，通过同一公开 Profile 取得入口验证争用、释放、不同 Profile 并行和残留诊断文件，不新增仅供测试的锁接口。
- [x] 同步本批重建命令说明与交付记录，列出测试命令、实际结果及尚未迁移平台；本票只验证重建和占用，浏览器启动及持久化实测由 02 完成。


## Answer

已交付第一批四平台的显式 `reset-profile`，以及供后续会话复用的 `utils.local_profile.acquire_local_profile(platform, account, browser_kind, *, root=None, create=False)`。这是同步 context manager，产出 `LocalProfile.path`（实际浏览器种类叶子目录）和 `exists`；调用方必须保持作用域直到浏览器关闭。`create=True` 只用于登录初始化；`exists` 不代表平台已登录。未迁移平台和既有会话/上传动作没有切换。

平台归属记录位于资料根，账号归属、种类互斥文件及未完成重建记录位于账号父目录；种类归属位于叶子目录。原始别名不参与裁剪、大小写/Unicode 变换或编码，元数据字段仅有平台、别名及种类，不绑定真实账号。平台记录不占用账号名空间，`.sau-owner.json` 等合法别名也可使用。现有目录必须能核验归属；链接、损坏、冲突和不支持的文件名明确失败。

短时 layout 互斥只覆盖平台/账号元数据的创建和校验，随后释放；整个 Browser session 使用对应种类的非等待式 OS 锁（POSIX flock / Windows msvcrt）。不同账号和同别名的 Chrome/Chromium 可同时持有各自占用。锁文件保留作为诊断，PID/时间及文件存在不参与活锁判定。重建复用同一取得路径和种类锁，只删除叶子资料；若删除中断，父级重建记录阻止后续会话使用残缺资料。重跑可容忍已经删除的叶子元数据，但仍存在的损坏/冲突元数据不能被重建记录覆盖。

CLI 在任何本地路径访问前拒绝托管模式，不调用 provider；浏览器配置、产品识别和启动不参与重建。外部 singleton/lockfile 证据一律保守拒绝，报告“占用或残留状态、无法安全确认”，不删除这些浏览器锁、不终止浏览器。成功显示目标及登录提示，不登录、不恢复发布任务。README 与 CLI 使用说明已同步；既有 `/browser_profiles/` ignore 规则经命令验证有效。

## Comments

### 2026-11-17 — 实施与实际验证

- 独立 worktree：`/private/tmp/sau-local-profile-01`，分支 `codex/local-profile-01`，基线和 integration tip 均为 `47cc185`。实施前已读取 TDD skill 及 tests/mocking 指引，使用规格中已确认的正式 CLI 与公开 Profile 取得 seam；没有为锁增加测试专用接口。
- 按 red → green 推进：先观察缺失 CLI/API、非法别名误成功、未归属目录误删除、真实第二进程误取得占用、部分删除未报告未完成、外部 singleton 未阻止重建、合法别名与平台元数据冲突、重建记录覆盖冲突归属、非普通元数据读取超时等失败，再补对应最小实现。
- 主机实际为 Darwin 25.6.0 arm64。临时目录实测大小写等价与 NFC/NFD 等价均为 true，因此碰撞测试实际走了拒绝合并分支。Linux/Windows 原生进程互斥没有在本机执行；不把 POSIX 结果表述为这些系统的实测。
- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_local_profile -v`：**20 tests passed**，日志 `/private/tmp/sau-profile01-ownership.log`。真实子进程验证同 Profile 立即失败（断言 <2 秒）、CLI 在占用中拒绝重建、释放后复用、两个种类/不同账号并行、被终止的测试进程释放 OS 锁、残留诊断文件不阻塞、等价路径无法绕过；另有真实临时文件系统上的元数据、路径、精确删除与保留范围。部分删除只在文件系统边界注入 PermissionError。
- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_local_profile tests.test_sau_browser_cli tests.test_tiktok_note_cli tests.test_multilogin_cli tests.test_adspower_cli tests.test_browser_session -q`：**213 tests passed**（5.129 秒），日志 `/private/tmp/sau-profile01-regression.log`。首次回归发现原 `--account` 全部可选断言不适用于明确删除目标，已更新为仅 reset-profile 必填；其余既有 CLI/provider/session 契约通过。
- `git check-ignore browser_profiles/synthetic/check` 返回该路径；`git diff --check` 通过。`git merge --no-edit codex/local-chrome-profile` 在本 worktree 执行，结果 `Already up to date.`；sandbox 不允许写 worktree Git 元数据时经授权 escalation 完成，没有修改 integration checkout。
- Windows `lockfile` 的保守检查依据 [Chromium process_singleton_win.cc](https://raw.githubusercontent.com/chromium/chromium/main/chrome/browser/process_singleton_win.cc) 的 delete-on-close 文件行为；不宣称检查能够证明残留进程已退出。
- 本票没有启动浏览器、接触真实账号、发布或删除作品。浏览器启动/持久化实测属于 02；四平台现有业务会话仍待 02–05 接入，其他平台待各自票开放 reset-profile。无本票阻塞。
