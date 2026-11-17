# 11 视频号持久化 Profile 验证

日期：2026-11-17。基线：集成 `821e161`；独立工作树 `/private/tmp/sau-local-profile-11`。解释器为原项目 `.venv/bin/python`（3.11.11），`conf.py` / `sau_cli` / BASE_DIR 已核对绑定本工作树。没有读取真实账号资料或执行真实平台操作。

## 覆盖入口与行为

- 正式 `sau tencent login/check/upload-video/reset-profile`；直接 `tencent_setup`、`weixin_setup`、`tencent_cookie_gen`、`get_tencent_cookie`、`cookie_auth`、`TencentVideo.upload/tencent_upload_video/main`。原 account_file 形参仅用于从明确 `tencent_<alias>.json` 文件名取得别名，其他路径需显式 account_name；不读取旧文件。
- 创建、登录预检、扫码回调与视频操作共用所选持久化 context/Profile 占用。只有 login 创建/等待人工登录；注入 session 的 uploader 不另开或关闭会话。二维码刷新/回调保留，回调取消后清理已保存图片。
- 来源与 headless 经过共享真实解析；覆盖配置默认、显式 False、两种种类隔离、自定义产品识别、失败不回退、缺少非选定资料与缺失可选配置。启动基线为 no_viewport，无 stealth/UA/语言/权限覆盖。
- Profile 缺失、明确登录表面、验证退出 10；HTTP 403/503、网络/空页面等退出 1。必须有可见发表/草稿控件作为正向证据，不能仅因停在 upload URL 即报 valid。无永久账号绑定；旧 JSON 损坏及换号不会影响正常使用。
- 视频的描述/标签/短标题、原生定时、草稿与 not-before 实际到达页面替身控件；not-before 提交时仍持有 Profile 占用。保留封面/合集参数及人类化既有回归。
- 清理失败不覆盖成功、普通失败、结果未知 9 或提交后登录/验证 10；提交至多一次。页面在提交后断开仍是结果未知。取消传播，局部 page.close 不阻塞 persistent context 的有界清理。
- reset 精确种类、占用防护、无需 binary、幂等、另一种类/历史结果保留；共享原有 partial-failure / 跨进程测试继续通过。
- MLX/AdsPower 仅新 headless 默认来源；保持 provider、日志参数、created-page 清理、登录限制和 11，不解析本地错误路径/来源或访问 Profile。

## Red → green

按已批准的 CLI → 真实配置/Profile/session → 浏览器/平台/provider 替身边界逐片推进，没有替换整个 session 来验证新 parser：

1. login/check 原入口失败于临时 `chromium.launch`（`Must use persistent Profile`），接入后通过。
2. 本地检查的空 upload 页面和 HTTP 403 原先错误退出 0，captcha 退出 1；严格本地正向证据/分类后全部按 1/10 通过。
3. 正式 video 原路径尚依赖旧 account-file 分支，移除分离 JSON preflight 后，在一条 persistent 调用内完成预检和模拟上传。
4. 发表后 login/captcha 跳转原先四种情况错误退出 0；本地提交观察分类后均为 10、`publish_attempted=true`、单次点击。
5. 提交后 DOM 断开原先退出 1；保持结果未知后退出 9，清理错误不覆盖。
6. QR callback 取消原先留下已保存图片；在回调前记录文件所有权后，取消传播、图片删除、context 关闭且 Profile 可再次取得。
7. 刷新 QR 原先误用 alias 作为相对图片路径；传递稳定 artifact 基路径后，两次回调均位于同一隔离 QR 目录，刷新和最终清理通过。

## 最终离线回归

在工作树执行：

```sh
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest \
  tests.test_tencent_profiles tests.test_mlx_tencent_baijiahao tests.test_tencent_humanize \
  tests.test_sau_browser_cli tests.test_adspower_video_platforms tests.test_publish_cleanup \
  tests.test_local_profile tests.test_publish_timeout tests.test_publish_gate \
  tests.test_publish_ambiguity tests.test_review_regressions \
  tests.test_adspower_browser_session tests.test_browser_session -q
```

结果：233 tests 通过（10.416s）。其中新增 Tencent CLI/Profile 行为 22 tests；真实临时目录、真实跨进程锁测试沿用共享套件。旧 TencentVideo JSON writeback/double-close golden 断言已由 persistent 流程测试替代；未注册 TencentNote 的原有断言保留。shared session/Profile 生产代码没有修改。

## 受控真实浏览器

通过环境批准在 sandbox 外执行，系统 Chrome `157.0.8103.79`，完整 browser、headless、独立临时 Profile、`no_viewport=True`，全部请求由 context.route 本地 fulfill，无真实站点流量：

```sh
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_tencent_profile_dom -v
```

2 tests 通过，21.362s：正向控件、二维码 iframe、空页面、实名验证分类；合成视频文件从 iframe input 进入、描述写入、视口外发表按钮被滚动到并仅点击一次。fixture 最初因 HTML 没有 UTF-8 charset、以及 Patchright 隔离世界无法回读主世界 window counter 失败；修正为 UTF-8 与 DOM 属性计数后通过，未以此修改生产行为。

另以临时目录直接执行既有 `tests.test_tencent_verification_dialog.test_wait_for_realtime_verification_saves_qr_and_resumes`，1 test 通过：既有非 Profile/托管路径的实名验证截图与等待恢复保持。该测试也只用空白页 set_content。

未修改共享来源能力，因此不重复 02 已完成的 8 种来源/有头/无头/存储隔离矩阵。

## 边界

未执行真实视频号登录、素材上传、发布、草稿或删除；托管 provider 仅离线替身。未注册 note 不新增 CLI 入口，其旧独立启动/JSON 代码属于范围外调用方；正式视频启动链不再可达这些分支。旧资料迁移 19、四平台 no-publish 验收 20 不在本票。按本票基线，其余未迁移平台为抖音、快手、百家号、微博、虎扑、支付宝、大鱼号、知乎、雪球；09/10/12 各自并行接入。Bilibili 不参与本次浏览器迁移。
