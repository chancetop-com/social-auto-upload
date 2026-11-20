# 小红书、Rednote、Instagram 和 TikTok 的 AI 披露、帖子地点与标签

Label: wayfinder:map

## Destination

本轮为小红书、Rednote、Instagram 和 TikTok 的视频与图文发布命令确定元数据参数和验收口径。以当前账号在桌面网页点击发布前可设置、可回读的 AI 声明、地点和配文话题为依据。

## Notes

- 新增参数的验收覆盖四个平台的八条命令。按命令和字段分别记录网页能力、CLI 已接入能力和实际验证的账号。单一账号或帖型上的观察只适用于该样本。
- [交接调查原文](research/01-ai-location-tags.md)来自另一工作树。它提供第一方资料和已有调查，具体帖型、失败行为和账号覆盖以当前源码及对应验收记录为准。代码核对基线为 `ebdeb43`。
- 后续取证可在发布前停止，记录账号类型、帖型、界面语言、控件和选中后的值。已有的发布后回读可用来佐证当时通过网页设置的效果。[仓库术语](../../GLOSSARY.md) · [本地工单约定](../../docs/agents/issue-tracker.md)

## Decisions so far

- [小红书和 Rednote 能从哪里回读笔记选中的地点？](issues/01-xhs-rednote-post-location.md) 两端的视频和图文候选均显示名称与地址，选中后收起只显示名称；同名地点需在列表内核对地址。
- [TikTok Studio 的视频和图片帖分别怎样确认地点可用并选中？](issues/02-tiktok-location-by-post-type.md) 同一测试账号的两种编辑器均可按地址区分同名地点，选中后只显示名称。搜索无精确匹配时仍可能出现建议。
- [Instagram 哪些组合可以沿用已有验收，哪些还需要验证？](issues/03-instagram-acceptance.md) 沿用 Personal 的发布后记录，当前 Creator 的 Reel 和轮播按 Share 前逐字段回读验收。
- [显式请求 AI 披露时，每种控件要满足什么条件才可以发布？](issues/04-ai-disclosure-contract.md) 保留各平台参数名，显式开启须回读确认，显式关闭遇到入口缺失时统一按关闭放行，冲突声明在上传前报错。
- [各平台的标签写到哪里，什么结果算设置成功？](issues/05-tags-native-and-fallback.md#answer) 既有十三条命令移除旧参数 `--tags`，从配文识别 `#话题`。原文完整时允许部分话题只保留文字，并逐项报告。
- [一条地点请求怎样匹配候选并报告选中的地点？](issues/09-location-match-and-result.md#answer) 四个平台按名称取第一个同名地点，记录候选行与选中后的名称。无匹配、入口不可用或回读失败时停止发布。
- [当前 Instagram Creator 的 Reel 和轮播在 Share 前能回读哪些元数据？](issues/11-instagram-creator-field-readback.md#answer) 中文 Creator 两种帖型均读到地点和正文话题，Reel 的 AI 从关切到开，轮播确认原本已关。双弹窗曾导致一次回读失败。
- [小红书、Rednote 和 TikTok 怎样在发布前区分已关联的话题和普通文字？](issues/12-inline-topic-readback.md#answer) 六个编辑器都能逐词回读关联，选中话题后移除自动空格可保留原稿标点。跳过「新建话题」或 `Add` 后，第二个词保留为文字。
- [遇到同名的「新建话题」或 Add 候选时，发布命令应该点选还是保留文字？](issues/13-topic-create-candidate.md#answer) 有同名候选就选，包括「新建话题」和 `Add`。只有无同名候选时才按原文保留。
- [调用方如何知道某个帖型支持什么，以及本次请求实际生效了什么？](issues/10-release-evidence.md#answer) 八条命令按帖型列证据，沿用现有结果输出。Instagram 的退出确认框挡住编辑器时停止分享，六个编辑器均须验过特殊话题候选才交付话题功能。
- [六个编辑器点选「新建话题」或 Add 后，能否在配文原位读到同名关联？](issues/14-created-topic-readback.md#answer) 六处均在发布前读到同名关联，移除自动空格后，整句配文和标点逐字一致。

## Not yet specified

- 如果某个帖型的控件只在特定账号出现，待看到两个页面的具体差异后，再确定该变体需要哪些补充证据。

## Out of scope

- [YouTube Studio 如何回读 AI 声明、拍摄地点和简介里的话题？](issues/06-youtube-studio-fields.md) YouTube 新增参数及其上传向导取证超出本轮四个平台的范围。
- [Facebook 个人主页的视频和图文发帖器各有哪些 AI 与签到控件？](issues/07-facebook-profile-fields.md) Facebook 个人主页新增参数及其发帖器取证超出本轮范围。
- [Facebook Page 图文和 Reel 在发布前各提供哪些元数据控件？](issues/08-facebook-page-fields.md) Facebook Page 新增参数及其 Business Suite 取证超出本轮范围。
- 新增发布平台或帖型。
- 移动端专属能力、发布后编辑和 API 补标，包括 Facebook Page 发布后通过 Graph API 设置 AI 标识。
- 上传器和 CLI 的代码实现，留到后续开发阶段。
