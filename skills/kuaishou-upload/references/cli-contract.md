# 快手 CLI 契约

这个 skill 默认假设当前环境已经安装并可调用 `sau` 命令。

## 命令列表

### 登录

```bash
sau kuaishou login --account <account>
```

- 必填参数:
  - `--account`
- 作用:
  - 在所选本地持久化 Profile 引导快手扫码登录
  - 如果登录过程中生成本地二维码图片，agent 应优先直接把图片展示/发送给用户扫码，而不是只回传路径
- 账号说明:
  - `--account` 传的是用户自定义的 `account_name`，不是固定只能叫 `creator`
  - 原始别名与浏览器种类共同选择独立 Profile；同一 Profile 只能串行使用。别名可换号，不做永久身份绑定

### 检查登录

```bash
sau kuaishou check --account <account>
```

- 必填参数:
  - `--account`
- 预期输出:
  - `valid`：当前 Profile 已登录
  - 缺少 Profile 或明确未登录退出 `10`；探测/权限/页面故障退出 `1`

### 上传视频

```bash
sau kuaishou upload-video \
  --account <account> \
  --file <video-path> \
  --title "<title>" \
  [--desc "<description>"] \
  [--tags tag1,tag2] \
  [--schedule "YYYY-MM-DDTHH:MM:00Z"] \
  [--thumbnail <image-path>] \
  [--debug] \
  [--local-browser chrome|chromium] \
  [--headless | --headed]
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
  - `--collection`（现有合集名）
  - `--local-browser`
  - `--not-before`（带时区的客户端最早提交时刻）
  - `--debug`
  - `--headless`
  - `--headed`

### 上传图文

```bash
sau kuaishou upload-note \
  --account <account> \
  --images <image-1> [image-2 ...] \
  --title "<title>" \
  [--note "<content>"] \
  [--tags tag1,tag2] \
  [--schedule "YYYY-MM-DDTHH:MM:00Z"] \
  [--debug] \
  [--local-browser chrome|chromium] \
  [--headless | --headed]
```

- 必填参数:
  - `--account`
  - `--images`
  - `--title`
- 可选参数:
  - `--note`
  - `--tags`
  - `--schedule`
  - `--local-browser`
  - `--not-before`（带时区的客户端最早提交时刻）
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
- `upload-note` 当前要求传入真实的多张图片文件，而不是同一路径重复多次

## 配置、恢复与重建

四个动作都接受 `--local-browser chrome|chromium` 以及 `--headless` / `--headed`。默认 Chrome 有头，显式开关优先于 `LOCAL_CHROME_HEADLESS`；已有 True 配置继续生效。自定义 `LOCAL_CHROME_PATH` 优先，按实际 Chrome/Chromium 种类选资料；否则 CLI browser > `LOCAL_BROWSER` > chrome。仅要求所选来源，失败不回退，不修改语言或固定 viewport。

正常命令不接触旧 JSON。仅 login 引导扫码；check 和上传不会自动恢复登录。人机验证退出 `10` 并保留 `reason=verification`。提交后退出 `10` 带 `publish_attempted=true`，结果未知退出 `9`：均先人工核查作品，禁止自动重发。

```bash
sau kuaishou reset-profile --account <account> --browser-kind chrome
```

重建无需浏览器 binary，拒绝占用；只清空所选资料，历史结果保留。重建后先 login，不自动重跑发布。托管模式拒绝 login/reset-profile，check/两类上传仅采用 headless 配置并忽略本地 browser/path。
