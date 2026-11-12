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

