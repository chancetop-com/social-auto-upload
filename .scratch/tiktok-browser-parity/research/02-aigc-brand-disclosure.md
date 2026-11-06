# 02 — AI 生成标识与品牌内容声明（TikTok Studio 网页端）

状态：research / 只读调研  
调研日期：2026-11-05  
调研对象：TikTok Studio 网页上传页（`https://www.tiktok.com/tiktokstudio/upload`），非官方 Content Posting API。

## 置信度图例

- **【官方文档】**：TikTok Help Center、TikTok for Developers、TikTok 法务/政策页。
- **【开源实现/前端产物】**：公开 GitHub 实现，以及 TikTok Studio 当前公开前端 bundle / i18n JSON 的只读检查。前端 bundle 不是官方承诺，但能反映当前构建的真实文案、DOM 结构和默认值。
- **【仅推断】**：由上述证据推导、尚未在真实 MLX Profile 上点选验证。

> 本次没有启动浏览器、没有登录、没有修改业务代码。前端 bundle 仅通过 HTTP 只读抓取。

---

## Question

TikTok Studio 网页端如何表达 API 的：

- `is_aigc`
- `brand_content_toggle`
- `brand_organic_toggle`

具体回答：

1. “AI-generated content”标识在哪个面板/步骤，视频与图片帖是否都可用？
2. 准确文案、默认值、是否记住上次选择、勾选后对发布结果的影响。
3. 品牌内容声明：`Your brand` 与 `Branded content` 的页面文案、是否互斥、账号是否需要先接受品牌内容政策。
4. 这三项与隐私级别、定时发布是否互相影响。
5. 是否存在于 “More options / Advanced settings” 折叠区，展开与保存的可靠路径。

---

## TL;DR

- 网页端三项能力都存在，且都在右侧 **Settings → Show more** 的高级设置区，不在上传前的独立步骤，也不是单独的 “Advanced settings” 页面。
- 对应关系：
  - `is_aigc` ↔ **AI-generated content** 开关。
  - `brand_organic_toggle` ↔ **Your brand** 复选框。
  - `brand_content_toggle` ↔ **Branded content** 复选框。
- `Your brand` 与 `Branded content` **不是互斥单选**，官方开发者文档明确说这是 multiple selection，可同时勾选，至少选一个；同时勾选时发布标签为 **Paid partnership**。
- 品牌声明总开关默认关闭；`AI-generated content` 默认关闭；未发现跨帖子“记住上次选择”的证据，只有草稿/编辑回填。
- `Branded content` 与 **Private** 互斥：Private 时 Branded content 复选框被禁用；已勾 Branded content 时 Private 选项被禁用。`Your brand` 和 AIGC 不受此限制。
- 这三项与定时发布没有代码层面的互斥；定时只是延后发布，标签在发布时生效。
- 最大实现风险：AIGC 开关受 A/B flag `show_aigc_toggle` 控制，部分账号/地区可能根本没有 `[data-e2e="aigc_container"]`；首次打开还可能弹出 “Labeling AI-generated content” 引导弹窗，必须点 **Turn on** 才真正生效。

---

## Findings

### 1. AI-generated content 在哪个面板/步骤？

**结论：在右侧 Settings 卡片的 “Show more” 折叠区内，与品牌内容声明并列；视频确定可用，图片帖在网页端代码路径中也存在。**

- **【官方文档】** TikTok 的网页端说明是：
  - `Click Upload`
  - `Click Select video and choose the video`
  - `Click See more`
  - `Turn on AI-generated content`
  - `Click Post`
  - 来源：TikTok “AI-generated content” 页面（`tiktok.com/tns-inapp/pages/ai-generated-content`）。
  - 注意：官方页面写的是 “See more”；当前 Studio 前端 i18n 实际是 **“Show more”**。这是文案漂移，不是两个不同入口。
- **【官方文档】** 移动端：
  - 图片帖：`Add post +` → `Post settings` → `AI-generated content`。
  - 视频：`Add post +` → `Next` → `More options ...` → `AI-generated content`。
  - 说明官方产品层面图片帖也有 AIGC 标识能力。
- **【开源实现/前端产物】** 当前 Studio 上传表单把 AIGC 组件放在 `settingsExtra` 中；`settingsExtra` 只有展开 `advanced_settings_container` 后才可见。视频表单的 `settingsExtra` 顺序大致为：
  1. 地理位置/受众相关
  2. 互动权限（评论/合拍/拼接/内容复用/AI remix）
  3. **Disclose post content**（品牌内容声明）
  4. **AI-generated content**（AIGC 开关）
  5. 受众控制
- **【开源实现/前端产物】** 图片帖表单（`POST_PHOTO` 路径）同样把 `tcmInfo`（品牌声明）和 `aigcInfo`（AIGC）放进可折叠的 `collapsibleItems`，并把 `isAIGCChecked` 传给预览组件。也就是说，网页端图片帖代码路径支持 AIGC 和品牌声明。
- **【仅推断】** 官方网页帮助只写了 “Select video” 的路径，没有明确写图片帖网页入口；因此“图片帖网页端可点选 AIGC”目前是代码 + 移动端文档支持，仍建议在目标账号实测一次。
- **【官方文档/开源实现冲突】** Metricool 的帮助页（2026-08 更新）声称 “AI-generated content option is available for video posts only (not photos)”。这与 TikTok 官方移动端说明、Photo API 的 `is_aigc` 字段、以及当前 Studio 图片帖前端代码都不一致，判断为第三方实现或旧限制，不应作为否定依据。

**位置总结：**

