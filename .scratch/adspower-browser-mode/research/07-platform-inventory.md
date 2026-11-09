# 07 — 逐平台迁移清单与能力对齐

基线与方法：`ee79dec`（2026-11-06）。下文所有 `文件:行` 均为当前工作树实测；统计口径为 `grep -rn`（含单双引号变体），不含 `def` 定义行。

本文件只记录事实，不新增设计决策。设计结论以 01/02/03/04/05/06/10 已解决的 ticket 为准。

---

## 1. CLI 入口与平台清单

- 入口：`sau_cli.py:18-37` 的 `PLATFORMS` 共 **18 个命令名**：`article`、`douyin`、`kuaishou`、`xiaohongshu`、`bilibili`、`tencent`、`alipay`、`weibo`、`hupu`、`facebook`、`facebook-page`、`instagram`、`youtube`、`baijiahao`、`dayu`、`xueqiu`、`zhihu`、`tiktok`。
- 每个平台在 `sau_commands/<platform>.py:register()` 中声明子命令；`sau_cli.py:40-46` 统一装配。
- `sau_cli.py:54-59` 在 `dispatch()` 中为手工构造的 `Namespace` 补齐 `folder_id` / `profile_id` / `account`，说明这三个字段是跨平台的隐式契约。
- `sau_cli.py:69-83` 退出码映射：`LoginRequiredError → 10`、`UsageError → 2`、`PublishResultUnknownError → 9`、其它 `Exception → 1`。当前**没有** 429 分支，也没有 provider 冲突分支。

---

## 2. `sau_commands/*` 对 `sau_commands.multilogin` 的依赖

### 2.1 import 点（17 个平台模块）

| 模块 | import 行 |
|---|---|
| `sau_commands/alipay.py` | 23 |
| `sau_commands/baijiahao.py` | 22 |
| `sau_commands/bilibili.py` | 15 |
| `sau_commands/dayu.py` | 38 |
| `sau_commands/douyin.py` | 29 |
| `sau_commands/facebook.py` | 27 |
| `sau_commands/facebook_page.py` | 28 |
| `sau_commands/hupu.py` | 23 |
| `sau_commands/instagram.py` | 27 |
| `sau_commands/kuaishou.py` | 28 |
| `sau_commands/tencent.py` | 26 |
| `sau_commands/tiktok.py` | 24 |
| `sau_commands/weibo.py` | 23 |
| `sau_commands/xiaohongshu.py` | 29 |
| `sau_commands/xueqiu.py` | 25 |
| `sau_commands/youtube.py` | 24 |
| `sau_commands/zhihu.py` | 30 |

`sau_commands/article.py` 不依赖；`sau_commands/multilogin.py` 自身是定义处。

### 2.2 调用点统计（实测）

| 函数 | 调用点数 | 说明 |
|---|---:|---|
| `add_multilogin_flags` | **41** | 只出现在 `check` 与 `upload-*` 解析器；`login` / `verify` / `delete` / bilibili 一律没有 |
| `resolve_multilogin_target` | **16** | 每个走浏览器会话的平台各 1 处；bilibili 没有 |
| `resolve_account_label` | **17** | 16 个浏览器平台 + bilibili |
| `require_local_account` | **33** | login 与 run 两侧都会调用 |
| `require_account` | **7** | 仅本地动作（`verify` / `delete`）与 zhihu/xueqiu/facebook 等的 else 分支 |
| `reject_multilogin_login` | **17** | 16 个浏览器平台 + bilibili |
| `reject_multilogin_platform` | **1** | 仅 `sau_commands/bilibili.py:123` |
| `login_required_error` | **14** | 14 个平台命令级登录拒绝 |
| `multilogin_enabled` | **5** | 仅定义模块内部使用 + 测试 |

> 与 `map.md:29` 的“`add_multilogin_flags` 32 个调用点、`resolve_multilogin_target` 35 个调用点”不一致：按当前 HEAD 实测为 **41 / 16**。实现 ticket 03/05 时应以本清单为准，map 的数字疑似来自旧提交或不同统计口径。

### 2.3 `add_multilogin_flags` 的逐平台落点

| 平台 | 落点（行） | 数量 |
|---|---|---:|
| alipay | 45, 56 | 2 |
| baijiahao | 44, 55 | 2 |
| dayu | 61, 77, 92 | 3 |
| douyin | 52, 72, 84 | 3 |
| facebook | 75, 91, 101 | 3 |
| facebook-page | 70, 83, 97 | 3 |
| hupu | 45, 55 | 2 |
| instagram | 53, 64, 75 | 3 |
| kuaishou | 50, 62, 72 | 3 |
| tencent | 48, 65 | 2 |
| tiktok | 152, 177, 221 | 3 |
| weibo | 45, 56 | 2 |
| xiaohongshu | 51, 62, 72 | 3 |
| xueqiu | 104, 121 | 2 |
| youtube | 46, 60 | 2 |
| zhihu | 65, 82, 101 | 3 |
| **合计** | | **41** |

