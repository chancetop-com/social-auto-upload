# 12 百家号验证记录

日期：2026-11-17。工作树 `/private/tmp/sau-local-profile-12`，分支 `codex/local-profile-12`，开始时集成基线 `821e161`。已确认该基线为当前分支祖先；conf.py 从示例建立，conf/sau_cli/utils/uploader/tests 与 BASE_DIR 均解析到本工作树。未读取真实 Cookie 内容、启动真实账号或向平台提交内容。

## 交付边界

正式 login、check、upload-video、reset-profile，以及直接 baijiahao_setup、baijiahao_cookie_gen、cookie_auth、BaiJiaHaoVideo.main/upload/upload_in，全部采用实际本地 BrowserSession、共享配置解析与 Profile 占用。只有 login 创建资料并引导扫码/验证；内部预检和视频流程持有同一个 context 与锁。注入 session 不重开、不关闭调用方资源。临时二维码位于系统临时目录，退出时清理。

本地资料为 `browser_profiles/baijiahao/<原始别名>/<实际浏览器种类>`。Chrome 有头为未配置默认，已有 headless 配置保留，显式 False 与未提供区分；自定义路径优先并按产品种类选 Profile，完整 Chromium 可选，不回退。没有旧 JSON 存在门槛、storage_state 恢复/导出或永久真实账号绑定；旧位置参数仅从明确的 `baijiahao_<alias>.json` 文件名提取别名，不读文件。reset 通过共享精确目标契约，无需 binary，拒绝占用并保留其他种类、旧资料、历史结果。

成功登录须有当前后台业务控件，空白/未知页面不能用“没有登录按钮”作为成功证明。缺 Profile、明确登录页/登录控件为 10；验证码/验证为 10 且保留 reason=verification。网络、HTTP 403/503、页面结构和必需字段/文件权限故障为 1，二次诊断失败不覆盖主故障。login 可在当前 context 等待人工验证；业务不重新引导或恢复任务。提交后登录/验证携带 publish_attempted=true，未知结果为 9，单次最多派发一次。

视频标题、封面、创作声明、合集、not-before、15 分钟预算和结果判断保持原流程。百家号原本就必须提供横版 thumbnail，不支持原生 schedule 或 no-publish，本票未新增这两项能力。明确传入封面后的权限/上传故障不能被自动封面掩盖；没有自定义封面时的内部自动封面分支保留，托管封面容错保留。现有 AI/合集的可选容错保留。进度页面读取故障在本地上抛，避免页面断开后误认为视频已传完。

本地不授予旧 geolocation 权限、不传旧上下文/指纹/语言/viewport 参数。自然 macOS 窗口使用 ControlOrMeta+A 清空预填标题；托管继续原 Control+A。托管探测、忽略选项日志、provider 路由、CDP 所有权与停止/断开均保留，只采用批准的 headless 来源；本地浏览器路径/选择无关。共享 Profile/config/session 生产代码未改变。

## TDD 证据

使用正式 CLI dispatch，经真实 resolver/Profile/session，浏览器、DOM、时钟、provider 为外部替身；直接调用只补兼容和注入入口。全部资料位于临时目录。

1. login/check 重用：新增测试先失败 `Use the persistent Profile`（旧临时 launch）；改用持久化会话后通过，旧 malformed JSON 不变，无 storage_state。
2. 视频链：指定 Chromium 的 CLI 原仍预检 Chrome，失败 10；迁移后一次 persistent launch 覆盖预检与完整视频动作，提交一次，正确选择封面。
3. 分类：检查导航中登录跳转原返回 1；保留确定 URL 证据后为 10。验证诊断保留 reason，403/503/网络/空壳/意外域名维持 1。
4. 提交后验证：原本地安全验证返回 9；现在为 10、reason=verification、publish_attempted=true，即使 context.close 失败也不丢阶段、不重发。
5. 必填封面：明确传入 thumbnail，set_input_files 抛 PermissionError 时原流程使用自动封面继续提交（实测退出 0）；现在本地退出 1、保留原权限原因、提交计数 0。未修改无自定义封面的自动封面分支或托管行为。
6. 主异常：标题权限错误后登录诊断再失败，原输出 secondary diagnostic failed；修复后保留 primary title permission error。
7. 登录验证：login 遇到 challenge 原立即关闭并返回 10；现有本地 context 等待人工验证，出现业务证据后成功且正常释放。
8. 上传进度：body 读取断开原被吞掉并最终提交（退出 0）；本地现退出 1，原 progress page disconnected 原因保留，不提交。
9. 百度 passport 页上的可见安全验证原被普通 login URL 抢先归类；新增 CLI 失败断言后改为 verification 优先，同时 DOM 故障不抹掉明确登录 URL 证据。
10. 实际窗口：受控 Chrome/Chromium 的标题原读回 `Fixture video titlefilename.mp4`，证明 macOS Control+A 未清空；改为本地 ControlOrMeta+A 后读回精确标题。