```
Upload 页面
└─ 右侧 Settings 卡片
   ├─ 始终可见：隐私、定时等
   └─ Show more（折叠，默认收起）
      ├─ 互动权限
      ├─ Disclose post content   ← 品牌声明总开关
      │  ├─ Your brand
      │  └─ Branded content
      └─ AI-generated content    ← AIGC 开关
```

---

### 2. 准确文案、默认值、是否记住上次选择、发布影响

#### 2.1 准确文案（当前英文 i18n）

以下为当前 Studio 前端 `en.json`（构建 `2.0.0.2604`）中的实际英文值。

**AIGC：**

| 元素 | 文案 |
|---|---|
| 开关标题 | `AI-generated content` |
| 辅助说明（代码 fallback） | `Add this label for aigc.` |
| 了解更多 | `Learn more` |
| 首次开启弹窗标题 | `Labeling AI-generated content` |
| 弹窗按钮 | `Not now` / `Turn on` |
| 自动标识时的提示 | `Can’t turn off because post contains AI-generated content.` |
| 发布后标签 | `Creator labeled as AI-generated` |

说明：`syntheticMedia_post_moreOptionsHalfSheet_aiGenerated_desc` 这个辅助说明 key 没有出现在当前 `en.json` 中，实际很可能显示代码 fallback `Add this label for aigc.`；该句看起来不像最终产品文案，**准确辅助说明未能确认（公开资料不足）**。标题 `AI-generated content` 和发布后标签是确定的。

**品牌内容声明：**

| 元素 | 文案 |
|---|---|
| 总开关 | `Disclose post content` |
| 总开关说明 | `Let others know this post promotes a brand, product or service.` |
| 选项 1 标题 | `Your brand` |
| 选项 1 说明 | `You are promoting yourself or your own business.` |
| 选项 2 标题 | `Branded content` |
| 选项 2 说明 | `You are in a paid partnership with a brand. After posting the video, open your TikTok mobile app and link the campaign under the video’s “Ad settings”.` |
| Private 时的 Branded content 说明 | `To disclose your post as branded content, your post must be set to “Public”.` |
| 两个都没选时的错误 | `You need to indicate if you are representing yourself, collaborating with another brand, or both.` |
| 勾选 Branded content 后的政策声明 | `By posting, you agree to our Branded Content Policy and Music Usage Confirmation.` |
| Private 选项被禁用时的提示 | `Branded content posts cannot be set to Private.` |

注意：

- 旧版/部分页面仍可能出现 `Disclose video content`、`Disclose commercial content` 的措辞；当前网页 i18n 已统一为 **`Disclose post content`**。
- 移动端文案是 `Content disclosure and ads`、`Disclose commercial content`，与网页端不同。网页自动化不要用移动端文案做定位。

#### 2.2 默认值

- **【官方文档】** 商业内容披露总开关默认关闭。TikTok Content Sharing Guidelines 明确要求：“Content Disclosure Setting ... with this feature turned off by default.”
- **【官方文档】** `is_aigc` 在 API 中默认 `false`。
- **【开源实现/前端产物】** 视频表单初始状态：
  - `isBrandOn: false`
  - `tcmParams: { commerce_toggle_info: {} }`
  - `aigcLabelType: NONE`
  - 即：品牌声明关闭，两个品牌复选框都未选，AIGC 关闭。
- **【开源实现/前端产物】** 图片帖的 `aigcInfo` 初始为 `AigcLabelTypeUnknown`，UI 上等价于关闭；品牌 `tcmInfo` 初始 `isSwitchOn: false`。
- **【官方文档】** 如果内容带 C2PA Content Credentials 或使用了 TikTok 官方 AI 效果，TikTok 可能自动打 `AI-generated` 标签；此时创作者标签开关可能被禁用/置为自动，不能关闭。前端提示为 `Can’t turn off because post contains AI-generated content.`
- **【仅推断】** 自动标签的判定在服务端/上传元数据层，网页自动化无法可靠预判；只能读取开关是否 `disabled` 和最终提示。

#### 2.3 是否记住上次选择？

- **【开源实现/前端产物】** 未发现 AIGC 或品牌声明写入 `localStorage` 的代码。Studio 的 `localStorage` 主要保存：
  - 定时发布时区 `tiktok_studio_schedule_timezone`
  - AIGC 引导弹窗已读标记 `_aigc_modal`
  - 其他编辑器 UI 状态
- **【开源实现/前端产物】** 新上传的初始状态固定为关闭/未选；只有以下情况会回填：
  - 从草稿继续：`web_feature_common_info.aigc_info.aigc_label_type`
  - 从草稿继续：`web_feature_common_info.tcm_params`
  - 编辑已发布内容：从 item 的 `web_feature_common_info` 回填
- **【仅推断】** 因此“记住上次选择”应理解为 **草稿/编辑回填**，不是跨新帖记忆。连续发布两个新视频时，第二个默认仍是关闭；账号是否存在服务端个性化默认，**未能确认**。
- 注意：`_aigc_modal` 只记住“引导弹窗已读”，不记住 AIGC 开关值。不要把它误判为“上次勾选状态”。

#### 2.4 勾选/开启后对发布结果的影响

| 选项 | 发布后标签 | 可变性 | 分发影响 |
|---|---|---|---|
| `AI-generated content` | `Creator labeled as AI-generated`（描述/视频上的 AI 标签） | 官方：发布后不能移除 | 官方：只要不违反 Community Guidelines，不会仅因该标识降权 |
| `Your brand` | `Promotional content`（Brand Organic） | 官方：发布后不能改 | 官方：打开披露本身不影响分发 |
| `Branded content` | `Paid partnership`（Branded Content） | 官方：发布后不能改；编辑已发布内容也可能被禁止 | 官方：打开披露本身不影响分发；但不披露商业内容可能导致 For You feed 资格受限 |
| 两者都勾 | `Paid partnership`（官方明确） | 同上 | 同上 |