### 2.4 关键语义事实

- `sau_commands/multilogin.py:27-29`：`multilogin_enabled()` **只**读 `MLX_API_TOKEN`。AdsPower key 单独存在时它返回 `False`。
- 因此以下函数在 AdsPower 模式下会“误判本地”：
  - `resolve_multilogin_target()`（`:46-58`）→ 返回 `None`，平台走本地分支；
  - `resolve_account_label()`（`:61-71`）→ 不把 `profile_id` 当标签；
  - `require_local_account()`（`:74-78`）→ 在 AdsPower 模式下错误地要求 `--account`；
  - `reject_multilogin_login()`（`:101-107`）→ 不拒绝 login；
  - `reject_multilogin_platform()`（`:110-114`）→ 不拒绝 bilibili。
- 结论：ticket 03 的 `resolve_managed_provider` / `reject_managed_login` / `reject_managed_platform` 不是“改名洁癖”，而是 AdsPower 激活正确性的必要条件。16 个浏览器平台模块与 bilibili 都必须迁移到 provider-aware 判定（或让 shim 的新语义覆盖旧名）。

---

## 3. `utils` 生命周期接缝

- `utils/browser_session.py:45-49`：`BrowserSession.mode: Literal["local", "multilogin"]`，无 `managed` 属性。
- `utils/browser_session.py:52-92`：`browser_session(..., multilogin: MultiloginTarget | None = None, ...)`；分发条件为 `if multilogin is None`。
- `utils/browser_session.py:95-148`：`_local_session`。
- `utils/browser_session.py:151-201`：`_multilogin_session`；读 `MLX_API_TOKEN`（`:158-162`），probe/start 在 `try` 外（`:166-174`），contexts 必须为 1（`:185-190`），`finally` 中 disconnect 后 stop（`:196-201`）。
- `utils/browser_session.py:204-240`：`_connect_over_cdp`，固定 `http://127.0.0.1:{port}`、3 次、2s/4s backoff。
- `utils/multilogin.py:33-42`：`MultiloginTarget`；`:44-176`：`MultiloginClient` 的 `probe/start/stop/status`，同步 `requests.get`，可注入 `http_get`。
- `utils/errors.py` 当前只有 `LoginRequiredError` / `PublishResultUnknownError` / `UsageError`，**没有** `RateLimitedError` / `StartIncompleteError`。

### 3.1 `browser_session(...)` 调用点（36 处，16 个模块）

| 平台 | 行 |
|---|---|
| alipay | 110, 156 |
| baijiahao | 97, 154 |
| dayu | 126, 160 |
| douyin | 180, 210, 254 |
| facebook | 161, 249 |
| facebook-page | 160, 214 |
| hupu | 103, 127, 158 |
| instagram | 139, 193 |
| kuaishou | 153, 183, 227 |
| tencent | 125, 194 |
| tiktok | 452, 524 |
| weibo | 110, 156 |
| xiaohongshu | 152, 182, 226 |
| xueqiu | 56, 76 |
| youtube | 113, 159 |
| zhihu | 111, 141 |

bilibili 与 article 没有 `browser_session` 调用。

> `map.md:29` / ticket 03 §8 的“35 个调用点”与实测 36 略有差异；以本表为准。

---

## 4. uploader 的 `multilogin=` 接缝

### 4.1 `session.mode == "multilogin"` 判定（**28 处，18 个文件，全部在 `uploader/`**）

| 文件 | 行 | 备注 |
|---|---|---|
| `uploader/alipay_uploader/main.py` | 820 | 赋给局部 `multilogin` |
| `uploader/baijiahao_uploader/main.py` | 443 | 同上 |
| `uploader/dayu_uploader/main.py` | 209 | 同上 |
| `uploader/dayu_uploader/article.py` | 281 | 同上 |
| `uploader/douyin_uploader/main.py` | 1086, 1095, 1374 | 视频与图文 |
| `uploader/hupu_uploader/main.py` | 480 | |
| `uploader/ks_uploader/main.py` | 758, 764, 1042, 1047 | 视频与图文 |
| `uploader/meta_uploader/facebook_uploader/main.py` | 341, 344 | 直接 if |
| `uploader/meta_uploader/facebook_page_uploader/main.py` | 523, 531 | 直接 if |
| **`uploader/meta_uploader/insgraph_uploader/main.py`** | **446, 456** | **单引号 `'multilogin'`，静态守卫最容易漏改** |
| `uploader/tencent_uploader/main.py` | 1274, 1407 | 视频与图文 |
| `uploader/tk_uploader/main_chrome.py` | 1122 | |
| `uploader/weibo_uploader/main.py` | 461 | |
| `uploader/xiaohongshu_uploader/main.py` | 830, 975 | 视频与图文 |
| `uploader/xueqiu_uploader/article.py` | 258 | |
| `uploader/youtube_uploader/main.py` | 358 | |
| `uploader/zhihu_uploader/article.py` | 249 | |
| `uploader/zhihu_uploader/video.py` | 245 | |

