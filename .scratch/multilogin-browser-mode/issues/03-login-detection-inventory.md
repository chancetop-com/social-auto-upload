# 03 — 各平台登录态检测清单（MLX 模式）

Status: resolved
Type: research
Blocked by: —
Assignee: —

## Question

Multilogin 模式必须在**不读 cookie 文件**的前提下判断 Profile 是否已登录。请对每个使用 Playwright 的平台，盘点现有 `cookie_auth()` / `*_setup()` 的页面级判断，评估能否抽成 `is_logged_in(context) -> bool`：

对每个平台回答：

1. 现有检测访问的 URL 是什么？
2. 用了哪些登录/未登录标记（文本、selector、URL 片段、cookie 名）？
3. 这些判断是否依赖 `new_context(storage_state=...)`，还是只依赖 page/context？
4. 能否在**外部传入的 context**上直接复用？需要拆出哪个函数、改哪几行？
5. 判断的可靠性（高/中/低），误判场景（慢加载、弹窗、二次验证、地区跳转）。
6. 如果不可靠，备选信号是什么（例如访问创作者中心 URL、检查 API 响应、检查头像元素）。

平台范围（不含 Bilibili / 旧 xhs 签名器）：

- 国内：douyin、xiaohongshu、ks、tencent（含 weixin）、weibo、hupu
- 海外：tk（main.py 与 main_chrome.py 都要看）、youtube、facebook、facebook-page、instagram
- 图文：zhihu（video/article/session）、xueqiu、dayu、alipay、baijiahao

输出一张表：

| 平台 | 模块/文件:行 | 检测 URL | 标记 | 可复用函数 | 可靠性 | 备注 |

并单独列出：

- **必须新写检测**的平台；
- **无法可靠检测、只能靠上传失败归类**的平台；
- 现有检测里会**创建新 context / 写 cookie** 因而绝不能直接用于 MLX 模式的调用点。

## Context

- 现有实现集中在各 `uploader/*/main.py` 的 `cookie_auth`，以及 `session.py` / `verification.py`。
- 相关入口：`sau_commands/*.py` 的 `check_*_account()`。
- Bilibili 走 `biliup`，不在本 ticket 范围。
- 不需要改代码；只做代码阅读与结论。

产物写到 `.scratch/multilogin-browser-mode/research/03-login-detection-inventory.md`，所有结论附 `文件:行`。

## Answer

详见 [research/03-login-detection-inventory.md](../research/03-login-detection-inventory.md)。要点：

- **没有任何平台现有检测接受外部 context**：全部 `cookie_auth()` / `check_*_account()` 都自己 `launch()` + `new_context(storage_state=...)`，MLX 不能直接调用。页面级判断大多可抽出。
- 可直接抽 `is_logged_in(context)` 且可靠性中高以上的：抖音、小红书、快手、视频号、YouTube、Facebook、Facebook Page、Instagram、知乎、雪球、大鱼号。
- 需补正向信号：微博、虎扑、视频号。
- **必须新写**：TikTok（现有 `select` 反推不可靠，且未接入 CLI）、支付宝、百家号。
- 身份绑定特殊风险：知乎/雪球/大鱼号/Instagram 还要比对 `.identity.json` / 账号 JSON 的用户 ID；MLX 无 `--account` 时只能判断“已登录”，不能判断“是哪个账号”。→ 另开 ticket 12。
- 错误语义必须区分：网络错误/5xx/超时 → 抛异常（退出 1）；明确的登录页/登录表单/未登录锚点 → `False`（退出 10）。现有大量 `except: return False` 不能照搬。
- 超时建议 15–30s，不要沿用 2.5s/3s/5s 的固定等待。
- 绝不能用于 MLX 的调用点：所有 `new_context(storage_state=...)`、`set_init_script`、`storage_state(path=...)`；完整清单见研究文件第 5 节。

**对设计的直接影响：** 每个平台新增 MLX 专用登录检测，本地 `cookie_auth` 不动；统一签名 `async def is_logged_in(context) -> bool`，内部只允许 `context.new_page()` / `page.goto()` / `page.close()`。
