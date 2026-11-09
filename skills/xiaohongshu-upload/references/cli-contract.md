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
  - 启动小红书登录流程，为指定账号生成或刷新 cookie 文件
  - 如果登录过程中生成本地二维码图片，agent 应优先直接把图片展示/发送给用户扫码，而不是只回传路径
- 账号说明:
  - `--account` 传的是用户自定义的 `account_name`，不是固定只能叫 `creator`
  - 一个 `account_name` 对应一个账号文件，可用于多账号隔离和并发任务

### 校验 cookie

```bash
sau xiaohongshu check --account <account>
```

- 必填参数:
  - `--account`
- 预期输出:
  - `valid`：cookie 可用
  - `invalid`：cookie 缺失或已失效

### 上传视频

```bash
sau xiaohongshu upload-video \
  --account <account> \
  --file <video-path> \
  --title "<title>" \
  [--desc "<description>"] \
  [--tags tag1,tag2] \
  [--schedule "YYYY-MM-DD HH:MM"] \
  [--thumbnail <image-path>] \
  [--original | --no-original] \
  [--content-type fiction|ai|marketing|self-shot|repost] \
  [--repost-source <media-name>] \
  [--shoot-location <location>] \
  [--shoot-date YYYY-MM-DD] \
  [--no-publish] \
  [--debug] \
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
  [--note "<content>"] \
  [--tags tag1,tag2] \
  [--schedule "YYYY-MM-DD HH:MM"] \
  [--original | --no-original] \
  [--content-type fiction|ai|marketing|self-shot|repost] \
  [--repost-source <media-name>] \
  [--shoot-location <location>] \
  [--shoot-date YYYY-MM-DD] \
  [--no-publish] \
  [--debug] \
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
  - `--original` / `--no-original`
  - `--content-type`（`repost` 时必须同时传 `--repost-source`）
  - `--repost-source`
  - `--debug`
  - `--headless`
  - `--headed`

## 发布策略

- 如果不传 `--schedule`，CLI 使用立即发布
- 如果传了 `--schedule`，CLI 自动切换为定时发布
- 时间格式为:

```text
YYYY-MM-DD HH:MM
```

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
- `--no-publish` 完成填写和声明后停止，不点击发布，适合回归验证。

## 额外说明

- `upload-video` 每次命令只支持一个视频文件
- `upload-note` 每次命令支持多张图片
- 视频描述字段统一使用 `--desc`
- 图文正文统一使用 `--note`