合计 **28**，与 ticket 05 §6 的基线一致（含 `insgraph_uploader/main.py:446/456` 两处单引号）。

### 4.2 `multilogin: bool` 内部参数（26 处，13 个文件）

`alipay`、`baijiahao`、`dayu/article`、`douyin`、`hupu`、`ks`、`tencent`、`tk`、`weibo`、`xiaohongshu`、`xueqiu/article`、`youtube`、`zhihu/article`。

ticket 03 §5 已裁决：阶段 1 **不重命名**这些内部 bool 参数，只把传值来源从 `session.mode == "multilogin"` 换成 `session.managed`。改名登记为可选清理。

### 4.3 上传器入口（接收 `session=` 的方法）

| 平台 | 入口类/方法 | 关键行 |
|---|---|---|
| alipay | `AlipayVideo.upload / upload_in` | `uploader/alipay_uploader/main.py:786,819` |
| baijiahao | `BaiJiaHaoVideo.upload / upload_in` | `uploader/baijiahao_uploader/main.py:411,442` |
| dayu | `DayuVideo.main/upload_in`、`DayuArticle.main/upload_in` | `main.py:189,207`；`article.py:261,279` |
| douyin | `DouYinVideo.upload/upload_in`、`DouYinNote.upload/upload_in` | `main.py:1053,1083,1337,1371` |
| facebook | `FacebookPost.upload_in/upload` | `meta_uploader/facebook_uploader/main.py:336,347` |
| facebook-page | `MetaBusinessUploader.upload_in/upload` | `meta_uploader/facebook_page_uploader/main.py:518,537` |
| hupu | `HuPuVideo.upload/upload_in` | `uploader/hupu_uploader/main.py:449,478` |
| instagram | `InstagramUploader.upload_in/upload` | `meta_uploader/insgraph_uploader/main.py:441,466` |
| kuaishou | `KSVideo` / `KSNote` 的 `upload/upload_in` | `uploader/ks_uploader/main.py:721,755,1005,1039` |
| tencent | `TencentVideo` / `TencentNote` 的 `upload/upload_in` | `uploader/tencent_uploader/main.py:1242,1273,1373,1406` |
| tiktok | `TiktokVideo.upload`、`TiktokNote.upload` | `uploader/tk_uploader/main_chrome.py:2686,3275` |
| weibo | `WeiBoVideo.upload/upload_in` | `uploader/weibo_uploader/main.py:427,460` |
| xiaohongshu | `XiaoHongShuVideo` / `XiaoHongShuNote` 的 `upload/upload_in` | `uploader/xiaohongshu_uploader/main.py:798,827,943,972` |
| xueqiu | `XueqiuArticle.main/upload_in` | `uploader/xueqiu_uploader/article.py:223,249` |
| youtube | `YouTubeVideo.upload/upload_in` | `uploader/youtube_uploader/main.py:313,351` |
| zhihu | `ZhihuArticle.main/upload_in`、`ZhihuVideo.main/upload_in` | `article.py:208,235`；`video.py:203,229` |
| bilibili | 无浏览器会话；`run_biliup_command` 子进程 | `sau_commands/bilibili.py:86-116`；`uploader/bilibili_uploader/runtime.py:178` |

---

## 5. 测试覆盖矩阵

### 5.1 平台级 MLX 覆盖

| 平台 | 测试文件 | 主要类 |
|---|---|---|
| alipay | `tests/test_mlx_alipay_weibo.py` | `AlipayLocalGoldenTests`、`AlipayMultiloginTests`、`AlipayIsLoggedInTests`、`AlipayCliTests` |
| weibo | 同上 | `WeiboLocalGoldenTests`、`WeiboMultiloginTests`、`WeiboIsLoggedInTests`、`WeiboCliTests` |
| hupu | `tests/test_mlx_hupu_dayu.py` | `HupuLocalGoldenTests`、`HupuMultiloginUploadTests`、`HupuCliTests` |
| dayu | 同上 | `DayuLocalGoldenTests`、`DayuMultiloginUploaderTests`、`DayuCliTests` |
| facebook | `tests/test_mlx_meta.py` | `LocalGoldenTests`、`MultiloginUploaderTests`、`FacebookCliTests` |
| facebook-page | 同上 | 同上 + `FacebookPageCliTests` |
| instagram | 同上 | 同上 + `InstagramCliTests` |
| tencent | `tests/test_mlx_tencent_baijiahao.py` | `TencentLocalGoldenTests`、`TencentMultiloginUploadTests`、`TencentCheckCliTests`、`TencentUploadCliTests` |
| baijiahao | 同上 | `BaijiahaoLocalGoldenTests`、`BaijiahaoMultiloginUploadTests`、`BaijiahaoCheckCliTests`、`BaijiahaoUploadCliTests` |
| tiktok | `tests/test_mlx_tiktok.py` | `TiktokParserTests`、`MlxLoginRejectionTests`、`UploaderSeamTests`、`TiktokCheckCliTests`、`TiktokUploadCliTests`、`StopOwnershipTests` |
| xiaohongshu | `tests/test_mlx_xhs_kuaishou.py` | `LocalGoldenTests`、`MultiloginSeamTests`、`XhsCliTests` |
| kuaishou | 同上 | 同上 + `KuaishouCliTests` |
| youtube | `tests/test_mlx_youtube.py` | `LegacyLocalUploadTests`、`MultiloginUploadTests`、`YouTubeMlxCliTests` |
| zhihu | `tests/test_mlx_zhihu_xueqiu.py` | `ZhihuLocalGoldenTests`、`MultiloginUploaderSeamTests`、`ZhihuMlxCliCheckTests`、`ZhihuMlxCliUploadTests` |
| xueqiu | 同上 | `XueqiuLocalGoldenTests`、`XueqiuMlxCliTests` |
| douyin | `tests/test_douyin_mlx_check.py`、`tests/test_douyin_upload_seam.py` | `DouyinCheckCliTests`、`LegacyLocalUploadTests`、`MultiloginUploadTests`、`DouyinMlxCliUploadTests` |
| bilibili | `tests/test_sau_bilibili_cli.py`、`tests/test_bilibili_runtime.py` | 仅本地；无 MLX 用例 |
| article | 无 MLX 用例 | 纯本地工具 |

