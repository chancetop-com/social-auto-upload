# 16: Facebook 个人与 Page 的发布目标隔离

Status: resolved

Blocked by: 08

批次：第二批 · [托管 Profile 默认共享规格](../spec.md)

## What to build

从同一 Profile 分别给个人账号和 Facebook Page 准备内容，确保两份发布各自指向预期主体，并能从结果文件分别核对。

| 平台 | 本单负责的托管入口 |
| --- | --- |
| Facebook 个人、Facebook Page | `check`、`upload-video`、`upload-note` |

## Acceptance criteria

- [x] 逐项以正式 CLI 离线覆盖六个动作，核对登录探针、预览和编辑器的页面归属。预置同行草稿，在成功及失败清理后回读草稿并继续编辑。
- [x] 个人发布命令等待 `--not-before` 时让 Page 命令选择目标主页。在等待前后分别观察个人发帖主体、Page 名称和可见主页标识，验证每份草稿仍面向原定发布目标。
- [x] 同一 Profile 上 `facebook` 与 `facebook-page` 可并行。两条 `facebook-page` 即使指定不同主页，后来者也须在开页前立即报告平台占用并以 `1` 退出。
- [x] 离线并发运行 Instagram 与 Facebook Page，省略 `--result` 时得到不同的 UUID 结果文件。显式传入不同路径时分别得到各自结果；显式传入相同路径时两条照常执行，在可控写入顺序下最后写入者覆盖前一份。

## Comments

16 个离线验收用例覆盖个人与 Page 的六个正式入口。两条命令在各自的发布时间前后回读编辑器，验证了个人主体、Page 名称和页面可见的 asset_id。名称相似的主页按完整名称匹配；等待后目标变化时在提交前退出。另一条 Page 命令即使指定不同主页，也在开页前报告占用并以 1 退出。Instagram 与 Page 使用默认 UUID、独立显式路径和同一显式路径的三种结果均已检查。既有 Facebook 回归通过 126 项和 68 个子用例。合入提交为 `4f98fdc`，场景见 `tests/test_shared_facebook_process.py`。
