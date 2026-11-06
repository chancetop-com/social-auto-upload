# 03 — 隐私级别与互动开关：`privacy_level` / `disable_comment` / `disable_duet` / `disable_stitch`

- 调研日期：2026-11-05
- 目标页面：`https://www.tiktok.com/tiktokstudio/upload`（English (US)）
- 方式：只读静态调研。未启动浏览器、未登录、未修改业务代码。
- 证据分级：
  - **官方文档**：TikTok 开发者文档 / TikTok 帮助中心。
  - **官方前端实现**：TikTok Studio 线上 JS bundle 静态分析（第一方代码，但不是文档，仍可能随 A/B 与发版变化）。
  - **开源实现**：公开 GitHub 项目的选择器与文案。
  - **仅推断**：以上都没有直接证据，只做保守推理。

---

## Question

TikTok Studio 网页端如何表达 Content Posting API 的四个字段：

1. `privacy_level`：`PUBLIC_TO_EVERYONE` / `MUTUAL_FOLLOW_FRIENDS` / `FOLLOWER_OF_CREATOR` / `SELF_ONLY` 与页面文案如何一一对应？
2. 公开账号与私有账号分别看到哪些选项？不可用选项是隐藏还是置灰？
3. 评论、合拍、拼接开关的准确文案、默认值、禁用条件是什么？
4. 这些设置逐条生效还是会被记住？如何可靠读取当前选中值？
5. 如果账号级设置已经禁止某项互动，页面表现是什么？

---

## Findings

### F1. 隐私选项只有三个，且“第一项”会随账号公开/私有切换文案

**官方文档** + **官方前端实现**：

| 账号类型 | 页面上的三项（自上而下） |
| --- | --- |
| 公开账号 | `Everyone`、`Friends`、`Only you` |
| 私有账号 | `Followers`、`Friends`、`Only you` |

关键点：私有账号不是“额外出现一个 Followers，同时把 Everyone 置灰”，而是**同一个第一项从 `Everyone` 改名为 `Followers`**。前端代码里只有三个 option，第一项的 label 由 `private_account` 决定：

```js
} else {
  t.Public = i("commonStrings_privacySettings_option_everyone")
}
```

以及较老的 Form 实现中更直白：

```js
O = {
  Everyone: L(l ? "Followers" : "Public"),
  Friends: L("Friends"),
  Private: L("Private")
}
// l = user.private_account
```

因此：

- 公开账号不会看到 `Followers`。
- 私有账号不会看到 `Everyone` / `Public`。
- 两种账号都只有 3 个可选项，没有第 4 个。

置信度：**官方文档 + 官方前端实现，高**。

---

### F2. 页面文案存在 `Everyone` / `Public` 两套历史/实验变体

**官方前端实现**：

线上 bundle 同时存在两套组件：

- 新组件（`6240.*.js`，隐私设置面板）使用：
  - `webCreation_postingPage_visibility_everyone` → `Everyone`
  - `webCreation_postingPage_visibility_follower` → `Followers`
  - `webCreation_postingPage_visibility_friend` → `Friends`
  - `webCreation_postingPage_visibility_onlyYou` → `Only you`
- 老/备用 Form 组件（`Form.*.js`）使用：
  - 公开账号第一项 → `Public`
  - 私有账号第一项 → `Followers`

**TikTok 帮助中心当前（2026）统一写的是 `Everyone`**，开源项目 2026-02 版本也用 `Everyone`。因此线上主路径大概率是 `Everyone`，但**不要把 `Everyone` 写死为唯一匹配文本**，应同时接受 `Everyone` 和 `Public`。

置信度：**官方前端实现，高；具体线上命中哪套取决于 A/B，需实测复核**。

---

### F3. API 枚举 ↔ 页面文案 ↔ 提交内部值

**官方文档**（Query Creator Info）：

- 公开账号可选：`PUBLIC_TO_EVERYONE`、`MUTUAL_FOLLOW_FRIENDS`、`SELF_ONLY`
- 私有账号可选：`FOLLOWER_OF_CREATOR`、`MUTUAL_FOLLOW_FRIENDS`、`SELF_ONLY`