### 5.2 跨平台测试

| 文件 | 覆盖 |
|---|---|
| `tests/test_multilogin_cli.py` | 激活、parser 注册范围、helper 语义、退出码（`ActivationTests` / `ParserContractTests` / `HelperTests` / `UsageAndExitCodeTests`） |
| `tests/test_multilogin_client.py` | client probe/start/stop/status 协议与脱敏 |
| `tests/test_browser_session.py` | 本地生命周期 + MLX 生命周期/所有失败面 |
| `tests/test_mlx_smoke.py` | opt-in 真实 MLX 冒烟（默认 skip） |
| `tests/fakes.py` | `FakePlaywright` / `FakeContext` / `FakePage` 等 |

### 5.3 改名/改签名后会直接受影响的断言

**直接传 `multilogin=` 给 `browser_session()` 的测试调用点（15 处，3 个文件）：**

| 文件 | 行 |
|---|---|
| `tests/test_browser_session.py` | 260, 295, 313, 335, 357, 385, 408, 428, 448, 469, 491, 512, 540（13 处） |
| `tests/test_mlx_smoke.py` | 377（1 处） |
| `tests/test_mlx_hupu_dayu.py` | 405（1 处，`HupuMultiloginUploadTests.test_browser_session_mlx_ignores_context_setup_and_local_kwargs`） |

> **与 ticket 03/05 的潜在冲突**：ticket 03 §8 决定“不做 `multilogin=` 别名，一次性改名 `managed=`”；ticket 05 §5 又要求“8 个 `test_mlx_*.py` 零改动”。但 `test_mlx_smoke.py:377` 与 `test_mlx_hupu_dayu.py:405` 直接调用 `browser_session(multilogin=...)`，签名改名后不可能零改动。**ticket 08 汇总时需要二选一**：允许这两个文件各改 1 行，或保留 `multilogin=` 仅用于 `browser_session` 的兼容别名（与 ticket 03“不做别名”冲突）。建议在规格中明确豁免这两处，而不是声称 8 个文件绝对零改动。

**只断言上传器内部 `multilogin=` bool 的位置（阶段 1 不改名，理论上零改动）：**

- `tests/test_mlx_alipay_weibo.py:379-380, 618-620, 674`
- `tests/test_mlx_hupu_dayu.py:1035, 1040, 1078`
- `tests/test_mlx_tencent_baijiahao.py:389-393, 459-463, 518-519`
- `tests/test_mlx_tiktok.py:865, 1054, 1070, 1081, 1091`
- `tests/test_mlx_xhs_kuaishou.py:494, 513`
- `tests/test_mlx_youtube.py:352`
- `tests/test_mlx_zhihu_xueqiu.py:477, 504, 554, 559, 566`
- `tests/test_douyin_upload_seam.py:256`
- `tests/test_tiktok_exit_codes.py`（12 处）
- `tests/test_tiktok_note_cli.py`（1 处）
- `tests/test_tiktok_settings.py`（2 处）

这些断言在 ticket 03 §5 的方案下应保持零改动；若实现者顺手重命名内部 bool 参数，它们会全部变红。

**`mode="multilogin"` 构造点：** 平台测试直接构造 `BrowserSession(..., mode="multilogin")`，改造后上传器看 `session.managed`；因此这些构造需要 `managed` 属性由 `mode` 派生（ticket 05 真值表），构造本身可以不改。

---

## 6. 平台 × 模式 × action 矩阵

图例：**✓** 支持；**✗** 不支持/被拒绝；**本地** 表示即使设置 key 也仍走本地模式；**→** 与左边同义。

