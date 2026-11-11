# 39 — 话题插入与回读

**What to build:** 话题是增强项：插不进去就保留纯文本 `#tag` 继续发布，绝不因此失败；但只要插进去，就必须**恰好一个**且名字**完全等于**请求的话题，否则点击前中止。编辑区回读取代整页计数，避免预览镜像造成的"每次都 +2"。

**Blocked by:** 33（候选、编辑区与回读锚点）.

**Status:** ready-for-agent

**候选匹配**

- [x] 顺序扫描全部渲染候选项（真机热榜排序，精确项可能在第 4 位），读候选项名字
- [x] 两侧同规则归一化：去前导 `#` → 去首尾空白 → 折叠内部连续空白 → casefold
- [x] 只点名字**全等**的项；多个全等取最前并打 info；无全等即判"无候选"，不做前缀/包含匹配
- [x] 候选容器按 `attached` 档，被点项按 `interactive` 档

**就绪与重试**

- [x] 200ms 轮询，deadline `min(5s, 剩余预算)`，每轮重新扫
- [x] 就绪条件 = 候选项数 > 0，**不是**容器可见（容器会先以 0 项空壳出现）
- [x] 最多 3 次点击；退出条件：连续找不到 / 用满 3 次 / deadline 到
- [x] 循环内不回读；循环后统一回读一次

**回读判据**

- [x] 作用域 = 正文编辑器根（不查整页）
- [x] 基线按标签条目固定：该标签第一次点击前取一次，重试不刷新；新增 = 点击后多重集合 − 基线
- [x] 50ms 轮询，窗口 `min(1s, 剩余预算)`；节点只需 `attached`
- [x] 从话题数据解析名字；解析失败算"名字未知" → 按插错处理

**出口**

- [x] 候选未出现或 3 次点击后 0 个新增 → 降级：保留纯文本 `#tag` + 一个空格，warning，不算失败
- [x] 新增 ≥1 但名字 ≠ 请求 → 中止，`reason=topic-mismatch` → `1`
- [x] 编辑区内新增 > 1 → 中止，`reason=topic-multi-insert` → `1`
- [x] 恰好 1 个且名字全等 → 成功
- [x] 降级时**不按 `Backspace` 清理**；不做输入前复位（真实连续插入无需复位）
- [x] 失败对象带 `tag`/`observed_names`/`new_nodes`/`attempts`，一律点击前 `1`

**上限口径**

- [x] 只在校验期一处生效：超过 10 个 → warning 列出被丢弃项并取前 10
- [x] 删除运行时静默截断；CLI 两处"超过 10 报错"降为同文案 warning（不再是 `1`）

**测试**

- [x] 全等匹配（1 / 4 / 50 项）；0 项空壳不误判；无候选降级 + 空格；插错中止；2 个新增中止；基线不刷新；预算收紧；正文形态示例（`#旅行 #治愈[话题]#`）

## Comments

- 候选匹配：`_scan_topic_candidate()` 每轮重新 `page.locator` 并顺序扫描 `#creator-editor-topic-container .item` 全部渲染项，逐项读 `.name` 的 `text_content()`；归一化函数 `_normalise_topic()`（去前导 `#` → strip → `\s+` 折叠 → casefold）两侧共用。多个全等打 `info` `topic-ambiguous:N` 并取最前；容器 `utils.dom.check(..., "attached")`，被点项 `check(..., "interactive")`。
- 就绪/重试：`_insert_topic()` 用 `XHS_TOPIC_READY_WINDOW_MS=5s`、`XHS_TOPIC_POLL_SECONDS=0.2`，窗口经 `_topic_window_ms()` 收紧到剩余预算；就绪只认 `.item` 数 > 0；最多 `XHS_TOPIC_MAX_CLICKS=3` 次点击；点后候选消失即停止（上游语义），循环内不回读。
- 回读：`_read_topic_nodes()` 只读 `XHS_TOPIC_READBACK_CANDIDATES`（`div.tiptap[role="textbox"] a[data-topic]`），`data-topic` → `json.loads` → `name`；`_readback_new_topics()` 50ms 轮询、窗口 1s 收紧到预算，多重集合差以 `data-topic` 原始串为元素。基线 `S0` 在该标签第一次点击前取一次，重试不刷新。
- 出口：0 新增 → `_degrade_topic()` 打 `press("Space")` + warning（不按 `Backspace`）；1 个全等 → info `topic-match:<tag>`；>1 → `topic-multi-insert`；1 个不等/无法解析 → `topic-mismatch`。失败对象为 `utils.dom.ElementUnusableError`（`publish_clicked=False`），实例上另挂 `tag` / `observed_names` / `new_nodes` / `attempts`。
- 删除：旧 `fill_tags` 的 `#creator-editor-topic-container` `wait_for(visible)`、`.item.first` 盲点、失败后 `Backspace × len("#tag")` 清理、运行时 `tags[:10]` 截断全部移除；未加入 `ArrowDown×20 + Enter×2` 复位。
- 上限：唯一截断点 `validate_base_args()` → `_cap_tags()`（warning 列出 `tags[10:]`）；`sau_commands/xiaohongshu.py` 两处 `>10` 改 `print(f"警告：{format_tag_cap_warning(...)}", file=sys.stderr)` 后继续，不再 `return 1`。
- 测试：新增 `tests/test_xhs_topics.py` 22 条（全等位置 1/4/50、前缀不匹配、归一化、0 项空壳、无候选降级 + 空格、缺失容器、歧义 info、插错/未知 payload、2 个新增、恰好 1 个、基线不刷新、循环外回读、预算收紧两个窗口、正文形态、校验截断、运行时不再截断、CLI 超过 10 不退出 1）；`tests/test_xiaohongshu_uploader.py` 两条旧 `fill_meta` 断言改为降级形态。
- 全量：`python -m unittest discover -s tests -t .` → 1307 tests OK（skipped=2）。
- 真机项：`未验证（无真机环境）` —— 多话题连续插入已由 23 取证，本轮未重复；本票新增的「降级时补空格」「编辑器内恰好 1 个新增」未再上真机复核。
