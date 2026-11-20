# 小红书和 Rednote 能从哪里回读笔记选中的地点？

Type: task
Label: wayfinder:task
Status: resolved

## Question

在两边各自的视频和图文编辑器中，笔记的「添加地点」如何搜索、展示名称和地址、区分同名项，并在关闭候选列表后显示所选地点？用至少一个成功样例和一个无匹配或重名样例记录可观察信号，注明四种组合中实际见到的页面。

两份旧 `set_location()` 都默认传入青岛市，点击后直接返回成功。来源声明的 `--shoot-location` 在另一个弹窗里；已有 Rednote 自主拍摄干跑只能作候选匹配的参考。[Rednote 验收](../../rednote-support/acceptance.md)

## Comments

2026-11-20 核对历史真机快照。以下两个本地账号均显示中文界面，账号类型未记录。

| 平台与账号别名 | 视频编辑器 | 图文编辑器 |
| --- | --- | --- |
| 小红书 `180`，11 月 11 日 | [视频快照](../../xhs-publish-reliability/research/raw/22-zh-CN-video-video.json)中「添加地点」可见 | [图文快照](../../xhs-publish-reliability/research/raw/22-zh-CN-image-editor.json)中「添加地点」可见。[图文 DOM](../../xhs-publish-reliability/research/raw/editor-image.html) 将控件定位在 `.address-card-wrapper .address-card-select` |
| Rednote `rednote`，11 月 16 日 | [视频快照](../../../.local/rednote-acceptance/original-video-acceptance/video-final.json)中地点选择器显示「添加地点」 | [图文快照](../../../.local/rednote-acceptance/original-note-acceptance/note-final.json)中同一选择器显示「添加地点」 |

Rednote 本机留存的 82 条笔记地点选择器快照都显示空值占位「添加地点」，包括自主拍摄声明已选地点的草稿。[自主拍摄草稿快照](../../../.local/rednote-acceptance/self-shot-acceptance/note-final.json)

归档的 Rednote 网页组件把每条地点候选的名称和完整地址分别放在 `.option-name` 和 `.option-subname`，以 `poiId` 区分地点，使用名称作选中标签。两个旧上传器都按 class 含 `name` 且文本相等查找元素，名称和地址都可能命中，点击后即返回成功。下一次真机观察需同时记录候选行的名称和地址、收起后的可见字段，以及重名或无匹配时页面显示的值。[归档组件](../../../.local/rednote-acceptance/resources/project-publish-vue.371d26b5.js) · [Rednote 上传器](../../../uploader/rednote_uploader/main.py) · [小红书上传器](../../../uploader/xiaohongshu_uploader/main.py)

## Answer

2026-11-20，小红书 `180` 和 Rednote `rednote` 的本地 Chrome 测试账号均在中文桌面网页实测（浏览器语言 `zh-CN`，账号类型未知）。使用获授权的中性素材 `check-1.png`、`check-video.mp4` 进入各平台的图文和视频编辑器。四次都在发布前完成观察，未点击发布。

四个页面都从笔记的「添加地点」进入。在 `.address-card-wrapper .address-card-select` 内输入「人民公园」后，展开的候选列表在每个 `.option-item` 中分别显示名称（`.option-name`）和地址（`.option-subname`）。每次实测均返回 47 条名称完全等于「人民公园」的候选。按名称和完整地址找到唯一一行并点击后，列表自动收起；同一地点控件的 `.d-select-description` 显示名称，搜索输入值为空。收起后的可见字段没有地址，因此单凭回显无法区分成都和上海的同名地点。

| 实测页面 | 点击的候选行 | 收起后的可见值 | 证据 |
| --- | --- | --- | --- |
| 小红书图文 | 房山人民公园 · 北京市房山区良乡政通路2号院区政府 | 房山人民公园 | [候选和回读](../research/post-location-2026-11-20/xiaohongshu-note.json) · [控件截图](../research/post-location-2026-11-20/xiaohongshu-note-closed.png) |
| 小红书视频 | 人民公园 · 上海市黄浦区南京西路231号 | 人民公园 | [候选和回读](../research/post-location-2026-11-20/xiaohongshu-video.json) · [控件截图](../research/post-location-2026-11-20/xiaohongshu-video-closed.png) |
| Rednote 图文 | 人民公园 · 成都市青羊区小南街8号(人民公园地铁站B口步行250米) | 人民公园 | [候选和回读](../research/post-location-2026-11-20/rednote-note.json) · [控件截图](../research/post-location-2026-11-20/rednote-note-closed.png) |
| Rednote 视频 | 人民公园 · 上海市黄浦区南京西路231号 | 人民公园 | [候选和回读](../research/post-location-2026-11-20/rednote-video.json) · [控件截图](../research/post-location-2026-11-20/rednote-video-closed.png) |

两端的视频编辑器在已有选中值时再次搜索 `不存在的地点QZX974631`，精确命中均为零。小红书显示四条「不存驿站」，Rednote 列表仍显示原先选中的上海「人民公园」。两端都未点候选，收起后原选中名称仍为「人民公园」。可见列表非空、收起后仍有值，都可以和无精确匹配同时发生。两端图文编辑器的同名样例已完成；额外的无匹配探测在等待空态时超时，没有记录当时的候选内容。

名称和地址如何进入 CLI 请求、何时报告歧义，由[一条地点请求怎样匹配候选并报告选中的地点？](09-location-match-and-result.md)决定。