| 平台 | action | 本地 | MLX | AdsPower | 依据 |
|---|---|:--:|:--:|:--:|---|
| **article** | themes / setup / render | ✓ | ✓ | ✓ | `sau_commands/article.py:9-20`；无账号/浏览器 |
| **alipay** | login | ✓ | ✗ | ✗ | `alipay.py:140-142` |
| | check | ✓ | ✓ | ✓ | `alipay.py:45,153` |
| | upload-video | ✓ | ✓ | ✓ | `alipay.py:56,171` |
| **baijiahao** | login | ✓ | ✗ | ✗ | `baijiahao.py:138-140` |
| | check | ✓ | ✓ | ✓ | `baijiahao.py:44,151` |
| | upload-video | ✓ | ✓ | ✓ | `baijiahao.py:55,172` |
| **bilibili** | login | ✓ | ✗ | ✗ | `bilibili.py:120-123` |
| | check | ✓ | ✗ | ✗ | `bilibili.py:123,135` |
| | upload-video | ✓ | ✗ | ✗ | `bilibili.py:123,140` |
| **dayu** | login | ✓ | ✗ | ✗ | `dayu.py:143-145` |
| | check | ✓ | ✓ | ✓ | `dayu.py:61,157` |
| | upload-video | ✓ | ✓ | ✓ | `dayu.py:77,187` |
| | upload-article | ✓ | ✓ | ✓ | `dayu.py:92,199` |
| | verify | ✓ | ✓（仍本地） | ✓（仍本地） | `dayu.py:93-101,211`；无 profile flags |
| **douyin** | login | ✓ | ✗ | ✗ | `douyin.py:238-240` |
| | check | ✓ | ✓ | ✓ | `douyin.py:52,251` |
| | upload-video | ✓ | ✓ | ✓ | `douyin.py:72,274` |
| | upload-note | ✓ | ✓ | ✓ | `douyin.py:84,297` |
| **facebook** | login | ✓ | ✗ | ✗ | `facebook.py:216-218` |
| | check | ✓ | ✓ | ✓ | `facebook.py:75,246` |
| | upload-video | ✓ | ✓ | ✓ | `facebook.py:91,288` |
| | upload-note | ✓ | ✓ | ✓ | `facebook.py:101,267` |
| | verify | ✓ | ✓（仍本地） | ✓（仍本地） | `facebook.py:227-244`；无 profile flags |
| | delete | ✓ | ✓（仍本地） | ✓（仍本地） | 同上 |
| **facebook-page** | login | ✓ | ✗ | ✗ | `facebook_page.py:185-188` |
| | check | ✓ | ✓ | ✓ | `facebook_page.py:70,211` |
| | upload-video | ✓ | ✓ | ✓ | `facebook_page.py:83,232` |
| | upload-note | ✓ | ✓ | ✓ | `facebook_page.py:97,232` |
| | verify | ✓ | ✓（仍本地） | ✓（仍本地） | `facebook_page.py:194-209` |
| | delete | ✓ | ✓（仍本地） | ✓（仍本地） | 同上 |
| **hupu** | login | ✓ | ✗ | ✗ | `hupu.py:142-144` |
| | check | ✓ | ✓ | ✓ | `hupu.py:45,155` |
| | upload-video | ✓ | ✓ | ✓ | `hupu.py:55,173` |
| **instagram** | login | ✓ | ✗ | ✗ | `instagram.py:163-165` |
| | check | ✓ | ✓ | ✓ | `instagram.py:53,190` |
| | upload-video | ✓ | ✓ | ✓ | `instagram.py:64,215` |
| | upload-note | ✓ | ✓ | ✓ | `instagram.py:75,215` |
| | verify | ✓ | ✓（仍本地） | ✓（仍本地） | `instagram.py:172-186` |
| | delete | ✓ | ✓（仍本地） | ✓（仍本地） | 同上 |
| **kuaishou** | login | ✓ | ✗ | ✗ | `kuaishou.py:211-213` |
| | check | ✓ | ✓ | ✓ | `kuaishou.py:50,224` |
| | upload-video | ✓ | ✓ | ✓ | `kuaishou.py:62,244` |
| | upload-note | ✓ | ✓ | ✓ | `kuaishou.py:72,262` |
| **tencent** | login | ✓ | ✗ | ✗ | `tencent.py:178-180` |
| | check | ✓ | ✓ | ✓ | `tencent.py:48,191` |
| | upload-video | ✓ | ✓ | ✓ | `tencent.py:65,214` |
| **tiktok** | login | ✓ | ✗ | ✗ | `tiktok.py:502-505`；`test_mlx_tiktok.py:MlxLoginRejectionTests` |
| | check | ✓ | ✓ | ✓ | `tiktok.py:152,521` |
| | upload-video | ✓ | ✓ | ✓ | `tiktok.py:177,565` |
| | upload-note | ✓ | ✓ | ✓ | `tiktok.py:221,542` |
| **weibo** | login | ✓ | ✗ | ✗ | `weibo.py:140-142` |
| | check | ✓ | ✓ | ✓ | `weibo.py:45,153` |
| | upload-video | ✓ | ✓ | ✓ | `weibo.py:56,171` |
| **xiaohongshu** | login | ✓ | ✗ | ✗ | `xiaohongshu.py:210-212` |
| | check | ✓ | ✓ | ✓ | `xiaohongshu.py:51,223` |
| | upload-video | ✓ | ✓ | ✓ | `xiaohongshu.py:62,245` |
| | upload-note | ✓ | ✓ | ✓ | `xiaohongshu.py:72,266` |
| **xueqiu** | login | ✓ | ✗ | ✗ | `xueqiu.py:128-130` |
| | check | ✓ | ✓ | ✓ | `xueqiu.py:104,145` |
| | upload-article | ✓ | ✓ | ✓ | `xueqiu.py:121,149` |
| | verify | ✓ | ✓（仍本地） | ✓（仍本地） | `xueqiu.py:107-111,140`；无 profile flags |
| **youtube** | login | ✓ | ✗ | ✗ | `youtube.py:143-145` |
| | check | ✓ | ✓ | ✓ | `youtube.py:46,156` |
| | upload-video | ✓ | ✓ | ✓ | `youtube.py:60,174` |
| **zhihu** | login | ✓ | ✗ | ✗ | `zhihu.py:160-162` |
| | check | ✓ | ✓ | ✓ | `zhihu.py:65,177` |
| | upload-article | ✓ | ✓ | ✓ | `zhihu.py:82,183` |
| | upload-video | ✓ | ✓ | ✓ | `zhihu.py:101,183` |
| | verify | ✓ | ✓（仍本地） | ✓（仍本地） | `zhihu.py:68-72,181`；无 profile flags |