补充：

- **【官方文档】** API Direct Post 对 `is_aigc` 的描述：设置为 true 后，视频会被标注 `Creator labeled as AI-generated` tag in video's description。
- **【官方文档】** API Photo 也支持 `is_aigc`，描述为 “the photo will be labeled with an AI-generated tag in the description”。
- **【官方文档】** Branded content 可能被加入 TikTok Commercial Content Library（依法要求时），即使原帖删除也可能保留记录。
- **【官方文档】** 未正确披露商业内容时，TikTok 可能先通知，24 小时内未处理则可能失去 For You feed 资格。披露本身不导致降权。
- **【开源实现/前端产物】** 编辑已发布内容时，前端文案有 `Branded content cannot be edited.`，说明品牌内容帖的编辑可能被直接阻止；不要承诺“发布后可改”。

---

### 3. 品牌内容声明：文案、互斥性、账号前置条件

#### 3.1 `Your brand` 与 `Branded content` 是否互斥？

**不互斥。**

- **【官方文档】** TikTok Content Sharing Guidelines 明确：
  - “Enabling this feature will display checkboxes for `Your brand` and `Branded content` ... allowing users to select their preferences.”
  - “It is a multiple selection, and at least one of the options above must be chosen to proceed with publishing.”
  - “If both the above options are selected by the user, a prompt should state `Your photo/video will be labeled as 'Paid partnership'`.”
- **【开源实现/前端产物】** 当前 Studio 用两个独立 checkbox 实现，不是 radio；校验逻辑只在“总开关打开且两个都没选”时报错。错误文案也明确说 “...or both.”。
- **【开源实现/前端产物】** TikTokAutoPost 的实现同样把两个选项当作独立 checkbox，并规定 `disclose_content=true` 时至少一个为 true；两者都为 false 时返回 400。
- **【仅推断】** 因此组合规则是：
  - 只选 `Your brand` → `Promotional content`
  - 只选 `Branded content` → `Paid partnership`
  - 两个都选 → `Paid partnership`（不是两个标签叠加）
  - 都不选但总开关开 → 前端校验错误，不能发布

#### 3.2 账号是否需要先接受品牌内容政策？

**没有发现“账号级事先接受”前置步骤。**

- **【官方文档】** 品牌内容政策要求发布时打开商业内容披露开关；没有说需要先在账号设置里点“Accept”。
- **【官方文档】** 正确用法是：勾选 Branded content 后，发布页显示 “By posting, you agree to our Branded Content Policy and Music Usage Confirmation.”，即发布动作本身构成同意。
- **【开源实现/前端产物】** `tcmInfo` 只有 `isSwitchOn`、`tcmParams`、`disabledBrandedContent` 等状态，没有 `policyAccepted` 字段；UI 只有内联政策声明和 Music Usage Confirmation 链接，没有“必须接受才能继续”的模态。
- **【开源实现/前端产物】** 勾选 Branded content 后可能出现 `Music usage confirmation` 弹窗（点击链接时打开），但它是信息确认，不是账号级政策开通。
- **【官方文档】** 真正有账号/项目前置条件的是 **TikTok One / 品牌合作项目**（需要满足地区、年龄、账号状态、粉丝数等，具体以 TikTok One 资格页为准），不是网页上的 `Branded content` 复选框。设置 `brand_content_toggle=true` 本身不需要先加入 TikTok One。
- **【仅推断】** 某些账号可能因为 `brandOrganic.hidden` 或 `brandedContent.disabled` 而看不到/不能用某个选项；这是账号权限/地区/业务状态导致的 UI 差异，不是“先接受政策”的流程。

#### 3.3 账号/内容前置条件

- **【开源实现/前端产物】** 前端会根据账号权限状态决定：
  - `disabledBrandOrganic`：`Your brand` 可能被隐藏或禁用。
  - `disabledBrandedContent`：`Branded content` 可能被禁用。
  - 额外规则：`visibility === Private` 时 `Branded content` 一定禁用。
- **【官方文档】** `Branded content` 只能配 Public / Friends，不能配 Private（Only me）。官方 Content Sharing Guidelines 要求：Private 时禁用 Branded content，或自动切到 Public；已勾 Branded content 时 Private 选项应禁用，并提示 “Branded content visibility cannot be set to private.”
- **【官方文档】** 第三方品牌合作必须遵守 Branded Content Policy；受限行业需要品牌通过 TikTok One 获得授权。这不是网页复选框能替代的。
- **【仅推断】** 2021 年新闻稿曾提到 “over 10k followers” 的测试范围；当前官方文档没有把 10k 粉丝作为 `Branded content` 复选框的统一门槛。是否存在账号级粉丝门槛，**未能确认**；不要据此做硬编码，应以目标账号实际 UI 为准。

---

### 4. 与隐私级别、定时发布的关系

#### 4.1 与隐私级别

| 组合 | 是否允许 | 证据 |
|---|---|---|
| `Your brand` + Private | 允许 | 代码只对 Branded content 做 Private 限制 |
| `Your brand` + Public/Friends | 允许 | 无额外限制 |
| `Branded content` + Private | **禁止** | Private 时 Branded content 复选框禁用；已勾 Branded content 时 Private 选项禁用 |
| `Branded content` + Public | 允许 | 正常路径 |
| `Branded content` + Friends | **代码层面允许**；官方文档说 Public/Friends | 前端只显式阻止 Private；Friends 在真实账号上是否最终允许，**未能确认** |
| `AI-generated content` + 任意隐私级别 | 允许 | 前端无隐私耦合 |
| `AI-generated content` + 品牌声明 | 允许 | 两组独立状态，可同时开启 |

