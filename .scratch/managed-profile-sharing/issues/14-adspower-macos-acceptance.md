# 14: 在 macOS 上验收 AdsPower 共享发布

Status: needs-info

Blocked by: 09, 11

批次：第一批 · [托管 Profile 默认共享规格](../spec.md)

## What to build

在现有 Mac 和同时登录 Instagram、TikTok 的 AdsPower 测试 Profile 上，让两个 CLI 的编辑阶段实际重叠。两份草稿放入不同标记，真实发布动作均用 `--no-publish` 停在最终提交前。

## Acceptance criteria

- [ ] 从空闲 Profile 同时启动。观察到一次 Start、两张独立编辑页。启动者先退，此时 Stop 为零且同行草稿仍可编辑；最后离开后合计一次 Stop，并在桌面或状态接口确认 Profile 已关闭。
- [ ] 桌面先打开 Profile，保留带标记的原标签。两个 CLI 直接加入并另开各自页面。首条退出后原标签与同行草稿仍在；末条离开时一次 Stop 关闭整个 Profile。
- [ ] 强杀全部 CLI 后做两轮：保留原浏览器，以及手动关闭后重开。每轮的新命令都通过当前连接新开页，最后一次 Stop 关闭 Profile。已有结果保留，旧草稿无提交。
- [ ] 逐轮记录 macOS 和 AdsPower 版本、命令进出顺序、脱敏的 Start/Stop 次数、提交前的页面标记与最终 Profile 状态。结果注明实际通过或失败的场景。

## Comments

已在 macOS 26.6.2、AdsPower Global 8.9.23 上尝试冷启动。Instagram 和 TikTok 的两个正式命令都传入 `--no-publish`，进入时间相差约 11 毫秒。合计发出 1 次 Start、0 次 Stop，两个命令均在编辑器打开前以 1 退出；随后两次状态查询均为 `Inactive`。当前 API Key 可以访问本机 API。针对历史验收里使用的同一标识，V1 和 V2 的按 ID 查询均成功返回 0 条匹配。已向操作者请求当前同时登录两个平台的测试 Profile ID 或环境序号，以继续冷启动、桌面已打开和强杀恢复的真实草稿验收。