**汇总：**

- 浏览器平台 16 个：alipay、baijiahao、dayu、douyin、facebook、facebook-page、hupu、instagram、kuaishou、tencent、tiktok、weibo、xiaohongshu、xueqiu、youtube、zhihu。
- 纯本地平台 2 个：`article`（工具命令）、`bilibili`（biliup 子进程）。
- `verify` / `delete` 只在 5 个平台存在：dayu（verify）、facebook（verify/delete）、facebook-page（verify/delete）、instagram（verify/delete）、xueqiu（verify）、zhihu（verify）——共 6 个平台命令对象、9 个 action；全部仅本地。
- `login` 在所有 17 个有账号概念的平台上都拒绝托管模式。

---

## 7. 平台特有约束

### 7.1 身份绑定（Profile 即身份）

| 平台 | 事实 | 依据 |
|---|---|---|
| dayu | MLX 下 `expected = None`，读本地 `.identity.json` 只在本地分支；日志提示“以 Profile 为身份”且不写时区 | `uploader/dayu_uploader/main.py:209-210`；`sau_commands/dayu.py:109-121,137` |
| zhihu | MLX 下不读 cookie/identity；登录检测后只打“身份未校验”日志 | `sau_commands/zhihu.py:47-51,106-118,149` |
| xueqiu | 同 zhihu | `sau_commands/xueqiu.py:42-62,84` |
| instagram | MLX 下不读 `.identity.json`、不做 account-id 比对；用 `_multilogin_identity` | `sau_commands/instagram.py:135-136`；`uploader/meta_uploader/insgraph_uploader/main.py:147,443-458` |

### 7.2 代理与网络出口

| 平台 | 事实 | 依据 |
|---|---|---|
| facebook | `--proxy` / `SAU_FACEBOOK_PROXY` **不**转发到 MLX；Profile 拥有出口 IP | `sau_commands/facebook.py:143-158` |
| facebook-page | 同上；`upload_meta_content` 在 `target is not None` 时用 `proxy=None` 构建 uploader | `sau_commands/facebook_page.py:150-165` |
| instagram | 同上 | `sau_commands/instagram.py:132-140` |
| youtube | 本地 launch 用 `conf.YT_PROXY`；MLX/AdsPower 的 `launch_kwargs` 被忽略，Profile 决定出口 | `uploader/youtube_uploader/main.py:26-46`；`sau_commands/youtube.py:113-120,159-166` |

### 7.3 TikTok

- 托管 Profile 必须已设置 **English (US)**；MLX 分支**跳过** `change_language`，避免改写 Profile 偏好：`uploader/tk_uploader/main_chrome.py:45-55,1159-1161,1178-1206`。
- 本地模式显式设置 `locale=en-US` 并调用 `change_language`：同上。
- 图文（Photos）发布依赖 **Photos tab 灰度**；若账号没有图片发帖入口，`ensure_mode` 在选文件前直接失败，不会把图片塞进视频 input：`uploader/tk_uploader/main_chrome.py:2996,3049-3092`。
- 图文标题可选（≤90 字符）、描述与 `--notef` 互斥、无封面/内容复用开关：`sau_commands/tiktok.py:180-221`。

### 7.4 图文 / 视频差异