实现细节：

- **【开源实现/前端产物】** `tcmInfo` 的 `onStatesChange` 监听隐私设置：
  - `disabledBrandedContent = (visibility === ONLY_YOU)`。
  - 反向：如果已勾 Branded content，Private 选项在隐私组件中被禁用，并显示 `Branded content posts cannot be set to Private.`。
- **【官方文档】** 正确 UX 是“禁用 Branded content”或“自动切 Public”，二者选一；TikTok Studio 网页采用前者 + 反向禁用 Private 的双向约束。
- **【仅推断】** 自动化若先设 Private 再设 Branded content，会点不到/点不动复选框；应先设 Public，或先设 Branded content 再设 Public。建议在 preflight 直接拒绝 `--branded-content` + `--privacy private` 的组合，给出明确错误。

#### 4.2 与定时发布

- **【官方文档】** 网页端可以先设置定时，再调整其他设置，最后点 `Post`；没有要求先保存披露再定时。
- **【开源实现/前端产物】** 定时状态（`isScheduleSwitchOn`、`scheduleTime`）与 `tcmInfo`、`aigcInfo` 是独立状态；没有代码在切换定时时清空品牌/AIGC。
- **【仅推断】** 可以组合：定时 + Branded content + AIGC。标签在真正发布时生效，不是设置定时时生效。
- **【仅推断】** 但 Branded content 的说明写着 “After posting the video, open your TikTok mobile app and link the campaign under the video’s ‘Ad settings’.” 定时发布只是延后发帖，**不会自动完成品牌合作活动（campaign）关联**。如果业务要求品牌伙伴 tagging/Spark Ads 授权，网页自动化只能完成 disclosure，不能完成 campaign 关联。
- **【开源实现/前端产物】** 定时选择可能触发 “Allow” 同意弹窗（现有 `set_schedule_time` 已处理 `div.TUXButton-content >> text=Allow`）；这与 AIGC/品牌声明无关，但会改变页面焦点，建议先处理完定时弹窗再展开高级设置。

---

### 5. 是否在 “More options / Advanced settings” 折叠区？展开与保存路径

**是。网页端对应的是右侧 Settings 卡片底部的 “Show more”，不是移动端的 “More options”。**

- **【官方文档】** 网页端步骤：`Upload` → 选择文件 → `Show more`（可能需要向下滚动）→ `Disclose post content` / 其他设置 → `Post`。
- **【开源实现/前端产物】** 当前 DOM：
  - 折叠容器：`[data-e2e="advanced_settings_container"]`
  - 收起时容器 class 含 `collapsed`，例如 `more-collapse collapsed`
  - 展开按钮：容器内 `.more-btn`
  - 展开文案：`Show more`；收起文案：`Show less`
  - 折叠时 `settingsExtra` 子节点带 `hidden` 属性
- **【开源实现/前端产物】** 默认是收起状态（`useState(true)` 表示 collapsed），所以每次新上传都要显式展开；不要假设上一次展开状态会被保留。
- **【开源实现/前端产物】** 当前没有针对这三项的 “Save / Apply” 按钮。它们是表单状态的一部分：
  - 直接发布：点 `Post`，提交时一起带上。
  - 存草稿：点 `Save draft`，AIGC 写入 `web_feature_common_info.aigc_info.aigc_label_type`，品牌声明写入 `web_feature_common_info.tcm_params`。
  - 移动端才常见 `Save` + `Continue`；网页端不要等这个按钮。

#### 5.1 推荐展开流程

```python
advanced = base.locator('[data-e2e="advanced_settings_container"]')
if await advanced.count():
    classes = await advanced.get_attribute("class") or ""
    if "collapsed" in classes:
        await advanced.locator(".more-btn").click()
    await base.locator('[data-e2e="aigc_container"]').wait_for(state="visible")
```

可靠性要点：

1. 先判断 `collapsed` class，避免“已展开又点一次”导致重新收起。
2. 点击容器本身或内部 `.more-btn` 都可；当前代码容器有 `onClick`。
3. 展开后等待目标 container 可见，而不是只等 `hidden` 属性消失。
4. 如果 `advanced_settings_container` 不存在，说明该账号/该表单没有额外设置；不要盲点。
5. 如果 `[data-e2e="aigc_container"]` 不存在，可能是 A/B flag 未开，不要把它当成“关闭状态”。

#### 5.2 推荐保存/发布流程

```python
# 设置完成后不需要 Save；直接 Post
await base.locator('[data-e2e="post_video_button"]').click()
```

- **【开源实现/前端产物】** 当前 Post 按钮 selector：`[data-e2e="post_video_button"]`。
- 现有 `main_chrome.py` 用的是 `div.button-group button` nth(0)，也能工作，但更容易受布局变化影响；建议新逻辑优先 `data-e2e`。
- 如果弹出了 AIGC 引导弹窗、Music Usage Confirmation、定时 Allow 弹窗、品牌政策弹窗，必须先处理弹窗再点 Post；否则可能点到弹窗按钮或无效区域。

---

## UI 路径与候选选择器

### 6.1 视频帖（确定路径）

