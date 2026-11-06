# TikTok ticket 19 — 本地模式真实验收记录

- 日期：2026-11-06
- 账号：`lukechen`（私有账号）
- 模式：本地 cookie 模式（未设置 `MLX_API_TOKEN`）
- 浏览器：Patchright 自带 Chromium，`locale=en-US`，`--headed`
- Cookie：`cookies/tiktok_lukechen.json`
- 说明：公开账号专属项（无参数公开发布、`--privacy public` 正向、公开账号首项文案）因账号类型不满足，标记为“条件未满足/未验证”。

## 预检

| 项 | 结果 | 证据 |
| --- | --- | --- |
| 本地登录 | 成功保存 cookie | `.venv/bin/sau tiktok login --account lukechen`；`cookies/tiktok_lukechen.json` |
| `check`（无头） | `valid` / `0` | 14:39 |
| `check`（有头，中文界面问题修复后） | `valid` / `0` | 14:51；`data-e2e=select_video_button` + `locale=en-US` |

## 负向用例

| 用例 | 期望 | 实际 | 证据 |
| --- | --- | --- | --- |
| 私有账号请求 `--privacy public` | 严格失败，退出 `1`，不发布 | 退出 `1`；请求 `public`，实际 `Followers`；浮层已关闭 | `.local/tiktok19/public-negative-v2.log` |
| `--branded-content --privacy only-me` | 本地校验失败，退出 `2`，不启动浏览器 | 待跑 | — |

## 正向发布（待填）

| 用例 | 参数 | 退出码 | 帖子 ID / URL | 页面/帖子核对 |
| --- | --- | --- | --- | --- |
| only-me 基线 v3 | `--privacy only-me` | `0` | `https://www.tiktok.com/@lukechen95/video/7704949738667298062` | Content 列表显示 **Only me**；标题残留旧文案 “emo”，已用 `Meta+A` 修复，v4 复验 |
| 隐私 followers | `--privacy followers` | 待跑 | — | — |
| 隐私 friends | `--privacy friends` | 待跑 | — | — |
| 互动/复用/AIGC/品牌组合 | `--privacy only-me --no-comments --disable-reuse --aigc --your-brand` | 待跑 | — | — |
| branded-content + friends | `--branded-content --privacy friends` | 待跑 | — | 页面若禁用/缺失记录为“页面不支持” |
| 自定义封面 | `--thumbnail videos/demo.png --privacy only-me` | 待跑 | — | — |
| 定时发布 | `--schedule <近未来> --privacy only-me` | 待跑 | — | 到点/Content 核对 |
| 图文多图 | `upload-note --images videos/demo.png videos/demo1.png videos/demo2.png --title ... --note ... --tags ... --privacy only-me` | 待跑 | — | 顺序/封面/文案 |
| 图片帖设置项 | `upload-note ... --no-comments --aigc --your-brand` | 待跑 | — | 页面渲染则核对 |

## 真实环境发现并修复

1. `LOCAL_CHROME_PATH` 为空时 `executable_path=""` 导致浏览器启动失败 → 空值改用 Patchright 自带 Chromium。
2. `--lang` 被拆成两个 tokens，Patchright 报 “Arguments can not specify page to be opened” → 改为 `--lang=en-US` 单参数。
3. 登录后入口等待 5s 与客户端渲染竞态 → MLX 15s / 本地 20s。
4. 首次上传出现 `Turn on automatic content checks?` 弹窗与 react-joyride 引导遮罩拦截点击 → `dismiss_blocking_overlays`（Cancel / 点击遮罩）+ 编辑器点击重试。
5. 有头浏览器使用系统中文，英文入口选择器失效 → 本地 context `locale=en-US`；入口优先 `data-e2e="select_video_button"`。
6. 图片页 Title 输入框在选图后才出现 → `ensure_mode` 改用 `input[type=file][accept*="image"]` 作为入口信号。
7. 隐私下拉当前是 `div[role="option"]`，不是 `li[role="option"]` → 改为按 role 匹配。
8. 隐私选项渲染在 portal 里，不在 `video_visibility_container` 内部 → 增加 `fallback_scope`（在 `locator_base`/页面根上找 `[role="option"]`）。
9. Content 列表不再使用 `data-tt="components_PostTable_Container"` → `read_result` 改为等待/读取 `a[href*="/video/"]` 并提取 `/video/<id>`。
10. macOS 上 `Control+A` 不能全选 caption（残留旧文案）→ 改用 `Meta+A`；其他平台仍用 `Control+A`。