| 平台 | 视频 | 图文/文章 | 依据 |
|---|---|---|---|
| douyin | `upload-video` | `upload-note` | `sau_commands/douyin.py:54-84` |
| facebook | `upload-video` | `upload-note` | `sau_commands/facebook.py:77-102` |
| facebook-page | `upload-video` | `upload-note` | `sau_commands/facebook_page.py:72-98` |
| instagram | `upload-video`（Reel，可自定义封面） | `upload-note`（图片/轮播） | `sau_commands/instagram.py:54-76` |
| kuaishou | `upload-video` | `upload-note` | `sau_commands/kuaishou.py:52-70` |
| tencent | `upload-video` | `upload-note` | `sau_commands/tencent.py:50-63` |
| tiktok | `upload-video` | `upload-note`（Photos） | `sau_commands/tiktok.py:154-221` |
| xiaohongshu | `upload-video` | `upload-note` | `sau_commands/xiaohongshu.py:53-70` |
| dayu | `upload-video` | `upload-article` | `sau_commands/dayu.py:62-90` |
| zhihu | `upload-video` | `upload-article` | `sau_commands/zhihu.py:73-102` |
| xueqiu | — | `upload-article` | `sau_commands/xueqiu.py:112-123` |
| alipay / baijiahao / hupu / weibo / youtube | 仅视频 | — | 各自 `register()` |

### 7.5 `--schedule` 支持

| 支持 | 不支持 |
|---|---|
| bilibili（仅视频，且本地专属）`bilibili.py:41`；dayu（视频/文章）`dayu.py:72,87`；douyin（视频/图文）`douyin.py:60,82`；facebook-page（视频/图文）`facebook_page.py:79,93`；kuaishou（视频/图文）`kuaishou.py:58,70`；tencent（视频）`tencent.py:56`；tiktok（视频/图文）`tiktok.py:170,215`；xiaohongshu（视频/图文）`xiaohongshu.py:59,70`；youtube（视频）`youtube.py:58`；zhihu（文章/视频）`zhihu.py:77,96` | alipay、baijiahao、facebook（个人主页）、hupu、instagram、weibo、xueqiu |

### 7.6 其它平台参数差异（迁移时不需要改，但规格要保留）

- **douyin**：`--declaration` 精确匹配平台声明；省略即不设置；双比例封面 `--thumbnail` / `--thumbnail-landscape` / `--thumbnail-portrait`；商品链接/标题；合集：`sau_commands/douyin.py:61-71`。
- **tencent**：`--short-title`、`--category`、`--draft`、`--collection`、双比例封面：`sau_commands/tencent.py:57-63`。
- **weibo**：标题 ≤30 字符、封面 <5MB、合集：`sau_commands/weibo.py:50-54`。
- **youtube**：`--playlist`、定时发布：`sau_commands/youtube.py:54-58`。
- **zhihu/xueqiu**：`--prepare-only`、`--schedule`、剪贴板权限在托管模式跳过：`sau_commands/zhihu.py:77-80`、`sau_commands/xueqiu.py:119-123`；`uploader/zhihu_uploader/article.py:27-33`、`uploader/xueqiu_uploader/article.py:26-31`。
- **dayu**：`--prepare-only`、`--upload-timeout`、`--cover-indices`、`--source/--source-url`：`sau_commands/dayu.py:66-90`。
- **hupu**：标题 4–40 字符：`sau_commands/hupu.py:50`。
- **alipay/baijiahao/weibo/tencent/kuaishou/douyin** 的 `--collection` 只支持“已存在的合集”。

---

## 8. 代码改动 vs 测试/文档改动

### 8.1 必须改代码（AdsPower 正确性）

| 区域 | 改动 | 依据 |
|---|---|---|
| `utils/browser_session.py` | `multilogin=` → `managed=`；`BrowserSession.managed`；`_managed_session` 模板 | ticket 03 §3；当前 `:45-49,52-92,151-201` |
| `utils/browser_session.py` | `mode` 增加 `"adspower"` | ticket 03 §5；当前 `:49` |
| `utils/managed_browser.py`（新） | `ManagedBrowserProvider` Protocol / `MultiloginProvider` | ticket 03 §2 |
| `utils/adspower.py`（新） | V2 client + provider + `StartIncompleteError` | ticket 03/04/10 |
| `utils/errors.py` | 新增 `RateLimitedError`、`StartIncompleteError` | ticket 03 §6 + 04 补充；当前文件无这两个类型 |
| `sau_commands/browser.py`（新） | `resolve_managed_provider`、managed-aware 的 flags/label/account/login/platform 拒绝 | ticket 03 §4 |
| `sau_commands/multilogin.py` | 降为 re-export shim | ticket 03 §8 |
| `sau_cli.py` | `RateLimitedError → 11`；非空 `MLX_API_TOKEN` + `ADSPOWER_API_KEY` → `1` | ticket 02；当前 `:69-83` 无这两个分支 |
| 16 个浏览器平台模块 | `multilogin=` → `managed=`（36 处）；import/调用迁移到 provider-aware 函数（41 个 flags 落点、16 个 target 解析点） | 本文件 §2、§3.1 |
| 18 个 uploader 文件 | 28 处 `session.mode == "multilogin"` → `session.managed`；**含 insgraph 的 2 处单引号** | 本文件 §4.1；ticket 05 §6 |
| **`sau_commands/bilibili.py`** | **`reject_multilogin_login` / `reject_multilogin_platform` → `reject_managed_login` / `reject_managed_platform`** | `bilibili.py:121,123`；见 §8.3 |