**官方前端实现**（提交给服务端时的 `visibility_type` 字符串）：

```js
{
  [EVERYONE]: private_account ? "followers" : "public",
  [FRIENDS]: "friends",
  [ONLY_YOU]: "private"
}
```

映射表：

| API 枚举 | 公开账号页面文案 | 私有账号页面文案 | Studio 提交值 | 说明 |
| --- | --- | --- | --- | --- |
| `PUBLIC_TO_EVERYONE` | `Everyone`（部分变体 `Public`） | 不出现 | `public` | 私有账号无此能力 |
| `FOLLOWER_OF_CREATOR` | 不出现 | `Followers` | `followers` | 公开账号无此能力 |
| `MUTUAL_FOLLOW_FRIENDS` | `Friends` + 副标题 `Followers you follow back` | 同左 | `friends` | 两账号类型都可用 |
| `SELF_ONLY` | `Only you`（少数文案变体 `Private`） | 同左 | `private` | 两账号类型都可用 |

注意：页面上的 `Followers you follow back` 是 `Friends` 的说明文字，不是独立选项。若用 `has-text("Followers")` 匹配，会同时命中 `Followers` 选项和 `Friends` 的说明，必须用精确文本或 `role=option` 边界。

置信度：**官方文档 + 官方前端实现，高**。

---

### F4. 当前 Studio 的互动区是“评论 + 内容复用”两个主开关，不再有独立的 Duet / Stitch

**官方前端实现**：

当前隐私面板的结构是：

```text
Allow users to:
  [x] Allow comments
  [x] Allow reuse of content
      Duet、Stitch、Stickers、添加到 Story 由这一个开关统一控制
  [x] Allow AI to remix content
```

代码中的三个开关分别是：

```js
label: __("Comment")                        // 实际英文文案为 "Allow comments"
label: __("provideUnifiedToggle_settings_privacy_toggle")  // 实际为 "Allow reuse of content"
label: __("remixToggle_settings_remix_header")             // 实际为 "Allow AI to remix content"
```

**官方帮助中心**也明确：逐条发布的开关是 `Allow comments` 与 `Allow reuse of content`；`Allow reuse of content` 同时影响 Duet、Stitch、Stickers、Story。

**开源实现**（`wkaisertexas/tiktok-uploader`，2026-02 迁移到 Playwright 后的版本）仍然使用三个独立控件：

```toml
comment = "//label[.='Comment']/following-sibling::div/input"
duet    = "//label[.='Duet']/following-sibling::div/input"
stitch  = "//label[.='Stitch']/following-sibling::div/input"
```

这说明 TikTok 在 2025→2026 之间做过 UI 收敛：**旧界面有独立 Duet / Stitch，新界面合并为 `Allow reuse of content`**。截至调研日期，线上主 bundle 是合并后的版本。

置信度：

- 当前为合并开关：**官方前端实现 + 官方帮助中心，高**。
- 旧界面存在独立控件：**开源实现，中高（可能仍被 A/B 命中）**。

---

### F5. 默认值：新上传默认全开，隐私默认第一项

**官方前端实现**：

隐私状态初始化：

```js
{
  allowComment: true,
  allowDuet: true,
  allowStitch: true,
  allowContentReuse: true,
  allowAiRemix: true,
  visibility: VISIBILITY_TYPE_EVERYONE_OR_FOLLOWERS  // 即第一项
}
```

因此新上传的默认表现是：

| 设置 | 默认 |
| --- | --- |
| 可见性 | 公开账号 `Everyone`；私有账号 `Followers` |
| `Allow comments` | 勾选（开） |
| `Allow reuse of content` | 勾选（开），但私有账号会被强制置灰/取消 |
| `Allow AI to remix content` | 勾选（开） |

注意：这是 TikTok 原生 Studio 的默认值，不等同于 Content Posting API 对第三方客户端的 UX 要求（API 文档要求第三方客户端“默认不勾选、必须用户手动打开”）。浏览器自动化走的是原生 UI，应服从原生默认值。

