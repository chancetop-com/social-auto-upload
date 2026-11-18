# 14: 在 macOS 上验收 AdsPower 共享发布

Status: ready-for-agent

Blocked by: 09, 11

批次：第一批 · [托管 Profile 默认共享规格](../spec.md)

## What to build

在现有 Mac 和同时登录 Instagram、TikTok 的 AdsPower 测试 Profile 上，让两个 CLI 的编辑阶段实际重叠。两份草稿放入不同标记，真实发布动作均用 `--no-publish` 停在最终提交前。

## Acceptance criteria

- [ ] 从空闲 Profile 同时启动。观察到一次 Start、两张独立编辑页。启动者先退，此时 Stop 为零且同行草稿仍可编辑；最后离开后合计一次 Stop，并在桌面或状态接口确认 Profile 已关闭。
- [ ] 桌面先打开 Profile，保留带标记的原标签。两个 CLI 直接加入并另开各自页面。首条退出后原标签与同行草稿仍在；末条离开时一次 Stop 关闭整个 Profile。
- [ ] 强杀全部 CLI 后做两轮：保留原浏览器，以及手动关闭后重开。每轮的新命令都通过当前连接新开页，最后一次 Stop 关闭 Profile。已有结果保留，旧草稿无提交。
- [ ] 逐轮记录 macOS 和 AdsPower 版本、命令进出顺序、脱敏的 Start/Stop 次数、提交前的页面标记与最终 Profile 状态。结果注明实际通过或失败的场景。
