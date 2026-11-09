# 06 — AdsPower 模式的文档、术语与部署前提

Status: resolved
Type: grilling
Blocked by: 02, 04
Assignee: LukeChen

## Question

定义 AdsPower 模式交付时必须同步的文档、术语与运维前提。需要确认：

1. `GLOSSARY.md` 新增/调整哪些术语：AdsPower、Profile、`user_id`、Local API、API Key、AdsPower 模式、managed browser provider；现有 Multilogin 术语是否需要泛化。
2. `README.md`、`docs/CLI.md` 增加哪些章节：激活、参数矩阵、退出码、与 MLX 的差异、部署前提、示例命令。
3. 部署前提：AdsPower 付费版、桌面应用运行、API 已开启、`ADSPOWER_API_KEY` 有效、Profile 已人工登录且无验证码/2FA、TikTok Profile 界面 English (US)、`ADSPOWER_API_BASE` 何时需要；V2 端点要求较新的 AdsPower 客户端（官方未给最低版本，只写 latest patch），文档需写「升级到最新 patch」。
4. 调度侧责任：Profile 即身份、账号一致性不校验、并发/锁、登录失效退出 `10`、不要自动重发。
5. 安全：API key 只从环境变量读取，不写入 dataclass/日志/异常；`ADSPOWER_API_BASE` 的合法值。
6. Skills：`skills/*-upload/SKILL.md` 与 `skills/social-auto-upload/SKILL.md` 如何描述两种 managed 模式；是否需要逐平台改。
7. 迁移/兼容说明：未设置 `ADSPOWER_API_KEY` 时行为不变；同时设置两个变量退出 `1`。
8. 文档验收清单：哪些文件、哪些段落、哪些示例必须存在；如何验证没有把无 key 模式写成支持。
9. 是否更新 `CHANGELOG.md`；版本号策略。
10. 中文/英文术语一致性：`profile_id`、`user_id`、`folder_id` 在文档中的写法。

## Context

- 现有 Multilogin 文档：`README.md`、`docs/CLI.md`、`GLOSSARY.md`、`docs/skill-distribution.md`、`skills/`。
- 上一个 effort 的文档验收：`.scratch/multilogin-browser-mode/issues/26-docs-and-acceptance.md`。

## Answer

决议日期：2026-11-09（HITL grilling，逐题确认）。本 ticket 只产出文档规格，不执行文档修改；实施与验收在执行阶段完成，最终汇总进 ticket 08 的 `spec.md`。

### 1. 统一称法

- 统一称“托管浏览器模式（managed browser mode）”；下设两个 provider 子模式：`Multilogin X 模式（MLX）` 与 `AdsPower 模式`。
- 厂商名只出现在 provider 专属章节与词条中，不写进公共层标题。
- 禁用“云浏览器”“远程浏览器”“指纹浏览器模式”。

### 2. GLOSSARY.md

改为“泛化 + 分层”结构，头部语境从“Multilogin X 接入语境”改为“浏览器身份与上传语境”。

**通用层（跨 provider）**

- `托管浏览器模式（managed browser mode）`：由环境变量激活、通过 provider 启动/接管 Profile 并复用登录态的模式；本地模式的对立面。
- `Managed browser provider`：把 target 身份与 client 原语组合起来的抽象；MLX 与 AdsPower 各一份实现。
- `Profile`：泛化为“浏览器身份容器”：独立 Cookie、localStorage、指纹（及代理）配置；Profile 是托管模式下 Cookie 的唯一真相源。再注明 MLX 用 `folder_id + profile_id` 定位、AdsPower 用 `user_id`（V2 请求体字段 `profile_id`）定位。
- `Owned session（所有权）`：谁启动谁停止；本次调用 Start 成功的 Profile 才由本次调用 Stop。
- `Login required（登录失效）`：平台侧登录态无效；托管模式下以退出码 `10` 表达，不是 API key/token 失效。
- `Account label`：仅日志与上报标签；本地模式决定 cookie 文件名，托管模式下 `--account` 可省略且缺省取 `profile_id`，不代表身份校验。
- `Browser session`：一次“取得浏览器并交还”的生命周期单元；托管模式连接已有 Profile 上下文，只断开 CDP，不销毁浏览器。
- `本地模式`：保留现有定义，并明确“不设置任一托管模式环境变量”时仍走本地模式。
- 保留 `发布结果未知`、`set-then-readback`、`Photos tab / 图片帖` 词条。

