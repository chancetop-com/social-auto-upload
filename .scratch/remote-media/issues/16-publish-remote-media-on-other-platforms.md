# 16: 将远程素材接入其余六个平台

Status: ready-for-agent
Resolution: completed
Blocked by: 15

**What to build:** 小红书、Rednote、YouTube、Facebook、Facebook Page 和 Instagram 各自已有的视频、图文和封面参数接入与 TikTok 相同的取材流程。

规格见[网络素材预下载与上传 CLI 规格](../spec.md)。

## 验收条件

- [x] 逐个平台从实际 `sau` 入口验证已有的 `upload-video --file`。对原本支持图文或自定义封面的入口，分别验收 `upload-note --images`、`--thumbnail`，覆盖本地和 URL 参数。YouTube 按其现有视频入口验收。
- [x] 在本机离线平台夹具上核对视频、封面的文件内容，以及混排本地和远程图片时的输入顺序和重复位置。平台原有的文件类型、数量、账号、发布目标和发布选项约束继续生效。
- [x] 覆盖本地模式、托管浏览器模式及纯本地回归。显式 ID 可复用预下载的文件，省略 ID 时远程素材按临时目录规则处理。平台只收到已就绪的本地文件。
- [x] 按同一组发布契约核对慢速取材和素材失败。平台计时从整组就绪后开始，必需素材失败时退出 `1` 并指出该项，离线平台收到零次提交。沿用各平台已有的发布结果和不发布模式语义。

## Comments

六个平台已有的视频、图文及封面入口逐项验收。离线测试检查交付的字节、输入顺序、缓存复用与失败时零提交，并从托管 YouTube 入口核对预算。无扩展名的 AVIF、HEIC 和 HEIF 图片也经 CLI 验证。见 `tests/test_remote_media_platforms.py`。
