# 05 — Instagram 真机验收（`--no-publish`）

**What to build:** 不改生产代码。本地模式真机用 **`--no-publish` 干跑** Instagram（视频 + carousel 图文各一次），跑到 Share 就绪（窗口 `min(60s, 剩余预算)`）即停，**不点击发布、不上真实帖子**；`--result` 的状态应为 `prepared`，不写 `content_id` / `post_url`。同时记录 `HUMANIZE=1` 与 `HUMANIZE=0` 两条路径的墙钟、预算消耗与成败，落 `.scratch/humanize-rollout/acceptance.md`。

规格依据：§6.4、§7.1；干跑契约见 `docs/CLI.md` 的 `--no-publish` 一节。

Blocked by: 02

Status: ready-for-human

- [ ] 视频 + carousel 各一次跑到 Share 就绪，退出码 0
- [ ] 就绪超时（退出 1）视为失败：记录目标、reason 与预算余量
- [ ] 配文 >1000 码点 `insert_text` 后读回一致；≤1000 时逐字可读回
- [ ] 地点候选逐字后按全等选中；未错选相邻项
- [ ] alt text 逐张写入后失焦保存，读回一致
- [ ] `HUMANIZE=1` / `=0` 双基线已记录（墙钟、差值、成功与否、停止点）
- [ ] 风控观测：是否出现验证码 / 滑块 / 限流提示
- [ ] 发布按钮的真实点击**不验**（§9-28）
- [ ] 若失败且判定为人类化导致 → 回滚 02 的平台提交，不保留双形态

## Answer

真机首次导航点击在 ~7s 报 `ElementUnusableError(reason="point-drift")`（截图停在首页，创建弹窗未出现）：Instagram 左侧导航栏 hover 即展开，`Humanizer.click` 的移动与 stillOn 复核之间包围盒位移 >1px。按 spec §2.5.1 的唯一处方**只在调用点**修——`uploader/meta_uploader/insgraph_uploader/main.py` 的 `_click_nav`（创建入口与向导 Next 共用）先 `await humanizer.hover(locator)` 再 `await humanizer.click(locator)`，与小红书 `.cover-edit-entry` 同模式；`utils/humanize.py`、`utils/dom.py` 零改动：不加内部重试、不放宽容差、不改事件序列，hover 后仍遮挡照常 `covered-by:*` 硬失败。

覆盖（`tests/test_instagram_humanize.py`，24 passed）：
- `test_nav_helper_hovers_before_its_own_move_and_mouse_down`：用两次 `pointer_settle` 切段，hover 的 `mouse.move*` 爆发在前，`click` 自己的移动爆发与唯一一次 `down` 在后。
- `test_both_nav_call_sites_go_through_the_hovering_helper`：`_click_nav` 内调用序列为 `hover → click → after_navigate`；`_click_nav` 恰两个调用点（`_upload_files` 的 `entry`、`_advance_media_editor` 的 `action`）；`humanizer.click` 只允许出现在 `_click_nav` / `_click_submit` / `_dismiss_optional_prompt`。
- fast path（`HUMANIZE=0`）：一次直通 `locator.hover` 先于一次 `locator.click`，零停顿不变。

`Status:` 未改（真机复跑仍需按上面清单执行）。

### 第二次干跑：配文回读（同日，integration tip `3d506a8`）

导航修好后流程 ~58s 到达配文页，随后在 `expect(editor).to_have_text(caption)` 失败（stage `publish`，退出 1）：期望 `人类化回归 Reel 1113\n\n人类化交互层回归干跑。\n\n#回归测试 #自动化`，`textContent` 实得 `人类化回归 Reel 1113人类化交互层回归干跑。#回归测试 #自动化`。证据 `.local/instagram-errors/8d8c8d8794aa4040863d4c5eb3b1d773/page.html` 显示 Lexical 段间插入的是 `<br><br>` 而非多个 `<p>`：`textContent` 丢换行，`innerText` 保留。人类化移植前该字段用 `editor.fill(caption)`，DOM 形态不同才让 `textContent` 恰好相等；移植后按 spec §2.4 rule 3 把 `\n` 打成 Enter，因此**只改编读取形态，不改编键入**。