置信度：**官方前端实现，高；线上是否被 A/B 覆盖需复核**。

---

### F6. 设置是逐条生效；新上传不继承上一条，草稿会恢复

**官方前端实现**：

- 每次新上传的表单状态从上面的默认值开始，没有发现把上一次发布的隐私/互动选择写入 `localStorage` 或跨表单复用的代码。
- 草稿（cloud draft）会从 `web_feature_common_info.privacy_setting_info` 恢复：

```js
{
  allow_comment, allow_duet, allow_stitch,
  allow_content_reuse, allow_ai_remix, visibility_type
}
```

- 账号级设置（谁能评论、Reuse of content 权限）是全局的，会作为上限约束逐条设置；逐条开关只能在其允许范围内收窄。

结论：

- **逐条生效**：是。
- **记住上一条**：没有证据；默认每次重置。
- **草稿恢复**：是。

置信度：**官方前端实现，中高；需要一次真实连续发布两条来最终确认**。

---

### F7. 如何可靠读取当前选中值

**官方前端实现**：

可见性选择器：

- 容器：`div[data-e2e="video_visibility_container"]`
- 触发器：`button[role="combobox"]`，同时带 `TUXSelect-button` class
- 当前值：触发器内部文本（组件会把选中项的 `label` 渲染进 button），也可读 `aria-label`
- 菜单项：`li[role="option"]`
- 选中项：`li[role="option"][aria-selected="true"]`
- 禁用项：`li[role="option"].TUXSelect-menuOption--disabled`（代码只加 class，没有稳定的 `aria-disabled`）

互动开关：

- 容器：`div[data-e2e="user_perm_container"]`
- 控件：`input[type="checkbox"]`
- 选中值：`input.checked` / Playwright `is_checked()`
- 禁用：`input[disabled]`、`is_disabled()`，外层另有 `TUXCheckbox--disabled` / `TUXCheckboxStandalone--disabled`

推荐读取顺序：

1. 先读可见性 trigger 的 `inner_text()`，这是最稳的“当前值”。
2. 需要确认选项全集时再点开，读所有 `li[role="option"]` 的文本。
3. 用 `aria-selected="true"` 交叉验证，不要只依赖 trigger 文本（trigger 文本不含副标题）。
4. 复选框直接读 `input.is_checked()`；不要靠 CSS 背景色判断。

置信度：**官方前端实现，高**。

---

### F8. 账号级限制：控件置灰且取消勾选，不是隐藏

**官方前端实现**：

- 评论权限：
  ```js
  ce = Q !== NO_PERM          // Q = user.comment_setting
  // Comment checkbox: checked = ne, disabled = !ce
  ```
  如果账号级 `comment_setting === NO_PERM`，评论开关会被强制取消勾选并置灰。
- 内容复用权限：
  - 私有账号：`reuseShowType = DISABLED`，且 `checked = allowContentReuse && !private_account`，所以显示为**未勾选 + 置灰**。
  - 账号级 `content_reuse_permission.show_type === DISABLED`：同样置灰。
- 年龄门槛（U16/年龄门控）：所有可见性选项置灰，并强制 `Only you`；提示 key 为 `setting_disabled_16`。
- 品牌内容：`Only you` 置灰，tooltip 文案为 `Branded content posts cannot be set to Private.`
- 地理围栏：`Friends` 与 `Only you` 置灰。

“隐藏 vs 置灰”：

- 当前隐私组件里 `hiddenVisibilities` 始终为空数组，不可用项进入 `disabledVisibilities`。
- 因此主路径是**保留选项并置灰**，不是删除。
- 唯一的“看起来像替换”的情况是私有账号把第一项从 `Everyone` 改名为 `Followers`，这不是禁用。

置信度：**官方前端实现，高**。

---

### F9. 账号级禁止 Duet / Stitch 时，页面没有独立反馈点

**官方文档**：