**Multilogin X 专属**

- `Multilogin X`、`Folder`（MLX 专属）、`Launcher`（MLX 专属）、`Automation Token`（MLX 专属）、`Multilogin X 模式（MLX）`。

**AdsPower 专属**

- `AdsPower`：多账号隔离的浏览器 Profile 管理产品；Local API 仅付费版提供。
- `Local API`：AdsPower 桌面应用在本机暴露的 HTTP 接口，默认 `http://127.0.0.1:50325`，本 effort 只使用 V2。
- `API Key`：AdsPower 客户端 **Automation → API** 页面生成/重置的 Local API 凭据，请求以 `Authorization: Bearer <API Key>` 发送；不是 AdsPower 登录密码。
- `user_id`：AdsPower 的 Profile 标识；CLI 通过 `--profile-id` 传入，映射为 V2 请求体字段 `profile_id`。
- `AdsPower 模式`：由 `ADSPOWER_API_KEY` 激活的托管模式子模式。

### 3. docs/CLI.md

三层结构：

**`## 托管浏览器模式（通用）`**（新增）

- 激活与优先级矩阵：两个变量都未设置/空串/纯空白 → 本地；仅 `MLX_API_TOKEN` → MLX；仅 `ADSPOWER_API_KEY` → AdsPower；两个都非空 → 退出 `1`（固定文案 `MLX_API_TOKEN 与 ADSPOWER_API_KEY 不能同时设置；请只保留一个。`）。`ADSPOWER_API_BASE` 不参与激活。
- 参数矩阵：列本地 / MLX / AdsPower，覆盖 `--account`、`--folder-id`、`--profile-id`、缺参、`--headless`/`--headed`、`--debug`、`login`、`verify`/`delete`、未登录 `check`、Bilibili。
- 退出码表：`0` 成功、`1` 运行失败、`2` 用法错误、`9` 发布结果未知、`10` 需要登录、`11` 请求过于频繁（429，MLX 与 AdsPower 共用）、`130` 用户中断；写明 CLI 不 sleep、不自动重试。
- 平台支持范围：一张表覆盖 MLX 与 AdsPower（两者对齐）；按平台列 `check` / `upload-*`；Bilibili 不支持；`verify`/`delete`/`article` 仍走本地。
- 调度侧责任、账号一致性风险、安全（见 §7）。

**`## Multilogin X 模式`**（保留标题与锚点）

- 只留 MLX 专属：Launcher `https://launcher.mlx.yt:45001`、`folder_id` + `profile_id`、Automation Token、Mimic 内核、45001/45003、探活与 Docker 提示。
- 行为变更提示：429 由 `1` 改为 `11`，调度层应改为退避重试。

**`## AdsPower 模式`**（新增）

- `ADSPOWER_API_KEY` 激活、`ADSPOWER_API_BASE` 默认值与合法值、`--profile-id` → `user_id` 映射（只写一次映射句）、`--folder-id` 忽略、`--account` 仅标签。
- 只支持 V2 Local API，不做 V1 fallback；客户端升级到最新 patch。
- Bearer 与 key 重置说明：`Authorization: Bearer <API Key>`（一个空格，key 无首尾空白）；key 在 Automation → API 生成/重置，重置后旧 key 立即失效，必须停服务、换环境变量、重启；普通成员需被授予 API 权限。
- 部署前提、明确不支持、连不上三步排查（应用、API 开关、端口）。

