# 托管 Profile 默认共享

Label: wayfinder:map

## Destination

让同机独立运行的 CLI 默认共享 AdsPower 或 Multilogin X Profile，覆盖 `check` 和所有托管发布入口。同一 Profile 可并行运行不同平台的命令，每个平台同时限一条。每条命令负责自己的页面和结果。同一 Profile 上最后一条托管 CLI 命令离开时关闭整个 Profile，手动打开的也适用。

## Notes

- 用户已确认取消 `--share-profile` 开关。Instagram 与 TikTok 使用同一 Profile 是首个验收场景，覆盖范围包括全部现有托管动作。
- 一个任务失败时，其他任务按各自的 `--not-before`、发布结果和退出码继续执行。
- 本轮按 Wayfinder 建图。后续实施以托管命令的加入、退出和页面隔离决策为依据。参照 [项目术语](../../GLOSSARY.md) 和 [本地工单约定](../../docs/agents/issue-tracker.md)。
- 既有规格把同一 Profile 的串行调度交给调用方。新契约把同机共享移入托管会话层。[AdsPower 既有规格](../adspower-browser-mode/spec.md) · [Multilogin X 既有规格](../multilogin-browser-mode/spec.md)
- [双进程示例](../../examples/shared_profile_demo.py)验证了 macOS 上模拟 provider 的进程锁和退出顺序。

## Decisions so far

<!-- 已完成的子工单在此按标题链接。 -->

- [两家 provider 怎样证明 Profile 由 CLI 启动](issues/01-provider-ownership.md) — 两家的 Stop 均按 Profile ID 生效。[官方来源与真机验证场景](research/01-provider-ownership.md)
- [谁负责加入、离开和停止共享托管会话](issues/02-process-lifecycle.md) — 同一用户的 CLI 用本机进程锁协调，同 Profile 同平台占用即退，最后离开者关闭整个 Profile。
- [每个托管动作怎样只操作自己的页面和内容](issues/03-command-isolation.md) — 每条命令只操作和清理归属明确的页面，共用剪贴板的写入与粘贴互斥，文章正文回读采用弱校验。
- [进程中断后怎样识别和恢复遗留会话](issues/04-abandoned-session.md) — 全部 CLI 被强杀后，下一条命令可加入仍开着的 Profile，在最后离开时关闭。原有发布结果独立保留。
- [哪些证据足以验收托管 Profile 默认共享](issues/05-acceptance.md) — 本轮在 macOS 上用 AdsPower 实测 Instagram 与 TikTok 共用 Profile，离线覆盖全部托管入口；Multilogin X 真机和其他系统的双进程测试待条件具备后补验。
- [两条命令指定同一结果文件时由谁处理冲突](issues/07-result-path-collision.md) — 显式传入 `--result` 时，调用方负责为并行命令分配不同路径。

## Not yet specified

若桌面实测在不同产品版本间出现差异，再界定哪些版本需要单独的兼容处理。

## Out of scope

- [桌面和 CLI 先后启动时能观察到什么](issues/06-manual-start-race.md)中关于辨认启动者的调查到此为止。关闭条件只取决于还有几条托管命令在用。
- 本地浏览器 Profile、纯本地命令和不走托管浏览器的 Bilibili 动作。
- 跨机器共享，以及让多个平台同时成功或同时失败的发布批次。
