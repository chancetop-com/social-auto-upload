# 故障排查

## 找不到 `sau` 命令

可以尝试以下方式：

```powershell
.\.venv\Scripts\Activate.ps1
sau xiaohongshu --help
```

```powershell
.\.venv\Scripts\sau.exe xiaohongshu --help
```

```bash
uv run sau xiaohongshu --help
```

如果当前环境还没有安装项目：

```bash
uv pip install -e .
```

## Profile 缺失或登录态失效

使用同一别名与浏览器种类检查：

```bash
sau xiaohongshu check --account <account>
```

退出 `10` 且未尝试提交时重新登录；人机验证先完成验证。网络/结构错误为 `1`，先排查故障，不按失效反复扫码。提交后带 `publish_attempted=true` 或退出 `9` 时先核对笔记是否已存在。

```bash
sau xiaohongshu login --account <account>
```

## 无头登录二维码处理

如果用户无法使用终端二维码输出：

- 查找 CLI 打印出来的临时二维码图片
- agent 不要只把图片路径回给用户
- agent 应优先直接把本地二维码图片展示/发送给用户扫码

如果终端二维码显示不正常，优先使用保存下来的图片路径，而不是反复尝试随机的终端设置。

## 上传参数缺失

### 视频上传

最少需要：

- `--account`
- `--file`
- `--title`

### 图文上传

最少需要：

- `--account`
- `--images`
- `--title`

`--note` 当前是可选图文正文。

## 定时发布

时间格式使用：

```text
YYYY-MM-DDTHH:MM:00Z
```

如果不需要定时发布，去掉 `--schedule` 即可改为立即发布。

## 浏览器与 Profile 故障

启动日志标明 source、browser_kind、headless 和 Profile 路径。只修复该来源，不自动改成另一浏览器或模式。占用时先结束拥有它的任务/浏览器；不删除锁或强制接管。只有用户明确要求丢弃该 Profile 时执行 `reset-profile --account <account> --browser-kind chrome|chromium`；旧 Cookie 文件既不恢复也不自动删除。
