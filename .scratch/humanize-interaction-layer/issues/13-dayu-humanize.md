# 13 — 大鱼号：跨 iframe 正文与 `#author` 保留

**What to build:** 视频表单与图文表单接入人类化。图文正文在独立 iframe 内：聚焦与工具栏点击用 frame 内 `Locator`；正文粘贴保持原生。`#author` 的清空策略为 `none`（缺省保留页面预填，只有显式传 `author` 才覆盖）；两个标题字段的预填未知，按「先读空再写」处理。定时与发表各点接入。

规格依据：§3.3、§2.4、§4。波次：W4。

Blocked by: 01

Status: ready-for-agent

- [x] iframe 内目标用 frame 内 `Locator`；不把 `frame_locator` 当 page 传给 `Humanizer`
- [x] `#author` 不被清空；显式传值时覆盖
- [x] 标签逐字 + Enter；每个标签一次 `after_type`
- [x] 失焦专用点击带 `# native-click: focus`；文件入口带 `# native-click: file`
- [x] `tests/test_dayu_humanize.py` 三条（含 `#author` 不被抹、iframe 正文事件序列）
- [x] 大鱼入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W4 小节加本平台一行

## Answer

- 视频/图文各在 `new_page()` 后构造并缓存唯一 `Humanizer(page, sleep=self._humanize_pause)`；图文 iframe 正文用 frame 内 `Locator` 交给主 page 实例，粘贴保持原生按键。
- 视频标题与图文标题按「先读空再写」处理；`#author` 缺省完全不动页面预填，显式传入时才全选覆盖；标签逐槽输入后逐个 Enter，每标签恰一次 `after_type`。
- 分类、标签组件、封面裁剪、iframe 工具栏、封面槽与定时/发表点击全部走坐标点击；3 处正文失焦点击与 3 处文件入口保留原生并带 marker；`publication.py` 两次提交点击前各付一次 `before_submit`。
- 新增 `tests/test_dayu_humanize.py` 5 个用例（事件序列 / iframe 正文 / `#author` 读回 / `HUMANIZE=0` / 静态门 A–E），全部通过。


