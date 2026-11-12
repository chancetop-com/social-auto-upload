# 03 — `force=True` 白名单准入规则

Status: resolved
Type: grilling
Blocked by: 01

## Question

已决定：`force=True` 默认改严格，只白名单保留少数。现在要把「白名单」从一句话变成可执行的规则。

要定的事：

1. **准入条件**：什么样的点击才配留在白名单？候选判据——(a) 元素按设计就不可命中（`opacity:0` 的 input 由 label 触发）；(b) 元素被同组件的正常遮罩覆盖，且遮罩本身不可交互；(c) 元素是零尺寸锚点。哪些准入、哪些一律拒绝？
2. **数量上限**：白名单允许几条？是「不超过 N 条」还是「只允许上述类别、数量不设限」？
3. **记录形式**：写在代码注释里、集中在平台常量表里，还是两边都要？注释必须包含哪些字段（原因、真机日期、替代方案）？
4. **测试约束**：离线测试怎么断言「没有偷偷加回来的 force」——全仓 grep 断言，还是只断言白名单文件里的清单？白名单本身要不要有测试锁住？
5. **失败文案**：`stillOn` 拦下来时抛 `ElementUnusableError`，CLI 会走 exit 1。这算「页面问题」还是「选择器问题」？日志里要不要点名是哪个控件被挡住？
6. **过渡期**：改严格后必然有一批平台先失败。是允许「先白名单全保留、逐平台收紧」，还是要求一次收紧到位（失败就失败）？

产出：准入规则表 + 记录格式 + 测试断言 + 过渡策略。

## Answer

### 1. 准入判据（一句话）

**只有当一条路径「走不通人类化」时，才考虑 `force=True`；能走通就走人类化。**

「走不通」既不是「以前失败过」，也不是「作者觉得危险」，而是**坐标点击在这条路径上无解**：目标不可命中，且改点任何可命中目标都不能完成同一语义动作。

判断顺序（每条调用点依次过）：

1. **能不能改点？** 找同一语义动作的可命中目标——组件本体、`label` 本体、装饰层、行内文字 `span`、可见父级。能 → `Humanizer.click`，不留 force。
2. **这条路径本来就不人类化？** 登录 / 二次验证 / 文件选择器 / 纯失焦滚动（01 已判「保持原生」）→ 原样保留，force 不动。这是「不走」，不是白名单。
3. **都不成立？** 才是真「不可能」，保留 force 并写三字段注释。

本次 18 条按此顺序判定后，**真残余为 0 条**。

### 2. 三条硬事实（决定了上面的顺序）

**2.1 `force=True` 不绕过遮挡，它只是不再检查遮挡。**
`[code]` patchright `driver/package/lib/coreBundle.js` `_performPointerAction`：`force` 只跳过 `visible/enabled/stable` 等待与 `_checkFrameIsHitTarget` + hit-target interceptor，随后仍在元素中心坐标派发**真实鼠标事件**。所以「被浮层盖住 → 加 force」是错的：鼠标事件落在浮层上。这条同时否掉了把 force 当提交按钮保险的用法。

**2.2 `interactive` 的命中判定接受后代。**
`[code]` `utils/dom.py:184`：`self: hit === el || el.contains(hit)`。因此「目标被自己组件的 icon / 装饰层盖住」不是不可命中——把目标换成那个容器就通过。`tk:462`、`baijiahao:641` 属于此类，**改点即解**。

**2.3 零尺寸目标禁止用 force。**
`Humanizer.click` 在零尺寸时于 `mouse.down` 之前抛 `zero-box`（确定未派发）；`force=True` 在零尺寸元素上会在其退化坐标点一下，点到的是**别的元素**。所以 `ks:110` 的回退分支不该保留 force，而该让 `zero-box` 直接失败。

### 3. 记录格式

不建中央白名单表。唯一运行时记录是**残留 force 处的三字段注释**；逐条去向的汇总由 06 的「每平台实施表」承载。

```python
await verify_btn.click(force=True)  # humanize-impossible: 原生短信二次验证路径，元素可点但整链不接入；[code]；已试 无（不属改造面）
```

- **失败模式**：一句话说清为什么走不通（不可命中 / 零尺寸 / 原生路径）。
- **依据等级**：`[code]` 工作树可读 / `[inferred]` 由代码推导 / `[needs-live]` 需真机。三选一，必须出现。
- **已排除的替代**：试过哪些可命中目标、为什么不行；写「无」等于声明此项不适用，会被 review 追问。

不写「真机日期」：18 条里多数是历史改动，写日期只会制造假精度。

### 4. 静态门（标记门）

`force=True` 用 **AST 判定 + 行内标记**，不用 grep（grep 会把 `tk:1030` 的 docstring 算进去，现有 XHS 门就是这么误报的）。

