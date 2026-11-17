# 09 — creator 账号创建入口与 AdsPower 干跑证据

> 历史记录：保留自 `adspower` 提交 `7ee8380716132f315e7f70a9852927dc5eda9d50`。
> 以下环境、代码版本和结果均描述当时的实测，不代表当前 `main` 已完成真发验证。

- 日期：2026-11-17（本地时间）
- 账号：creator（不记录账号名 / Cookie / Profile ID）
- 界面语言：English (US)；AdsPower Profile 由人工保持英文，CLI 不写入语言
- 环境：macOS，AdsPower Local API V2，Chromium Profile（headed）
- 代码版本：`adspower` 分支工作区（本次改动尚未提交）
- 结论：creator 账号只验证到发布就绪，**不代表真发通过**

## 背景

普通号点 Create 直接打开 `Create new post` 弹窗；creator 账号点 Create 先出现
`Post / Live video / Ad` 下拉菜单。旧流程只等待弹窗，因此在 creator 账号上以
`Instagram 创建弹窗未出现素材入口（可能被未知弹窗遮挡）` 退出 `1`。

## 入口观察

| 步骤 | 观察结果 |
|---|---|
| 点 Create | 菜单出现（Post / Live video / Ad）；`role=dialog` 计数 0，`input[type=file]` 计数 0 |
| 菜单结构 | 无 `role=menu` / `role=menuitem`；Post 项没有可用的文案无关属性，唯一稳定锚点是图标 `svg[aria-label="Post"]`（菜单打开时全页唯一，点击冒泡到菜单项容器） |
| 点 Post | `Create new post` 弹窗出现；`role=dialog` 计数 1，`input[type=file]` 计数 1 |
| hover 后点菜单项 | 菜单项包围盒在 hover 与点击复核之间变化 → `point-drift`（未派发）；改为不 hover 的坐标点击后成功并打开弹窗 |

菜单项是图标 + 普通 `div`，没有 role；不使用文本 `Post` 定位是因为信息流里也会出现
同名的 “Post” 文本（同一页面精确文本计数为 2）。

## 干跑（`--no-publish`）

```bash
sau instagram upload-video --profile-id <id> \
  --file videos/demo.mp4 --title "<标题>" --desc "<正文>" --tags sau \
  --no-publish --result .local/instagram-video.json

sau instagram upload-note --profile-id <id> \
  --images videos/demo.png videos/demo1.png --title "<标题>" --note "<正文>" --tags sau \
  --no-publish --result .local/instagram-note.json
```

两条均退出 `0`，结果文件 `status=prepared`，日志停在
`Instagram 发布就绪，--no-publish 停在 Share 前（未点击发布）`；未点击发布。
运行结束后 AdsPower Profile 查询为 `Inactive`，无残留。

## 覆盖与未覆盖

- 已覆盖：普通号与 creator 两种创建入口；视频 / Reel 与图文干跑到 Share 就绪。
- 未覆盖：creator 账号真发、中文界面、其他发布选项组合、定时（当前实现不支持）。