补充回归涵盖直接 setup/登录/probe/uploader、显式 False、可选配置缺失、自定义产品识别与无回退、两种浏览器隔离、reset/占用、挂起 page.close、context 清理超时、取消传播、初始化失败、成功/未知/登录结果与清理优先级、提交前/后的登录跳转、not-before 保持锁、预算耗尽、托管默认/显式 headless、忽略无效本地配置、login/reset 限制及 429=11。旧双重关闭/JSON 写回的百家号测试由真实 Profile CLI 行为测试替换，其他平台条目保留。

## 实际执行

所有命令 cwd 为本工作树，解释器为项目原 checkout 的 Python 3.11.11。

```sh
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_baijiahao_profiles tests.test_mlx_tencent_baijiahao tests.test_baijiahao_humanize tests.test_adspower_video_platforms tests.test_publish_cleanup tests.test_local_profile tests.test_publish_timeout tests.test_publish_ambiguity tests.test_publish_gate tests.test_local_browser_session tests.test_browser_session tests.test_adspower_browser_session tests.test_adspower_cli tests.test_review_regressions tests.test_humanize -v
```

结果：**315 tests，9.655s，OK**。含 23 项新的百家号公开接口测试；共享 local_profile 测试使用真实临时目录和跨进程占用，provider 为离线替身。

```sh
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_baijiahao_profile_dom -v
```

首轮受控真实浏览器：1 项测试在 119.429s 后因预填标题残留失败。修复后：**1 test，115.673s，OK**，包含系统 Chrome **157.0.8103.79** 有头与完整 Chromium **156.0.8078.4** 无头各一次 login 和完整合成视频流程，共 4 次真实 persistent launch。全部请求 route 到本地合成 HTML；验证标题精确读回、隐藏封面 input、创作声明 modal、合集全等选择、自然窗口滚动至发布、单次模拟提交以及 context 关闭后的浏览器断开。所有 launch 都是 no_viewport，未传固定 viewport。

这些是受控 DOM 窗口证据，不是百家号线上登录/上传/发布验收。共享来源/持久化机制未改，沿用 [02 浏览器矩阵](02-browser-validation.md)，不重复全矩阵。

## 未执行与范围

未执行真实百家号账号登录、素材上传、发布、删除，也未使用真实 MLX/AdsPower 服务。本票没有 no-publish 开关，不能用真实提交替代离线验收。旧资料一次性作业 19、四平台真实不发布回归 20 尚未执行。

本票未修改抖音、快手、视频号或后续平台的生产代码；前三者同批独立票交付，微博、虎扑、支付宝生活号、大鱼号、知乎、雪球仍保持各自后续票范围。未新增业务身份绑定、跨 Profile 同步、自动迁移或发布重试。

## 最终复验

补充 `tests.test_sau_browser_cli tests.test_multilogin_cli` 后，上述离线命令尾部添加这两个模块：**372 tests，12.925s，OK**。其中包含 passport URL 上可见验证的 reason 优先级回归。独立两模块曾通过 57 tests / 4.213s。

最终登录等待与窗口流程再次执行受控浏览器命令：**1 test（Chrome 有头 + Chromium 无头两条完整合成流程），117.795s，OK**。最后的验证 reason 优先级改动仅影响 challenge/login URL，受控上传页面无此分支；该改动已由上述 CLI 边界回归验证。`git diff --check` 通过。

## 集成合并复验

实现提交 `a7034da` 后，合入 Tencent 11 集成 `a9626ca`（本分支合并提交 `0cfd5f2`），207 项百家号/视频号/托管/所有权/CLI 回归通过（17.816s）。随后合入最新集成 `02f2362`（含 Douyin 09）。共享冲突按平台并集处理：docs/config/reset 列表保留抖音、视频号、百家号；AdsPower 的本地资料禁止访问守卫覆盖各自入口；旧双重关闭测试仅移除各已迁移平台条目。

```sh
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_douyin_profile_cli tests.test_baijiahao_profiles tests.test_tencent_profiles tests.test_mlx_tencent_baijiahao tests.test_baijiahao_humanize tests.test_tencent_humanize tests.test_adspower_video_platforms tests.test_publish_cleanup tests.test_local_profile tests.test_sau_browser_cli tests.test_multilogin_cli -q
```

结果：**221 tests，20.416s，OK**。首次该组命令误写不存在的 `tests.test_douyin_profiles`，其余 207 项通过后报告单个 import error；修正为实际 `tests.test_douyin_profile_cli` 后得到上述全通过结果。合并未改百家号生产代码或浏览器夹具，沿用已完成的两条受控 DOM 证据。当前分支包含 09/11；快手仍由 10 独立交付，后续平台和 19/20 不在本票内。`git diff --check` 通过，无未解决冲突或本票阻塞。
