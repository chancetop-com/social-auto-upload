# 抖音 CLI 契约

这个 skill 默认假设当前环境已经安装并可调用 `sau` 命令。

## 命令列表

### 登录

```bash
sau douyin login --account <account>
```

- 必填参数:
  - `--account`
- 作用:
  - 启动抖音登录流程，在指定持久化 Profile 中完成登录
  - 如果登录过程中生成本地二维码图片，agent 应优先直接把图片展示/发送给用户扫码，而不是只回传路径
- 账号说明:
  - `--account` 传的是用户自定义的 `account_name`，不是固定只能叫 `creator`
  - Profile 按平台、原始别名、实际浏览器种类隔离；同一 Profile 拒绝并发占用，别名不绑定真实账号

### 检查登录态

```bash
sau douyin check --account <account>
```

- 必填参数:
  - `--account`
- 预期输出:
  - `valid`：Profile 已登录
  - 缺少 Profile、未登录或验证退出 `10`；网络/页面故障退出 `1`

### 上传视频

```bash
sau douyin upload-video \
  --account <account> \
  --file <video-path> \
  --title "<title>" \
  [--desc "<description>"] \
  [--tags tag1,tag2] \
  [--schedule "YYYY-MM-DDTHH:MM:00Z"] \
  [--thumbnail <image-path>] \
  [--product-link <url>] \
  [--product-title "<title>"] \
  [--debug] \
  [--headless | --headed] \
  [--local-browser chrome|chromium]
```

- 必填参数:
  - `--account`
  - `--file`
  - `--title`
- 可选参数:
  - `--desc`
  - `--tags`
  - `--schedule`
  - `--thumbnail`
  - `--product-link`
  - `--product-title`
  - `--debug`
  - `--headless`
  - `--headed`

### 上传图文

```bash
sau douyin upload-note \
  --account <account> \
  --images <image-1> [image-2 ...] \
  --title "<title>" \
  [--note "<content>"] \
  [--tags tag1,tag2] \
  [--schedule "YYYY-MM-DDTHH:MM:00Z"] \
  [--debug] \
  [--headless | --headed] \
  [--local-browser chrome|chromium]
```

- 必填参数:
  - `--account`
  - `--images`
  - `--title`
- 可选参数:
  - `--note`
  - `--tags`
  - `--schedule`
  - `--debug`
  - `--headless`
  - `--headed`

## 发布策略

- 如果不传 `--schedule`，CLI 使用立即发布
- 如果传了 `--schedule`，CLI 自动切换为定时发布
- 时间格式为:

```text
YYYY-MM-DDTHH:MM:00Z
```

## 额外说明

- `upload-video` 每次命令只支持一个视频文件
- `upload-note` 每次命令支持多张图片
- 视频描述字段统一使用 `--desc`
- 图文正文统一使用 `--note`
- `upload-note` 当前不支持 GIF
- `upload-note` 当前最多支持 35 张图片

## 浏览器、重建和提交结果

抖音 login/check/视频/图文及直接 uploader 使用 `browser_profiles/douyin/<原始别名>/<chrome|chromium>/`。默认系统 Chrome、有头；`LOCAL_CHROME_PATH` 非空优先，否则显式 `--local-browser chrome|chromium` > `LOCAL_BROWSER` > Chrome。显式 `--headed`/`--headless` > `LOCAL_CHROME_HEADLESS` > False，保留用户已有配置。只要求所选浏览器，失败不回退；Chrome 由用户安装，Chromium 用 `uv run patchright install --no-shell chromium`。预检与发布共用一个会话，浏览器保存完整状态，旧 Cookie JSON 不导入、读写或删除。

只有 login 引导扫码或验证；缺少 Profile、明确未登录/验证退出 `10`，网络、权限和页面故障退出 `1`。同别名可以重新登录另一真实账号，Chrome 与 Chromium 各自隔离。发布中遇到验证即结束本次任务；提交后退出 `10` 会附 `publish_attempted=true`，退出 `9` 表示结果未知，都先核对作品再决定重试。重建使用 `sau douyin reset-profile --account creator --browser-kind chrome`，无需 binary，拒绝占用，保留另一浏览器及历史结果；不会自动恢复发布任务。抖音没有 `--no-publish`，环境验证使用离线或受控页面，不能以真实提交验收。
