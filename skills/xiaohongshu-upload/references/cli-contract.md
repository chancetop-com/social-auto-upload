# 小红书 CLI 契约

这个 skill 默认假设当前环境已经安装并可调用 `sau` 命令。

## 命令列表

### 登录

```bash
sau xiaohongshu login --account <account>
```

- 必填参数:
  - `--account`
- 作用:
  - 在选定的专用持久化 Profile 中扫码，登录后重新打开发布页取得正向登录证据；浏览器关闭后保存资料
  - 如果登录过程中生成本地二维码图片，agent 应优先直接把图片展示/发送给用户扫码，而不是只回传路径
- 账号说明:
  - `--account` 传的是用户自定义的 `account_name`，不是固定只能叫 `creator`
  - 一个原始别名按浏览器种类隔离 Profile；同一 Profile 同时只能由一个命令使用，别名可重新登录其他账号

### 检查登录态

```bash
sau xiaohongshu check --account <account>
```

- 必填参数:
  - `--account`
- 预期输出:
  - `valid`：发布页存在上传入口且未命中登录/验证
  - `invalid`：Profile 缺失、登录/验证阻断或探测失败；结合退出码判断原因

### 上传视频

```bash
sau xiaohongshu upload-video \
  --account <account> \
  --file <video-path> \
  --title "<title>" \
  [--desc "<description; public topics as #topic>"] \
  [--schedule "YYYY-MM-DDTHH:MM:00Z"] \
  [--thumbnail <image-path>] \
  [--original | --no-original] \
  [--content-type fiction|ai|marketing|self-shot|repost] \
  [--repost-source <media-name>] \
  [--shoot-location <location>] \
  [--shoot-date YYYY-MM-DD] \
  [--no-publish] \
  [--debug] \
  [--local-browser chrome|chromium] \
  [--headless | --headed]
```

- 必填参数:
  - `--account`
  - `--file`
  - `--title`
- 可选参数:
  - `--desc`（公开话题写成 `#话题`）
  - `--schedule`
  - `--thumbnail`
  - `--original` / `--no-original`
  - `--content-type`（`repost` 时必须同时传 `--repost-source`）
  - `--repost-source`
  - `--debug`
  - `--headless`
  - `--headed`

### 上传图文

```bash
sau xiaohongshu upload-note \
  --account <account> \
  --images <image-1> [image-2 ...] \
  --title "<title>" \
  [--note "<content; public topics as #topic>"] \
  [--schedule "YYYY-MM-DDTHH:MM:00Z"] \
  [--original | --no-original] \
  [--content-type fiction|ai|marketing|self-shot|repost] \
  [--repost-source <media-name>] \
  [--shoot-location <location>] \
  [--shoot-date YYYY-MM-DD] \
  [--no-publish] \
  [--debug] \
  [--local-browser chrome|chromium] \
  [--headless | --headed]
```

- 必填参数:
  - `--account`
  - `--images`
  - `--title`
- 可选参数:
  - `--note`（公开话题写成 `#话题`）
  - `--schedule`
  - `--original` / `--no-original`
  - `--content-type`（`repost` 时必须同时传 `--repost-source`）
  - `--repost-source`
  - `--debug`
  - `--headless`
  - `--headed`

## 本地配置与退出码

login/check/视频/图文都复用 `browser_profiles/<种类>/xiaohongshu/<别名>`。`LOCAL_CHROME_PATH` 优先于 `--local-browser` / `LOCAL_BROWSER`；缺省 Chrome。显式 headed/headless 优先于 `LOCAL_CHROME_HEADLESS`，未配置默认有头。旧 JSON 不参与，业务不会自动扫码或恢复旧任务。

