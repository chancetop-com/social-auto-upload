# 更新说明

这个文档分成两部分：

- `For Humans`：给正常使用仓库的人看
- `For AI Agents`：给能执行命令和自动排查的 agent 看

## For Humans

### 1. 拉取最新代码

```bash
git pull
```

如果你平时是切分支开发，请先确认当前所在分支。

### 2. 更新本地可编辑安装

如果仓库最近改了 CLI、入口脚本、依赖配置，建议重新执行：

```bash
uv pip install -e .
```

### 3. 如有需要，更新浏览器依赖

升级时保留已有配置、账号文件、浏览器 Profile、素材及历史结果。既有 `conf.py`（包括 `LOCAL_CHROME_HEADLESS=True`）继续生效。升级本身不安装或检查浏览器：系统 Chrome 由用户管理，不自动重装/更新；只有选择 Chromium 且固定 Patchright 版本变化时，执行 `uv run patchright install chromium`，可加 `--no-shell`。安装和运行使用同一 Python 环境与浏览器缓存，只有 headless shell 不满足正式运行契约。已有兼容自定义 binary 可继续通过 `LOCAL_CHROME_PATH` 复用；托管动作无需本地 Chrome/Chromium。Linux 依赖与 Xvfb 见[安装说明](./install.md#可选-ci-环境两条独立路线)。

### 4. 更新后自检

用帮助和本地主题列表确认安装，用自己的别名检查已经登录的小红书 Profile：

```bash
sau --help
sau xiaohongshu --help
sau article themes
sau xiaohongshu check --account your_account
```

如果你在使用 skill，也建议同步看一下：

- `skills/xiaohongshu-upload/SKILL.md`
- `docs/CLI.md`

## For AI Agents

如果你是 agent，更新仓库后建议按下面顺序做最小验证：

1. 拉取最新代码：

```bash
git pull
```

2. 重新同步本地安装：

```bash
uv pip install -e .
```

3. 保留已有配置与 Profile，按实际选择来源执行上方按需浏览器准备；不自动安装或更新 Chrome。

4. 重新验证 CLI：

```bash
sau --help
sau xiaohongshu --help
sau article themes
```

5. 如果任务是浏览器平台链路，再继续验证：

```bash
sau xiaohongshu check --account test
```

6. 如果用户依赖 skill，再检查这些路径是否仍存在且契约没变：

- `skills/xiaohongshu-upload/SKILL.md`
- `skills/xiaohongshu-upload/references/cli-contract.md`
- `skills/xiaohongshu-upload/references/runtime-requirements.md`

### 对 agent 的额外说明

- 优先相信 `pyproject.toml` 中的依赖定义
- 当前 README 只做总览，安装和更新以 `docs/install.md`、`docs/update.md` 为准
- 如果更新后的登录流程输出了本地二维码图片，agent 应直接把图片展示/发送给用户扫码，不要只回传图片路径