- 私有账号天然不能 Duet / Stitch。
- 账号级 `Reuse of content` 设为 `No one` 时，Duet / Stitch 都不可用。
- API 的 `duet_disabled` / `stitch_disabled` 在私有账号下恒为 `true`。

**官方前端实现**：

- 当前 UI 不再分别展示 Duet / Stitch 权限，只展示统一的 `Allow reuse of content`。
- 代码里仍保留 `duet_setting` / `stitch_setting` / `allowDuet` / `allowStitch`，但主要作为旧状态与提交 payload 的兼容字段；新 UI 的 `onChange` 只更新 `allowContentReuse`。
- 因此，如果账号级只禁了 Duet 或只禁了 Stitch，页面上**没有独立的置灰项**可以直接观察；只能通过统一的 reuse 开关是否可用、以及发布后的实际效果来判断。

置信度：**官方前端实现，中高；“只禁单项时统一开关是否置灰”属于仅推断，需实测**。

---

## 枚举 ↔ 页面文案映射表（汇总）

| API 字段 / 枚举 | 页面控件 | 页面文案 | 公开账号 | 私有账号 | 备注 |
| --- | --- | --- | --- | --- | --- |
| `privacy_level=PUBLIC_TO_EVERYONE` | 可见性下拉第 1 项 | `Everyone` / 变体 `Public` | ✅ | ❌ 不出现 | 私有账号提交 `public` 会被服务端拒绝或降级 |
| `privacy_level=FOLLOWER_OF_CREATOR` | 可见性下拉第 1 项 | `Followers` | ❌ 不出现 | ✅ | 公开账号提交 `FOLLOWER_OF_CREATOR` 不在可选集 |
| `privacy_level=MUTUAL_FOLLOW_FRIENDS` | 第 2 项 | `Friends`（副标题 `Followers you follow back`） | ✅ | ✅ | |
| `privacy_level=SELF_ONLY` | 第 3 项 | `Only you` / 变体 `Private` | ✅ | ✅ | |
| `disable_comment=false` | 复选框 | `Allow comments` | ✅ | ✅（除非账号级 No one） | 勾选 = 允许评论 |
| `disable_comment=true` | 复选框 | 取消勾选 | ✅ | ✅ | |
| `disable_duet=false` 且 `disable_stitch=false` | 统一复选框 | `Allow reuse of content` | ✅ 勾选 | ❌ 置灰 | 一项控制 Duet+Stitch+Stickers+Story |
| `disable_duet=true` 且 `disable_stitch=true` | 统一复选框 | 取消勾选 | ✅ | ❌ 置灰 | |
| `disable_duet != disable_stitch` | 无 | 无 | ❌ | ❌ | **当前 UI 无法表达** |
| 无 API 对应 | 复选框 | `Allow AI to remix content` | ✅ | ❌ 置灰 | TikTok 新增能力，API 四字段之外 |

---

## UI 路径与候选选择器

### 路径

1. 打开 `https://www.tiktok.com/tiktokstudio/upload`。
2. 选择/拖入视频，等待上传完成。
3. 右侧表单（与标题、封面、标签同一列，内联，不在折叠的高级设置里）：
   - `Who can see this post` → 隐私下拉
   - `Allow users to:` → 评论 / 内容复用 / AI remix
   - `Post` 按钮
4. 页面可能被包在 `iframe[data-tt="Upload_index_iframe"]` 中；现有代码的 `choose_base_locator()` 已经处理了 iframe 与顶层两种形态，新选择器应继续挂在 `self.locator_base` 下。

### 候选选择器（patchright 风格，与 `main_chrome.py` 一致）

