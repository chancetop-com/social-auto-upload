# 26 — 文档与验收

**What to build:** 把 Multilogin 模式作为一条完整、可交接的能力交付：部署前提、两种模式的差异、退出码契约、调度侧责任、身份一致性风险都有文档；同时跑完 spec §15 的验收清单，确认本地模式零回归。

**Blocked by:** 18, 19, 20, 21, 22, 23, 24, 25.

**Status:** ready-for-agent

- [ ] README 与 `docs/CLI.md` 增加 MLX 模式章节：`MLX_API_TOKEN` 激活、`--folder-id` / `--profile-id`、`--account` 仅作标签、退出码 0 / 1 / 2 / 10 / 130。
- [ ] 文档写明 v1 部署前提：CLI 与 Multilogin 桌面应用同机、Mimic 内核、Profile 已人工登录且无待处理验证码/2FA、TikTok Profile 界面为 English (US)。
- [ ] 文档明确不支持项：Docker launcher、跨机、Linux 无桌面、哔哩哔哩、TikTok 本地模式。
- [ ] 文档写明调度侧责任：同一 Profile 不并发、收到 10 安排人工登录、Stop 失败时清理残留 Profile、跨机调度应远程执行 CLI 而不是指向远程 launcher。
- [ ] 文档写明账号一致性风险：MLX 只验证“已登录”，Profile 即身份；知乎/雪球/大鱼号/Instagram 的本地身份比对在 MLX 下不执行。
- [ ] 更新相关平台 skill / 文档中的命令示例，至少覆盖抖音、小红书、YouTube 与 TikTok 的 MLX 用法。
- [ ] 逐条执行 spec §15 验收清单并记录结果；重点确认无 token 时旧命令解析与行为不变、本地单测全绿。
- [ ] 验收记录包含：MLX 下 check 的 0/10/1/2、upload 的 0/10/1、connect 失败仍 Stop、取消时 shield 发 Stop、Profile 已运行时不误 Stop、token 不出现在日志/异常、MLX 不读写 cookie。
- [ ] 明确标注真实 MLX 冒烟（ticket 08 / 本目录 27）是否已执行；未执行时文档不得声称已验证。
