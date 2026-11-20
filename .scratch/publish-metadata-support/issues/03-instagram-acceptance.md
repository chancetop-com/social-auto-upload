# Instagram 哪些组合可以沿用已有验收，哪些还需要验证？

Type: grilling
Label: wayfinder:grilling
Status: resolved

## Question

英文 Personal 账号的轮播已真发回读地点和 AI，Reel 已真发回读 AI 和正文标签。Reel 带地点、显式关闭 AI、其他账号或界面语言应取得什么证据才算覆盖？请确定本次最小验收集合，以及哪些组合可以直接引用已有证据。

Creator 账号的 AdsPower 干跑验证过创建入口和发布就绪，命令未请求 AI 和地点。[Personal 发布后回读](../../instagram-browser-parity/research/08-acceptance-evidence.md) · [Creator 干跑记录](../../instagram-browser-parity/research/09-creator-entry-evidence.md)

## Comments

- 2026-11-20，操作者确认当前账号已转为 Creator。11 月 10 日的发布后回读按当时的英文 Personal 样本保留。[Personal 发布后回读](../../instagram-browser-parity/research/08-acceptance-evidence.md)
- 11 月 13 日已有发布前设置后回读的实机记录。Reel 和两图轮播都选中「上海」，地点与 AI 开启均回读为 `set`，随后停在 Share 前。该次记录列出本地账号别名，未注明当时的账号类型。11 月 17 日的英文 Creator 干跑两种帖型均传了 `--tags sau`，记录了 Share 就绪，但未单独列出配文回读值。[本地实机验收](../../humanize-rollout/acceptance.md#instagramw1) · [Creator 干跑记录](../../instagram-browser-parity/research/09-creator-entry-evidence.md)
- `--no-ai-generated` 已有实现和离线验收。查到的真实账号记录中没有显式请求关闭 AI 的样本。既有契约将开关原本已关及入口缺失都记为 `default_off`，从开启切到关闭并回读成功记为 `set`。[AI 生成标识端到端](../../instagram-browser-parity/issues/12-ai-generated-label.md)

## Answer

2026-11-20，操作者确认沿用历史样本，在当前 Creator 账号上补齐发布前的逐字段回读。每项结论标明实测账号类型、页面实际语言、帖型和观察阶段。

| 可沿用的样本 | Reel | 两图轮播 |
| --- | --- | --- |
| [11 月 10 日，英文 Personal，发布后回读](../../instagram-browser-parity/research/08-acceptance-evidence.md) | 帖子显示 AI 标识，正文保留 `#回归 #测试` | 帖子显示地点 `Shanghai` 和 AI 标识 |
| [11 月 13 日，本地账号，类型未记，Share 前](../../humanize-rollout/acceptance.md#instagramw1) | 地点「上海」及 AI 开启回读一致，带话题的配文已回读 | 地点「上海」及 AI 开启回读一致 |
| [11 月 17 日，英文 Creator，Share 前](../../instagram-browser-parity/research/09-creator-entry-evidence.md) | 带 `--tags sau` 到达发布就绪，未留逐字段回读值 | 同次两图轮播也带 `--tags sau` 到达发布就绪 |

当前 Creator 的最小补验覆盖 Reel 与两图轮播。两种帖型均核对选中后的地点和编辑器中的实际配文标签，AI 请求覆盖显式开启和关闭，结论分别归到实际观察的帖型与方向。各字段可在同一草稿取证，使用 `--no-publish` 停在 Share 前。其他账号类型和界面语言按各自已有证据记录。

显式关闭 AI 时记录开关是否可见、操作前状态和操作后回读。可见且原本已关，证明该次请求的关闭状态已满足。从开切到关并读回关闭，才证明切换成功。入口缺失时记录缺失原因及 `default_off`，该样本的开关状态记为未观察。
