# 实施手册（15 平台 · 人类化交互层）

给**实施者 subagent** 的共享上下文。平台规格在
`.scratch/humanize-rollout/spec.md` §3 对应小节；本文件只写每次都要重复的
机械约定，不替代规格。

## 0. 工作树与分支

1. 进入分配给你的工作树，确认 `git log -1` 包含集成分支
   `humanize-interaction-layer` 的最新提交；不是就
   `git fetch` / `git reset --hard humanize-interaction-layer`。
2. 建自己的分支：`git checkout -b agent/<ticket>`。
3. 只改：你的平台包目录、`tests/test_<platform>_humanize.py`、你的工单文件、
   `CHANGELOG.md` 里**一行**。不要改 `utils/humanize.py`、`utils/dom.py`、
   `tests/fakes_xhs_dom.py`、`tests/humanize_gates.py`：需要额外 fake 就在自己
   的测试文件里写局部 double / 子类。
4. 完成前：`git merge humanize-interaction-layer`（允许冲突自行解决，重点是
   `CHANGELOG.md`），然后跑全量 `pytest -q`，全绿再报告。

## 1. TDD 纪律

先调 `tdd` skill。每个工单至少三条测试，先红后绿：

1. **事件序列**：每个改 Humanizer 的点断言正确原语（`press` vs
   `insert_text`）、`after_type` 次数、`mouse.move* → down → up`、`stillOn`
   （hit-test）先于 `down`、零 `force` 派发、零 `el.click`。
2. **字段值读回**：fake locator 持有键入缓冲，断言最终值等于预期（抓「序列
   对、值错」：清空不净、追加、`#author` 被抹、文件名残留）。
3. **平台静态门**：调用 `tests/humanize_gates.py` 的
   `assert_clean(package)`（ticket 01 提供）。它在你的包上跑门 A–E。

测试不需要浏览器：用 `tests/fakes_xhs_dom.py` 的 `RecordingPage` /
`RecordingLocator` / `RecordingKeyboard` / `RecordingMouse`，或局部简化
double。**没有 scripted 的选择器要抛错**，不要用 `MagicMock` 掩盖选择器漂移。

## 2. 接入样板（照小红书 `uploader/xiaohongshu_uploader/main.py:2318`）

```python
from utils.humanize import Humanizer

def _humanizer(self, page: Page) -> Humanizer:
    cached = getattr(self, "_humanizer_instance", None)
    if cached is None or cached.page is not page:
        cached = Humanizer(page, sleep=self._humanize_pause)
        self._humanizer_instance = cached
    return cached

async def _humanize_pause(self, seconds: float) -> None:
    remaining = max(0.0, self.publish_budget.remaining_seconds())
    if seconds > remaining and not getattr(self, "_pause_warned", False):
        logger.warning("人类化停顿被预算裁剪: {}s > {}s",
                       round(seconds, 2), round(remaining, 2))
        self._pause_warned = True
    await asyncio.sleep(min(seconds, remaining))
```

- 构造点：`context.new_page()` / `open_upload_page()` **之后**；`expect_popup()`
  / `new_page()` 之后重建（缓存按 `cached.page is not page` 失效）。
- `HUMANIZE=0` 在构造时快照；不要在运行中读 env。
- 一个 page 一个实例；同一 page 不得混用原生 `locator.click()` 与
  `Humanizer.click`。
- 不新增 `type_into` 封装；清空逐字段手写。

## 3. 文本输入

先收窄：`locator.count() == 1`，多义直接 `ElementUnusableError`
（`ambiguous:N`），不要自动 `.first`。

三种清空形态（规格 §2.4），按工单指定的列选：

- `sel`：`click`/`focus` → `humanizer.press("ControlOrMeta+A")` →
  `press("Delete")` → `humanizer.type_text(...)`，中间不插其它动作。
- `seq`：保留平台既有键序，只把 `keyboard.press` 换成 `humanizer.press`。
- `none`：只聚焦 → `type_text`。

硬规则：

- 单行字段不得含 `\n` / `\r` / `\t`；多行先 `\r\n` → `\n`。
- `type_text` 自己付一次 `after_type`；不要手动再付。
- >1000 码点由 `type_text` 整段 `insert_text`，平台不得切段。
- 不要 `fill()`（唯一例外抖音 2FA 验证码，需 `# native-fill: ...`）。
- 不要 `page.keyboard.type()` / `press_sequentially` 写用户内容。

## 4. 点击与标记

- 可见点击：`await humanizer.click(locator)`；比例落点用
  `point=(x, y)`（0–1）。
- 需要先显形：`await humanizer.hover(locator)` 再 `click`。
- 提交点前：`await humanizer.before_submit()`；导航点后：
  `await humanizer.after_navigate()`。
- 保留原生的点击必须在同一行/同一调用跨度内写：

  `# native-click: <login|file|focus|manage|read|verify|chrome|language>；<原因>`

- 保留的 `force=True` 必须带：

  `# humanize-impossible: <失败模式>；<code|inferred|needs-live>；<已排除替代>`

  只有规格点名的 4 条允许存在。
- 不要 `el.click()` / `evaluate("el => el.click()")`，不要「失败降级 JS」。

## 5. 失败语义

`Humanizer.click` 不传 `what`；异常原样上抛。`mouse.down` 之后失败会带
`click_dispatched="maybe"`，**不得再次派发**。业务循环可以按状态重试，
但 `ambiguous:` 不重试。

## 6. CHANGELOG

在 `## [Unreleased]` 下新建/追加对应波次小节（例如
`### 人类化交互层（W2 国外）`），加一行：

`- <平台>：<覆盖点数量> 个交互点接入人类化（<包路径>）。`

## 7. 报告

结束时报告：分支名、提交列表、改动的文件、测试命令与结果、入册门结果、
`HUMANIZE=0` 用例结果、与规格表的偏差（含无法验证项）。同时勾掉工单文件里
已完成的复选框，并在 `## Answer` 写 3–5 行结论（**不要**改 `Status:`）。