### 8.2 只改测试/文档

| 区域 | 内容 |
|---|---|
| 本地模式测试 | 零改动（`test_mlx_*` 的本地 golden、`test_tiktok_local_mode.py`、`test_sau_browser_cli.py` 等） |
| 平台 MLX 测试 | 按 ticket 05，业务断言零改动；仅 `test_browser_session.py` 迁移 `managed=`，并允许 `test_mlx_smoke.py:377` / `test_mlx_hupu_dayu.py:405` 各 1 行（见 §5.3 冲突） |
| `test_multilogin_client.py` | 改为 import 共享 fake；新增 429 → 11 |
| `test_multilogin_cli.py` | 仅新增 429→11 与 shim 符号清单两处 |
| 新增测试 | `tests/test_adspower_client.py`、`test_adspower_browser_session.py`、`test_adspower_cli.py`、`test_adspower_platform_contract.py`（ticket 05） |
| 文档 | `GLOSSARY.md`、`docs/CLI.md`、`README.md`、18 个 Skill（ticket 06） |

### 8.3 重点风险：bilibili 在 AdsPower 模式下会静默回退本地

- 现状：`sau_commands/bilibili.py:120-123` 只调用 `reject_multilogin_login` / `reject_multilogin_platform`。
- 这两个函数只在 `multilogin_enabled()`（即 `MLX_API_TOKEN` 非空）时生效：`sau_commands/multilogin.py:101-114`。
- 因此只设置 `ADSPOWER_API_KEY` 时：
  1. `bilibili login` **不会**被拒绝，会走本地扫码登录；
  2. `bilibili check/upload-video` **不会**被拒绝，会走本地 `biliup` 子进程。
- 这与 charter“平台覆盖与 MLX 对齐、Bilibili 不支持托管模式”直接冲突。
- ticket 03 §4 已提供 `reject_managed_login` / `reject_managed_platform`；bilibili 是**唯一**需要从 `reject_multilogin_*` 迁到 `reject_managed_*` 但不使用 `browser_session` 的平台。实现时不能只做机械改名（它没有 `browser_session`，容易被脚本漏掉）。

### 8.4 其它迁移风险

1. **`resolve_multilogin_target` 被 16 个模块调用**：只改 `browser_session` 签名而不改解析器，AdsPower 会全部落回本地。必须把激活判定上移到 provider 解析层。
2. **`require_local_account` 有 33 个调用点**：AdsPower 下 `--account` 可选，必须 managed-aware，否则每个平台都会错误退出 `2`。
3. **`resolve_account_label` 有 17 个调用点**：AdsPower 下 `--account` 纯占位（ticket 02），语义要与 MLX 对齐。
4. **`login_required_error` 文案**：14 个平台调用点硬编码“Multilogin 应用”；AdsPower 需要按 provider 选择文案（ticket 03 §4）。这些调用点签名可能要加 provider/mode 参数。
5. **`_log_identity_unverified` 文案**：dayu/zhihu/xueqiu 写死 “Multilogin Profile”；AdsPower 下文案应 provider 中立（ticket 06 术语统一）。
6. **`multilogin: bool` 内部参数 26 处**：阶段 1 不改名，但实现者若顺手重命名会打爆 §5.3 列出的断言。
7. **`tools` 静态守卫**：需同时匹配单双引号；当前 28 处基线含 `insgraph_uploader/main.py:446,456` 两处单引号。

---

## 9. 结论

1. AdsPower 复用现有上传逻辑是可行的：16 个浏览器平台全部已经收敛到 `browser_session` + `session.mode`，上传器只依赖 `utils/errors.py`。
2. 但“复用”不等于“零改动”：至少 36 个会话调用点、16 个 target 解析点、41 个 flag 落点、28 个 `session.mode` 判定需要迁移；其中 bilibili 的 2 个拒绝调用点是独立于会话的遗漏风险。
3. 平台能力矩阵与 MLX 完全对齐：除 bilibili 外的 16 个浏览器平台都支持 `check` + 各自的上传 action；`login` 全部拒绝；`verify`/`delete` 仅本地。
4. 平台特有约束（TikTok 语言/Photos 灰度、Meta/YouTube 代理、身份绑定、时区、剪贴板权限、schedule、图文/视频差异）在托管模式下都由 `session.managed` 继承 MLX 分支，无需 AdsPower 专属实现。
5. 测试侧建议把“8 个 `test_mlx_*.py` 零改动”修正为“业务断言零改动；`test_mlx_smoke.py:377` 与 `test_mlx_hupu_dayu.py:405` 各 1 行 `browser_session` 签名迁移”，避免规格与实现直接冲突。
