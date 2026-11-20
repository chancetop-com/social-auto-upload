# 一条地点请求怎样匹配候选并报告选中的地点？

Type: grilling
Label: wayfinder:grilling
Status: resolved
Blocked by: 01, 02

## Question

基于小红书、Rednote、Instagram 和 TikTok 的实际候选，决定 `--location` 接受的值、名称归一化规则、同名不同地址的处理和选中后的回读信号。明确省略、空白、无候选、多候选、资格受限及回读失败在 CLI 和结果中的区别。

Instagram 已有地点请求、无精确匹配时的失败用例和逐项结果，可作为兼容基线。[Instagram 验收](../../instagram-browser-parity/research/08-acceptance-evidence.md)

另见[小红书和 Rednote 能从哪里回读笔记选中的地点？](01-xhs-rednote-post-location.md)与[TikTok Studio 的视频和图片帖分别怎样确认地点可用并选中？](02-tiktok-location-by-post-type.md)。

## Comments

- 2026-11-20，操作者选择按平台顺序取第一个同名地点，随后确认按名称传参、失败时停止发布，以及按页面可见值记录选中结果。

## Answer

小红书、Rednote、Instagram 和 TikTok 的视频与图文命令都用 `--location "地点名"` 请求帖子地点。省略时保留页面原值。显式传入空串或纯空白时，在上传前报参数错误。

| 阶段 | 四个平台的约定 |
| --- | --- |
| 匹配 | 比较完整地点名称，忽略大小写，去掉首尾空白并合并连续空白。按本次搜索结果的页面顺序点击第一个同名候选，更靠前的近似名称跳过。地址只用于记录所点行。 |
| 选中后回读 | 候选列表已收起，且地点控件显示所选名称，两项都满足才算成功。结果记录请求名称、所点行的可见名称及地址（如有），以及控件最终显示的名称。 |
| 停止发布 | 没有同名候选时报告无匹配，包括列表为空和只有近似建议。地点入口缺失时报告缺失，只有页面明确提示资格限制时才报告该限制。列表未收起、读不到选中名称或读回名称不符时报告回读失败。 |

例如，搜索「人民公园」时，即使「房山人民公园」排得更靠前，也跳过这一行。遇到多个名称完整匹配的「人民公园」，选择其中排名第一的候选并记录它显示的地址。收起后只显示「人民公园」时，地址的证据来自点选前的候选行。[小红书与 Rednote 地点实测](01-xhs-rednote-post-location.md#answer) · [TikTok 地点实测](02-tiktok-location-by-post-type.md#answer)

Instagram 现有实现按候选整行文字匹配，已有 Personal 轮播地点验收。Creator 补验时观察名称与地址是否分行显示，核对实际点选行和最终值。[Instagram 地点控件](../../../uploader/meta_uploader/insgraph_uploader/controls/location.py) · [当前 Instagram Creator 的 Reel 和轮播在 Share 前能回读哪些元数据？](11-instagram-creator-field-readback.md)