- `0`：检查通过、登录完成或流程完成；no-publish 仅证明到达提交前停止点。
- `1`：浏览器、网络、页面结构、必需字段或权限故障；不能据此认定登录失效。
- `2`：参数错误。
- `10`：Profile 缺失或明确未登录；`reason=verification` 时先人工完成验证。提交后 stderr 带 `publish_attempted=true`，先核对笔记再决定是否重跑。
- `9`：提交结果未知，禁止自动重发。
使用托管模式前，读取运行 `sau` 的项目根目录 `docs/CLI.md` 的“托管浏览器模式（通用）”（[在线入口](https://github.com/dreammis/social-auto-upload/blob/main/docs/CLI.md#托管浏览器模式通用)），确认共同退出码、部署前提、调度责任与身份安全。

### 重建指定本地 Profile

```bash
sau xiaohongshu reset-profile --account <account> --browser-kind chrome
```

不需要 binary；只清空明确指定的种类，保留其他种类、历史结果和旧文件。占用或归属不明时失败，不接管外部浏览器。重建后先 login。

## 发布策略

- 如果不传 `--schedule`，CLI 使用立即发布
- 如果传了 `--schedule`，CLI 自动切换为定时发布
- 时间格式为:

```text
YYYY-MM-DDTHH:MM:00Z
```

- 定时窗口为绝对时刻的 `now + 2h < t <= now + 14d`；填写前读取浏览器时区换算墙上时间，越界在启动浏览器前退出 `1`
- CLI 在 FIRE（点击发布）前复核定时开关与时间值；回读不一致或时间已过期退出 `1`，不会改成立即发布
- 回读只证明客户端接受设置，不证明服务端受理；定时是否真正生效需真机验证

## 发布声明

`upload-video` 与 `upload-note` 都支持以下可选声明，默认全部不操作页面：

| 参数 | 作用 |
| --- | --- |
| `--original` | 开启原创声明 |
| `--no-original` | 关闭原创声明 |
| `--content-type fiction` | 虚构演绎，仅供娱乐 |
| `--content-type ai` | 笔记含AI合成内容 |
| `--content-type marketing` | 内容包含营销广告 |
| `--content-type self-shot` | 内容来源声明 → 自主拍摄，需 `--shoot-location` + `--shoot-date` |
| `--content-type repost` | 内容来源声明 → 来源转载，需 `--repost-source` |
| `--repost-source <媒体名称>` | 来源转载的媒体名称 |
| `--shoot-location <地点>` | 自主拍摄的拍摄地点 |
| `--shoot-date <YYYY-MM-DD>` | 自主拍摄的拍摄日期 |

- 不传这些参数时，页面保持平台默认；
- `--original` 与 `--content-type repost` 互斥；
- `--no-original` 不能与 `self-shot` / `repost` 组合；
- `--repost-source` 必须与 `repost` 一起使用且不能为空；
- `--shoot-location` / `--shoot-date` 必须与 `self-shot` 一起使用，日期格式 `YYYY-MM-DD`；
- 组合错误在启动浏览器前退出 `2`；
- `--original` 是硬闸：点前读状态、未开则点击并确认须知，任一步失败退出 `1`（确定未发布）；
- `--no-original` 与内容类型声明失败只记 warning 并继续；封面失败同样 warning 并回退到视频首帧；
- `--no-publish` 跑到 ARM 就绪（发布按钮存在、可点击且未被禁用/遮挡）后停止，不点击发布，也不等待 `--not-before`，适合回归与真机验收。

## 发布超时

- 与 TikTok 对齐，整条上传/发布流程使用 15 分钟总预算；
- 预算覆盖上传、填表、声明、定时设置、ARM 就绪等待与点击发布；
- 尚未点击发布前超时（含 ARM 就绪窗/预算耗尽）：退出 `1`，确定未发布；
- 已经点击发布后超时：退出 `9`，结果未知，禁止自动重发，需先到笔记管理核对；
- FIRE 之后只按 URL path 判定是否离开发布页，并先分类登录/人机验证页；**不扫描页面文案**、不区分「明确拒绝」与「限流提示」、不做重试；
- 点击后落在登录/验证页：退出 `10`，stderr 额外打单独一行 `publish_attempted=true`；
- `--no-publish` 跑到 ARM 就绪即返回，不进入 FIRE/OBSERVE，不受发布观察窗影响（仍受总预算约束）。

## 额外说明

- `upload-video` 每次命令只支持一个视频文件
- `upload-note` 每次命令支持多张图片
- 视频描述字段统一使用 `--desc`
- 图文正文统一使用 `--note`
