# 01 — `--schedule` / `--not-before` 时区契约

**What to build:** `--schedule` 只收 UTC 绝对时刻，填写平台控件前读取页面实际浏览器时区；`--not-before` 收任意带偏移的绝对时刻并换算到运行机器本地时区。移除所有写死的 `Asia/Shanghai` 与 naive 时间格式。

Blocked by: 无

Status: resolved
