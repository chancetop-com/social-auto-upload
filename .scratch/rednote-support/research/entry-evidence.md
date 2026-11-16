# Rednote 官方入口与初次页面观察

日期：2026-11-16。仅导航和读取页面，没有上传或发布内容。

- [Rednote 官网](https://www.rednote.com/) 的 Post 链接实际指向 `https://creator.rednote.com/login?source=official`。
- 当前 Chrome 登录态可以进入 [Rednote 发布页](https://creator.rednote.com/publish/publish)，标题 `rednote Creator Center`。
- 视频、图文 tab 都存在，文件输入都使用 `input.upload-input`；图文输入的 accept 为 `.jpg,.jpeg,.png,.webp`。
- 当前账号页面显示中文；账户菜单只观察到 cookie 偏好和退出登录，未发现语言选择。
- [小红书隐私政策](https://agree.xiaohongshu.com/h5/terms/ZXXY20230227002/-1)（2026-04-27）将 mainland Xiaohongshu 与 overseas-operated rednote 区分为 distinct products。不能据此推导 cookie 或账号可互换。

结论：默认使用 `https://creator.rednote.com`，独立账号命名空间。用户要求英文环境，本地 context 设为 `en-US`；现有中文 UI 证据不足以确定纯英文 UI 文案，暂保留结构优先的小红书选择器基线。

局限：这次浏览器观察未验证登录前页面、编辑器元数据控件、上传完成或最终发布结果。
