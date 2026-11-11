# 29 — 参数契约：默认有头、debug 唯一来源

**What to build:** 一个从命令行直接跑小红书发布的用户，不传任何浏览器参数时看到浏览器窗口（默认有头）；`--debug` 默认关闭，且 `debug` 只有 CLI 一个来源，配置文件和 uploader 默认值不再与它打架。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `--headed` / `--headless` / 都不传，三种组合得到预期的 `headless` 值；**都不传 = 有头**
- [ ] `debug` 默认关；删除配置项 `DEBUG_MODE` 及三处 uploader 默认值来源；静态检索后除变更日志外无残留
- [ ] CLI 参数层仍不读配置里的本地无头开关（现状如此，非回归）；该配置的作用域只影响直接调用 uploader 的路径，并在安装文档中标注
- [ ] 直接调用 uploader 的路径默认值本轮只从 `True` 改为 `False`，其余不变
- [ ] 原先断言"默认无头"的用例同步改写（不是新增纪念性断言）
- [ ] CLI 文档的默认值投影（三列默认值）回写为有头；母本仍是规格 §4/§5
- [ ] 受影响平台的 `check` 冒烟记录：本地与托管各一次（托管缺账号则只记本地）
