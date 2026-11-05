# 27 — opt-in MLX 冒烟测试

**What to build:** 提供一套默认跳过、需要真实 Multilogin 桌面应用才能运行的冒烟测试，用来把 spec 中标注“官方/社区”置信度的结论落成实测证据。它只验证浏览器生命周期，不上传任何内容。真实执行依赖外部账号，ticket 08 仍保持开放。

**Blocked by:** 15.

**Status:** resolved（代码与说明已交付；真实环境未执行）

- [x] 测试由 `SAU_MLX_SMOKE=1` 显式开启；默认 `python -m unittest discover -s tests` 不启动浏览器、不访问网络、不失败。
- [x] 冒烟流程：probe → start → `connect_over_cdp` → 断言恰好 1 个 context → `browser.close()` → stop；不上传、不读写 cookie。
- [x] 断言 Stop 在成功路径只调用一次；stop 已停止的 Profile 被视为成功。
- [x] 断言 `no_defaults=True` 在当前 patchright/Mimic 组合下可用；若不可用，记录回退结论（去掉 `no_defaults`）并回填 spec。
      - 真实环境未执行，`no_defaults=True` 仍未实测；测试文件头部写明回退规则（不得静默改动生产默认值）。
- [x] 失败时输出可用于排障的信息（profile_id / folder_id / port / Launcher 错误码），但绝不输出 token 或 Authorization 头。
- [x] 测试文件头部注明所需环境变量、前置条件（桌面应用、Mimic、同机）与“无账号时跳过”的说明。
- [x] 在有真实账号的环境中执行一次，并把结果回填到 spec 的风险表与 ticket 08；若仍无账号，本票交付代码与说明即可，不伪造实测结论。
      - 当前仍无账号：未执行，未伪造实测结论。环境变量为 `SAU_MLX_SMOKE` / `MLX_API_TOKEN` / `SAU_MLX_FOLDER_ID` / `SAU_MLX_PROFILE_ID`。
