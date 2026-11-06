# 02 — AI 生成标识与品牌内容声明

Status: resolved
Type: research
Blocked by:

## Question

网页端如何表达 API 的 `is_aigc`、`brand_content_toggle`、`brand_organic_toggle`？具体要回答：

1. “AI-generated content”标识在哪个面板/步骤，视频与图片帖是否都可用？
2. 准确文案、默认值、是否记住上次选择、勾选后对发布结果的影响。
3. 品牌内容声明：paid partnership 与 your brand 的页面文案、是否互斥、账号是否需要先接受品牌内容政策。
4. 这三项与隐私级别、定时发布是否互相影响。
5. 是否存在于“More options / Advanced settings”折叠区，展开与保存的可靠路径。

输出：UI 路径、候选选择器、组合规则、风险，并逐条标注置信度。

## Answer

详见 [研究文档](../research/02-aigc-brand-disclosure.md)。

- 三项都在右侧 Settings → `Show more` 折叠区：`[data-e2e="advanced_settings_container"]`，默认收起；没有额外 Save，直接 Post 时提交。
- `is_aigc` ↔ **AI-generated content** 开关（`[data-e2e="aigc_container"]`），默认关闭；首次开启会弹 `Labeling AI-generated content`，必须点 `Turn on`；发布后标签为 `Creator labeled as AI-generated`。
- `brand_organic_toggle` ↔ **Your brand**，发布标签 `Promotional content`。
- `brand_content_toggle` ↔ **Branded content**，发布标签 `Paid partnership`。
- 两个品牌选项**不互斥**，可同时勾选，至少选一个；同选时标签仍为 `Paid partnership`。
- 总开关 **Disclose post content** 默认关闭；打开后必须至少选一个品牌项。
- `Branded content` 与 Private 双向互斥；`Your brand` 和 AIGC 不受隐私级别限制。
- 发布后三项都不可改；Branded content 的品牌 campaign 关联仍需发布后在移动端 `Ad settings` 完成，网页自动化不覆盖。
- 最大风险：AIGC 开关受 A/B flag `show_aigc_toggle` 控制，部分账号可能没有容器；图片帖网页端有代码路径但官方网页帮助未明示，需实测。
- 待复核 12 项已列在文档末尾。

## Comments
