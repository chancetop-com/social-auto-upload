# 29 — 参数契约：默认有头、debug 唯一来源

**What to build:** 一个从命令行直接跑小红书发布的用户，不传任何浏览器参数时看到浏览器窗口（默认有头）；`--debug` 默认关闭，且 `debug` 只有 CLI 一个来源，配置文件和 uploader 默认值不再与它打架。

**Blocked by:** None — can start immediately.

Status: resolved

- [x] `--headed` / `--headless` / 都不传，三种组合得到预期的 `headless` 值；**都不传 = 有头**
- [x] `debug` 默认关；删除配置项 `DEBUG_MODE` 及三处 uploader 默认值来源；静态检索后除变更日志外无残留
- [x] CLI 参数层仍不读配置里的本地无头开关（现状如此，非回归）；该配置的作用域只影响直接调用 uploader 的路径，并在安装文档中标注
- [x] 直接调用 uploader 的路径默认值本轮只从 `True` 改为 `False`，其余不变
- [x] 原先断言"默认无头"的用例同步改写（不是新增纪念性断言）
- [x] CLI 文档的默认值投影（三列默认值）回写为有头；母本仍是规格 §4/§5
- [ ] 受影响平台的 `check` 冒烟记录：本地与托管各一次（托管缺账号则只记本地）

## Comments

### 2026-11-11 — 实施记录

- 默认有头：`sau_commands/arguments.py` 的 `set_defaults(headless=False)`；三种参数组合由 `tests/test_runtime_defaults.py` 与 `tests/test_adspower_cli.py` 断言。
- `debug` 唯一来源：删除 `conf.example.py`、`docs/install.md` 的配置项，以及 5 个 uploader 的 import/构造默认值；其余 `debug: bool = True` 构造器一并改为 `False`。`tests/test_runtime_defaults.py` 做残留静态检查。
- CLI 参数层仍不读取 `conf.LOCAL_CHROME_HEADLESS`；作用域已写入 `docs/install.md` 与 `docs/CLI.md`。
- `docs/CLI.md` 的三列默认值与运行时参数说明回写为有头。
- 16 平台 `check` 冒烟：**未验证（无真机环境）**（本地与托管均需要真实浏览器/账号）。
- 离线回归：`python -m unittest discover -s tests -t .` → `Ran 1073 tests`，`OK (skipped=2)`。
