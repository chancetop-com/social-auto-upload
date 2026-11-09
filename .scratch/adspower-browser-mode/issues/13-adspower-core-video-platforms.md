# 13 — AdsPower 模式核心与视频平台端到端

Status: ready-for-agent
Type: task
Blocked by: 11, 12
Assignee: —

## What to build

让 `ADSPOWER_API_KEY` 真正激活 AdsPower 模式，并让视频类浏览器平台的 `check` / `upload-*` 通过 AdsPower Profile 完成：

- 激活矩阵：key 非空 → AdsPower；与 `MLX_API_TOKEN` 同时非空 → `RuntimeError`，`sau_cli.main` 退出 `1`，文案精确。
- `ADSPOWER_API_BASE` 仅在 AdsPower 激活后校验：默认 `http://127.0.0.1:50325`；只允许 http/https + host + 可选端口；拒绝 userinfo/path/query/fragment；非法 → `UsageError` → `2` 且不发请求。
- 参数：`--profile-id` 必填；`--folder-id` 注册但忽略；`--account` 可选（纯标签）；`--headless/--headed` 映射 `"1"/"0"`；`--debug` 不传给 AdsPower。
- `login` → `1`（AdsPower 文案）；bilibili 的 login/check/upload → `1`；`verify`/`delete`/`article` 仍本地。
- 生命周期：probe → start → connect → `contexts == 1` → yield → disconnect → shield stop；start 失败不停；`StartIncompleteError` 先 best-effort stop 再抛；取消时仍 stop；stop 失败只 warning；stop 阶段 429 不改变主结果。
- CLI 退出码：`RateLimitedError → 11` 排在通用 `Exception` 之前；`check` 未登录 → `10`，成功只输出 `valid`。
- 覆盖视频平台：alipay、baijiahao、douyin、hupu、kuaishou、tencent、tiktok、weibo、xiaohongshu、youtube。
- 新增 `tests/test_adspower_browser_session.py`、`tests/test_adspower_cli.py`、`tests/test_adspower_platform_contract.py`，并补齐 `test_multilogin_cli.py` 的 429→11 与 shim 符号断言。

## Acceptance criteria

- [ ] 双 key 冲突退出 `1`，文案为 `MLX_API_TOKEN 与 ADSPOWER_API_KEY 不能同时设置；请只保留一个。`
- [ ] 只设置 `ADSPOWER_API_BASE` 不激活、不告警；非法 base 退出 `2` 且无任何 HTTP 调用。
- [ ] AdsPower `check` 成功 → `0` 且 stdout 只有 `valid`；未登录/验证码/2FA → `10`；缺 `--profile-id` → `2`。
- [ ] 视频平台在 AdsPower 下上传走 Profile，不读写 `cookies/*.json`，不调用 `new_context`。
- [ ] ws URL 原样传给 `connect_over_cdp`，不反推 http。
- [ ] 退出码 `0/1/2/9/10/11/130` 均有测试锁住；`130` 只验证不捕获语义。
- [ ] key 不出现在 stdout/stderr/异常/`repr`/日志。

## Context

- 规格：§3（激活）、§4（CLI 契约）、§5.2–5.3（provider/session）、§6（生命周期）、§7.1–7.2、§11.1（测试）。
- 设计裁决：ticket 02（激活与退出码）、ticket 04（所有权）、ticket 10（client 原语）。
