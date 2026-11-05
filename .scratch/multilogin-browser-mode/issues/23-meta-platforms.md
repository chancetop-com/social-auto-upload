# 23 — 平台迁移：Facebook / Facebook Page / Instagram

**What to build:** Meta 三个上传入口在 MLX 模式下可 `check` 与上传；`*_PROXY` 与本地 launch 假设被静默丢弃，出口 IP 由 Profile 决定。Instagram 的本地身份比对在 MLX 下跳过。

**Blocked by:** 17.

**Status:** resolved

- [x] Facebook、Facebook Page、Instagram 的上传入口都支持 keyword-only `session`，MLX 分支只执行 `upload_in(session)`。
- [x] 三个平台各自新增 `is_logged_in(context)`：明确未登录返回 False，网络/5xx/超时/结构异常抛异常；预算 15–30s。
      - Facebook 20s 导航 + 2.5s settle；Facebook Page 25s + 2.5s；Instagram 20s + 8s outcome wait。
      - `_is_instagram_logged_out` 增加可选 `timeout_ms`，旧调用仍默认 60s。
- [x] MLX 分支静默忽略 `channel="chrome"` 与各自代理配置（含 `--proxy` 传入的值）。
      - 本地用 `facebook_launch_kwargs` / `facebook_page_launch_kwargs` / `instagram_launch_kwargs` 注入 proxy；CLI 的 MLX 分支只传不含 proxy 的 golden dict。
- [x] Instagram MLX 下不读取 `.identity.json`、不做用户 ID 比对；会话建立后输出“账号一致性未校验”的 INFO。
      - MLX 的 `_multilogin_identity` 只读当前会话 cookie 的 `ds_user_id`（用于校验创建响应归属），不读账号文件、不与账号文件比对。Facebook / Facebook Page 本就没有身份比对，无需跳过。
- [x] 三个平台的本地 `launch_kwargs` / `context_kwargs` / `init_script` 用 golden dict 锁定。
- [x] `check` 返回 0 / 10 / 1 / 2；`upload-*` 返回 0 / 10 / 1，成功后 Stop 恰好一次。
- [x] MLX 全程不读写 `cookies/*.json`，不调用 spec §6.2 的禁止 API。
- [x] 新增登录检测、身份 reader 未被调用、禁止 API 的测试。

**实现备注：** `tests/test_mlx_meta.py`（ticket 唯一文件名）覆盖本地 golden、MLX 禁止 API、`is_logged_in` True/False/raise 表、`check` 0/10/1 与 upload 0/10/1、身份 reader 未被调用、session 进出各一次。Facebook Page 的 `upload()` 保持自建 `async_playwright()` 的 legacy 分支，新增 `session=` 注入分支。
