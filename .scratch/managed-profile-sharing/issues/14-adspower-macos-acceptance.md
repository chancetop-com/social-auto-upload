# 14: 在 macOS 上验收 AdsPower 共享发布

Status: needs-info

Blocked by: 09, 11

批次：第一批 · [托管 Profile 默认共享规格](../spec.md)

## What to build

在现有 Mac 和同时登录 Instagram、TikTok 的 AdsPower 测试 Profile 上，让两个 CLI 的编辑阶段实际重叠。两份草稿放入不同标记，真实发布动作均用 `--no-publish` 停在最终提交前。

## Acceptance criteria

- [x] 从空闲 Profile 同时启动。观察到一次 Start、两张独立编辑页。启动者先退，此时 Stop 为零且同行草稿仍可编辑；最后离开后合计一次 Stop，并在桌面或状态接口确认 Profile 已关闭。
- [ ] 桌面先打开 Profile，保留带标记的原标签。两个 CLI 直接加入并另开各自页面。首条退出后原标签与同行草稿仍在；末条离开时一次 Stop 关闭整个 Profile。
- [ ] 强杀全部 CLI 后做两轮：保留原浏览器，以及手动关闭后重开。每轮的新命令都通过当前连接新开页，最后一次 Stop 关闭 Profile。已有结果保留，旧草稿无提交。
- [ ] 逐轮记录 macOS 和 AdsPower 版本、命令进出顺序、脱敏的 Start/Stop 次数、提交前的页面标记与最终 Profile 状态。结果注明实际通过或失败的场景。

## Comments

2026-11-18，操作者确认了当前测试 Profile。冷启动复测通过。TikTok 和 Instagram 各自准备草稿。TikTok 先退后，Instagram 的原页仍可追加文字，最后仅一次 Stop，确认 `Inactive`。强杀全部 CLI 并保留浏览器的恢复场景也已通过，新命令在第三张标签准备草稿，旧结果摘要保持一致。

手动重开场景已执行至强杀两个进程，两张原草稿页均在，Profile 为 `Active`。已请操作者从 AdsPower 桌面关闭并重开指定环境，以核验恢复命令。桌面预先打开且保留原标签的场景也待验。各轮均使用 `--no-publish`。[实机时间线](../research/14-macos.md)
