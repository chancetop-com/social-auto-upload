# 18 — 虎扑：专区/声明链路接入

**What to build:** 标题与简介清空后逐字，专区选择、原创/二创、AI 声明下拉与发布点击接入人类化。AI 声明下拉的裸 `combobox` 先收窄到唯一 Locator。登录与两个文件入口保持原生并加标记。

规格依据：§3.5、§4。波次：W5。

Blocked by: 01

Status: ready-for-agent

- [x] 标题/简介逐字；简介 >1000 码点一次 bulk
- [x] `combobox` 收窄到 1；多义即硬错
- [x] 发布点 `before_submit`；零 `fill(`、零 `el.click()`、无 force
- [x] `tests/test_hupu_humanize.py` 三条
- [x] 虎扑入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W5 小节加本平台一行

## Answer

- 接线：`upload_in` 建页后缓存 `Humanizer(page, sleep=self._humanize_pause)`；标题/简介各一次坐标聚焦后 `ControlOrMeta+A` → `Delete` → `type_text`（合并原先独立的聚焦点击），简介保留 `\r\n`→`\n` 且 >1000 码点由共享层整段 `insert_text`。
- 点击：专区四击（添加专区 / 步行街 / 步行街主干道 / 确 定）、原创/二创、AI 声明下拉与「含AI生成内容」、「确定发布」（前置 `before_submit`）全部走 `humanizer.click`；`page.goto` 后补一次 `after_navigate`。
- AI 声明下拉的裸 `get_by_role("combobox")` 经 `_narrow_unique` 收窄：`count > 1` 直接 `ElementUnusableError(reason="ambiguous:N")`，位于「失败继续」try 之外，不会被日志吞掉；0 匹配保持原有「无此控件则跳过」语义。
- 原生保留并标记：QQ 登录 `# native-click: login`；视频/封面的 file chooser 点击 `# native-click: file`（与 `expect_file_chooser` 成对）。
- 测试：`tests/test_hupu_humanize.py` 10 条（事件序列 2、值读回 2、多义硬错 1、静态门/标记 3、`HUMANIZE=0` 与实例缓存 2），全绿；全量 1627 passed / 2 skipped。真机未验证（无虎扑账号环境）。
