# 07: Facebook 全流程与作品管理接入

**What to build:** Facebook 用户以同一 Profile 登录、检查、发布视频/图文及核验或删除已有作品；重建只影响 Facebook 的指定浏览器资料，原作品与作者核验继续有效。

**Blocked by:** [03：Rednote 全流程接入](./03-rednote-persistent-profile.md)；[04：Instagram 全流程与作品管理接入](./04-instagram-persistent-profile.md)；[05：小红书全流程接入](./05-xiaohongshu-persistent-profile.md)

**Status:** claimed

**批次：** 第二批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [ ] 完成本票范围内所有已注册正式动作及可达独立启动、内部预检和直接 uploader 调用的接入，预检与业务复用同一 Browser session 和 Profile 占用；注入会话的业务不另开同目录或自行关闭会话。同步开放本平台 reset-profile，保持 01 的精确目标、无需 binary、占用防护和部分失败契约。
- [ ] 正式 CLI 与直接调用采用 02 的来源和 headless 优先级，区分未提供与显式 False；默认 Chrome 有头，允许 Chromium 与自定义路径。只使用所选来源及按实际种类隔离的持久化 Profile，no_viewport，失败不回退；切换同种路径/模式复用资料，未选浏览器无需安装。
- [ ] Profile 是唯一登录态来源，删除本平台正式路径的旧 JSON 存在检查、Cookie 预检、storage_state 恢复/导出及旧身份门槛。只有 login 引导登录；缺少 Profile、明确未登录或业务中登录失效退出 10，结束本次业务；探测、页面、权限或必需字段故障退出 1，人机验证保留 reason=verification 与补救提示。正常命令不承担 19 的一次性迁移。
- [ ] 允许同别名重新登录不同真实账号及两种浏览器使用不同账号，不新增永久绑定、跨 Profile 身份同步或仅为防换号的比较；原有显式请求目标与历史作品证据继续校验，历史结果不改写或删除。
- [ ] 覆盖 login、check、视频/图文发布及已注册 verify/delete，包含独立作品操作的启动和关闭链；保持作品操作原有本地/托管动作路由，不以 provider 的存在擅自改变路由。
- [ ] Facebook 与 Facebook Page 按不同正式平台隔离资料；重建、检查及换号不能影响 Page Profile，不能因为共享 Meta 业务辅助能力而合并登录容器。
- [ ] 保留已有原作品、作者、expected-text 等证据校验，以及永久删除、回收站、已删除状态等已注册参数语义；换号不改写历史结果。作品管理和删除通过离线替身验收，不操作真实作品。
- [ ] 在无固定 viewport 基线下验证相关 composer、素材选择、弹窗和覆盖层交互；保留已有代理与发布结果语义，与 06、08 可在第一批完成后独立推进。
- [ ] 本地移除项目增加的 stealth、UA/请求头、自动化掩饰、固定 viewport、额外最大化、locale/语言和无业务依据的权限；保留 Patchright 默认、必要业务脚本、二维码、现有代理、超时、人类化交互、响应监听、发布预算、not-before 及结果文件，不修改界面语言。
- [ ] 初始化、正常完成、异常、取消、超时与登录失效按所有权有界清理，取消继续传播，失败不回滚或重建 Profile。已有业务错误、成功、发布结果未知（9）及 publish_attempted 不被清理覆盖；提交后登录/验证异常保留原语义，不自动恢复旧任务或重发。
- [ ] 本平台 MLX/AdsPower 仅采用新 headless 来源；忽略本地浏览器选择/路径且不额外报错或警告，不访问本地安装、Profile、锁或旧资料。保留原动作路由、login 限制、provider 参数/日志、CDP 所有权、停止/断开与限流退出 11；尚未迁移的平台保持旧行为。
- [ ] 从正式 CLI dispatch 经真实配置解析和共享编排，复用浏览器/平台/provider 边界替身完成相关离线回归；覆盖本票动作、配置传播、旧文件无关、换号、登录分类、重建、资源所有权和提交结果保护，不把 session 整体替换成 parser 测试。直接调用只补缺口，共享能力变化时补跑受影响的跨进程/真实浏览器检查。
- [ ] 同步本平台 CLI/平台 skill、配置及登录说明、Agent Bootstrap 和运行依赖说明；只在本平台接入后更新其行为描述，保留未迁移平台的准确说明。交付记录列出覆盖入口、验证命令/实际结果、未迁移平台和未执行项，离线结果不表述为真实平台验收。

## Comments

- 2026-11-17：在隔离 worktree `/private/tmp/sau-local-profile-07`、`codex/local-profile-07` 实施；基线 ec6ea39。使用 tdd skill 与原规格已批准的 CLI → 真实配置/Profile/session → 浏览器/provider 边界替身测试。conf.BASE_DIR 及本地导入已确认绑定本 worktree。Facebook Page 不在本票生产修改范围。
- Red → green：check 首次因旧 JSON 门槛失败；login 首次因缺少 Profile 退出 10；视频/图文首次因旧登录态文件检查失败且视频预检另启会话；works 首次仍经旧独立 launch 失败；提交前验证首次错误返回 0；提交中断首次丢失 publish_attempted；提交后断开首次错误退出 1；延迟挂载 composer 首次误判页面结构异常。各失败均先实际执行，然后改动并重跑至通过。
- 当前已通过 207 项离线/共享回归、13 项受控浏览器/DOM 回归。随后补入延迟挂载用例，13 项 Facebook Profile CLI 测试通过。额外 114 项通用契约执行发现既有 Instagram 旧测试补丁问题，合并集成分支已有修复后重跑；最终命令与结果记录在 [07 验证记录](../research/07-facebook-validation.md)。
- 测试覆盖当前用户与原作者/作品 ID/expected-text，回收站、永久删除和已删除查询，全程仅本地替身或 route.fulfill DOM。未登录真实 Facebook，未发布或删除真实作品；19 一次性旧资料作业与20四平台真实验收不在本票。