`uploader/meta_uploader/insgraph_uploader/main.py`：
- 新增 `_normalise_caption_text`（`\r\n`/`\r` → `\n`，去尾部空白）、`_read_back_caption`（取 `locator.inner_text()`，每 200ms 轮询，`budget.clamp_ms(30_000)` 上限，不等即 `AssertionError` 带上期望/实际）与两个上限常量。
- `_publish` 里那次 `to_have_text` 换成单次 `_read_back_caption(...)`。比较仍是**全等**（非前缀），探测异常不捕获、照常上抛；失败仍是点击前普通失败（stage `publish`、退出 1、未发布）。
- 共享层、其他平台、依赖：零改动。

覆盖（`tests/test_instagram_humanize.py`，29 passed = 原 24 + 5；全库 1707 passed / 2 skipped）：
- `test_caption_readback_accepts_br_rendered_inner_text`：真机原配文（`\n\n` 段间）通过，首次采样即相等、零轮询等待。
- `test_caption_readback_fails_on_a_single_missing_character`：少一个字符即失败，消息含期望与实际。
- `test_caption_readback_polls_until_the_editor_catches_up`：前两次探测不等、第三次相等，恰好两次 `wait_for_timeout(200)`。
- `test_caption_readback_fails_loudly_when_the_probe_errors`：探测抛错向上抛，绝不静默放行。
- `test_caption_readback_compares_rendered_text_not_to_have_text`：静态哨兵，`_publish` 不再出现 `to_have_text` 且调用 `_read_back_caption`，helper 必须用 `inner_text()`。

`Status:` 未改（真机复跑仍需按上面清单执行）。

### 第三次干跑：配文页开关的点击目标（同日，integration tip `c037298`）

配文回读修好后流程 ~62s 到达 `options` 阶段，`--no-comments` 与 `--ai-generated` 同时以
`ElementUnusableError(reason="opacity-zero")`（role `interactive`）失败，结果
`comments=mismatch; ai_generated=mismatch`、退出 1、未发布任何内容。证据：IG 的开关是
`<input type="checkbox" role="switch" aria-checked="...">`，Instagram 把 **input 自身**
样式成 `opacity: 0`，用户看到的轨道/滑块在它的直接父容器里。`utils.dom.check` 按 spec
把 `opacity < 0.1` 判为不可点，而 `SwitchControl.set` 之前把 input 直接交给
`Humanizer.click`，于是死在坐标点击自己的 `interactive` 复核。

`uploader/meta_uploader/insgraph_uploader/controls/toggles.py`（共享层与 `_rows.py` 零改动）：
- `_locate` 不变，仍返回 `input[role=switch]`：回读继续读真实开关的 `aria-checked` /
  `is_checked()`，语义值不受影响。
- 新增模块内 `_click_target(switch)` / `_visible_target(node)`：**只解析点击目标**。
  开关自身通过共享 `utils.dom.check(..., "visible")` 时就是目标（普通开关坐标不变）；
  否则逐层 `xpath=..` 向上最多 4 层（`_CLICK_ANCESTOR_LEVELS`），返回第一个通过同一
  可见性检查的祖先；一个都没有则原样返回开关，让点击以原来的 `opacity-zero` 硬错失败。
  没有 `force`、没有 JS 点击、没有键盘或重试兜底。
- `set()` 只把 `click_control(...)` 的 locator 换成 `await _click_target(switch)`，
  `_rows.activate` / `click_control` 语义与其他控件零变化。

覆盖（`tests/test_instagram_humanize.py`，34 passed = 原 29 + 5）：
- `test_opacity_zero_switch_clicks_the_visible_parent`：`opacity:0` 的 input + 可见直接父容器 →
  命中测试发生在父容器、恰好一次 `mouse.down`/`up`、零原生点击，回读仍读 input 的
  `aria-checked`（点击父容器翻转它）。
- `test_no_visible_ancestor_keeps_the_opacity_zero_hard_error`：4 层祖先全不可见 →
  目标退回开关本身，抛出的就是原来的 `opacity-zero`（role `interactive`、
  `publish_clicked=False`），且零点击。
