# Rednote 平台接入

Label: wayfinder:map

## Destination

基于现有小红书逻辑初始化独立的 Rednote 平台入口，再根据 Rednote 账号的真实页面调整登录、视频和图文发布流程。

## Notes

- 用户明确要求「先用 xiaohongshu 的逻辑做第一版初始化，然后基于这个调整为 rednote」，本轮包含代码实现，覆盖 wayfinder 默认仅规划的限制。
- 第一版以小红书已有 CLI 能力为基线，包括本地模式、托管浏览器模式和不点击发布的验证入口。
- 用户已人工登录并授权中性素材的 `--no-publish` 验证；第一版登录、检查、图文和视频主流程已完成真实账号验收。
- 使用 wayfinder；遵循根 GLOSSARY.md 和 docs/agents/issue-tracker.md。
- 以小红书人类化实现为基线，仅按实际页面差异改动。结构可用时不添加文本；确需文本须取证后按英文、中文排序，不自行翻译或猜测兜底。
- 用户当前没有纯英文后台或托管 Profile，明确先完成本地账号验收；对应外部环境留待取得真实样本后继续。

## Decisions so far

- [确认 Rednote 官方入口与小红书的关系](issues/01-entry-research.md)：采用官方 `creator.rednote.com`，账号与大陆版隔离，浏览器默认英文。
- [初始化 Rednote 独立平台并保留页面差异调整入口](issues/02-initialize-adapter.md)：四类命令与独立上传器、测试、文档已接入，保留小红书功能基线。
- [使用 Rednote 账号核实登录与发布页面差异](issues/03-account-validation.md)：按实际 cookie 修正登录态；新进程检查、双图和视频干跑通过，未发布。

- [核实 Rednote 高级选项和纯英文页面兼容性](issues/04-advanced-options.md)：当前账号封面、AI 声明、关闭原创、话题和定时干跑通过；按真实结构收敛，缺样本范围单列后续验收。
- [完成 Rednote 本地账号剩余验收](issues/05-real-variant-validation.md)：五种声明、扫码会话闭环、图文与视频原创开启通过；纠正短视频禁用被误判为账号限制，完成本地验收。
- [核对 Rednote 第一版本地交付完整性](issues/07-local-delivery-check.md)：补齐能力表和独立 Skill 文档，构建包与四个 CLI 入口验证通过。
- [修正动态候选刷新时的偶发长停顿](issues/08-topic-refresh-stall.md)：实测定位 30 秒旧序号等待；修复 Rednote、小红书、TikTok 和百家号的同类路径，Rednote 图文与视频干跑复验通过。

- [保留发布结果并立即拒绝发布按钮歧义](issues/09-publish-result-contracts.md)：修复 Rednote / 小红书及其他 CLI 平台的同类清理、唯一性和重试问题；故障注入、CLI 退出码及本地 Chromium 验证通过。

## Not yet specified

- 暂无无法明确描述的问题；仍缺真实样本的变体验收已记录为独立子票据。

## Out of scope

- 本轮不自动向真实账号发布测试内容。