```
1. goto https://www.tiktok.com/tiktokstudio/upload
2. 选择视频文件
3. 等上传/处理完成（Post 按钮可用）
4. 右侧 Settings 卡片 → 点击 “Show more”
   [data-e2e="advanced_settings_container"]
5. 找到 “Disclose post content”
   [data-e2e="disclose_content_container"]
6. 找到 “AI-generated content”
   [data-e2e="aigc_container"]
7. 点 Post
   [data-e2e="post_video_button"]
```

### 6.2 图片帖（代码支持；网页端真实入口与文案未能确认）

```
1. 进入图片帖上传/编辑表单（TikTok Studio 图片帖入口）
2. 右侧 Settings 卡片 → 展开折叠项（Show more / collapsibleItems）
3. 同样出现 Disclose post content 与 AI-generated content
4. 点 Post
```

- **【开源实现/前端产物】** 图片帖表单把 `tcmInfo` 与 `aigcInfo` 都放进 `collapsibleItems`；不是视频专属。
- **【仅推断】** 图片帖的可见文案、折叠按钮 text 是否同样是 “Show more”，**未能确认**；`data-e2e` 可能相同，也可能因表单组件不同而变化。

### 6.3 候选选择器

> 作用域：以下大部分选择器应作用在现有 `self.locator_base` 上（它可能是 `page.frame_locator('[data-tt="Upload_index_iframe"]')`）。弹窗/toast 可能挂在顶层 `page`，需要单独判断。不要一律用 `page.locator(...)`。

**折叠区：**

```css
[data-e2e="advanced_settings_container"]
[data-e2e="advanced_settings_container"].collapsed
[data-e2e="advanced_settings_container"] .more-btn
```

**品牌声明：**

```css
[data-e2e="disclose_content_container"]
[data-e2e="disclose_content_container"] [role="switch"]
[data-e2e="disclose_content_container"] .Switch__content
```

- 读取状态：`aria-checked="true"`（开源实现用这个）。
- 点击：优先点 `[role="switch"]` 或 `.Switch__content`；不要点整行文字，避免点到 tooltip/链接。

**两个品牌复选框：**

当前 DOM 中，复选框不是 `disclose_content_container` 的子节点，而是它后面的兄弟容器（class 含 hash `jsx-4041535456`）。候选：

```css
/* 推荐：按可访问名/文本，避免 hash */
page.get_by_role("checkbox", name="Your brand")
page.get_by_role("checkbox", name="Branded content")

/* 备选：按文本点击 label */
page.get_by_text("Your brand", exact=True)
page.get_by_text("Branded content", exact=True)

/* 兜底：开源实现使用的 hash class（脆弱） */
.jsx-4041535456 .Checkbox__inputWrapper   /* nth(0)=Your brand, nth(1)=Branded content */
```

建议实现顺序：

1. `get_by_role("checkbox", name=...)`；
2. 失败则 `get_by_text(..., exact=True).click()`；
3. 再失败才用 hash class 的 `.Checkbox__inputWrapper`；
4. 每次点击后读 `checked` / `aria-checked` 验证。

**AIGC 开关：**

```css
[data-e2e="aigc_container"]
[data-e2e="aigc_container"] [role="switch"]
[data-e2e="aigc_container"] .Switch__content
```

**AIGC 首次引导弹窗：**

- 标题：`Labeling AI-generated content`
- 按钮：`Not now` / `Turn on`
- 候选：

```css
[role="dialog"] button:has-text("Turn on")
.TUXModal button:has-text("Turn on")
page.get_by_role("button", name="Turn on")
```

**发布按钮：**

```css
[data-e2e="post_video_button"]
```

**隐私/权限辅助：**

```css
[data-e2e="video_visibility_container"]
[data-e2e="user_perm_container"]
```

---

## 组合规则

### 7.0 API ↔ UI 映射表

| API 字段 | 出现位置 | 网页端控件 | 默认 | 发布结果 |
|---|---|---|---|---|
| `is_aigc` | 视频：`post_info.is_aigc`；图片：顶层 `is_aigc` | `[data-e2e="aigc_container"]` 内的 **AI-generated content** 开关 | `false` / 未开启 | `Creator labeled as AI-generated` |
| `brand_organic_toggle` | 视频：`post_info.brand_organic_toggle`；图片：`post_info.brand_organic_toggle` | `Disclose post content` 打开后的 **Your brand** 复选框 | 未勾选 | `Promotional content` |
| `brand_content_toggle` | 视频：`post_info.brand_content_toggle`；图片：`post_info.brand_content_toggle` | `Disclose post content` 打开后的 **Branded content** 复选框 | 未勾选 | `Paid partnership` |
| （无独立 API 字段） | 网页端品牌声明总开关 | **Disclose post content** switch | 关闭 | 总开关本身不产生标签；必须至少选一个品牌选项 |

补充：

- **【官方文档】** 图片帖 API 的 `is_aigc` 位于请求顶层，不在 `post_info` 内；视频 Direct Post 的 `is_aigc` 在 `post_info` 内。实现参数契约时不要混用层级。
- **【官方文档】** `brand_content_toggle` 与 `brand_organic_toggle` 是两个独立 bool；API 没有“总开关”字段，总开关是网页表单的 UI 概念。
- **【官方文档】** 两者都为 true 时，网页端标签按 `Paid partnership` 处理；API 文档没有描述“两个标签同时出现”。

### 7.1 状态机