### 4. README.md

- `#### Multilogin X 模式（可选）` 改名 `#### 托管浏览器模式（可选）`，下设 `##### Multilogin X（MLX）` 与 `##### AdsPower`（无入站锚点，改名安全）。
- 两个子节各给一组 `check` / `upload-video` 示例：MLX 用 `--folder-id` + `--profile-id`；AdsPower 只用 `--profile-id`。
- 保留并更新共同条目：激活、`--account` 仅标签、`login` 拒绝、退出码（含 `11` 与 MLX 429 变更）、部署前提、不支持、调度责任、身份风险、TikTok 本地模式说明。
- 功能表中 TikTok 行、按内容形态的“本地或 Multilogin X 模式”改为“本地或托管浏览器模式”；TikTok 示例区补 AdsPower 示例。
- 链接 `docs/CLI.md#multilogin-x-模式` 必须继续有效，并新增指向 `#adspower-模式` 的链接。

### 5. Skills（18 个文件）

统一模板（只替换 `<actions>`，由 `docs/CLI.md` 平台表决定）：

```markdown
## 托管浏览器模式（可选）

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，<actions> 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 两种模式下 `--account` 仅作日志标签，缺省为 `profile_id`；`login` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 退出码、部署前提与调度责任见 `docs/CLI.md` 的“托管浏览器模式（通用）”。
```

- 全部 17 个平台 Skill + `skills/social-auto-upload/SKILL.md` 都加；Bilibili 不套模板，只写“托管浏览器模式不支持 Bilibili（`biliup` 无浏览器上下文）”。
- `skills/tiktok-upload/SKILL.md` 的 frontmatter `description` / `summary` 与正文模式段同步改为“本地或托管浏览器模式（MLX / AdsPower）”。
- `skills/social-auto-upload/SKILL.md` 的 TikTok 行与模式说明同步。
- `docs/skill-distribution.md` 的 TikTok 行与平台表说明同步。
- 不复制共同契约长文，只链 `docs/CLI.md`。

### 6. 部署前提

**硬前提**

1. AdsPower 付费版（Local API 仅付费版提供）。
2. 桌面应用与 CLI 同一台 macOS/Windows 机器；桌面应用已启动；Local API 已开启；`50325` 未被占用。
3. `ADSPOWER_API_KEY` 有效；请求带 `Authorization: Bearer`。
4. Profile 为 Chromium 内核；Firefox 不支持。
5. Profile 已人工登录目标平台，无待处理验证码/2FA；TikTok Profile 界面 English (US)。
6. AdsPower 客户端升级到最新 patch（官方未给最低版本，文档只写“最新 patch”）。
7. `ADSPOWER_API_BASE` 默认 `http://127.0.0.1:50325`；仅在改端口或使用 `http://local.adspower.net:50325` 等官方地址时设置；禁止远程/跨机地址。
8. 同一 Profile 串行使用；CLI 不加锁、不做 active 预检。

**明确不支持**：无 key 安装（关闭 API 安全校验）、V1 API、Firefox Profile、Docker/跨机/无桌面 Linux、Bilibili、通过 CLI 登录、在 AdsPower 中创建/修改 Profile 或管理代理/Cookie。

**排查**：连不上时依次检查桌面应用、API 开关、端口。

### 7. 安全与调度责任

- 沿用现有 MLX 口径并泛化，不新造一套。
- 通用章节写：API key/token 只从环境变量读取，不写入命令行、日志、异常文本或 `repr`；`ADSPOWER_API_BASE` 合法值约束（`http/https`、必须有 host、端口可选、禁止 userinfo/path/query/fragment，末尾 `/` 归一化，非法退出 `2`）；文档示例不把 key 放进命令行。
- 调度侧责任：Profile 即身份；同一 Profile 串行；`10` 安排人工登录；`9` 禁止自动重发（平台中立的核对表述，保留 TikTok Studio 例子）；`11` 退避重试；`1` 运行失败，不与登录失效混淆；stop 失败只 warning，主操作成功仍返回 `0`，调度侧清理残留 Profile。
- AdsPower 专属增量：Bearer 说明、key 重置/旧 key 立即失效/需重启、`ADSPOWER_API_BASE` 取值。

