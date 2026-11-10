# 09 — 汇总第一波实施规格

Status: resolved
Type: task
Blocked by: 08

## Question

把 01–08 的结论汇总成可实施规格：能力矩阵、第一波 4 项（location / alt_text / 关评论 / AI 标识）的参数契约、UI 路径与选择器、set-then-readback、失败语义、三层测试、待验收附录、部署/回滚。产出 `.scratch/instagram-browser-parity/spec.md`。

08 已定：collaborators 不纳入；静态输入错误统一 exit 2（caption 超长也改为 2）；真发验收只作为独立附录且不写账号。

## Answer

已产出实施规格：[`spec.md`](../spec.md)（2026-11-10）。

规格内容与工单要求逐项对应：

- **能力矩阵摘要**：4 项本轮实现；Stories/定时/配乐/选帧/user_tags/collaborators 等延后或排除；完整矩阵仍以 `capability-matrix.md` 为准。
- **参数契约**：`--location`、`--alt-text`（仅 `upload-note`）、`--no-comments`、`--ai-generated/--no-ai-generated`；未传不动页面默认；collaborators 不实现。
- **UI 路径与选择器**：四项均定位在配文页（location 输入、Accessibility 模态框、Advanced settings 开关、AI 开关）；区分「已实测」与「候选回退」，并给出中英文回退策略。
- **set-then-readback**：每项定义 `resolve/read/set` 三态协议与幂等规则；AI/评论开关语义反转单独标注。
- **失败语义**：5 个 status + `entry_missing/account_ineligible` 两个 reason 的完整映射；选项失败一律在点 Share 前、退出 1，不使用 9。
- **三层测试**：纯逻辑（A1–A6）、fake 控制件（B1–B12）、真实 DOM 哨兵（C1–C4）与退出码矩阵；新文件 `tests/test_instagram_options.py`。
- **待验收附录**：6 条真发用例，不写账号，不阻塞合并；未验收前文档标 `offline-verified / post-publish unverified`。
- **部署/回滚**：无迁移，纯增量 flag；caption 退出码 1→2 作为唯一破坏性变更单独记录。

硬约束均已落入规格：静态输入错误统一 exit 2（含 caption）、`options` 结果字段照 07/08、不引入 manifest、真实 DOM 只验 happy path、验收清单独立成附录。

未决但不阻塞实施：选择器仅在 English/Personal 账号实测，中文与专业账号文案需真实 DOM 用例与 §8 验收固定。