```python
# 可见性
visibility_box = self.locator_base.locator(
    'div[data-e2e="video_visibility_container"]'
)
visibility_trigger = visibility_box.locator(
    'button[role="combobox"], button.TUXSelect-button'
)
current_visibility = (await visibility_trigger.inner_text()).strip()

# 打开后读取选项
options = visibility_box.locator('li[role="option"]')
selected = visibility_box.locator('li[role="option"][aria-selected="true"]')
disabled_options = visibility_box.locator(
    'li[role="option"].TUXSelect-menuOption--disabled'
)

# 互动开关
perm_box = self.locator_base.locator('div[data-e2e="user_perm_container"]')

comment_checkbox = perm_box.locator(
    'label:has-text("Allow comments") input[type="checkbox"], '
    'label:has-text("Comment") input[type="checkbox"]'
).first

reuse_checkbox = perm_box.locator(
    'label:has-text("Allow reuse of content") input[type="checkbox"]'
).first

ai_remix_checkbox = perm_box.locator(
    'label:has-text("Allow AI to remix content") input[type="checkbox"]'
).first

is_comment_allowed = await comment_checkbox.is_checked()
is_comment_disabled = await comment_checkbox.is_disabled()
```

### 选择建议

- **不要按 `nth(0/1/2)` 盲点**：私有账号第一项语义变了，但顺序不变；按语义匹配更安全。
- 第一项匹配文本使用集合：`{"Everyone", "Public", "Followers"}`，再结合账号类型判断。
- `Friends` 选项含副标题 `Followers you follow back`，用 `get_by_role("option", name="Friends", exact=True)` 或先取 `li` 再取首行文本。
- 点击自定义 checkbox 时优先点 `label` 或外层容器，点完必须回读 `input.is_checked()`；`input` 可能被视觉隐藏。
- 置灰判断不要只看 `opacity`；读 `input[disabled]` / `is_disabled()` / option 的 `TUXSelect-menuOption--disabled` class。

---

## 不可用 / 置灰时的表现

| 场景 | 表现 | 证据 |
| --- | --- | --- |
| 私有账号 | 第一项文案变为 `Followers`；`Allow reuse of content` 未勾选且置灰 | 官方前端实现 |
| 账号级评论设为 `No one` | `Allow comments` 保留、未勾选、置灰 | 官方前端实现 |
| 账号级 Reuse 设为 `No one` | `Allow reuse of content` 置灰 | 官方前端实现（中高） |
| 只禁 Duet 或只禁 Stitch | 没有独立控件；统一开关可能仍可用或置灰，页面不直接说明是哪一项 | 仅推断，需实测 |
| 品牌内容 + Only you | `Only you` 置灰；tooltip：`Branded content posts cannot be set to Private.` | 官方前端实现 |
| 地理围栏已选地区 | `Friends`、`Only you` 置灰 | 官方前端实现 |
| U16 / 年龄门控 | 三个可见性选项全部置灰，强制 `Only you` | 官方前端实现 |
| 长视频 | 内容复用开关置灰，提示 key `hint2`（具体文案未取到） | 官方前端实现 |
| 广告授权视频 | 评论开关可能出现额外 tooltip，说明广告主也可控制评论 | 官方前端实现 |

补充：私有账号页面可能还有一行提示（代码 key `hint1`），用于解释为什么 reuse 不可用；**具体英文文案未能确认**。

---

## 可行性结论

### 1. `privacy_level`：可行，但必须做账号类型预检

- 公开账号：
  - `PUBLIC_TO_EVERYONE` → 第 1 项 `Everyone` / `Public`
  - `MUTUAL_FOLLOW_FRIENDS` → 第 2 项 `Friends`
  - `SELF_ONLY` → 第 3 项 `Only you`
- 私有账号：
  - `FOLLOWER_OF_CREATOR` → 第 1 项 `Followers`
  - `MUTUAL_FOLLOW_FRIENDS` → 第 2 项 `Friends`
  - `SELF_ONLY` → 第 3 项 `Only you`
- 预检建议：
  - 打开下拉，读三项文本；第一项是 `Followers` 即私有账号。
  - 私有账号请求 `PUBLIC_TO_EVERYONE` → 直接失败，不发布。
  - 公开账号请求 `FOLLOWER_OF_CREATOR` → 直接失败。
  - 选择后回读 trigger 文本，文本不符 → 视为设置失败，不要继续点 Post。

### 2. `disable_comment`：可行

