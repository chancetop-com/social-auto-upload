# 13 — Location 端到端

Status: ready-for-agent
Type: task
Blocked by: 10
规格依据: spec.md §3.1、§3.3、§4.2、§4.3.1、§5、§7.2–§7.4

## What to build

两个上传命令支持 `--location`。在配文页输入地点，等待联想列表，按规范化精确匹配选中候选并回读；没有精确匹配时列出候选并失败，绝不点击模糊匹配。

## Acceptance criteria

- [ ] `upload-video` 与 `upload-note` 都注册 `--location`；未传为 `None`，不触碰页面。
- [ ] `--location` 去空白后为空 → 浏览器启动前 `UsageError`，退出 `2`。
- [ ] 输入后等待联想列表；大小写、首尾与连续空白不敏感地精确匹配。
- [ ] 无精确匹配 → `mismatch`，退出 `1`，错误信息列出观察到的候选（最多 10 条），不点任何候选。
- [ ] 多个同名候选取第一个，不额外报歧义。
- [ ] 选中后以页面回读值记 `applied`；仅当回读与被点候选标签规范化一致时记 `set`。
- [ ] 入口缺失 / disabled / 账号不合格 + 请求值 → `unsupported` + `entry_missing` / `account_ineligible`，退出 `1`。
- [ ] 联想为空时清空重输一次再失败，避免 debounce 误判。
- [ ] 选项失败不点 Share；结果文件记录 location 的 requested / applied / status / reason。
- [ ] fake 控制件覆盖精确匹配、无匹配候选、同名、缺失、回读不一致；真实 DOM 验输入→联想→选中→回读。
- [ ] 不修改其他三个选项；文档留到 15。

## Comments

- 2026-11-10：由 `spec.md` 拆分。
