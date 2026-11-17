# 雪球长文

支持 UTF-8 HTML、Markdown、TXT 正文。图片写在原稿对应位置，程序上传本地图片并在该处插入；支持独立封面、公开/私人分享和创作声明。已使用正式 CLI 验证 HTML 结构、段间配图、封面、真实发表及后台原作品查询。

## 首次安装

先按[项目安装说明](./install.md)安装 Python 3.10–3.12、依赖和 `sau` 命令，并从 `conf.example.py` 复制生成本地 `conf.py`。保留已有 `conf.py`。默认选择系统 Chrome，只准备所选浏览器；显式 `--local-browser chromium` 使用项目固定 Patchright 配套的完整 Chromium，可用 `uv run patchright install --no-shell chromium` 安装。`LOCAL_CHROME_PATH` 非空时优先使用并识别实际产品种类，否则 `--local-browser` > `LOCAL_BROWSER` > chrome；启动失败不切换来源。

推荐使用 Markdown 原稿。需要 Node.js 22+，首次执行 `sau article setup` 安装渲染依赖。仓库提供带两张段间配图的 [Markdown 示例](../examples/xueqiu_article.md)，配图文件随仓库提供，直接从项目根目录运行：

```powershell
sau article setup
sau xueqiu upload-article --account creator --title "雪球文章示例" --content-file examples/xueqiu_article.md --visibility 私人 --declaration "本文包含AI生成内容" --prepare-only
```

运行前先按下一节登录。准备预览仍会自动保存远端草稿；确认内容后，实际发表时去掉 `--prepare-only`。

也支持 [HTML 示例](../examples/xueqiu_article.html)和 TXT，这两种格式不需要 Node.js。

## 登录一次

```powershell
sau xueqiu login --account creator --expected-name "你的雪球昵称"
sau xueqiu check --account creator
```

登录时在所选浏览器中完成验证；关闭后用同配置 check。login/check/文章/verify 共用 `browser_profiles/<chrome|chromium>/xueqiu/<原始别名>/`，由浏览器保存会话，旧 Cookie JSON 和身份旁文件不读写、不自动迁移。别名只管理资料，允许同别名换号，两种浏览器也可登录不同账号；`--expected-name` 仍核对本次明确请求，verify 继续核对原作品作者。账号密码无需写入命令或源码。

显式 `--headed`/`--headless` > `LOCAL_CHROME_HEADLESS` > False，login/check/文章/verify 和直接调用遵循同一优先级，保持当前语言和自然窗口。只在 login 引导登录；缺少 Profile、明确未登录或人机验证退出 10（验证带 `reason=verification`），网络、403、页面或必需身份字段故障退出 1。

重建一个明确种类：`sau xueqiu reset-profile --account creator --browser-kind chrome`。无需浏览器 binary，只清空指定叶子 Profile；占用时拒绝，保留另一种类及历史结果，之后重新 login。

### Multilogin X 模式

设置 `MLX_API_TOKEN` 后，`check` 与 `upload-article` 通过 `--folder-id/--profile-id` 使用 Multilogin Profile，不再读写 `cookies/*.json` 或 `.identity.json`，也不注入本地 Chrome 路径和时区；身份与浏览器指纹由 Profile 决定。`check` 只判断是否已登录，不校验账号一致性；调度侧需确保 `profile_id` 与目标账号匹配。登录页/验证码/二次验证返回退出码 10。

## 原稿与配图

Markdown 示例，图片路径相对于**原稿文件所在目录**：

```markdown
# 第一部分

图片前面的段落，含**加粗**文字。

![第一张配图](images/第一张.png)

## 第二部分

这段位于两张图片之间。

![第二张配图](images/第二张.jpg)

第二张图之后的结尾。
```

HTML 也使用同样的原稿顺序：

```html
<h1>第一部分</h1>
<p>图片前面的段落，含<strong>加粗</strong>文字。</p>
<img src="images/第一张.png">
<h2>第二部分</h2>
<p>这段位于两张图片之间。</p>
<img src="images/第二张.jpg">
<p>第二张图之后的结尾。</p>
```

Markdown 使用 `# 标题`、`## 小标题`、`**加粗**` 和 `![说明](images/配图.png)`。首次使用 Markdown 需要 Node.js 22+，在仓库中执行 `sau article setup` 安装现有渲染依赖。图片接受本地 GIF/JPEG/PNG，必须存在且非空；不接受网络图片地址或 data URL。

雪球采用自己的原生样式：各级标题统一为平台小标题；保留段落、加粗、斜体和链接；列表转为保留编号/圆点的段落；引用保留文字和段落。自定义颜色、字体、间距等 CSS 不保证保留，结果文件会列出发生的转换。表格、代码块、分隔线等尚未验证的结构会在创建远端草稿前明确报错。

## 发表

```powershell
sau xueqiu upload-article --account creator --title "文章标题" --content-file "文章.md" --declaration "本文包含AI生成内容"
```

不传 `--prepare-only` 就会实际发表。`--visibility` 可选 `公开`、`私人`，默认公开；测试或仅自己查看时明确传 `--visibility 私人`。`--declaration` 必须按实际情况选择 `不添加创作声明` 或 `本文包含AI生成内容`。

独立封面可选 `--cover "封面.png"`，采用平台默认裁剪区域。正文图片只从原稿读取，没有文末追加图片参数。标题须为非空单行，正文须有文字；大小及长度限制以平台校验为准。

只想检查时增加 `--prepare-only`。雪球在编辑时会自动保存远端草稿，此模式会核对预览并保存截图；重复运行可能新增草稿。若页面恢复了已有文章，程序会拒绝覆盖。`--debug` 保存失败截图。

## 结果与异常查询

发表成功返回 `status: published` 和作品 ID；程序核对最终受理的主体、标题、分享范围与正文，并在已发布管理列表按 ID 查询。`management_verified: true` 表示后台原作品查询也通过。私人文章显示“仅自己可见”，不代表未发表。

`prepared` 只表示草稿/预览检查完成。命令输出结果 JSON 路径，结果及截图保持原路径 `cookies/xueqiu_results/`，重建 Profile 不删除历史记录。

提交遇到超时或 `submission_unknown` 时，只查询原作品，不重复上传：

```powershell
sau xueqiu verify --account creator --result "本次结果文件.json"
```

此命令按结果文件中的原作品 ID、标题、账号及分享范围核对后台，并使用发表时记录的原稿路径重查后台正文和图片。查询前请保留原稿和图片且不要修改内容；原稿改变时明确报错。旧版未记录原稿路径的成功结果仅核查作品身份和分享范围，不代表重新验证正文。没有 ID 时应先在后台按标题和时间核查，不直接重跑发表。平台已受理但后续检查报错时，保留该 ID 查询，避免重复作品。

本次账号的完整长文表单没有观察到定时设置；视频、Word 导入、自定义封面裁剪、@好友、话题和股票关联尚未接入。

## 开发验证

以下跨浏览器测试需要系统 Chrome、完整 Chromium 和 `sau article setup` 的渲染依赖；正常运行只需所选浏览器。准备后执行：

```powershell
python -m unittest tests.test_xueqiu_profiles tests.test_xueqiu_uploader tests.test_xueqiu_humanize tests.test_xueqiu_profile_dom -v
```

这些测试使用临时文件、本地浏览器页面和模拟查询响应，不需要雪球账号，也不会发表文章。分页查询包含模拟测试；不同系统和账号仍需在各自环境验证，历史真实发表验收环境为 Windows Chrome；本次持久化迁移仅验证离线流程和隔离合成浏览器页面，未操作真实账号或发表。
