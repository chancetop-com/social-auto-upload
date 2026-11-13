# 09 — 汇总 GoLogin 模式设计规格

Status: open
Type: task
Blocked by: 08
Assignee: —

## Question

把 01–08 的裁决汇总成 `.scratch/gologin-browser-mode/spec.md`，要求与 `.scratch/adspower-browser-mode/spec.md` 同等级、可直接交给后续会话实施：

1. 目标与非目标；术语；模式激活与 runtime 选择。
2. CLI 参数矩阵（本地 / MLX / AdsPower / GoLogin-local / GoLogin-cloud）。
3. 模块图与运行时时序（本地与云端各一张）。
4. Provider 接缝与最小改动面（文件清单、要改的行级位置）。
5. 本地/云端 API client 契约（端点、请求/响应、错误）。
6. 生命周期、所有权、超时与失败边界。
7. 逐平台迁移表（16 个托管平台 + article/bilibili 缺口）。
8. 登录失效、人机验证、身份与账号标签规则。
9. 退出码与 stderr 机器信号表。
10. 安全（token 不落日志）、部署前提、调度侧责任。
11. 测试矩阵（离线 + opt-in 冒烟）。
12. 实施阶段拆分（供后续 effort 直接接单）。
13. 风险、未验证项与置信度。
14. 兼容性与回滚。
15. 文档交付清单。

每条结论标注置信度（官方文档 / 社区实测 / 推断），云端运行时若被 ticket 02 判为不可做，spec 必须写清楚用户可见的拒绝行为。

## Context

- 这是本 map 的终点产物；本轮不实现。
- 参考模板：`.scratch/adspower-browser-mode/spec.md`。
