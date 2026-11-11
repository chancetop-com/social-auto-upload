# 28 — 测试夹具、术语与退出码镜像骨架

**What to build:** 让后续每一票都能在离线环境里断言 DOM 判定、虚拟时钟与点击次数；把本规格新增的机器语义写进术语表；把退出码契约做成一棵"还差哪些码没覆盖"会自动报错的表。本票不改生产行为。

这是整个 effort 的预置工作（"先把改动变容易"）：后面 31–40 全部依赖同一套夹具和同一张码表。

**Blocked by:** None — can start immediately.

Status: resolved

- [x] `FakeLocator` 覆盖 `count`/`first`/`nth`/`get_attribute`/`is_visible`/计算样式/子节点/文本；**未 scripted 的选择器直接抛错**（防止假夹具把真实选择器漂移掩盖成"未命中"）
- [x] `RecordingPage` 可写 `url` 与 `main_frame.url`，记录 `goto`、`evaluate`（含 `elementFromPoint` 落点）、`mouse.*`、`keyboard.*`、`screenshot`、以及每次 `wait_for_*` 的 timeout 实参
- [x] `RecordingLocator.click` 计数，可断言"恰好一次"与"零次"
- [x] `FakeClock` 上下文管理器能替换被测模块的 `time.monotonic` 与模块级 `asyncio` 名；**生产代码不新增 clock/sleep 参数**
- [x] 退出码镜像表：一行一场景（异常/字段 → 码 → stderr 断言），覆盖集合 `{0,1,2,9,10,11,130}`；meta 断言维护"尚未实现"清单，随各票递减，41 时为空
- [x] 术语表按规格 §9.1 新增/修订：`ARM / FIRE / OBSERVE`、`publish_attempted`、`人机验证（verification）`、`元素角色（attached/visible/interactive/editable）`；`Login required` 条目改成"本地与托管同码 10，探测失败是 1，点击后检出带 `publish_attempted=true`"
- [x] 现有测试零改动仍全绿

## Comments

- 全量 `python -m unittest discover -s tests -t .`：1104 tests OK（skipped=2）。既有测试文件零改动。
- 环境说明：`utils/article_renderer/node_modules/baoyu-md` 是 gitignored 的本地依赖，worktree 里原本不存在，导致 article/dayu/xueqiu 共 16 个用例报 "Markdown 渲染需要 Node.js 22+ 及依赖"。把主仓库的 `utils/article_renderer/node_modules` 软链进本 worktree（未跟踪、未提交）后全绿；该依赖不是本票产物。
- 本票无真机验收项，不涉及 `未验证（无真机环境）` 条目。
- 夹具公共 API（供 31–40 使用）：`tests.fakes_xhs_dom` 导出 `FakeLocator` / `RecordingLocator` / `RecordingPage` / `RecordedWait` / `UnscriptedSelectorError` / `UnscriptedEvaluationError`。`RecordingPage(url=..., selectors={"<css>": RecordingLocator(...), "text:<文案>": ..., "role:<role>:<name>": ...}, evaluate_results=[...], hit_test_target=...)`；未 scripted 的 `locator`/`get_by_text`/`get_by_role` 抛错。交互记录：`locator.actions`/`click_count`/`assert_clicked_once()`/`assert_never_clicked()`，`page.goto_calls`/`evaluate_calls`/`screenshot_calls`/`wait_calls`（`RecordedWait(method, timeout, args, kwargs)`）/`timeouts(method)`，`page.mouse.actions`/`down_count`，`page.keyboard.actions`。`tests.fakes_clock.FakeClock(start=..., module=...)`：`monotonic()`/`advance(s)`/`sleep(s)`/`sleep_calls`，`with clock.patch(*modules)` 或 `with FakeClock(module=m)` 替换模块级 `time` 与 `asyncio` 名。