### 8. 兼容与迁移

- 未设置 `ADSPOWER_API_KEY` 时，本地模式与 MLX 的参数解析、默认值、错误码保持不变。
- 同时设置 `MLX_API_TOKEN` 与 `ADSPOWER_API_KEY` → 退出 `1`，不是用法错误 `2`。
- 本 effort 唯一改变 MLX 可观察行为的是 429：`1` → `11`；需在 CLI 通用表、MLX 章节、README、CHANGELOG 四处体现。
- `verify` / `delete` / `article` 不受托管模式影响，仍走本地。

### 9. CHANGELOG 与版本

- 只更新 `[Unreleased]`，新增 `### 托管浏览器（AdsPower）`：新模式、`ADSPOWER_API_KEY` 激活、退出码 `11`、MLX 429 行为变更、真实 AdsPower 冒烟未执行。
- `pyproject.toml` 版本保持 `0.1.0`，发布时按现有流程 bump；不新增升级/迁移专文。

### 10. 术语书写规范

- 产品名正文一律 `AdsPower`；代码标识保留 `AdspowerProvider` / `AdspowerClient` / `utils/adspower.py`；环境变量 `ADSPOWER_API_KEY` / `ADSPOWER_API_BASE`。
- 字段名用小写蛇形 + 反引号：`profile_id`、`folder_id`、`user_id`，不翻译。
- CLI 参数只写 `--profile-id` / `--folder-id`，不出现 `--user-id`。
- 唯一映射句：AdsPower 模式下 `--profile-id` 映射 AdsPower 的 `user_id`（V2 请求体字段为 `profile_id`）。
- `Profile`、`Local API`、`API Key`、`Automation Token` 首字母大写；首次出现写“托管浏览器模式（managed browser mode）”，子模式固定为 `Multilogin X 模式（MLX）`、`AdsPower 模式`。

### 11. 文档验收

采用与 MLX ticket 26 相同的人工方式：**人工核对 + 文件清单**，不新增文档测试、不写 grep 断言。

必须存在的文件与内容：

| 文件 | 必须存在 |
| --- | --- |
| `GLOSSARY.md` | 分层术语；`Profile` 泛化；AdsPower 的 Local API / API Key / `user_id`；MLX 专属词标注 |
| `docs/CLI.md` | 三个章节；旧锚点可用；参数矩阵；退出码含 `11`；平台表；部署前提；调度责任；身份风险；安全；AdsPower 的 Bearer/重置；不支持清单 |
| `README.md` | `#### 托管浏览器模式（可选）` + 两个子节；两套示例；退出码含 `11` 与 MLX 429 提示；部署前提；调度责任；身份风险；功能表/内容形态表述 |
| `docs/skill-distribution.md` | TikTok 模式说明与表格条目 |
| `skills/social-auto-upload/SKILL.md` | 总入口模式说明 |
| `skills/<17 个平台>/SKILL.md` | 统一模板；Bilibili 为“不支持”特例 |
| `CHANGELOG.md` | `[Unreleased]` 的 `### 托管浏览器（AdsPower）` |
| 验收记录 | `.scratch/adspower-browser-mode/acceptance.md`：文件清单逐项核对；明确写“真实 AdsPower 冒烟未执行（ticket 09）” |

人工核对时额外确认：所有“无 key / 关闭安全校验”表述只出现在“不支持”语境；示例只展示 Bearer + `ADSPOWER_API_KEY` 路径；没有把未执行的真实冒烟写成已验证。
