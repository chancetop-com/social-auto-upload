# 人类化交互层跨平台落地 — 实施规格

> 状态：**可实施**（2026-11-12 汇总，替代 01–08 各票的重复表述）
> 来源：[`map.md`](./map.md) 与 `issues/01`–`08`、`research/01-inventory.md`、`research/02-portability.md`
> 读者：后续实施会话。本文与 01–08 冲突时，**以本文为准**（本文已吸收全部决议）。
> 本文件只是规格，不含实现。本仓无 `.codegraph/`，实施时按行号 grep 定位。

---

## 0. 一句话

把已在**小红书**验证过的 `utils/humanize.py` 交互层（真实按键、逐字符节奏、贝塞尔指针、`stillOn` 复核、`mouse.down/hold/up`、三类停顿，外加两条禁令）移植到其余 **15 个浏览器上传器**；默认开启，`HUMANIZE=0` 全局退回原生。

---

## 1. 范围与禁令

### 1.1 只搬交互层（范围 = 6 项行为 + 2 条禁令）

| # | 行为 | 实现位置 |
| --- | --- | --- |
| 1 | 真实按键输入（ASCII 走 `keyboard.press`，非 ASCII 走 `insert_text`） | `Humanizer.type_text` / `_dispatch_char` |
| 2 | 逐字符对数正态节奏 | `DEFAULT_PROFILE.keystroke` + `LogNormal` |
| 3 | 贝塞尔指针（内缩随机落点 + 5–9ms/步） | `Humanizer._path` / `_inset_point` |
| 4 | `stillOn` 复核（±1px + 落点命中） | `Humanizer.click` + `utils/dom.check(...,"interactive")` |
| 5 | `mouse.down` → `click_hold` → `mouse.up` | `Humanizer.click` |
| 6 | `before_submit` / `after_type` / `between_scroll` 等停顿 | `Humanizer` 的 pause 方法族 |

两条禁令：

- **禁止 `el.click()` / `evaluate("el => el.click()")`**（JS 合成点击绕过一切真实指针语义）。全仓 15 个平台目标 **0 处**，见 §4.2。
- **坐标点击不接受 `force=True`**。`force` 只保留在 4 条「不走」的原生路径上（2FA ×2、引导层、hidden file input），且每处必须带三字段标记，见 §4.3/§4.4。

### 1.2 明确不做（附理由）

| 不做 | 理由 |
| --- | --- |
| 提交语义：ARM/FIRE/OBSERVE、退出码 `9`/`10`、`publish_attempted`、`utils/blocked.py`、零网络预检、启动日志、失败截图 | 属于 XHS 发布可靠性 effort；本次只换「怎么点/怎么打」，失败契约沿用现状 |
| 身份层：UA / Client Hints、`stealth.min.js`、持久 `user_data_dir`、真实 Chrome `channel`、代理、每账号 fingerprint seed | 身份与行为是两个正交面；混改会让封禁归因不可分，且触犯 XHS 规格 §8.1 禁令 |
| `utils/dom.py` 的其余能力：唯一锚点解析、浮层注册表、Esc 清理、禁止删除节点 | 只携带 `check` / `ensure_in_viewport` 两个函数（含 08 的正确性修复），不引入候选解析体系 |
| 文件选择器（`expect_file_chooser` / `set_input_files`）、`select_option`、`page.evaluate`、剪贴板粘贴 | 原生路径不可坐标化或本就不是输入行为，见 §2.6 |
| 各平台 338 处裸 wait（105 `asyncio.sleep` + 233 `wait_for_timeout`）接预算 | 那是「单一时间源」重构（XHS `53c723f`），与本层是两个提交边界 |
| 限流 / 冷却 / 每日上限 / 熔断 | 与交互真实度无关 |
| 新增 `type_into` 封装 | 已决议：清空策略逐字段手写，见 §2.4 |
| B 站 `biliup` CLI、`myUtils/login.py` 遗留登录、Flask 后端、Vue 前端 | 无浏览器交互层 |
| 托管模式人类化行为**验收** | 本轮无托管账号；08 的视口缺陷按 §2.3 修复，但托管只做离线验证 |

---

## 2. 共享层契约

### 2.1 公开面（不改签名）

```python
Humanizer(page, *, profile=DEFAULT_PROFILE, rng=None, sleep=asyncio.sleep)
```

| 成员 | 语义 | 使用纪律 |
| --- | --- | --- |
| `type_text(text)` | ≤1000 码点逐字符（ASCII `press` / 非 ASCII `insert_text`），>1000 整段 `insert_text`；**末尾恰一次 `after_type`** | 不聚焦、不清空（§2.4） |
| `press(key)` | 单个具名键（`ControlOrMeta+A` / `Delete` / `Enter` / `Space` / `Backspace`），按后采样一次 `keystroke` | 清空与具名键专用 |
| `click(locator, *, point=None)` | 滚入视口 → 贝塞尔移动 → `pointer_settle` → `stillOn` → `down/hold/up`；**内部零重试** | 只能传 `Locator`，`count()==1` |
| `hover(locator, *, point=None)` | 移动 + 停顿，**不按下、无 `stillOn`** | 只为揭出 hover 后才渲染的入口；之后由调用方 `wait_for` 自证 |
| `after_type` / `after_navigate` / `before_submit` / `between_scroll` / `reading` / `after_interact` / `before_click` / `after_click` | 停顿采样点 | 只在语义正确处调用：输入后、导航后、提交点击前、滚动后、阅读/等待时 |

**不变量**（`utils/humanize.py` 模块 docstring 已写，实施时不得破坏）：

1. 内部零重试；重试只发生在调用方的「点后校验状态」循环里。
2. 不存在没有 `stillOn` 的坐标点击。
3. `mouse.down` 之前任何异常 = **确定未派发**（`ElementUnusableError(publish_clicked=False)`）。
4. `mouse.down` 及之后任何异常 = **可能已派发**（异常带 `click_dispatched="maybe"` 后原样上抛）。

### 2.2 实例与生命周期

- **一个 `page` 一个实例**，在该 page 的 `context.new_page()` / `open_upload_page()` 之后立刻构造，并缓存（模式照 XHS `_humanizer(page)`：`cached.page is not page` 即重建）。
- `expect_popup()` / `new_page()` 之后**必须重建**。重建会重置指针到 `(0,0)` 与 RNG（需要可复现时构造传 `rng`）。
- **微博有 2 个实例**：`Humanizer(page)` 只用于 `:508`（首页入口）；`Humanizer(publish_page)` 用于 `:524` 之后全部。其余 14 个平台各 1 个（多 tab 均为只读）。
- **生产构造必须传预算 clamp**（`sleep=`），照 XHS：

```python
async def _humanize_pause(self, seconds: float) -> None:
    remaining = max(0.0, self.publish_budget.remaining_seconds())
    if seconds > remaining and not self._pause_warned:
        logger.warning("人类化停顿被预算裁剪: {}s > {}s", round(seconds, 2), round(remaining, 2))
        self._pause_warned = True
    await asyncio.sleep(min(seconds, remaining))
```

- 预算耗尽时停顿收缩到 **0，不抛**；超时判据仍只在锚点 / 发布点击（`budget.check_pre_click()` / `pre_click_error()`）。
- `enabled` 在构造时快照；`HUMANIZE` 必须在建实例前设置。
- **禁止同一 page 混用原生 `locator.click()` 与 `Humanizer.click`**（`_pointer` 会与库内部位置发散）。该 page 要么全人类化，要么仅剩 §4.3 标记的 `N` 类原生点击。

### 2.3 `HUMANIZE` 环境变量

| 值 | 语义 |
| --- | --- |
| 未设置 / 非 `"0"` | 人类化开启（默认） |
| `"0"`（strip 后） | **语义切换**，不是「同路径去停顿」：文本一次 `insert_text`、点击一次 `locator.click()`、零 `sleep` |

`HUMANIZE=0` 是**唯一回滚开关**（§7.2）。验收必须同时覆盖开启/关闭两条路径——成功集合可能不同。

### 2.4 清空策略（三种手写形态，不新增封装）

`Humanizer` 不提供清空，也不新增 `type_into`。每个文本点按下列三形态之一手写，三选一后**逐字段登记**（§3 的「清空」列）：

