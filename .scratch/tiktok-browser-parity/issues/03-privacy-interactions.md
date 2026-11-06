# 03 — 隐私级别与互动开关

Status: resolved
Type: research
Blocked by:

## Question

网页端如何设置 API 的 `privacy_level`、`disable_comment`、`disable_duet`、`disable_stitch`？具体要回答：

1. 隐私级别的准确文案与 API 枚举如何映射：
   - `PUBLIC_TO_EVERYONE` / `MUTUAL_FOLLOW_FRIENDS` / `FOLLOWER_OF_CREATOR` / `SELF_ONLY`
2. 公开账号与私有账号分别能看到哪些选项；不可用选项是隐藏还是置灰。
3. 评论、合拍、拼接开关的准确文案、默认值、禁用条件。
4. 这些设置是逐条生效还是会被记住；如何可靠读取当前选中值。
5. 如果账号级设置已经禁止某项互动，页面表现是什么。

输出：UI 路径、候选选择器、映射表、不可用时的表现，并逐条标注置信度。

## Answer

详见 [研究文档](../research/03-privacy-interactions.md)。

- `privacy_level` 可行，但只有 3 个选项且随账号类型换文案：
  - 公开账号：`Everyone`（变体 `Public`）/ `Friends` / `Only you`
  - 私有账号：`Followers` / `Friends` / `Only you`
  - 不可用项是置灰，不是隐藏；私有账号请求 `PUBLIC_TO_EVERYONE`、公开账号请求 `FOLLOWER_OF_CREATOR` 都应预检失败。
- `disable_comment` 可行：`Allow comments` 勾选/取消；账号级禁止时控件置灰，逐条无法覆盖。
- **`disable_duet` / `disable_stitch` 无法独立设置**：当前 Studio 已合并为 `Allow reuse of content`，同时控制 Duet/Stitch/Stickers/Story。两者一致时可精确表达；不一致时只能拒绝发布或显式降级为两者都禁用。
- 当前 UI 还有 API 之外的 `Allow AI to remix content`，默认开启；是否主动关闭需要产品决策。
- 默认值：新上传隐私为第一项、三个开关全开；逐条生效，不继承上一条；草稿会恢复。
- 可靠读取：可见性读 `div[data-e2e="video_visibility_container"] button[role="combobox"]` 文本；选项读 `li[role="option"][aria-selected="true"]`；开关读 `input[type=checkbox].is_checked()`。
- 发布前必须回读可见性与开关状态，避免“点了但没生效”的静默错误。
- 待复核 10 项已列在文档末尾。

## Comments
