# 13 — Location 端到端

Status: resolved
Type: task
Blocked by: 10
规格依据: spec.md §3.1、§3.3、§4.2、§4.3.1、§5、§7.2–§7.4

## What to build

两个上传命令支持 `--location`。在配文页输入地点，等待联想列表，按规范化精确匹配选中候选并回读；没有精确匹配时列出候选并失败，绝不点击模糊匹配。

## Acceptance criteria

- [x] `upload-video` 与 `upload-note` 都注册 `--location`；未传为 `None`，不触碰页面。
- [x] `--location` 去空白后为空 → 浏览器启动前 `UsageError`，退出 `2`。
- [x] 输入后等待联想列表；大小写、首尾与连续空白不敏感地精确匹配。
- [x] 无精确匹配 → `mismatch`，退出 `1`，错误信息列出观察到的候选（最多 10 条），不点任何候选。
- [x] 多个同名候选取第一个，不额外报歧义。
- [x] 选中后以页面回读值记 `applied`；仅当回读与被点候选标签规范化一致时记 `set`。
- [x] 入口缺失 / disabled / 账号不合格 + 请求值 → `unsupported` + `entry_missing` / `account_ineligible`，退出 `1`。
- [x] 联想为空时清空重输一次再失败，避免 debounce 误判。
- [x] 选项失败不点 Share；结果文件记录 location 的 requested / applied / status / reason。
- [x] fake 控制件覆盖精确匹配、无匹配候选、同名、缺失、回读不一致；真实 DOM 验输入→联想→选中→回读。
- [x] 不修改其他三个选项；文档留到 15。

## Comments

- 2026-11-10：由 `spec.md` 拆分。
- 2026-11-10：已实现并合入 `feat/instagram-parity`（`92846ee`，合并 `0b6365f`）。`controls/location.py` 按「输入→等待联想→规范化精确匹配→回读」实现，`:visible` 过滤陈旧列表，10s 等待 + 一次重输重试；无精确匹配抛 `OptionMismatchError` 并列出候选（最多 10 条）。A/B/C 共 48 例全绿。