| 形态 | 代码 | 适用 |
| --- | --- | --- |
| `sel` 全选覆盖 | `click/focus` → `press("ControlOrMeta+A")` → `press("Delete")` → `type_text` | 默认形态；可整体替换的 `input` / `textarea` / `contenteditable` |
| `seq` 编辑器专用序列 | 保留平台现有手写键序，只把 `keyboard.press` 换成 `humanizer.press` | 已有明确清空序列且真机验证过：抖音（`Control+A`+`Delete`）、快手/大鱼（`Backspace`→`Control+A`→`Delete`）、TikTok（`End`→`ControlOrMeta+A`→`Delete`，macOS 坑注释在 `main_chrome.py:2430` 附近） |
| `none` 不清空 | 只 `click/focus` → `type_text` | ①字段有「非空即拒绝」守卫（雪球 `article.py:153`、知乎 `article.py:103`）；②有意保留预填（大鱼 `article.py:226` `#author`：缺省保留，只有显式传 `author` 才覆盖） |

硬性规则：

1. **清空与输入同属一次交互会话**：`click` 后立即清空再 `type_text`，中间不插其它动作。
2. **预填字段必须 `sel`**：日期/时间控件打开时自带当前值（XHS 真机 2026-11-12 证据）。抖音 `:454`、视频号 `:689` 属此类。
3. **单行字段不得含 `\n` / `\r` / `\t`**：换行会变成 `Enter`（可能提交表单），`\r` 走 `insert_text` 可能被丢弃。多行文本先 `\r\n`→`\n`。
4. **超 1000 码点整段 `insert_text`** 是**有意降级**：>1000 的字段见 §2.7 登记表，不得由平台切段/分片（否则等于第二份阈值）。

### 2.5 共享层前置修复（08 决议，**必须先于 W1 落地**）

三处缺陷全落在已携带的 `check` / `ensure_in_viewport` / `Humanizer.click` 内部，**不引入 dom 其它能力**，charter 原文不改。

#### 2.5.1 item 1 — hover 尺寸漂移：接受，`click` 一行不改

- **不加**重试、**不放宽** ±1px、**不改**事件序列，与 XHS「零内部重试」逐字对齐。
- 真机出现 `point-drift` 的平台 → 在该**调用点**先 `Humanizer.hover()` 再 `click`（XHS `.cover-edit-entry` 模式）。§3 的「前置 hover」列默认「否」，只有真机暴露才改。
- hover 触发浮层遮挡 → `covered-by:*` 硬失败，不重试、不进白名单。

#### 2.5.2 item 2 — 托管视口：尺寸彻底退出判定

`ensure_in_viewport` **不再读 `page.viewport_size`**；删除 `DEFAULT_VIEWPORT_WIDTH/HEIGHT` 与 1280×720 静默兜底。

改为在**元素自己的 frame** 内求「该比例落点是否几何可见」谓词：

```js
(el, point) => {
  const r = el.getBoundingClientRect();
  const x = r.left + r.width * point[0];
  const y = r.top + r.height * point[1];
  if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return false;
  for (let n = el.parentElement; n; n = n.parentElement) {
    const cs = getComputedStyle(n);
    if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') {
      const a = n.getBoundingClientRect();
      if (x < a.left || y < a.top || x > a.right || y > a.bottom) return false;
    }
  }
  return true;
}
```

- `false` → `scroll_into_view_if_needed`（Playwright 负责滚祖先容器与 frame 链），返回 `True` 让调用方 `between_scroll` 并重测 box。
- 求值异常 → **保守判需滚动**，不猜视口。
- 只有落点出**主 frame 视口**才滚是不够的：子 frame 目标还要把落点投影回主 frame，问同一谓词（`elementFromPoint` 非空）。只对 iframe 目标多一次往返。
- 不新增失败 `reason`：`covered-by:unknown` 字符串保留，诊断只进 DEBUG 日志（该文案是 XHS 13 号契约的派生面）。
- **不缓存**可见性结果（窗口尺寸与滚动位置随时变）。
- 测试：改写 `tests/test_xhs_dom.py:756-790` 三条算术用例；新增 `viewport_size=None` 仍正确的反例。

#### 2.5.3 item 3 — 容器裁剪：修，同一谓词两级应用

- 同 frame：视口内 + 逐层 `overflow != visible` 祖先 rect 包含判断（§2.5.2 的 JS 已含）。
- 子 frame：投影回主 frame 再判一次。
- 覆盖 exposure：抖音音乐侧滑面板、antd / Facebook 日历、知乎领域下拉、TikTok 上传 iframe。
- `hover()` 与 `click()` 共用该谓词。

**切分原则（不得违反）**：可见性是几何问题，可以修（滚）；可点性是命中问题，不修（不重试、不猜）。overlay 仍由 `check` 报 `covered-by:*` 硬失败。

> W1 必须重跑小红书真机（05）：共享层修复动的是小红书也在用的函数，其验收是「无回归」的唯一证据。

### 2.6 按设计不做坐标点击（保持原生）

| 类别 | 替代 | 本仓落点 |
| --- | --- | --- |
| `input[type=file]`（含 `opacity:0` 覆盖层） | `set_input_files()` / `expect_file_chooser()` + `set_files()` | 28 处 `set_input_files` + 9 处 file-chooser 点击（§3 标 `N/file`） |
| 原生 `<select>` / `<option>` | `select_option()` | **全仓 0 处 Playwright API**（知乎 `video.py:129/278/279` 是本地终端方法，别去改） |
| `visibility:hidden` / `display:none` 的 JS-only 按钮 | 先 hover 显形；仍 hidden 则**硬失败**，不得 JS 点击 | 抖音 `:686`（§3.4） |
| 零尺寸 / `display:contents` / `opacity:0` 捕手 | 点溢出子元素或可见父级 | §4.4 |
| shadow DOM 内部（closed） | 点 host / 不改造 | YouTube 见 §9 未验证 |
| `<area>` / 原生浏览器 UI / 拖拽目标 | 保持原生 | 大鱼 UEditor 选区拖拽（`article.py:166-167`） |

### 2.7 长期退化与限制（显式接受）

1. **>1000 码点整段 `insert_text`**：零 `keydown`、零采样、一条 info。阈值按 **Python 码点**（`len`），≈143 个 ZWJ emoji 即越线。逐字段登记：

| 平台 | 字段 | 调用点 |
| --- | --- | --- |
| 支付宝 | 作品描述 | `alipay_uploader/main.py:457` |
| 大鱼 | 视频简介 | `dayu_uploader/main.py:157` |
| 抖音 | 作品描述 | `douyin_uploader/main.py:477` |
| 虎扑 | 简介 | `hupu_uploader/main.py:556` |
| 快手 | 视频描述 / 图文正文 | `ks_uploader/main.py:798`、`:971` |
| Facebook | 正文 | `facebook_uploader/main.py:347` |
| Facebook Page | 正文 | `facebook_page_uploader/main.py:332` |
| Instagram | 配文 | `insgraph_uploader/main.py:799` |
| 视频号 | 视频描述（同一编辑器两次） | `tencent_uploader/main.py:865`、`:874` |
| 微博 | 正文 | `weibo_uploader/main.py:761` |
| TikTok | 配文 | `tk_uploader/main_chrome.py:2441` |
| YouTube | 标题/简介 | `youtube_uploader/main.py:249` |
| 知乎 | 视频介绍 | `zhihu_uploader/video.py:177` |
| 百家号 | 无长正文字段 | — |

