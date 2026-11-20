# 小红书、Rednote 和 TikTok 怎样在发布前区分已关联的话题和普通文字？

Type: task
Label: wayfinder:task
Status: resolved
Blocked by: 05

## Question

在当前账号的视频和图文编辑器里，从一条句中带两个话题的配文取证。分别记录选择同名候选后、没有同名候选而保留文字后，编辑器能回读哪些差异。用完整配文核对位置与标点，记录能证明每个词是否已关联的页面信息。按平台、帖型、账号类型与实际界面语言标注样本，停在发布前。

既有 TikTok 视频发布后显示过两个话题链接，图片帖也有带话题的正文样本，两次均使用旧的 `--tags` 入口。本题关注句中原位输入后在编辑器里能看到的证据。[TikTok 本地验收](../../tiktok-browser-parity/acceptance-local.md) · [各平台的标签写到哪里，什么结果算设置成功？](05-tags-native-and-fallback.md#answer)

## Answer

2026-11-20，用本地 Chrome 和中性测试素材，在六个编辑器中逐段输入同一句配文 `Today #coffee, then #qzx974631sau.`。逐个确认同名的 `#coffee` 候选，跳过第二个词的候选，补上句号，停在发布前。每个样本都能从正文读出一处已关联的话题和一处保留的文字，六份记录均附有候选行、选中后的正文和最终编辑器节点。

| 平台与本地账号 | 实际界面与账号类型 | 视频证据 | 图文证据 |
| --- | --- | --- | --- |
| 小红书 `180` | 中文，显示「话题」「添加地点」。账号类型未核验 | [视频编辑器](../research/inline-topics-2026-11-20/xiaohongshu-video.json) | [图文编辑器](../research/inline-topics-2026-11-20/xiaohongshu-note.json) |
| Rednote `rednote` | 中文，显示「话题」「添加地点」。账号类型未核验 | [视频编辑器](../research/inline-topics-2026-11-20/rednote-video.json) | [图文编辑器](../research/inline-topics-2026-11-20/rednote-note.json) |
| TikTok `lukechen` | 英文 Studio，两个编辑器的可见范围均显示 `Followers`。本次未独立核验账号类型 | [视频 Description](../research/inline-topics-2026-11-20/tiktok-video.json) | [Photos Description](../research/inline-topics-2026-11-20/tiktok-photos.json) |

**小红书和 Rednote。** 四个页面都显示了带「5.6亿浏览」的 `#coffee`。点击后，正文编辑器 `div.tiptap[role=textbox]` 内出现一个不可编辑的 `a[data-topic]`，其数据含 `name: coffee`、话题 ID 和链接。第二个词只出现带「新建话题」的同名行。跳过后，正文仍含完整的 `#qzx974631sau.`；它可以带有 `span.suggestion` 样式，但没有话题锚点。

四个页面首次直接续写时，逗号前都多出一个不换行空格（U+00A0）。复验时只退格一次，再输入逗号，原话题锚点仍在。原始 `innerText` 此时为 `Today #coffee[话题]#, then #qzx974631sau.`。按正文节点顺序将话题锚点读作 `#` 加其 `name`，其余文字逐字保留，所得全文与原稿相同。这种读法能同时排除锚点内部的 `[话题]#` 标记、发现锚点外多出的空格。

**TikTok。** 视频和 Photos 都在配文框中输入话题。键盘确认高亮的 `#coffee · 24.5M posts` 后，正文里出现 `span.mention[data-testid=mentionText]`，其中的文字为 `#coffee`。退格移除自动追加的一个普通空格后再输入逗号，关联仍在。第二个词返回了同名 `Add` 行，旁边还有其他拼写的建议。跳过后该词留在普通文本节点内。失焦后，两个编辑器都只有 `#coffee` 带上述关联标记，全文与原稿逐字相同。把第二个词放进括号的补充样本也保留了两侧括号和句号。

两类候选缺口要分别描述。六个完整样本中，第二个词都有显示「新建话题」或 `Add` 的同名行；可确认的是跳过该行后的文字状态。另一次 TikTok 视频搜索 `#coffee` 时，约 14 秒内只显示近似项 `#coffeecreamer`，当次停在候选阶段。该观察记录在视频证据的 `separate_positive_query_with_no_exact_row`。本轮取证限定于发布前的网页，CLI 从句中识别话题仍待后续实现。
