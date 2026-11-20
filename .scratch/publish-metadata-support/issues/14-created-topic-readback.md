# 六个编辑器点选「新建话题」或 Add 后，能否在配文原位读到同名关联？

Type: task
Label: wayfinder:task
Status: resolved
Blocked by: 10, 13

## Question

小红书、Rednote 的视频和图文，以及 TikTok 的视频和图片帖，分别在只有同名「新建话题」或 `Add` 候选时点选。记录页面实际提供的候选文案、输入的词和点选后能从正文读到的关联名称。用一句带标点的配文核对全文，停在发布前，记录账号样本、实际语言、帖型及停止点。普通同名候选及跳过特殊候选已有证据，本次补齐六处点选结果。

哪些帖型已同时确认关联和原文？若出现新弹窗、普通文字、错词、标点变化或无法回读，保留对应帖型的现场，作为该行交付验收的缺口。

参见[调用方如何知道某个帖型支持什么，以及本次请求实际生效了什么？](10-release-evidence.md#answer)和[遇到同名的「新建话题」或 Add 候选时，发布命令应该点选还是保留文字？](13-topic-create-candidate.md#answer)。

## Answer

2026-11-20，六个桌面网页编辑器均通过。各用一个不同的话题词，确认列表中只有一个同名候选，点击该行，再从正文回读关联。六次都在输入逗号前退格一次，去掉编辑器自动追加的空格。补完配文并移开焦点后，话题仍在原位，整句与原稿逐字一致。所有样本均停在点击发布前。

| 平台、帖型 | 本地账号、界面语言 | 输入的词 → 点选的同名行文案 | 从正文回读的完整配文 | 证据 |
| --- | --- | --- | --- | --- |
| 小红书视频 | `180`，中文 | `#fieldstudy1120a` · 新建话题 | `Field notes #fieldstudy1120a, after rain.` | [视频记录](../research/created-topic-2026-11-20/xiaohongshu-video.json) |
| 小红书图文 | `180`，中文 | `#fieldstudy1120b` · 新建话题 | `Field notes #fieldstudy1120b, after rain.` | [图文记录](../research/created-topic-2026-11-20/xiaohongshu-note.json) |
| Rednote 视频 | `rednote`，中文 | `#fieldstudy1120c` · 新建话题 | `Field notes #fieldstudy1120c, after rain.` | [视频记录](../research/created-topic-2026-11-20/rednote-video.json) |
| Rednote 图文 | `rednote`，中文 | `#fieldstudy1120d` · 新建话题 | `Field notes #fieldstudy1120d, after rain.` | [图文记录](../research/created-topic-2026-11-20/rednote-note.json) |
| TikTok 视频 | `lukechen`，英文 Studio | `#fieldstudy1120e` · Add | `Field notes #fieldstudy1120e, after rain.` | [视频记录](../research/created-topic-2026-11-20/tiktok-video.json) |
| TikTok 图片帖 | `lukechen`，英文 Studio | `#fieldstudy1120f` · Add | `Field notes #fieldstudy1120f, after rain.` | [图片帖记录](../research/created-topic-2026-11-20/tiktok-photos.json) |

小红书和 Rednote 的四个编辑器在点击前都只有文字，点击后都出现了不可编辑的 `a[data-topic]`。其中的 `name` 与输入词相同，`id` 有值，`link` 为空。核对全文时将锚点读作 `#` 加 `name`，保留锚点外的每个字符。四处自动追加的都是不换行空格（U+00A0）。

TikTok 的两个列表里也有其他拼写的建议。点击同名 `Add` 后，配文中出现了 `span.mention[data-testid=mentionText]`，其文字就是输入的完整话题。两处自动追加的都是普通空格（U+0020）。移开焦点后，标记和其后的逗号均可从编辑器读回。

每份记录保留了候选行、点选前后及退格后的读值、失焦后的编辑器 HTML 和停止点。Rednote 视频首次取证停在正文框未获得焦点，尚未输入话题；重新聚焦后完成了上表的验证。三个样本账号的类型均未核验，本次证据覆盖发布前网页编辑器，CLI 的端到端验收留到实现阶段。
