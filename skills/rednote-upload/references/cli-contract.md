# Rednote CLI 契约

执行前以 `sau rednote <子命令> --help` 核对安装版本的参数。`login`、`check`、`upload-video`、`upload-note` 使用独立的 Rednote 账号；本地模式需要 `--account`。

## 发布前准备

```bash
sau rednote upload-video --account creator \
  --file videos/demo.mp4 --title "Hello rednote" \
  --desc "Video description" --no-publish

sau rednote upload-note --account creator \
  --images videos/1.png videos/2.png --title "Hello rednote" \
  --note "Photo description" --no-publish
```

`--no-publish` 会上传素材、填写页面，在发布按钮就绪后停止；成功输出 `prepared (not published)`。省略该参数会尝试提交，仅在用户要求发布时使用。视频封面用 `--thumbnail <文件>`；标签用 `--tags tag1,tag2`。

## 原创与内容声明

默认保持平台声明设置；用户指定时才传以下参数：

| 参数 | 要求 |
| --- | --- |
| `--original` / `--no-original` | 开启或关闭原创，二者互斥 |
| `--content-type fiction` | 虚构演绎 |
| `--content-type ai` | AI 合成内容 |
| `--content-type marketing` | 营销广告 |
| `--content-type self-shot` | 同时提供 `--shoot-location <完整地点名称>` 和 `--shoot-date YYYY-MM-DD` |
| `--content-type repost` | 同时提供 `--repost-source <媒体名称>` |

当前 CLI 拒绝 `--original` 与 `repost` 组合，也拒绝 `--no-original` 与 `self-shot` / `repost` 组合。来源与拍摄字段仅用于对应内容类型。

实际页面在视频不足 10 秒或来源转载时禁用原创。地点须匹配建议列表中的完整名称，重名时停止。显式封面或声明设置、回读失败时命令退出，不会跳过该选项继续发布。

## 时间

`--schedule YYYY-MM-DDTHH:MM:00Z` 是平台定时，精确到分钟；`--not-before YYYY-MM-DDTHH:MM:SSZ` 是客户端提交等待，保留秒。均使用 UTC，先将用户提供的时区时间换算为 UTC。两者同时使用时，`--not-before` 应早于 `--schedule`；`--no-publish` 跳过客户端等待并停在就绪点。

## 结果与恢复

| 退出码 | 处理 |
| --- | --- |
| `0` | 按输出区分干跑准备完成和已提交 |
| `1` | 按错误上下文排查；保留明确失败的选项 |
| `2` | 修正参数后重试 |
| `9` | 发布结果未知，先人工核对作品，禁止自动重发 |
| `10` | 恢复登录或完成人机验证；若有 `publish_attempted=true`，先核对作品 |
| `11` | 托管服务限流，等待后再运行 |

托管模式由 `MLX_API_TOKEN` 或 `ADSPOWER_API_KEY` 二选一启用；MLX 需要 `--folder-id` 与 `--profile-id`，AdsPower 需要 `--profile-id`。先在 Profile 人工登录，CLI `login` 仅用于本地。托管模式忽略 `--account`、保留 Profile 设置、不读写本地 cookie。

已验收本地登录、扫码、图文/视频发布前准备、封面、五种声明、原创开关、话题和定时回读。实际英文后台、真实托管 Profile 及最终提交仍待验收。
