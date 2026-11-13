# 时区契约验收

- [x] `--schedule 2026-11-12T10:30:00Z` 在 `Asia/Shanghai` 浏览器填写 `2026-11-12 18:30`
- [x] 托管 Profile 的时区从页面 `Intl.DateTimeFormat().resolvedOptions().timeZone` 读取
- [x] 页面时区读取失败退出 `1`，不回退到进程时区
- [x] `--schedule` 传 `+08:00`、无时区或非零秒退出 `2`
- [x] `--not-before 2026-11-12T10:30:00Z` 在 +08 机器上等待到同一绝对时刻
- [x] `--not-before` 传 `+08:00`、空格分隔或无时区格式退出 `2`
- [x] `--not-before 2026-11-12T10:30:45Z` 保留秒级精度
- [x] 所有平台（含小红书 C2/C3、Facebook Page 回读）填写前完成换算
- [x] CLI 参数、文档与 skills 中不再保留 naive `YYYY-MM-DD HH:MM`；旧版库示例显式按本地时区格式化
