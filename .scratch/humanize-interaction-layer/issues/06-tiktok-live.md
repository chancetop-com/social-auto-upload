# 06 — TikTok 真机验收（`--no-publish`）

**What to build:** 不改生产代码。本地模式真机用 **`--no-publish` 干跑** TikTok 视频 + 图文，素材上传、标题/正文/话题、全部发布选项、封面与 `--schedule` 完成后，等发布按钮可点击（窗口 `min(60s, 剩余预算)`）即停，**不点击发布、不上真实帖子**。记录双基线（`HUMANIZE=1` / `=0`）、预算消耗与风控观测，落 `.scratch/humanize-rollout/acceptance.md`。

规格依据：§6.4、§7.1；干跑契约见 `docs/CLI.md` 的 `--no-publish` 一节。

Blocked by: 03

Status: resolved

- [x] 视频 + 图文各一次跑到发布按钮就绪，退出码 0
- [x] 就绪超时（退出 1）视为失败：记录目标、reason 与预算余量
- [x] 配文清空干净（无旧文案残留）；>1000 码点读回一致
- [x] 话题候选全等选中；未选中时保留纯文本且流程继续
- [x] 定时/隐私/开关等选项状态与设置一致（点后读回）
- [x] `HUMANIZE=1` / `=0` 双基线已记录
- [x] 风控观测 + 停止点；结论 pass/fail
- [x] 发布按钮的真实点击**不验**（§9-28）
- [x] 若失败且判定为人类化导致 → 回滚 03 的平台提交

## Answer

2026-11-13 真机 `--no-publish` 视频干跑在发布选项步骤（约 43s）失败：
`ElementUnusableError(reason="point-drift")`。首个应用的选项就是隐私；只跑
`--privacy only-me` 的探针在任何封面/定时步骤之前即复现。按规格 §2.5.1 的
补救条款处理：在真机出现 `point-drift` 的调用点先 hover、再 click。

- `uploader/tk_uploader/main_chrome.py` 的 `_humanized_click` 现在先
  `await humanizer.hover(target)`，再 `await humanizer.click(target)`。
  该辅助函数覆盖 `_LocatorControl.click` 与 `_LocatorPrivacyControl.click`
  （当前仅这两个调用点）。
- `Humanizer.click` 本身未改：仍是零重试、±1px 容差、同一事件序列。
- `HUMANIZE=0` 快路径保留：`Humanizer.hover` 直接透传 `locator.hover()`，
  所以顺序仍是 hover → click，且零停顿。
- 测试（`tests/test_tiktok_humanize.py` 新增 `OptionClickHoverTests`）：
  选项点击先有 hover 的移动段 + settle，随后才是 click 自己的移动与
  按下，且只有一次 `mouse.down`；两个适配器都经过先 hover 的辅助函数；
  `HUMANIZE=0` 恰好一次 `locator.hover` + 一次 `locator.click`、零停顿；
  hover 失败原样上抛且不回退点击。
- 仅测试侧附带修正：`tests/test_tiktok_settings.py` 的 `_Node` 夹具补上
  `hover`，并断言 hover/click 都落到第一个可见的重复节点（既有断言未削弱）。

未改动共享层、其他平台实现、`force` 或 JS click。



### 验收结果（2026-11-13，最终）

| 发布类型 | H1 墙钟 | H0 墙钟 | 停止点 | 结果 |
| --- | --- | --- | --- | --- |
| 视频（定时 + 封面 + 隐私 + 评论 + AIGC） | 83s | 100s | `TikTok 发布就绪，--no-publish 停在发布按钮前（未点击发布）` | exit 0 |
| 图文（2 图，1000 码点逐字） | 234s | —（无同内容对照） | 同上 | exit 0 |
| 图文（2 图，1100 码点 bulk） | 67s | 99s | 同上 | exit 0 |

- `>1000` 码点一次 `insert_text`（`chars=1100`）后读回一致；1000 码点逐字读回一致，无旧文案残留。
- 话题候选命中；未命中时保留纯文本。选项、封面、定时状态与设置一致。
- 预算最高 26%（逐字 1000 码点），无裁剪 warning；无验证码 / 滑块 / 限流提示。
- 真机发现两处 `point-drift`（选项控件、AIGC Turn on 弹窗），按 §2.5.1 在平台层统一改为
  hover → click（24 处收敛到 `_humanized_click`），没有回滚 ticket 03，也没有保留双形态。
- 发布按钮的真实点击未验（§9-28）。

详见 `.scratch/humanize-rollout/acceptance.md`。