2. **阈值唯一**：`type_horizon_chars = 1000` 全局唯一（`humanize.py:96`）；生产代码出现第二个字面量即违规（`tests/test_humanize.py:680-690` 已锁）。
3. **per-call 累积成本**：多个 <1000 字段可叠加吃光 15 分钟预算。最坏 = IG carousel alt text（`controls/alt_text.py:224` 逐张）。后果：点击前 exit 1（不发布），缓解只有 `HUMANIZE=0`。
4. **`insert_text` 不是按键**：中文/emoji 只有 `beforeinput`/`input`，无 `keydown`、无 IME composition。依赖 `keydown` 计数的编辑器会认为「没输入」。
5. **ASCII 走 US 布局**：大写字符的 `shiftKey` 为假（字符与 `event.code` 正确）。
6. **指针从 `(0,0)` 起步**：每实例第一段路径从左上看起，可能横穿导航栏触发 hover。
7. **无 OS 级指针**：事件 `isTrusted=true`，但系统光标不动；本 effort 不承诺反检测。
8. **`hover` 无 `stillOn`**；**`type_text("")` 仍付 `after_type`**；`press()` 不看 `enabled`，`HUMANIZE=0` 时仍按键只是不睡。
9. **托管模式**：motion 路径一致，但视口可观测性由 §2.5.2 修补；本轮**只做离线验证**（§9）。

---

## 3. 每平台实施表

### 3.0 记号与通用要求

**处置码**

| 码 | 含义 |
| --- | --- |
| `T/sel` / `T/seq` / `T/none` / `T/guard` / `T/wait` | 改 `Humanizer` 文本输入 + 对应清空形态（§2.4）；`T/wait` = 逐字 + 有界等待候选 + 文本全等点选 |
| `H` | `humanizer.click(locator)` |
| `H+nav` / `H+sub` | `H` 之后 / 之前加 `after_navigate` / `before_submit` |
| `H(pt)` | 带比例落点 `point=(x,y)` |
| `Hover` | `humanizer.hover(locator)` |
| `N/<类>` | **保持原生** `.click()`；类 = `login` / `file` / `focus`（失焦/聚焦专用）/ `manage`（删除·管理·核对）/ `read` / `verify`（2FA）/ `chrome`（引导层·浮层·关闭提示）/ `language` |
| `X` | 删除该调用 / 分支 / 函数 |
| `M→N` | 合并到第 N 行（点后不再单独计数） |

**所有 `N/*` 行必须在同一行加标记**：`# native-click: <类>；<一句话原因>`（§4.3 的门强制）。`X` 删除的行不留标记。

**通用要求**：①每个文本点先收窄到 `count()==1`（多义硬错，不自动 `.first`）；②`T/*` 结束即一次 `after_type`；③发布/提交点加 `before_submit`，导航点加 `after_navigate`；④不改任何固定 `sleep`（04：0 删 1 增）；⑤每平台一个 `Humanizer`（微博 2 个，见各节）。

对账：01 的 371 个交互点 → 改 Humanizer **246**、保持原生 **54**、待定 **45**（本规格已把 45 全部落到具体处置）。逐平台计数见 05 §A。

---

### 3.1 支付宝 `uploader/alipay_uploader/main.py`

`Humanizer` 构造：`session.context.new_page()`（`:824`）之后。
页面：单 page。输入 2、改 9、删除 1、原生 2、`set_input_files` 2。

| 行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| :450 | `T/sel` | 标题（+`#话题`，≤30）`input` |
| :457 | `T/sel` | 作品描述 `textarea`；>1000 走 bulk |
| :204 | `N/login` | 扫码 tab（iframe 内，登录路径） |
| :433 | `H+nav` | 「发布视频」入口 → SPA 路由 |
| :467 | `H` | 「上传封面」弹窗 |
| :475 | `H` | 弹窗内图片上传区 |
| :481 | `N/file` | 展开上传区（与 `:487` `set_input_files` 成对） |
| :495 | `H` | 「完 成」 |
| :513 | `H` | 合集下拉；先 `.first` 收窄两个候选分支 |
| :521 | `X` | 删 force 首选（03） |
| :524 | `H` | 合集项（承接 :521，合并为一次） |
| :697 | `H` | 质量提示「继续发布」 |
| :712 | `H+sub` | 发布 |
| :748 | `H+sub` | AIGC 后二次确认发布 |
| :443/:487 | `N/file` | `set_input_files`（视频 / 封面），不改 |

---

### 3.2 百家号 `uploader/baijiahao_uploader/main.py`

构造：`:446` 之后。单 page。输入 2、改 8、原生 2、`set_input_files` 2。

| 行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| :503 | `M→506` | 聚焦标题 |
| :506 | `T/seq` | 标题 `contenteditable`；**保留现有「点标题 → Ctrl+A → Backspace」**（`:503-505`），键改 `humanizer.press`；页面可能自动填文件名 |
| :698 | `T/wait` | 合集搜索：逐字 → 有界等待 `.cheetah-select` 候选 → 按合集名**全等**；`.first` 仅降级（07 §3） |
| :201 | `N/login` | 百度 passport |
| :584 | `H` | 「选择封面」 |
| :593 | `N/file` | 切「上传」tab（与 `set_input_files` 成对） |
| :615 | `H` | 裁剪「确定/完成/确认」 |
| :641 | `H` | 创作声明：**改点组件本体**（antd 装饰层可命中，03 §2.2），删 force |
| :649 | `H` | 「含AI生成内容」 |
| :657 | `H` | 关闭声明弹窗 |
| :692 | `H` | 合集下拉 |
| :704 | `H` | 合集项（精确匹配） |
| :753 | `H+sub` | 发布；遮挡走 07 清浮层，**不加 force** |
| :466/:602 | `N/file` | `set_input_files`，不改 |

---

### 3.3 大鱼号 `uploader/dayu_uploader/`

构造：`main.py:239`（视频）/ `article.py:303`（图文）之后。单主 page；`publication.py:64` 预览 tab 只读，不建实例。
视频 `main.py`：输入 4、点击 5、`set_input_files` 2。图文 `article.py`：输入 3、点击 12、`set_input_files` 1。定时 `schedule.py`：7。发表 `publication.py`：2。

| 文件:行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| `main.py:153` | `T/guard` | 视频标题 `contenteditable`；**默认值未知**（§9），清空前先读空；`fill` 语义是整体替换 |
| `main.py:157` | `T/sel` | 视频简介 `textarea`；>1000 bulk |
| `main.py:173` | `T/sel`+Enter | 标签第 N 空槽；逐字后 `press("Enter")`；`after_type` 与 2s 标签等待叠加需核预算 |
| `main.py:199` | `T/sel` | 原文链接（转载时） |
| `main.py:162` | `H` | 视频分类下拉 |
| `main.py:163` | `H` | 选分类 |
| `main.py:168` | `H` | 聚焦标签组件（可能 0×0 → 硬失败，不回退） |
| `main.py:175` | `N/focus` | 失焦标签组件（Vue 归并） |
| `main.py:185` | `H` | 封面裁剪「保存」 |
| `article.py:141` | `H` | 聚焦 iframe 内正文（粘贴保持原生） |
| `article.py:147` | `N/focus` | 失焦正文 |
| `article.py:171` | `H` | 工具栏「分隔线」（小目标，落点 ±8px 内缩） |
| `article.py:175` | `H` | 工具栏「插入图片」 |
| `article.py:186` | `H` | 确认插图 |
| `article.py:195` | `N/focus` | 失焦正文 |
| `article.py:200` | `N/focus` | 失焦正文 |
| `article.py:223` | `T/guard` | 图文标题；可能恢复草稿（§9），先读空 |
| `article.py:226` | `T/none` | 作者：**缺省保留页面值**；只有显式 `author` 才覆盖 |
| `article.py:239` | `T/sel` | 原文链接 |
| `article.py:247` | `H` | 封面模式 `.w-radio` |
| `article.py:253` | `H` | 第 N 封面槽 |
| `article.py:257` | `H` | 选正文第 N 张图 |
| `article.py:259` | `H` | 裁剪「下一步」 |
| `article.py:261` | `H` | 「保存」 |
| `schedule.py:65/:74` | `H` | 定时开关（幂等，保留状态读回） |
| `schedule.py:77` | `H` | 日期遮罩（input 被 mask 拦截，必须点 mask） |
| `schedule.py:86/:90/:93/:97` | `H` | 下月 / 日 / 时 / 分 |
| `publication.py:42` | `H+sub` | 「发表」 |
| `publication.py:101` | `H+sub` | 「确认发表」（保留 `expect_response` 包裹） |
| `main.py:181/:251`、`article.py:180` | `N/file` | `set_input_files`，不改 |

---

### 3.4 抖音 `uploader/douyin_uploader/main.py`