```
扫 uploader/ 下 15 个平台目录：
  对每个 ast.Call，存在 keyword(arg="force") 且 value 为 Constant(True) 时：
    该调用的 [lineno, end_lineno] 区间内必须有一行匹配 `# humanize-impossible: <reason>`
    且 reason 含 [code] / [inferred] / [needs-live] 之一
    否则 fail：<file>:<line> force=True 未自证
```

不锁位置、不锁数量、不要求归零。门只保证「每个残留 force 都必须自己解释」。

另两道门不属于本票：`el.click()` 归零（charter + 07 的微博例外）、`.click(` 只允许 `humanizer` receiver（XHS 已有先例，15 平台按平台推进）。

### 5. 失败语义

- **定性**：`ElementMissingError`（找不到）= 选择器问题，重试无用、改代码；`ElementUnusableError`（找到但不可用）= 页面问题，重试可能成功。两者不得合并成笼统失败；CLI 退出码沿用现状。
- **点名**：照 XHS——`Humanizer.click` 保持哑，不传 `what`，失败消息只有「点击目标」+ `reason`（`covered-by:…` / `point-drift` / `zero-box`）。上下文由调用点日志承担；确实需要携带上下文的关键点位可**手工构造**带 `what` 的 `ElementUnusableError`（XHS `uploader/xiaohongshu_uploader/main.py:2176` 是唯一先例）。
- 不采用：新增 `what=` 参数、失败时自动读标签名、全量强制传 `what`。

### 6. 过渡策略

一次到位，不留「临时 force」。判据当场落定；无真机平台的改点失败就失败，标 `[needs-live]`。回滚单位是 `HUMANIZE=0` 全局退回原生 `locator.click()`——**force 是正确性判断，不是回滚网**，两者不得混用。

数量不设上限（设了 N 就会有人为凑数删真残余、或为保住第 N+1 条编理由）。

### 7. 18 条逐条去向（决策记录，非运行时清单）

| 点位 | 判定理由 | 去向 | 依据 |
| --- | --- | --- | --- |
| `alipay:521` | 524 已是无 force 重试，本身走通 | 删 521，合并为一次 `Humanizer.click` | `[code]` |
| `baijiahao:641` | antd 组件盖住原生 input，属 2.2 | 改点组件本体 → `Humanizer.click` | `[code]`+`[needs-live]` |
| `baijiahao:753` | 发布按钮；被遮挡时 force 无用（2.1） | `Humanizer.click` + `before_submit`；遮挡走 07 清浮层 | `[code]` |
| `douyin:624` | `count()==0` 死分支 | 删分支（若保留则 `Humanizer.click`） | `[code]` |
| `douyin:846` / `:854` | 原生二次验证路径（「不走」） | 保留 force + 注释；两处合并 | `[code]` |
| `douyin:935` | hover 不要求可点，force 无意义 | 删 force → `Humanizer.hover` | `[code]` |
| `douyin:1241` | 发布按钮，同 753 | `Humanizer.click` + `before_submit` | `[code]` |
| `ks:110` | 回退分支可能 0×0，属 2.3 | 正常路径 `Humanizer.click`；回退分支让 `zero-box` 直接失败 | `[code]` |
| `ks:582` | Joyride 引导层，非发布路径（「不走」） | 保留 force + 注释 | `[code]` |
| `tencent:794` | 候选已 `is_visible()`，本就走通 | 删 force → `Humanizer.click` | `[code]` |
| `tencent:918` | force 仍会滚入视口，理由不成立；真实风险是 08 的容器裁剪 | 删 force → `Humanizer.click`，依赖 08 结论 | `[code]` |
| `tk:462` | styled label 的 icon 是 label 后代，属 2.2 | 改点 `label` 本体 → `Humanizer.click` | `[code]` |
| `tk:2003` | 不是命中问题，是 React checked 陈旧（幂等重复点） | 删 force，`Humanizer.click` 可重复调用 | `[code]` |
| `tk:2387` | 2382 普通 click 已是首选 | 删 force，保留 Enter 首选 | `[code]` |
| `tk:2904` | hidden file input，文件输入原生（「不走」） | 保留 force + 注释 | `[code]` |
| `weibo:795` | switch 装饰层可点 | 删 force，点 `span[role=switch]` | `[code]` |
| `weibo:858` | 598px 行中心落空 | 删 force，点行内文字 `span` | `[code]` |

### 8. 结论：白名单为空

15 个平台里**没有一条「人类化不可能」的点击**；残余 4 条（`douyin:846/854`、`ks:582`、`tk:2904`）全部是「不走」的原生路径，01 的处置列已判「保持原生」。本票的产出因此不是清单，而是两条：**一条判据顺序、一个标记门**。

### 9. 边界

- 提交按钮被浮层挡住后的**合法路径**（找点位 / 清浮层 / 父级重试）由 07 裁决；03 只判定「不得用 force 掩盖」。
- `douyin:686`、`weibo:861/912/941` 等 `el.click()` 归 07 与 charter 的禁令，不在本票。
- `tencent:918` 若 08 判定「接受容器裁剪缺陷」，则该点按「不可能」保留，并在注释里注明依赖 08。
