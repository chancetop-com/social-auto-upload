# 显式请求 AI 披露时，每种控件要满足什么条件才可以发布？

Type: grilling
Label: wayfinder:grilling
Status: resolved

## Question

小红书和 Rednote 用互斥的内容类型，TikTok 和 Instagram 有开关，YouTube 的入口按交接资料为问答。CLI 如何表达省略、显式开启和有原生语义的关闭？是否需要统一别名？定义与原参数并用、与其他内容声明冲突、控件缺失和回读不符时的结果。

一个现有差异会改变调用方行为：小红书显式声明失败可告警继续，Rednote 显式声明已要求设置后回读。另需区分账号自行选择的声明和平台自动加上的标识。[小红书发布声明](../../../docs/CLI.md#小红书发布声明) · [Rednote 发布参数](../../../docs/rednote.md)

## Comments

- 2026-11-20，操作者确认只保留各平台原生参数名。小红书和 Rednote 沿用 `--content-type ai`，TikTok 沿用 `--aigc` / `--no-aigc`，Instagram 沿用 `--ai-generated` / `--no-ai-generated`。不新增跨平台别名。
- 2026-11-20，操作者确认小红书显式传 `--content-type ai` 时，与 Rednote 一样在发布前回读「笔记含AI合成内容」。找不到该项、读不到选中值或读到其他内容类型时，停止发布。
- 同轮确认，未传 AI 声明参数时保留页面当前值。即使页面预先开启了 AI 声明，也保持开启。

## Answer

2026-11-20，操作者确认各平台沿用自己的参数名，按下表判断创作者的 AI 声明是否允许继续发布。

| 调用方的请求 | 点击发布前的判断 |
| --- | --- |
| 省略 AI 声明 | 保留网页当前值，开关原本开启也保持开启。问答保持页面原有的作答状态。 |
| 显式开启或回答 Yes | 从当前发布页读到创作者已选中 AI 内容类型、开启开关或选中 Yes，才可继续。入口缺失、读不到结果或最终值不符时停止。平台自动加上的 AI 标识不能证明创作者已作声明。 |
| 显式关闭或回答 No，页面有对应控件 | 已读到关或 No 即可继续。如需切换，操作后回读。最终值相反或读回失败时停止。 |
| 显式要求关闭，页面没有对应控件 | **各平台统一按关闭处理，可以继续发布。** 结果记为 `default_off`，注明入口缺失（`entry_missing`）。该次没有观察到开关状态，也不能据此声称已在问答中选中 No。 |

小红书和 Rednote 用 `--content-type ai` 选择「笔记含AI合成内容」，内容类型单选没有原生关闭参数。TikTok 沿用 `--aigc` / `--no-aigc`，Instagram 沿用 `--ai-generated` / `--no-ai-generated`。本轮新增参数的取证范围已限定为这四个平台。[地图范围](../map.md#destination)

同一条命令要求互斥值时，在上传前报参数错误。例如同时要求开启和关闭 AI，或同时传 `--content-type ai` 和 `--content-type marketing`。独立的原创声明 `--original` 可与 `--content-type ai` 并用。

后续实现需让小红书在选择 AI 内容类型后核对菜单收起时显示的选中值，失败即停止。TikTok 视频与图片帖显式关闭时，入口缺失应允许继续。Instagram 已有入口缺失记为 `default_off` 的记录。若控件可见且禁用，仍能读到它处于开启状态，则关闭请求与实际值不符，应停止发布。[小红书声明处理](../../../uploader/xiaohongshu_uploader/main.py) · [TikTok 开关处理](../../../uploader/tk_uploader/main_chrome.py) · [Instagram 哪些组合可以沿用已有验收，哪些还需要验证？](03-instagram-acceptance.md)
