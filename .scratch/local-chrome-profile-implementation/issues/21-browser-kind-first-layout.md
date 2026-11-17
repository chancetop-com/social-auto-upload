# 21: 按浏览器种类组织 Profile 并搬迁现有资料

**What to build:** 按用户 2026-11-17 的追加要求，最终目录为 `browser_profiles/<chrome|chromium>/<platform>/<raw_account>`，已有登录资料随目录调整继续可用。

**Blocked by:** [19：一次性迁移](./19-one-time-legacy-migration.md)（已完成）。基于 20 已验证基线 `a61628c`，与 22、23、24 可并行；最终 20 收口等待这些追加要求。

**Status:** claimed

**依据：** 最新用户目录层级要求覆盖原规格的旧顺序；其余 Profile、安全、托管和发布契约继续有效。

- [x] 共享取得、会话、reset 统一采用 browser-kind/platform/raw-account 顺序；目录名保留原始别名，不归一化，不按真实账号绑定。
- [x] 归属元数据、同 Profile 非等待跨进程锁、别名碰撞、外部 browser/singleton 防护、reset 部分失败隔离全部保持；锁和重建标记位于可删除的账号数据目录之外，内部文件名不占用有效别名空间。
- [ ] 审核所有硬编码路径，包括二维码、测试、受控浏览器脚本、当前文档及规格；历史真实执行记录保留当时路径，并追加本次搬迁记录。
- [x] 先 TDD 完成共享行为和路径断言，跨进程及受影响真实 Chrome/Chromium 持久化检查；代码就绪提交后先通知 root 集成新运行路径，再进行真实资料搬迁。
- [ ] 实际搬迁只针对原仓库内已验证归属且未被占用的 Profile，先清点；旧、新目标都受 guard 保护，不覆盖或合并目标、不复制到另一 browser kind、不读取 Cookie/History 内容、不清 singleton 或杀外部进程。
- [ ] 已有四个账号的资料保留在原仓库，使用 rename 等安全移动完成新布局；不通过 reset 或重新登录替代搬迁，不删除未知资料或历史结果。
- [ ] 四个迁移后的默认 Chrome 有头正常 check 真实通过，证据准确记录新路径和结果。只因路径变化不重复无关素材上传。
- [ ] 一次性旧布局搬迁程序和专用检测/兼容入口实际移除，日常命令只使用新布局；无永久双路径兼容。
- [ ] 更新本票、索引、规格和当前运行文档；完成实际搬迁与核验后才能 resolved。原 conf.py 不变。

## Comments

- 2026-11-17：已领取，基于 `a61628c`。应用 TDD 已确认的 CLI/Profile/session 测试边界与 writing-for-agents 技能；工作树 `conf.BASE_DIR`、`utils.local_profile.__file__` 均核验指向本工作树，测试只用临时目录。
- Red → green：先修改公开 session 启动路径断言，观察旧 `tiktok/Creator/chrome` 与新 `chrome/tiktok/Creator` 不符后实现新布局；新增数据目录缺失但外置归属冲突的拒绝测试先失败，再修复禁止覆盖；小红书公开 login 的 QR 回调先发现旧路径，再修复保存位置。
- 共享 30 项测试通过：真实进程互斥/崩溃释放、等价路径/别名、重建中竞争与失败后的跨进程隔离、metadata/guard symlink/损坏拒绝、合法内部文件名别名、Chrome/Chromium 与平台隔离；明确失败重建后仍保留别名碰撞证据。
- 所有当前路径断言及 README、CLI、安装、各平台独立 skill、规范与决策 Answer 已更新。19/20 的真实历史执行路径保持原样；01 旧实施记录追加版本说明。受控 browser smoke 增加新路径及数据叶子无项目元数据的断言。
- 初次 Profile 测试集 352 项：337 通过，15 项真实浏览器受 sandbox 启动限制（14 error 与 Facebook 捕获启动错误后断言失败）；正在批准的 sandbox 外重跑。初次隔离 smoke 的 Chrome headed 成功持久化后第二次关闭超时，下一次打开被 singleton 防护拒绝；没有清 singleton、杀外部浏览器或触及实际账号资料。原测试进程结束后未发现残留对应 browser；将在其他 DOM 批次结束后串行验证。
- 本票保持 claimed；必须先提交代码检查点并由 root 集成，再执行原仓库四个 Profile 的受保护移动与正常 check。

- sandbox 外相同 `*profile*.py` 集合 352/352 通过（610.800s）；另补 TikTok local-mode/session 12 项通过。已合入 integration `6e6e416`（22、24），并通过 post-merge 121 项共享与三平台 CLI 回归。新路径、managed-only 通用入口及新的 no-publish 文案共同生效。

- 串行 browser smoke 8/8 通过：Chrome/Chromium × channel/custom executable × headed/headless；Cookie/localStorage 重开持久化、匿名隔离、新路径、叶子无项目元数据、每行末尾重新取得 guard 全通过，无关闭超时。详见[21 验证记录](../research/21-layout-validation.md)。