```
disclose_content = false
  ├─ Your brand not selectable / hidden
  ├─ Branded content not selectable / hidden
  └─ 发布无商业内容标签

disclose_content = true
  ├─ your_brand = false, branded_content = false  → 校验错误，不能发布
  ├─ your_brand = true,  branded_content = false  → Promotional content
  ├─ your_brand = false, branded_content = true   → Paid partnership（要求 privacy != Private）
  └─ your_brand = true,  branded_content = true   → Paid partnership（要求 privacy != Private）

aigc = false
  └─ 无 Creator labeled as AI-generated

aigc = true
  └─ Creator labeled as AI-generated（若被自动标签则可能不可关闭）
```

### 7.2 规则清单

1. **总开关依赖**：`Your brand` / `Branded content` 只在 `Disclose post content` 打开时显示（编辑场景可能隐藏总开关但保留选项）。关闭总开关会清空已选品牌项（前端把 `tcmParams` 重置为 `{commerce_toggle_info:{}}`）；因此幂等设置时应先确保总开关状态正确，再设置复选框。
2. **至少一个**：总开关打开时，两个品牌选项至少选一个；否则前端校验错误，Post 不通过。
3. **可同时选**：两个都选合法；发布标签为 `Paid partnership`。
4. **Private 互斥**：`Branded content` 与 Private 不能共存；`Your brand` 与 Private 可以共存。
5. **AIGC 独立**：AIGC 与品牌声明、隐私级别均无硬互斥；可与任意品牌组合、任意隐私级别组合。
6. **AIGC 自动标签优先**：如果 TikTok 自动判定 AIGC，开关可能被禁用并显示“不可关闭”；此时不要强行点击。
7. **发布后不可改**：AIGC、Your brand、Branded content 发布后都不能改；品牌内容帖可能连编辑都被禁止。需要修正只能删除重发。
8. **账号权限**：`Your brand` / `Branded content` 可能因账号业务状态被隐藏/禁用；不是所有账号都看到完整选项。
9. **品牌合作关联**：勾选 Branded content 只完成 disclosure；品牌伙伴 tagging / campaign 关联需要在发布后用移动端 `Ad settings` 完成，网页自动化不覆盖。
10. **政策同意**：只选 `Your brand` 时，发布即表示同意 Music Usage Confirmation；勾选 `Branded content`（含两者同选）时，再额外包含 Branded Content Policy。没有独立的账号级“先接受”开关。

---

## 风险

### 8.1 高优先级

1. **AIGC 开关受 A/B flag 控制**
   - 前端逻辑：`showAigcToggle = abHitResult["show_aigc_toggle"] === ENABLED`；不满足时组件直接 `return null`。
   - 结果：某些 Profile/地区/账号根本没有 `[data-e2e="aigc_container"]`。
   - 应对：把“容器不存在”视为“不支持”，不要默认为关闭；如果用户显式要求 AIGC，应 fail fast 并给出明确原因。

2. **首次开启 AIGC 有引导弹窗**
   - 首次点击 AIGC 开关不会立即生效，而是弹出 `Labeling AI-generated content`，需要点 `Turn on`；点 `Not now` 会保持关闭。
   - 应对：点击后等待弹窗；若出现，点 primary `Turn on`；然后重新读取开关状态。不要只点一次开关就认为成功。
   - `localStorage` 的 `_aigc_modal` 只控制弹窗是否再次出现，不控制开关值。

3. **Branded content 与 Private 的双向禁用**
   - 先设 Private 会导致 Branded content 点不动；先勾 Branded content 会导致 Private 点不动。
   - 应对：preflight 拒绝 `branded_content && privacy=private`；或在设置品牌前先确保 Public/Friends。

4. **选择器漂移**
   - `data-e2e` 比 hash class 稳定，但仍可能改版；`.jsx-4041535456` 是构建 hash，下一次构建必变。
   - 应对：主 selector 用 `data-e2e` + 文本/role；hash class 只做最后兜底；每次点击后验证状态。

5. **发布后不可逆**
   - AIGC/品牌声明发布后不能改；Branded content 帖可能不能编辑。
   - 应对：发布前截图/日志记录三项状态；CLI 参数一旦设置就按“不可回滚”处理。

### 8.2 中优先级

6. **AIGC 自动标签不可关闭**
   - C2PA / TikTok AI 效果可能触发 auto label；开关显示 disabled，提示不可关闭。
   - 应对：如果用户要求 `aigc=false` 但开关 disabled 且为 on，应报告“平台自动标签，无法关闭”，不要强行点击。

7. **图片帖网页端未在官方网页帮助中明示**
   - 代码路径支持，但官方 web 文档只写视频；第三方工具又有“仅视频”的说法。
   - 应对：图片帖功能先做 feature probe；真实 UI 不存在时降级为“不支持”，不要静默忽略用户请求。

8. **品牌政策/音乐确认弹窗**
   - 勾选 Branded content 后页面可能显示政策声明；点击链接会打开 Music Usage Confirmation 弹窗。
   - 应对：不要点击政策链接；只勾选复选框，然后直接 Post。若弹窗出现，先关闭/确认再 Post。

9. **账号级选项隐藏**
   - `brandOrganic.hidden` / `brandedContent.disabled` 可能让某个选项不可用。
   - 应对：设置前检查 count/disabled；用户要求但不可用时 fail fast。

10. **文案本地化**
    - 文本 selector 依赖 English (US)；MLX Profile 必须保持英文。
    - 应对：优先 `data-e2e`；文本 selector 只做 fallback；不要调用 `change_language` 改写 Profile 语言。

### 8.3 低优先级/待观察

11. **定时与品牌 campaign 关联分离**
    - 定时发布不会自动完成移动端 `Ad settings` 的 campaign 关联。
12. **Friends 隐私与 Branded content**
    - 官方说 Public/Friends；前端只显式阻止 Private。Friends 是否在所有账号可用，**未能确认**。