构造：`:1099`（视频）/ `:1425`（图文）之后，各自一个实例。单 page。输入 9、点击 28、原生 6、删除 4、hover 1、`set_input_files` 5。

| 行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| :465 | `T/sel` | 作品标题（≤30） |
| :477 | `T/seq` | 作品描述；保留现有 `Control+A`+`Delete`（`:471-476`），键改 `humanizer.press`；>1000 bulk |
| :480 | `T/seq` | 话题：`type_text(" #" + tag)` 逐字 → `press("Space")` 触发联想；不做整段插入 |
| :490 | `T/wait` | 地点：逐字 → 等联想 → 精确匹配（07 §3） |
| :454 | `T/sel` | 定时时间：picker 预填当前值，**必须先全选**；`type_text` 后 `Enter` |
| :503 | `T/sel` | 商品短标题（≤10） |
| :539 | `T/wait` | 商品链接：链接校验，逐字后等一次校验结果 |
| :662 | `T/wait` | 配乐搜索：逐字 → 有界等待 → 精确匹配 |
| :839 | `N/verify` | 短信验证码输入（2FA 路径，`# native-fill` 唯一例外） |
| :935 | `Hover` | 封面区：揭出「编辑/选择封面」（去 force） |
| :105/:114 | `X` | 删除整个 `_native_click`（含合成事件重放，07 §4） |
| :337 | `N/login` | 二维码失效刷新 |
| :447 | `H` | 切「定时发布」 |
| :452 | `H` | 打开日期时间 picker |
| :471 | `M→477` | 聚焦描述（合并） |
| :487 | `H` | 打开地点下拉 |
| :492 | `H` | 地点候选（精确匹配） |
| :508/:516/:519 | `H` | 商品弹窗完成 / 取消 / 关闭 |
| :532/:534 | `H` | 添加标签下拉 / 选「购物车」 |
| :547 | `H` | 添加链接（保留 disabled 前置校验） |
| :554 | `H` | 无效商品「确定」 |
| :598 | `H` | 自主声明入口（5 候选文案先收窄为 1） |
| :620 | `H` | 选声明类型 |
| :624 | `X` | 删 `count()==0` 死分支（03） |
| :634 | `H` | 声明「确定」 |
| :655 | `H` | 选择音乐侧栏 |
| :686 | `Hover`+`H` | BGM「使用」按钮 `visibility:hidden`：**先 hover 卡片使其显形再点**；仍 hidden → 硬失败，**不得回退 `el.click`**（02 §6.3） |
| :708 | `H` | 关闭音乐侧栏 |
| :806/:824 | `H` | 合集下拉 / 合集项（精确标题） |
| :838 | `N/verify` | 聚焦验证码输入 |
| :846/:854 | `N/verify` + force | 短信验证（保留 force + 三字段标记；两处合并） |
| :849 | `X` | 删除 2FA 的 JS 第三级兜底 |
| :890/:895 | `H` | 推荐封面 / 确认 |
| :978/:987 | `H` | 竖 / 横封面页签 |
| :1020 | `H` | 封面「完成」（保留 4 次循环 + detach 状态校验） |
| :1197 | `H` | 第三方同步开关：**改点 `.semi-switch` 可见装饰层**（原生 input 0 尺寸） |
| :1227 | `N/verify` | 获取验证码 |
| :1241 | `H+sub` | 视频发布 |
| :1328 | `H+nav` | 切图文发布页 |
| :1377 | `H+sub` | 图文发布 |
| :881/:982/:991/:1132/:1332 | `N/file` | `set_input_files`，不改 |

> `_native_click` 删除后，8 个调用点（`:600/:622/:636/:809/:826/:949/:1028/:1038`）改 `humanizer.click`，`try/except` 兜底结构与状态谓词全保留；兜底动作从「强点击」改为「按既有循环重试 / 降级跳过」。带 `MAYBE_DISPATCHED` 的异常**不得**再派发。

---

### 3.5 虎扑 `uploader/hupu_uploader/main.py`

构造：`:483` 之后。单 page。输入 2、改 10、原生 3（其中 file 2）。

| 行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| :538 | `T/sel` | 标题（4–40） |
| :556 | `T/sel` | 简介（正文 + `#tag#`）；>1000 bulk |
| :537/:555 | `M` | 聚焦标题 / 简介（并入 :538 / :556） |
| :240 | `N/login` | QQ 登录 |
| :520/:567 | `N/file` | 视频 / 封面（`expect_file_chooser` 配对） |
| :582 | `H` | 「添加专区」 |
| :588/:593 | `H` | 步行街 / 主干道 |
| :598 | `H` | 「确 定」 |
| :610 | `H` | 「原创/二创」 |
| :620 | `H` | AI 声明下拉；**先把裸 `get_by_role("combobox")` 收窄为 1** |
| :625 | `H` | 「含AI生成内容」 |
| :645 | `H+sub` | 「确定发布」 |

---

### 3.6 快手 `uploader/ks_uploader/main.py`

构造：`:760`（视频）/ `:1081`（图文）之后，各自一个。单 page。输入 4、点击 13、原生 8、`set_input_files` 3。

| 行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| :798 | `T/seq` | 视频描述；保留 `Backspace`→`Control+A`→`Delete`（`:795-797`）；>1000 bulk |
| :803 | `T/seq` | 话题（≤3 个），逐字 + 空格 |
| :971 | `T/seq` | 图文正文；同上 |
| :976 | `T/seq` | 图文话题 |
| :110 | `H` | 描述聚焦：正常策略 #0 走 `H`；**回退分支删 force，让 `zero-box` 直接失败**（03 §2.3） |
| :133 | `H` | 发布确认弹窗主动作 |
| :267/:272/:443 | `N/login` | 二维码登录 / 刷新 |
| :524 | `H` | 切「定时发布」 |
| :528 | `H` | 打开日期 picker；**日期值仍由 JS setter 写入**（`:530+`），不进入本层 |
| :582 | `N/chrome` + force | 关 Joyride 引导层（保留 force + 标记；非正常路径） |
| :661/:673 | `H` | 合集下拉 / 合集项 |
| :703 | `H` | 封面设置：先收窄到具体 `div`（无文本，需真机确认命中区，§9） |
| :710/:719 | `H` | 上传封面 tab / 确认 |
| :776/:953 | `N/file` | 视频 / 图文上传 |
| :785/:960 | `N/chrome` | 「我知道了」notice（每条都加停顿不划算） |
| :866 | `H+sub` | 视频发布（随后 :133 确认） |
| :945 | `H+nav` | 切图文 tab |
| :1026 | `H+sub` | 图文发布 |
| :1031 | `H` | 发布后确认 |
| :693/:714/:994 | `N/file` | `set_input_files`，不改 |

---

### 3.7 Facebook `uploader/meta_uploader/facebook_uploader/`

构造：`main.py:198` 之后。单 page。输入 1、改 2、原生 6、`set_input_files` 1。

| 文件:行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| `main.py:347` | `T/sel` | 正文（title+desc+tags，`\n\n` 连接）；>1000 bulk；`after_type` 后读回校验 |
| `main.py:346` | `M→347` | 聚焦正文 |
| `main.py:312` | `H+sub` | 发布 |
| `main.py:100/:103/:107` | `N/manage` | 删除路径（更多选项 / 移至垃圾箱 / 确认） |
| `main.py:175/:176/:179` | `N/manage` | 行内删除路径 |
| `main.py:337` | `N/file` | `set_input_files`，不改 |

---

### 3.8 Facebook Page `uploader/meta_uploader/facebook_page_uploader/main.py`

构造：`:543` 之后。单 page。输入 2、改 12、原生 8（含 file 1）。

