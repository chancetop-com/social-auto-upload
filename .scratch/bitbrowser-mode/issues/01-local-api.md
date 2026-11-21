# 比特浏览器本机 API 能为既有窗口提供哪些能力

Label: wayfinder:research
Type: research
Status: resolved
Assignee: LukeChen
Blocked by:

## Question

官方公开材料如何描述本机服务地址、启用条件、鉴权和窗口 ID？如何打开已配置的窗口、发现正在运行的窗口、取得同一实例的 CDP 地址并按 ID 关闭？分别查证有界面与无界面启动、重复打开、错误和限流信号。哪些行为有公开契约，哪些只有示例或必须用真实客户端验证？

## Answer

普通 Local API 支持可选 Token 鉴权。单窗操作使用复制得到的字符串 `id`，整数 `seq` 是展示序号。`/browser/open` 可打开已有配置并返回 CDP 地址，`/browser/ports` 能按窗口 ID 找到已运行实例的调试端口，`/browser/close` 按 ID 关闭。官方要求关闭后等待 5 秒再重开，在窗口预设或启动参数中可设置无头模式。[窗口接口](https://doc2.bitbrowser.cn/jiekou/liu-lan-qi-jie-kou.html) · [端口响应示例](https://doc.bitbrowser.net/api-docs/browser-profiles) · [Token 变更](https://www.bitbrowser.cn/blog/btllq_6_0_4_sjrz) · [无头指南](https://doc2.bitbrowser.cn/headless.html)

公开材料尚不足以保证重复打开会复用同一进程、已开窗口可切换显示模式，或业务错误能稳定识别限流。当前依据来自官方文档和样例，真实客户端上的行为仍待验收。[本机 API 研究笔记](../research/01-local-api.md) · [独立研究提交](https://github.com/chancetop-com/social-auto-upload/commit/bfc6b5e8d7a6e600602b64f7a9eeb6d077369a92)