13. **“Show more” 文案漂移**
    - 官方帮助写 “See more”，当前 UI 是 “Show more”；不要用官方文案做精确文本定位。

---

## 可行性结论

**视频帖：高可行性。**  
三项都能在网页端完成，且当前 DOM 有稳定的 `data-e2e` 容器。建议实现为上传表单中的一个独立步骤：

1. 等文件处理完成、Post 可用；
2. 展开 `advanced_settings_container`（仅当 `collapsed`）；
3. 按需设置 `disclose_content_container` / `aigc_container`；
4. 处理 AIGC 首次引导弹窗；
5. 校验品牌至少一个、Branded content 非 Private；
6. 再设置定时/封面（如需要）；
7. Post，并记录三项最终状态。

**图片帖：中高可行性，但必须实测。**  
当前前端代码路径包含 AIGC 与品牌声明组件，官方移动端和 Photo API 也支持；但官方网页帮助没有明示图片帖的 AIGC 路径，且存在第三方“仅视频”的说法。建议先做 feature probe，再决定是否对 `upload-note` 暴露这三个参数。

**建议的 CLI 契约（供后续规格使用）：**

```text
--aigc / --no-aigc                  # 默认 false
--your-brand                        # 默认 false
--branded-content                   # 默认 false
--disclose-content                  # 可选：显式打开总开关；由上面两个参数推导也可
```

约束：

- `--branded-content` 与 `--privacy private` 互斥，preflight 直接报错。
- 只要 `--your-brand` 或 `--branded-content` 为 true，就必须打开 `Disclose post content`。
- 两者都为 false 且 `--disclose-content` 为 true → 报错（至少选一个）。
- 两者都 true → 允许；发布标签预期为 `Paid partnership`。
- `--aigc` 与品牌声明可同时为 true。
- 如果 AIGC 容器不存在但用户显式要求 `--aigc`，报 “当前账号/地区不支持网页端 AIGC 标识”，不要静默降级。
- 如果 `--branded-content` 的复选框 disabled，报具体原因（Private 或账号权限）。

**不建议的做法：**

- 不要用 radio 逻辑实现 `Your brand` / `Branded content`（会错误地阻止两者同选）。
- 不要只点一次 AIGC 开关就认为成功（首次有弹窗）。
- 不要在 Private 状态下尝试点 Branded content。
- 不要承诺发布后还能修改这三项。
- 不要把 `_aigc_modal` 当作“上次选择”的记忆。

---

## 待复核点

以下需要在目标 MLX Profile 上做一次人工/半自动实测：

1. **AIGC 容器是否存在**：目标账号是否被 `show_aigc_toggle` A/B 命中？`[data-e2e="aigc_container"]` 是否出现？
2. **AIGC 首次弹窗**：首次开启是否一定弹 `Labeling AI-generated content`？`Turn on` 按钮的精确 role/name？点 `Not now` 后开关是否保持关闭？
3. **AIGC 辅助文案**：实际显示的是 `Add this label for aigc.` 还是其他 i18n 文案？
4. **图片帖网页入口**：`upload-note` 对应的图片帖表单是否有 `Disclose post content` 和 `AI-generated content`？折叠按钮是否同样叫 `Show more`？
5. **两者同选**：真实 UI 是否允许同时勾选 `Your brand` + `Branded content`？发布后标签是否为 `Paid partnership`？
6. **Friends + Branded content**：前端只阻止 Private；Friends 是否真的允许？官方说 Public/Friends，但 i18n 文案写 “must be set to Public”。
7. **账号粉丝门槛**：没有 10k 粉丝的账号是否能看到 `Branded content`？当前文档没有统一门槛，但旧资料有 10k 说法。
8. **跨帖记忆**：连续发两个新视频，第二个的 AIGC/品牌声明是否仍默认关闭？是否有个性化默认？
9. **定时 + 品牌**：定时发布时是否出现额外确认弹窗？Branded content 的 campaign 关联是否仍必须移动端完成？
10. **编辑已发布品牌内容**：是否真的不能编辑？`Branded content cannot be edited.` 是否会在 UI 出现？
11. **选择器稳定性**：`data-e2e` 是否在 iframe（`[data-tt="Upload_index_iframe"]`）内同样可用？当前代码需要在 `locator_base` 上操作，需确认 frame 内 selector 一致。
12. **自动标签**：带 C2PA 元数据的视频是否会把 AIGC 开关置为 disabled/on？此时 `--no-aigc` 应如何报告？

---

## 对现有代码的落点建议（只做调研，不改代码）

现有 `uploader/tk_uploader/main_chrome.py` 的关键事实：

- 入口：`TIKTOK_UPLOAD_URL = https://www.tiktok.com/tiktokstudio/upload`。
- `choose_base_locator()`：如果存在 `iframe[data-tt="Upload_index_iframe"]`，使用 `page.frame_locator(...)`；否则用 `page.locator("body")`。
- `_upload_on_page()` 当前只做：选文件 → `add_title_tags()` → `detect_upload_status()` → 可选缩略图 → 可选定时 → `click_publish()`。
- `set_schedule_time()`：`get_by_label("Schedule")` + `div.scheduled-picker`。
- `click_publish()`：`div.button-group button` nth(0)，不处理额外披露/品牌弹窗。
- **没有任何 AIGC / 品牌声明逻辑。**

建议后续实现位置：