- `test_comments_and_ai_label_controls_both_click_the_visible_parent`：经真实
  `resolve_instagram_option_controls` 注册表跑 `comments`（invert）与 `ai_generated`
  两条路径，各自命中父容器、各自回读 input；两次 `down`、零原生点击。
- `test_a_visible_switch_is_clicked_directly`：不是 opacity:0 的普通开关仍点开关本身，
  命中测试在开关上、祖先零点击——保证这次只改“不可见开关”的目标。
- `test_fast_path_still_clicks_once_on_the_visible_parent`：`HUMANIZE=0` 下同一条解析
  路径，恰好一次 `locator.click`（落在可见父容器）且零 pause；文档写明了期望目标。

全库：1712 passed / 2 skipped（781 subtests）。`utils/humanize.py`、`utils/dom.py`、
`_rows.py`、其他平台、真实 C 层 fixture 均零改动。

`Status:` 未改（真机复跑仍需按上面清单执行）。

### 第四次干跑：联想浮层关闭（同日，integration tip `57e9b0f`）

开关修好后同一支视频干跑（`--no-publish`，`HUMANIZE=1`）进入 `options`：逐字符键入
`#回归测试 #自动化` 后 Instagram 在右侧选项面板上弹出 hashtag 联想浮层；键入地点后
又弹出地点联想浮层。两处浮层在对应选项已应用后仍留在 DOM 且盖住面板，后续点击以
`covered-by:button._acmx`（联想行）失败；地点控件还因浮层未关而把输入值误判为已选。
用 `Humanizer.click` 点一次创建弹窗的 `role="heading"`（“New reel” / “Create new
post” 标题栏）即可关闭；完整干跑（配文回读后一次、地点选中后一次）随即通过，退出 0、
四项选项全部 `set`。诊断用的打印与临时原生 `candidate.click()` 探针**未提交**。

`uploader/meta_uploader/insgraph_uploader/controls/_rows.py`（新增唯一共享助手，
`main.py` / `location.py` 各自调用）：
- `dismiss_suggestions(dialog, humanizer)`：取 `dialog.get_by_role('heading',
  level=1).first`，仅当 `count() == 1` 时 `await humanizer.click(heading)` 并返回
  `True`；标题栏缺席（或探测失败）返回 `False`，**不抛错、不影响发布**。没有
  `force`、没有 JS 点击、没有重试。
- `main.py` `_publish`：配文回读之后、`_apply_options` 之前调用一次；未用
  `editor.blur()` 之类的失焦兜底——标题栏点击才是实测有效机制。
- `location.py` `LocationControl.set`：`_wait_row_detached` 通过之后、回读
  `applied` 之前调用；visible-parent 开关修复与人类化候选点击均保持原样。

覆盖（`tests/test_instagram_humanize.py`，39 passed = 原 34 + 5）：
- `test_caption_dismissal_runs_after_readback_and_before_the_first_option`：真实
  `_publish`（注入 `comments` 控件），事件序 `caption-readback` <
  `hit-test:heading` < `option-set:comments`，标题栏恰好一次、零原生点击。
- `test_location_dismissal_runs_after_the_candidate_and_before_set_returns`：候选
  命中与 `up` 之后才出现标题栏 `hit-test`，`set()` 返回时已关闭；两次 `down`
  （候选 + 标题栏），标题栏零原生点击。
- `test_missing_heading_is_a_no_op_and_never_fails_the_set`：标题栏 `count()==0`
  时零事件、返回 `False`；`LocationControl.set` 照常成功。
- `test_dismissal_clicks_the_heading_once_through_the_humanizer`：`HUMANIZE=1` 下
  每次调用恰好一次 `down`/`up`、`stillOn` 先于按下、`native_clicks` 为空；连续
  两次调用就是两次点击（不重试、不多点）。
- `test_fast_path_dismissal_is_one_native_click_and_zero_pauses`：`HUMANIZE=0` 下
  恰好一次 `locator.click`、无 `force`、零 `down`、零暂停。

全库：1717 passed / 2 skipped（781 subtests）。`utils/humanize.py`、`utils/dom.py`、
`toggles.py`、其他平台零改动。

`Status:` 未改（真机复跑仍需按上面清单执行）。
