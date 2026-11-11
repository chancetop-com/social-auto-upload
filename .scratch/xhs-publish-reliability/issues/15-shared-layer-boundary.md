# 15 — 共享层边界与迁移顺序

Status: open
Type: grilling
Blocked by: 10, 11, 12
Assignee: —

## Question

用户要求 humanize 等通用防封手段可被其它 15 个平台复用。需要确认：

1. **抽什么**：人类化输入/点击/延迟、可见性判定、上传完成判定、`set-then-readback` helper、风控页分类——逐项判断是否真的跨平台通用（平台 DOM 差异是否会让 helper 变成配置地狱）。
2. **放哪**：`utils/` 还是 `uploader/`；依赖方向（uploader 不得反向依赖 `sau_commands`；`utils` 不得 import 平台常量）。
3. **接口形态**：无状态函数 vs 带注入（随机源、时钟、logger）的类；与现有 `humanize` 概念（上游 Go 包）命名是否冲突。
4. **迁移顺序**：小红书先行验证 → 下一个平台选谁（按风险/收益）→ 如何灰度（默认开/关、按平台开关）。
5. **不迁的**：`biliup` 子进程（无浏览器上下文）等例外如何处理。
6. 与 `PublishTimeoutBudget`（已存在、仅 TikTok 用）的关系：是同一层还是两条线。

产出：模块清单 + 接口草案 + 迁移路线 + 每步的验收信号（如何判断“这个平台迁移后没变差”）。
