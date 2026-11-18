# 两条命令指定同一结果文件时由谁处理冲突

Label: wayfinder:grilling
Type: grilling
Status: resolved
Assignee: LukeChen

## Question

Instagram 与 Facebook Page 可以并行发布，两个入口的默认结果文件名各自带 UUID。如果调用方给两条命令显式传入指向同一文件的 `--result`，后写入的结果会覆盖前一份。「每条命令负责自己的结果」对这个显式路径承诺到哪里？由调用方分配不同路径，还是需要 CLI 在提交前识别冲突？这项选择怎样保留调用方核对两次发布结果的能力？[Instagram 结果文件](../../../uploader/meta_uploader/insgraph_uploader/main.py) · [Facebook Page 结果文件](../../../uploader/meta_uploader/facebook_page_uploader/main.py)

## Answer

2026-11-18，用户确认沿用现有行为。显式传入 `--result` 时，由调用方为每条并行发布命令分配不同的结果文件路径。若两条命令指向同一文件，CLI 会继续执行，后写入的结果会覆盖先前的结果。

Instagram 与 Facebook Page 发布命令省略 `--result` 时，各自生成带 UUID 的结果文件，两次发布的结果可分别核对。
