# 20: 先移除 11 个平台

Status: ready-for-agent

Blocked by: None

批次：前置 · [托管 Profile 默认共享规格](../spec.md)

## What to build

从产品中移除以下平台的全部动作与专属实现，覆盖本地模式和托管模式。这张工单完成后，从 [#08](08-adspower-shared-check.md) 开始共享 Profile 实施。

| 平台 | CLI 名称 |
| --- | --- |
| 抖音 | `douyin` |
| 快手 | `kuaishou` |
| Bilibili | `bilibili` |
| 视频号 | `tencent` |
| 大鱼号 | `dayu` |
| 百家号 | `baijiahao` |
| 支付宝生活号 | `alipay` |
| 微博 | `weibo` |
| 虎扑 | `hupu` |
| 雪球 | `xueqiu` |
| 知乎 | `zhihu` |

## Acceptance criteria

- [ ] 安装后的 `sau --help` 仅列出七个保留平台及通用工具 `article`。逐一用表中的旧名称调用 CLI，在本地及配置托管 provider 时均在参数解析阶段以 `2` 退出，浏览器、provider 和 biliup 的调用次数均为零。
- [ ] 移除各平台的 CLI 注册和分派、专属上传器、可运行脚本、示例及仅由它们使用的依赖。Bilibili 的 biliup 本地入口一并删除。清理混合测试中的旧平台用例，将仍适用的公共回归改用保留平台验证。
- [ ] 从干净检出安装后，七个平台均能加载，各平台的本地命令和 20 个托管入口均可解析。`sau article themes` 和本地 `render` 仍能处理示例原稿。保留功能不依赖已删除的平台模块。
- [ ] 更新 README、CLI 使用说明和仓库内面向使用者的命令示例。支持表与安装后帮助一致，历史决策和验收记录可追溯。
- [ ] 在含已有账号文件、浏览器 Profile、素材及结果文件的临时目录验证升级和旧命令调用，用户文件均保留。