- `disable_comment=false` → 确保 `Allow comments` 勾选。
- `disable_comment=true` → 取消勾选。
- 若控件已置灰：说明账号级禁止评论，无法通过逐条设置覆盖；应失败或按调用方策略跳过。
- 勾选/取消后回读 `is_checked()`，不要只点一次就认为成功。

### 3. `disable_duet` / `disable_stitch`：只能联合控制，无法独立控制

这是本调研最重要的可行性结论：

- 当前 Studio 主路径只有一个 `Allow reuse of content`，同时控制 Duet、Stitch、Stickers、Story。
- 因此：
  - `disable_duet == disable_stitch`：可精确表达。
    - 两者都 `false` → 勾选 reuse。
    - 两者都 `true` → 取消勾选 reuse。
  - `disable_duet != disable_stitch`：**浏览器 UI 无法表达**。
    - 安全策略：取消勾选 reuse（两项都禁用），并明确告知调用方“合拍/拼接被合并处理”。
    - 严格策略：预检直接失败，要求调用方把两个值改成一致。
- 私有账号：Duet/Stitch 本身就被平台强制禁用，reuse 开关置灰；不要尝试打开。

建议在参数契约中明确写成：

> `disable_duet` 与 `disable_stitch` 在浏览器通道中按“联合开关”处理，二者不一致时拒绝发布（或显式降级为两者都禁用）。

### 4. 设置作用域

- 逐条生效；新上传使用默认值，不继承上一条。
- 草稿会恢复保存时的值。
- 账号级设置是上限，逐条开关不能突破。

### 5. 发布前必须回读

建议 `click_publish()` 之前统一做一次校验：

```python
await self._verify_privacy_settings(
    expected_visibility=...,
    expected_comment=...,
    expected_reuse=...,
)
```

校验失败应抛错并停止发布，避免“页面点了但没生效”导致实际隐私级别与调用方预期不符。这是本 effort 中风险最高的一类静默失败。

---

## 待复核点

1. **线上主路径到底显示 `Everyone` 还是 `Public`**：bundle 同时存在两套组件，需要一次真实登录截图确认。
2. **`Allow reuse of content` 的准确英文文案**：第三方教程与帮助中心一致，但 bundle 里只有 i18n key，未能直接取到 value；需要真实页面确认。
3. **只禁 Duet 或只禁 Stitch 时，统一开关是可用还是置灰**：代码只能证明“没有独立控件”，不能证明统一开关的状态。
4. **关闭 reuse 时提交 payload 的字段**：bundle 中 `allowDuet` / `allowStitch` 仍保持 `true`，只把 `allow_content_reuse` 置 0；服务端是否以 `allow_content_reuse` 为准，需要抓包或发布后回查确认。
5. **`Allow comments` 的 key 回退**：代码写的是 `__("Comment")`，实际解析为 `Allow comments`；若某语言/AB 下回退成 `Comment`，选择器需兼容。
6. **私有账号提示文案（`hint1`）**：未取到具体英文，无法用于断言。
7. **iframe 形态**：当前 bundle 的 2026 开源实现已直接操作顶层页面，但本仓库仍保留 iframe 分支；两种形态都要测。
8. **图片帖**：官方 UX 指南规定图片帖只展示 `Allow comments`，Duet/Stitch 不适用；图片帖路径需单独复核。
9. **AI remix 默认开启**：这是 API 四字段之外的新开关，默认开；是否需要为保持 API 语义而主动关闭，需要产品决策。
10. **本地化**：本仓库约定 Profile 为 English (US)；若未来切中文，所有文本选择器都会失效。

---

## Sources

### 官方文档

1. TikTok for Developers — Query Creator Info（隐私选项集合、comment/duet/stitch disabled 语义）
   https://developers.tiktok.com/doc/content-posting-api-reference-query-creator-info
2. TikTok for Developers — Direct Post（`privacy_level` 枚举、`disable_duet` / `disable_stitch` / `disable_comment` 字段）
   https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