| 行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| :321 | `T/sel` | Reel 独立标题 |
| :332 | `T/sel` | 正文；>1000 bulk |
| :275/:279 | `H` | 发布主体下拉 / 选 Page |
| :301 | `N/file` | 媒体选择器 |
| :350 | `H` | Reel「下一步」×2 |
| :357 | `H` | 「同时发快拍」开关（先读 checked，再点） |
| :365 | `H` | 快拍弹窗主动作；**先把 `.nth(2)` 改为按文本/aria 收窄** |
| :381 | `H` | 切「定时」；先按文本收窄（`aria-pressed` 顺序会漂） |
| :389/:406/:413 | `H` | 日历 / 上下一月 / 日 |
| :419 | `H` | 小时·分钟 spinbutton；后续 `press(digit)` 已逐键，保留 |
| :465 | `H+sub` | 发布 |
| :499 | `H` | Reel 完成框关闭；先收窄（`.last` 不稳） |
| :106 | `N/chrome` | 引导说明卡（每条都加停顿不划算） |
| :42 | `N/manage` | 列表进详情 |
| :105/:111/:115/:118/:126 | `N/manage` | 删除路径 |

---

### 3.9 Instagram `uploader/meta_uploader/insgraph_uploader/`

构造：`main.py:946` 之后。单 page。输入 3 + `press_sequentially` 1、改 9、原生 1、删除 2、`set_input_files` 2。

| 文件:行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| `main.py:799` | `T/sel` | 配文（Lexical）；>1000 bulk；`after_type` 后读回；Lexical 对逐字敏感需真机 |
| `controls/location.py:190` | `T/none` | 清空动作改为 `press("ControlOrMeta+A")`+`press("Backspace")`，不再 `fill('')` |
| `controls/location.py:191` | `T/wait` | 地点逐字；**节奏不得快于 `TYPE_DELAY_MS`**，逐字符后等 debounce |
| `controls/alt_text.py:224` | `T/sel` | Alt text（逐张 ≤1000）；清空必须显式全选；`:226` 的 blur 保留 |
| `main.py:142` | `H` | 关可选提示（1.5s 窗口；坐标点击更慢，需核预算） |
| `main.py:546` | `H` | 打开「创建」 |
| `main.py:631` | `H` | 裁剪「下一步」 |
| `main.py:842` | `H+sub` | 分享（必须在响应监听之后） |
| `main.py:89` | `N/manage` | 作品更多选项 |
| `controls/_rows.py:106` | `H` | `activate`：保留 keyboard 优先（focus+Enter），最后一级换 `H` |
| `controls/_rows.py:110` | `X` | 删除 `el.click()` 兜底 |
| `controls/_rows.py:121` | `H` | `click_control`：`H` 优先 |
| `controls/_rows.py:130` | `X` | 删除 `el.click()` 兜底 |
| `controls/location.py:241` | `H` | 地点候选：**ElementHandle → Locator**（联想只响应真实指针） |
| `main.py:568/:601` | `N/file` | `set_input_files`，不改 |

> 公共 helper 是 IG 的移植底座：`activate` / `click_control` 必须先改，否则每个调用点自带一条 JS 后路。

---

### 3.10 视频号 `uploader/tencent_uploader/main.py`

构造：`:1311` / `:1445` 之后。单 page。输入 5、点击 27、原生 7、删除 1、`set_input_files` 2。

| 行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| :830 | `T/sel` | 短标题（7–15 字）`input` |
| :865 | `T/guard` | 视频描述 `div.input-editor`；**默认值未知**（§9），先确认再定清空；>1000 bulk |
| :868 | `T/guard` | 话题：`type_text("#"+tag)` + `press("Space")` |
| :874 | `T/guard` | 描述正文追加（同一编辑器，`fill_title_and_tags` 之后） |
| :689 | `T/sel` | 定时小时：picker 预填，先全选；`type_text` 后 `Enter` |
| :424/:442/:444/:451 | `N/login` | 二维码刷新链路 |
| :670 | `H` | 切「定时」；先把 `.nth(1)` 收窄为 1 |
| :671/:676/:687 | `H` | 日期面板 / 下月 / 时间下拉；**`page.click(selector)` 必须先改 `page.locator(selector)`** |
| :684 | `H` | 选日；`query_selector_all` 的 `ElementHandle` **必须先换 Locator** |
| :694 | `N/focus` | 收时间浮层（点描述区；失败已有 Escape 兜底） |
| :741 | `H+nav` | 首页「发表视频」 |
| :794 | `H` | 「发表视频」按钮；**删 force**（候选已 `is_visible()`） |
| :843 | `H` | 关「切换视频号」弹窗（2s 超时放宽） |
| :858/:864 | `H` | 聚焦描述（4 次重试语义保留；与 :865 合并） |
| :891/:915 | `H` | 合集下拉 / 合集项（精确 `.name`） |
| :918 | `H` | 合集项；**删 force**（headless 视口问题由 §2.5.2 解） |
| :940/:944 | `H` | 视频标注 / 「含AI生成内容」 |
| :1074 | `H+sub` | 发表（保留 20 轮状态重试） |
| :1076 | `X` | 删除 JS 兜底；失败即 `ElementUnusable` |
| :1162/:1163 | `N/manage` | 失败素材删除（错误重传路径） |
| :1173/:1197/:1213 | `H` | 封面弹窗 / 裁剪确认 / 保存 |
| :814/:1206 | `N/file` | `set_input_files`，不改 |

---

### 3.11 微博 `uploader/weibo_uploader/main.py`

**两个实例**：`Humanizer(page)` 只给 `:508`；`Humanizer(publish_page)` 给 `:524` 之后全部（`expect_popup()` 在 `:503-515`）。
输入 3、改 15、原生 1、删除 3、`set_input_files` 1。

| 行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| :508 | `H+nav`（首页实例） | 「视频」入口 → popup |
| :583 | `T/sel` | 标题（≤30） |
| :761 | `T/sel` | 描述（正文 + `#tag#`）；>1000 bulk |
| :872 | `T/sel` | 新建合集名（≤12） |
| :524 | `N/file` | 上传视频 |
| :582 | `M→583` | 聚焦标题 |
| :603 | `H` | 「编辑封面」层 |
| :657 | `H` | 封面「完成」：**改为「点一次 + 等状态」**，不许 4s 周期重复点 |
| :682 | `H` | 类型「二创」 |
| :711/:726/:738 | `H` | 声明下拉 / AI 选项 / 确定 |
| :760 | `M→761` | 聚焦描述 |
| :792 | `H` | 合集开关（点 `span[role=switch]`） |
| :795 | `X` | 删 force，合并到 :792（03 §7） |
| :829 | `H` | 勾选已有合集 |
| :855 | `H` | 「＋新建合集」 |
| :858 | `X` | 删 force，改点行内文字 `span` |
| :861 | `X` | 删除 `el.click()`，合并到 :858 的文字 span |
| :871 | `M→872` | 聚焦新建合集输入 |
| :912 | `H(0.65,0.5)` | 发布；失败且 `publish_clicked=False` 时换 `(0.35,0.5)` 再试一次；仍失败抛 `ElementUnusable`，**不退回 JS、不加 force**（07 §1） |
| :941 | `H` | 二次确认对话框（确定/继续/仍然发布） |
| :614 | `N/file` | `set_input_files`；必须 `.first`（`.last` 是隐藏裁切器） |

---

### 3.12 TikTok `uploader/tk_uploader/main_chrome.py`

构造：`:982` / `:1074` / `:1180` 之后。单 page，但 **`locator_base` 可能是 `frame_locator`**——`Humanizer(page)` 收 `page`，**绝不把 `locator_base` 当 page**。
输入 3、点击 30、原生 8、删除 3、`set_input_files` 2。