```text
_upload_on_page()
  ├─ choose_base_locator()
  ├─ 选文件
  ├─ add_title_tags()
  ├─ detect_upload_status()
  ├─ [新增] apply_disclosure_and_aigc()   ← 在定时/封面之前或之后均可
  ├─ 可选封面
  ├─ 可选定时
  └─ click_publish()
```

`apply_disclosure_and_aigc()` 内部建议：

1. `expand_advanced_settings()`；
2. `set_disclose_content(bool)`；
3. `set_brand_option("your_brand", bool)` / `set_brand_option("branded_content", bool)`；
4. `set_aigc(bool)` + 处理首次弹窗；
5. `verify_disclosure_state()`（读 aria-checked / checked，确认与请求一致）。

选择器建议：

- 主：`[data-e2e="advanced_settings_container"]`、`[data-e2e="disclose_content_container"]`、`[data-e2e="aigc_container"]`、`[data-e2e="post_video_button"]`。
- 状态：`aria-checked` / `input.checked`。
- 文本 fallback：`Your brand`、`Branded content`、`Disclose post content`、`AI-generated content`、`Show more`、`Turn on`。
- 不要依赖 `.jsx-4041535456` 这类构建 hash 作为首选。

---

## Sources

### 官方文档

1. TikTok Help Center — About AI-generated content  
   https://support.tiktok.com/en/using-tiktok/creating-videos/ai-generated-content
2. TikTok — AI-generated content（网页端 “See more” 步骤）  
   https://www.tiktok.com/tns-inapp/pages/ai-generated-content
3. TikTok Help Center — Promoting a brand, product, or service（网页端 `Show more` / `Disclose post content`）  
   https://support.tiktok.com/en/business-and-creator/creator-and-business-accounts/promoting-a-brand-product-or-service
4. TikTok — Branded Content Policy（生效日期 2026-10-30）  
   https://www.tiktok.com/legal/page/global/bc-policy/en
5. TikTok for Developers — Content Sharing Guidelines（multiple selection、默认关闭、Private 规则、政策声明）  
   https://developers.tiktok.com/doc/content-sharing-guidelines
6. TikTok for Developers — Direct Post（`is_aigc`、`brand_content_toggle`、`brand_organic_toggle`）  
   https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
7. TikTok for Developers — Photo（`is_aigc`、`brand_content_toggle`、`brand_organic_toggle`）  
   https://developers.tiktok.com/doc/content-posting-api-reference-photo-post
8. TikTok for Developers — Video Object（`is_aigc` 返回字段）  
   https://developers.tiktok.com/docs/en/tiktok-api-v2-video-object
9. TikTok for Business Help Center — About the Commercial Content Disclosure setting for creators（未披露的 24 小时处理窗口）  
   https://ads.tiktok.com/help/article/about-the-content-disclosure-setting-for-creators

### 开源实现

10. ZumaAkbarID/TikTokAutoPost — `automation/uploader.js`（`advanced_settings_container`、`disclose_content_container`、`aigc_container`、`Switch__content`、私密与品牌校验）  
   https://github.com/ZumaAkbarID/TikTokAutoPost  
   https://raw.githubusercontent.com/ZumaAkbarID/TikTokAutoPost/main/automation/uploader.js
11. 同仓库 README（`disclose_content` / `your_brand` / `branded_content` / `aigc_label` 参数与校验规则）  
    https://raw.githubusercontent.com/ZumaAkbarID/TikTokAutoPost/main/README.md

### TikTok Studio 当前前端产物（只读抓取，2026-11-05）

12. Studio 上传表单 bundle（`settingsExtra`、`AIGC`、`DISCLOSE_CONTENT_CONTAINER`）：  
    https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/static/js/async/Form.535991d5.js
13. 品牌声明组件（`Your brand` / `Branded content` 复选框、Private 禁用、错误文案）：  
    https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/static/js/async/337.cc43c2bc.js
14. 高级设置折叠容器（`advanced_settings_container`、`collapsed`、`Show more` / `Show less`）：  
    https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/static/js/async/9834.20461d33.js
15. `data-e2e` 枚举（`DISCLOSE_CONTENT_CONTAINER`、`AIGC_CONTAINER`、`ADVANCED_SETTINGS_CONTAINER`）：  
    https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/static/js/async/9602.bceb34cf.js
16. 当前英文 i18n（实际文案：`Disclose post content`、`Your brand`、`Branded content`、`AI-generated content`、`Show more`）：  
    https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/i18n/2.0.0.2604/Webapp/en.json

### 第三方参考（用于冲突对照）

17. Metricool — Schedule and Post on TikTok（声称 AIGC 仅视频，与官方/当前前端不一致）  
    https://help.metricool.com/schedule-and-post-on-tiktok-bkepi
18. Bazaarvoice — TikTok commercial content enforcement（2025-09 起未披露商业内容可能失去 For You feed 资格）  
    https://www.bazaarvoice.com/updates/the-new-rules-of-tiktok-what-brands-and-creators-need-to-know/

---

## 最终判断

- **能做的部分**：网页端可以完整表达 `is_aigc`、`brand_content_toggle`、`brand_organic_toggle`，且与 API 语义基本一一对应；两者品牌选项可同时选，发布标签按 `Paid partnership` 处理。
- **不能完全对齐的部分**：网页端不能完成 Branded content 的“品牌伙伴 tagging / campaign 关联”（需要在移动端 Ad settings 完成）；AIGC 开关受 A/B flag 和自动标签影响；图片帖网页路径需要实测。
- **实现优先级**：先做视频；把 AIGC 容器缺失、首次弹窗、Private+Branded 冲突、品牌至少一个这四类边界做成显式失败/校验；再决定图片帖是否暴露同样参数。
