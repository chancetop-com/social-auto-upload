# 核对 Rednote 第一版本地交付完整性

Type: task
Status: resolved
Blocked by: 05

## Question

本地实际账号流程通过后，核对独立平台登记、CLI 参数、技能分发和使用文档是否存在遗漏，使已验收的第一版可以从正常入口使用。以小红书现有接入为基线，只修正有代码或运行证据的问题；不重复已通过且没有变化的线上上传，不用离线检查替代英文后台或托管 Profile 的真实验收。

## Comments

- 用户继续 wayfinder，沿用已明确的本地范围。实际英文后台与托管 Profile 的票据因缺少对应环境暂留；本票只完成不依赖这些环境的交付核对。

## Answer

第一版本地交付核对完成：

- README 主能力表补上 Rednote，并将视频、图文和定时标为实验性，明确只完成发布前验收；许可证说明中的 Skill 数量同步为实际 19 个。
- Rednote Skill 新增随包分发的运行前提与 CLI 契约；高级选项和错误恢复不再依赖仓库外部路径。所有相对引用可解析，19 个 Skill slug 无重复。
- `.venv/bin/sau rednote --help` 正常；离线构建 wheel 包含 Rednote 命令、上传器和 `sau` 入口。在临时目录解包后，直接从包内加载四个 Rednote 子命令，帮助输出均成功，发布命令含已实现的声明、定时与 `--no-publish` 参数。
- 没有修改 Python 发布逻辑、没有新增线上上传、没有公开发布包或 Skill。既有本地真实验收继续有效；实际英文后台与托管 Profile 仍在独立票据中等待对应环境。

证据见 [验收记录](../acceptance.md)。本地构建与检查记录位于忽略目录 `.local/rednote-acceptance/`，不是公开发行物。