| 行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| :3242 | `T/sel` | 图片帖 Title |
| :2441 | `T/seq` | 配文 Draft.js；保留 `End`→`ControlOrMeta+A`→`Delete`（macOS 坑注释）；>1000 bulk；**≤1000 变逐字**是本平台主要变化 |
| :2338 | `T/seq` | 话题：改**逐字** `type_text("#"+tag)` → 等候选 → 按文本全等点选（同 XHS/YouTube）；失败保留纯文本 + 关联想 |
| :460 | `H` | `TiktokOptionControl.click` 公共底座（一处覆盖多个选项） |
| :462 | `X` | 删 force，**改点 label 本体**（03 §2.2） |
| :540/:673/:721/:759/:789 | `H` | 其它控件抽象 / toggle / switch / 隐私菜单 / 选项 |
| :1219/:1220/:1223 | `N/language` | 界面语言初始化（非用户内容） |
| :1440/:1479 | `H` | AIGC 开关 / 确认 |
| :1867/:1883/:1892 | `H` | Show more / 高级设置 |
| :2003 | `H` | 定时 radio；**删 force**，保留「重复点幂等」写法（React checked 陈旧） |
| :2032 | `H` | 首次定时 Allow |
| :2039/:2061/:2065/:2074/:2084 | `H` | 日期选择器 / 上下月 / 日（两套） |
| :2100/:2104/:2113/:2121 | `H` | 时间下拉 / 时 / 分（两套） |
| :2254 | `N/chrome` | 「automatic content checks」弹窗（每次编辑前都调，加停顿不划算） |
| :2277 | `N/chrome` | Joyride 遮罩（非用户控件） |
| :2294 | `M→2441` | 聚焦配文编辑器（8 次重试保留） |
| :2382 | `H` | 话题候选（精确首行文本；候选常重排，`stillOn` 关键） |
| :2387 | `X` | 删 force（Enter 为首选） |
| :2390 | `X` | 删 JS 兜底（Enter → H → 失败） |
| :2586 | `H+sub` | 发布 |
| :2669 | `H` | 发布后确认（可选兜底，失败不改退出码） |
| :2792/:2821 | `N/file` | 首次 / 重试视频上传 |
| :2856/:2866/:2973 | `H` | 封面编辑 / Upload cover / 保存 |
| :2904 | `N/file` + force | hidden file input 兜底（保留 force + 标记） |
| :3186/:3199 | `H+nav` | 切 Photos tab（两套选择器） |
| :2899/:3225 | `N/file` | `set_input_files`，不改 |

---

### 3.13 雪球 `uploader/xueqiu_uploader/`

构造：`article.py:271` 之后。单主 page；`:335` 核对 tab 与 `verification.py` 只读，不建实例。
输入 1、改 8、原生 3（含 1 只读）。

| 文件:行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| `article.py:155` | `T/guard` | 文章标题：**已有「非空即拒绝」守卫**（`:153`），清空 = `none`；这是全仓清空策略的样板 |
| `article.py:101` | `H` | 聚焦正文（粘贴 HTML 保持原生） |
| `article.py:104` | `N/focus` | 失焦正文触发保存 |
| `article.py:127` | `H` | 工具栏「上传图片」 |
| `article.py:141` | `N/focus` | 失焦等自动保存 |
| `article.py:173` | `H` | 确认裁剪 |
| `article.py:186` | `H` | 分享范围 / 创作声明下拉（先读状态） |
| `article.py:190` | `H` | 下拉项（精确文本） |
| `article.py:194` | `H` | 「预览」 |
| `article.py:290` | `H` | 关闭预览遮罩（注释说明不可删遮罩/强点，坐标点击正合适） |
| `article.py:316` | `H+sub` | 发布 |
| `verification.py:59` | `N/read` | 发布后内容管理核对（独立只读 path） |
| `article.py:164` | `N/file` | `set_input_files`，不改 |

---

### 3.14 YouTube `uploader/youtube_uploader/main.py`

构造：`:363` 之后。单 page。输入 2、点击 4（+helper）、原生 0、`set_input_files` 2。

| 行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| :249 | `T/sel` + `T/wait` | 标题/简介 `contenteditable`：**改为逐字**（含 `#`）；每段 `#tag` 后等 `tp-yt-iron-dropdown` → 在 `ytcp-hashtag-autocomplete` 内按文本**全等**点选；匹配失败保留纯文本 + `_dismiss_autocomplete`，继续流程（07 §2）；>1000 仍 bulk |
| :245 | `M→249` | 聚焦富文本 |
| :251 | `X` | 删除 `type(delay=6)` 提退路径（`type_text` 已覆盖） |
| :260 | `H` | `_click_if_present(selector)`：**签名加 `humanizer`**，20+ 调用点统一走 `H`，保留「可缺席」语义（`ElementMissing` → 返回 False） |
| :426 | `H` | 勾选已有播放列表 |
| :433 | `T/sel` | 新建播放列表名 |
| :434 | `X` | 删除 `type(delay=6)`（并入 :433） |
| :453 | `T/sel` | 标签输入；默认值未知（§9） |
| :454 | `X` | 删除 `type(delay=4)`（并入 :453） |
| :385/:410 | `N/file` | 视频 / 缩略图 `set_input_files`，不改 |

> `_fill_editable` 的 docstring 必须改写：原文「不要逐字输入」的结论作废，改为记录新路径与降级条件。

---

### 3.15 知乎 `uploader/zhihu_uploader/`

构造：`video.py:255` / `article.py:264` 之后。单主 page；`:311` 详情 tab 只读。
视频 `video.py`：输入 2、改 11、原生 1。文章 `article.py`：输入 1、改 2、原生 2。定时 `schedule.py`：16。`set_input_files` 2。

| 文件:行 | 处置 | 目标 / 说明 |
| --- | --- | --- |
| `video.py:173` | `T/sel` | 视频标题（`textarea`） |
| `video.py:177` | `T/sel` | 视频介绍 `contenteditable`；>1000 bulk |
| `video.py:108/:115` | `H` | 打开 / 关闭「所属领域」（读候选） |
| `video.py:117/:123` | `H` | 打开 / 取消视频标记弹窗 |
| `video.py:149/:150` | `H` | 领域下拉 / 选领域（精确） |
| `video.py:153/:155/:156` | `H` | 标记弹窗 / 选标记 / 确认 |
| `video.py:191` | `H` | 原创 checkbox（先读 `is_checked` 再点，幂等） |
| `video.py:302` | `H+sub` | 视频发布 |
| `video.py:312` | `N/read` | 发布后「查看详情」tab |
| `article.py:103` | `T/guard` | 文章标题：已有非空守卫，清空 = `none` |
| `article.py:119` | `H` | 聚焦正文（粘贴 HTML 保持原生） |
| `article.py:121/:168` | `N/focus` | 失焦正文 |
| `article.py:291` | `H+sub` | 文章发布 |
| `schedule.py:36` | `H` | 切「定时发布」 |
| `schedule.py:45/:52/:58/:64/:69/:70/:75/:80` | `H` | 日期 / 下月 / 日 / 时 / 分 / 确认（文章） |
| `schedule.py:102/:108/:114/:118/:123/:124/:129` | `H` | 同上（视频） |
| `video.py:266`、`article.py:159` | `N/file` | `set_input_files`，不改 |

> 知乎 `video.py:129/278/279` 的 `select_option` 是**本地终端交互方法**，不是 Playwright API，别改。

---

## 4. 禁止项与静态门

### 4.1 禁止项（行为层）

1. 任何 `el.click()` / `page.eval_on_selector(..., "el => el.click()")` / `locator.evaluate("el => el.click()")`。
2. 任何坐标点击上的 `force=True`（白名单外）。
3. 任何用户输入文本走 `fill()` / `press_sequentially()` / 剪贴板粘贴（多行正文的粘贴路径除外，且不属本层）。
4. 任何 `Humanizer.click` 收到 `ElementHandle`、裸选择器、`page.click(selector)`。
5. 任何平台复制 `DEFAULT_PROFILE` / `type_horizon_chars` 的第二份定义。
6. 任何在同一 page 上混用原生 `locator.click()` 与 `Humanizer.click`。
7. 任何「人类化失败 → 自动降级原生」的运行时兜底；任何把 `force` 当回滚网。

### 4.2 门 A：JS 点击归零

扫描 15 个平台目录（`uploader/{alipay,baijiahao,dayu,douyin,hupu,ks,meta_uploader,tencent,tk,weibo,xueqiu,youtube,zhihu}_*/**/*.py`）：

```
AST：Call(func=Attribute(attr in {"evaluate","eval_on_selector"}))
     且任一 Constant(str) 参数含 "el.click" 或 ".click()" → fail(file:line)
```

**期望 0 命中**。9 处现存点位的去向见 §3（抖音 :686/:849、IG `_rows.py:110/:130`、视频号 :1076、TikTok :2390、微博 :861/:912/:941）。

### 4.3 门 B：原生点击必须自证

```
AST：Call(func=Attribute(attr=="click"))
     且 receiver 不是 humanizer（名字不含 "humanizer"）
     → 该调用的 [lineno, end_lineno] 内必须有 `# native-click: <类>；<原因>`