3. TikTok for Developers — Content Sharing Guidelines（第三方 UX 要求：不可用项置灰、评论/合拍/拼接默认不勾选、图片帖只有评论）
   https://developers.tiktok.com/doc/content-sharing-guidelines
4. TikTok Support — Post privacy settings（公开账号 Everyone/Friends/Only you；私有账号 Followers/Friends/Only you）
   https://www.tiktok.com/support/faq_detail?id=7611812700171262475
5. TikTok Support — Comments（逐条 `Allow comments` 开关）
   https://www.tiktok.com/support/faq_detail?id=7636676985892739605
6. TikTok Support — Stitch privacy settings（`Allow reuse of content` 同时影响 Duet/Stitch/Stickers/Story）
   https://www.tiktok.com/support/faq_detail?id=7636676986101864980
7. TikTok Support — Duet privacy settings
   https://www.tiktok.com/support/faq_detail?id=7636670084584512021
8. TikTok Support — Public or private account（私有账号不能 Duet/Stitch）
   https://www.tiktok.com/support/faq_detail?id=7543538137926998533
9. TikTok Support — TikTok Studio（Studio 与 TikTok 共享隐私设置）
   https://www.tiktok.com/support/faq_detail?id=7581820705491229240

### 官方前端实现（静态 bundle，访问日期 2026-11-05）

10. 上传页路由与资源清单
    https://www.tiktok.com/tiktokstudio/upload?lang=en
11. 隐私设置组件（可见性三项、`private_account` 改文案、`disabledVisibilities`、`hiddenVisibilities`）
    https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/static/js/async/6240.60d62a9e.js
12. 互动开关组件（`user_perm_container`、`Comment`、`provideUnifiedToggle_settings_privacy_toggle`、`remixToggle_settings_remix_header`）
    https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/static/js/async/337.cc43c2bc.js
13. 上传表单（内联渲染顺序、老版 `Public`/`Followers` 文案）
    https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/static/js/async/Form.535991d5.js
14. i18n 与 `data-e2e` 常量（`video_visibility_container`、`user_perm_container`、`webCreation_postingPage_visibility_*`）
    https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/static/js/async/9602.bceb34cf.js
15. TUX Select / Checkbox 实现（`role="combobox"`、`role="option"`、`aria-selected`、`TUXSelect-menuOption--disabled`）
    https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/static/js/async/3148.5b452db5.js

### 开源实现

16. `wkaisertexas/tiktok-uploader` — `config.toml`（`data-e2e='video_visibility_container'`、`role=combobox`、旧版 Comment/Duet/Stitch 选择器）
    https://github.com/wkaisertexas/tiktok-uploader/blob/main/src/tiktok_uploader/config.toml
17. `wkaisertexas/tiktok-uploader` — `upload.py`（`_set_visibility` 的 `Everyone/Friends/Only you` 映射、`_set_interactivity`）
    https://github.com/wkaisertexas/tiktok-uploader/blob/main/src/tiktok_uploader/upload.py
18. `wkaisertexas/tiktok-uploader` — `settings.py`（`VisibilityOption = Public / Friends / Private`）
    https://github.com/wkaisertexas/tiktok-uploader/blob/main/src/tiktok_uploader/settings.py

### 第三方教程（用于交叉验证文案，不作为强证据）

19. Metricool — How to Post on TikTok（`Allow reuse of content` 覆盖 Duets、Stitches、stickers、Story）
    https://metricool.com/how-to-post-on-tiktok/
20. 公开教程截图文本（`Allow comments` / `Allow reuse of content` / `Allow AI to remix content` 同屏出现）
    https://www.facebook.com/groups/2722467874525047/posts/25939601862384987/

---

## 一句话结论

`privacy_level` 与 `disable_comment` 可以可靠地用浏览器 UI 表达；`disable_duet` 与 `disable_stitch` 在当前 Studio 已合并为 `Allow reuse of content`，**只能同开同关，无法独立设置**。实现时应把这一点写进参数契约，并在发布前回读可见性与开关状态，避免静默发布成错误的隐私级别。