```

类只允许：`login` / `file` / `focus` / `manage` / `read` / `verify` / `chrome` / `language`。缺标记即 fail。

这条是 05「可见目标的裸 `.click(` 归零」的可执行形式：**内容交互零原生；UI 外壳与范围外路径逐条登记**。§3 的 54 个 `N/*` 行就是登记册。

### 4.4 门 C：`force=True` 标记门（03）

```
AST：Call 有 keyword(arg=="force", value=Constant(True))
     → [lineno, end_lineno] 内必须有
       `# humanize-impossible: <失败模式>；<code|inferred|needs-live>；<已排除替代>`
```

不锁位置、不锁数量、不要求归零。**唯一合法残余 4 条**：`douyin:846/:854`（2FA）、`ks:582`（引导层）、`tk:2904`（hidden file input）。前三者是「不走」的原生路径，不是白名单扩容。

### 4.5 门 D：`fill(` 归零（1 条例外）

```
AST：Call(func=Attribute(attr=="fill")) → 必须有 `# native-fill: <原因>`
```

唯一例外：`douyin_uploader/main.py:839`（短信验证码输入，2FA 路径）。其余 33 处全部转 `type_text`。

### 4.6 门 E：阈值唯一定义（已有，沿用）

`tests/test_humanize.py:680-690`：全仓只允许 `utils/humanize.py` 出现 `type_horizon_chars = 1000`。

---

## 5. 失败语义与预算

### 5.1 异常与退出码

| 情况 | 异常 | 退出码 | 重试规则 |
| --- | --- | --- | --- |
| 候选都没出现 | `ElementMissingError` | `1`（确定未发布） | 不重试；这是**选择器问题**，改代码 |
| 找到但不可用：`ambiguous:N` / `zero-box` / `no-bounding-box` / `point-drift` / `covered-by:*` / `disabled` / `pointer-events-none` | `ElementUnusableError(publish_clicked=False)` | `1` | 只在调用方「点后校验状态」循环里可按业务重试；`ambiguous:` 不重试 |
| `mouse.down` 之后任何异常 | 原异常 + `click_dispatched="maybe"` | 提交阶段按现状 `9` | **禁止**再次派发 |
| 预算耗尽且尚未点发布 | `budget.pre_click_error()` | `1` | 修正后可无条件重跑 |
| 预算耗尽且已点发布 | `PublishResultUnknownError`（现状） | `9` | 禁止自动重发 |

- `Humanizer.click` **不传 `what`**（保持哑）；上下文由调用点日志承担。确需上下文的单点可手工构造带 `what` 的 `ElementUnusableError`（XHS `main.py:2176` 是唯一先例）。
- 退出码**映射逻辑沿用现状**，本层不新增码、不改 stderr 契约（`publish_attempted=true` 等归 XHS 规格 §4）。

### 5.2 日志

- `type_text` 越阈值：一条 `info`：`type_text→bulk insert_text, chars=NNN`（已有）。
- 预算裁剪首次发生：一条 `warning`（§2.2 模板），每流程一次。
- 其它：调用点自己打（进入哪个字段、哪一步），`Humanizer` 不打平台文案。

### 5.3 与 `PublishTimeoutBudget` 的关系

- `PUBLISH_TIMEOUT_SECONDS = 15*60` **不变**；不新增「人类化预算」。
- 人类化停顿只吃剩余预算：`min(sample, remaining)`，耗尽收缩到 0、不抛。
- 超时判据仍只在锚点 / 发布点击。
- 已知限制：per-call 累积（§2.7.3）。

---

## 6. 测试策略

### 6.1 共享契约（`tests/test_humanize.py` 扩）

保留现有 6 条契约 + XHS 包静态门，扩成 15 平台参数化：

1. 事件序列：`move* → pointer_settle → hit-test → down → hold → up`；`stillOn` 失败无 `down`。
2. 文本：逐字符 `press` / 非 ASCII `insert_text`；恰一次 `after_type`；1000/1001 边界。
3. `HUMANIZE=0`：一次 `insert_text` / 一次 `locator.click` / 零停顿。
4. 门 A–E（§4）。
5. §2.5 谓词：视口内 / 视口外 / 祖先裁剪 / `viewport_size=None` / 父 frame 裁剪 / 求值异常保守滚。

### 6.2 每平台一个 `tests/test_<platform>_humanize.py`

三条缺一不可（05 §C）：

1. **事件序列**：该平台每个改 Humanizer 的点，断言正确原语（`press` vs `insert_text`）、`after_type` 次数、点击序列、`stillOn` 先于 `down`、零 `force` 派发、零 `el.click`。
2. **字段值读回**：fake locator 持有键入缓冲，断言最终值等于预期（专抓「序列全对、值却错」：大鱼 `#author` 被抹、百家号标题自动填文件名、清空不净导致追加）。
3. **平台静态门**：该平台包内 §4.2–4.5 四道门全过。

Fake 约定（扩 `tests/fakes.py`）：

- `FakeKeyboard`：记录 `press(key)` / `insert_text(text)` 顺序与次数。
- `FakeMouse`：记录 `move/down/up` 与坐标。
- `FakeLocator`：已覆盖 `count/first/nth/get_attribute/is_visible/计算样式/子节点/文本`；**未 scripted 的选择器直接抛错**（防夹具掩盖选择器漂移）；新增 `evaluate(js, arg)` 用于可见性谓词与 hit-test。
- 测试矩阵只有 `HUMANIZE=1` / `=0` 两种，不按平台膨胀。

### 6.3 不做

- 不要求离线 HTML 快照 fixture（15 份易腐快照成本 > 收益；真机已覆盖三家）。
- 不写静态预算表、不估算耗时。

### 6.4 真机验收（`.scratch/humanize-rollout/acceptance.md`）

三平台各一节（Instagram / TikTok / 小红书），每节一张执行表：

| 列 | 用途 |
| --- | --- |
| 日期 / 账号 | 可复现 |
| 发布类型（视频 / 图文 / 文章） | 三家路径不同 |
| 触碰字段（引 §3 行号） | 失败定位 |
| `HUMANIZE=1` 墙钟 / `HUMANIZE=0` 墙钟 / 差值 | 双基线 |
| 预算消耗（占 15 分钟） | 验证 clamp 没吃爆 |
| 是否验证码 / 滑块 / 风控提示 | 唯一外部效果观测 |
| 停止点与就绪证据 | `--no-publish` 停在发布按钮 / Share 就绪前；记录日志里的就绪证据 |
| 结论 pass/fail + 失败字段 | 决定是否 revert |

- **只验本地模式**（表头注明）；托管一律「未验证」。
- **本轮一律 `--no-publish`（干跑）**：素材、配文/话题、封面、声明、定时、选项、读回全部照跑，**停在发布按钮 / Share 就绪前，不点真实发布**，不上真实帖子。
- 因此**发布点击本身不在真机验收范围**：发布按钮的 `Humanizer.click`、`before_submit` 与提交后行为只由离线测试 + XHS 既有真机证据背书，列入 §9 未验证项。就绪超时（退出 `1`）视为失败，必须记录目标与 reason。
- 文件末尾固定「未验证平台」表：12 平台 ×「未验证（无真机环境）」× 离线测试文件名，与 §9 一一对应。
- 撞到新卡死模式（`stillOn` 反复失败、动画按钮、hover 漂移）必须记目标 locator 与重试次数。

---

## 7. 波次与回滚

### 7.1 波次

| 波次 | 平台（交互点） | 依据 | 验收 |
| --- | --- | --- | --- |
| **W0 共享层** | `utils/dom.py` 的 §2.5 三处修复 + 共享测试 | 阻塞全部平台 | 离线 + XHS 回归前置 |
| **W1 真机探针** | Instagram（16）、TikTok（45）、小红书（参照+回归） | 仅有三个真机平台；覆盖 contenteditable / iframe+长文本 / 纯 input 三形态 | **真机（本地 + `--no-publish`）+ 离线三条** |
| **W2 国外** | YouTube（8）、Facebook（10）、Facebook Page（22） | 国外收口；YouTube `#` 候选在此消化（热点置顶） | 离线三条 |
| **W3 国内冲突** | 抖音（53）、微博（23） | 删 `_native_click`、微博覆盖按钮 + 双 page（两个都置顶） | 离线三条 |
| **W4 国内主体** | 知乎（37）、大鱼（36）、视频号（34）、快手（28） | 无硬冲突，规模中等偏大 | 离线三条 |
| **W5 长尾** | 支付宝（16）、百家号（15）、虎扑（15）、雪球（13） | 规模小；百家号搜索候选置顶 | 离线三条 |

合计 371。排序规则：①真机可验收先做；②用户定的分组优先（W1 三真机 / W2 其余国外）；③组内「冲突密度 > 调用点数量」。

**小红书**：不是移植对象，是**参照实现 + 回归对象**。W1 必须重跑其真机验收，确认 §2.5 共享层修复无回归。

### 7.2 回滚契约

- **唯一运行时开关 = 全局 `HUMANIZE=0`**。不新增 `HUMANIZE_EXCLUDE`。
- **回滚单位 = 平台提交**：出问题 → revert 该平台提交 + 重启。
- **不做运行时自动降级**；`force` 不得当回滚网。
- 某平台连续失败 → revert 该平台提交，并把「已退回原生 / 已知问题」写进 `acceptance.md`。不保留「人类化 + 标注」双形态。

### 7.3 「一个平台完成」= 离线三条全过（§6.2），真机平台再加 §6.4 记录

---

## 8. 文档改动（全部随 W1 落地）

| 文件 | 改什么 |
| --- | --- |
| `docs/CLI.md` | 新增 `## 人类化交互层（全平台）`，紧接发布超时预算一节：默认开启、`HUMANIZE=0` 语义、覆盖边界（文本输入 + 可见点击人类化；`set_input_files` / `select_option` / `evaluate` / 文件选择器原生）、失败语义、与 15 分钟预算关系、`force` 准入一句话、**托管模式未验证** |
| `GLOSSARY.md` | 四词条：`人类化交互层`、`交互真实度`、`清空策略`、`stillOn`。只写「是什么」 |
| `CHANGELOG.md` | `[Unreleased]` 建 `### 人类化交互层（15 平台）`，逐波追加平台、`HUMANIZE=0` 回滚、三平台真机结果（未做写未验证） |
| `skills/social-auto-upload/SKILL.md` | 一节三行：默认开启、`HUMANIZE=0` 退回原生、出问题先关它再报 |

不改：`README.md`、17 个平台 `skills/<platform>/SKILL.md`、不在 `docs/` 存规格副本（`CLI.md` 只链接本文件）。

---

## 9. 未验证清单（全部「未验证（无真机环境）」）

| # | 项 | 来源 | 影响的处置 |
| --- | --- | --- | --- |
| 1 | `document.elementFromPoint` 对 shadow 内元素是否 retarget 到 host | 02 §9 | shadow DOM 结论整体 |
| 2 | YouTube Studio `ytcp-*` 是否 native shadow DOM | 02 §9 / map 雾 | YouTube 是否大面积不可点 |
| 3 | `no_defaults` 下 `document.hasFocus()` 与编辑器聚焦 | 02 §9 | 托管路径 |
| 4 | TikTok 上传 iframe 在真实窗口下底部按钮是否落进「判定不滚」死区 | 02 §9 | §2.5.2 谓词在父 frame 的表现 |
| 5 | 各平台按钮 hover 变形幅度（IG 分享、抖音发布、FB Page 发布、视频号发布） | 02 §9 | 是否需调用点前置 `hover()` |
| 6 | 抖音 `.apply-btn` hover 后是否变可见 | 02 §9 | `:686` 能否成立 |
| 7 | 快手 antd 下拉、知乎领域下拉虚拟滚动是否让 `count()==0` | 02 §9 | 收窄策略 |
| 8 | 微博空 `div` 覆盖范围；`(0.65,0.5)` / `(0.35,0.5)` 哪个可命中 | 07 §8 | `:912` 落点 |
| 9 | YouTube `tp-yt-iron-dropdown` 候选结构与全等点选 | 07 §8 | `_fill_editable` 是否回退整段 |
| 10 | `Humanizer.click` 能否驱动抖音封面/声明/合集自定义组件 | 07 §8 | 是否静默失效 |
| 11 | 百家号 `.cheetah-select` 候选文本是否可全等 | 07 §8 | `:698` 匹配 |
| 12 | TikTok 话题逐字是否导致候选重排到不可点 | 本规格（对齐 07 §2 后的残余） | `:2338` |
| 13 | IG `_rows.activate` / `click_control` 是否存在只能靠 JS 展开的行 | 01 §16 | 删 JS 兜底后的失败面 |
| 14 | IG Lexical 对逐字输入的事件敏感度 | 01 §9 | `:799` |
| 15 | TikTok / IG / 小红书 >1000 字正文 `insert_text` 后读回一致 | 04 §2 | bulk 退化是否可接受 |
| 16 | IG carousel alt text 累积成本是否吃光预算 | 04 §3 | 已知限制 |
| 17 | 大鱼视频标题是否有预填 | 01 §3 | `main.py:153` 清空 |
| 18 | 大鱼图文标题是否恢复草稿 | 01 §3 | `article.py:223` |
| 19 | 抖音描述 / 快手描述 / 视频号描述的预填 | 01 §4/§6/§10 | `:471`、`:795`、`:865` |
| 20 | IG Alt text 是否回填已保存值 | 01 §9 | `alt_text.py:224` 全选 |
| 21 | YouTube 标签是否已被前面流程写入部分值 | 01 §14 | `:453` 清空 |
| 22 | 抖音 / 视频号日期时间控件是否总预填当前值 | 01 §4/§10 | `sel` 是否够 |
| 23 | 抖音 `_native_click` 删除后自定义组件是否「点了没反应」 | 07 §8 | 状态重试循环 |
| 24 | 快手封面设置无文本 `div` 的命中区域 | 01 §6 | `:703` |
| 25 | 托管模式（Multilogin / AdsPower）：§2.5.2 谓词在真实窗口的正确性 | 08 §2 | 只离线验证 |
| 26 | §2.5.3 容器裁剪谓词在真实页面（抖音侧滑面板 / antd 日历 / 知乎下拉）是否与真机一致 | 08 §3 | 只离线验证 |
| 27 | 12 个无可验证平台的真机行为 | 05 §A | 全部标未验证 |
| 28 | **发布按钮的真实点击与提交后行为**（本轮三平台都用 `--no-publish` 停在就绪点） | 本规格 | `before_submit`、发布点击、提交后状态只由离线测试 + XHS 既有真机证据背书 |
| 29 | `--no-publish` 就绪窗口（`min(60s, 剩余预算)`）在人类化停顿下是否够用 | 本规格 | 干跑超时退出 1，需据此调低停顿或复核预算 |

> 处置纪律：以上任何一项在真机被推翻，**按 03 的判据顺序处理**（先改点 → 再判是否原生路径 → 最后才是真不可能），不得现场加 `force` / `el.click` / 运行时降级。§2.5.2/§2.5.3 若在真机不成立，回退方式是 revert 共享层提交，不是逐平台加补丁。

---

## 10. 实施检查清单（每平台）

1. 在 `new_page` / `open_upload_page` 之后构造并缓存 `Humanizer(page, sleep=self._humanize_pause)`（微博 2 个）。
2. 按 §3 表逐行改：`T/*` 先收窄到 `count()==1` → 清空 → `type_text`；`H*` 直接换；`N/*` 加 `# native-click` 标记；`X` 删除。
3. 提交/导航点补 `before_submit` / `after_navigate`；滚动后由 `between_scroll` 自动付。
4. 删除平台内的重复坐标点击实现（抖音 `_native_click`）、JS 兜底与 `fill`（按 §4）。
5. 写 `tests/test_<platform>_humanize.py` 三条；跑 `tests/test_humanize.py` 五道门。
6. 更新 `CHANGELOG.md` 该波条目；真机平台补 `acceptance.md`（一律 `--no-publish`，记录就绪证据与「未点发布」）。
7. 平台完成 = 事件序列 + 字段值读回 + 平台静态门，三条全过。
