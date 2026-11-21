# 2026-11-21 真实账号 `--no-publish` 回归

八条命令均使用现有本地 Profile，跑到发布就绪点；**没有点击发布 / Share，未发布任何内容**。

- 浏览器：本地 Chrome 157.0.8103.79，有头模式
- 环境：`ADSPOWER_API_KEY` / `MLX_API_TOKEN` 未设置（本地 Profile 模式）
- 账号与界面：小红书 `180`（中文）、Rednote `rednote`（中文）、Instagram `luke`（简体中文 Creator）、TikTok `lukechen`（英文 Studio）
- 退出码：全部 `0`（`--no-publish` 就绪）
- 媒体：`videos/demo.mp4`、`videos/demo1.png`、`videos/demo2.png`

| 入口 | 请求 | 实机终值 | 证据文件 |
| --- | --- | --- | --- |
| `xiaohongshu upload-video` | `--content-type ai --location 人民公园`，配文 `今天喝了 #咖啡，配上 #栗子蛋糕。` | AI 回读「笔记含AI合成内容」；地点所点行 `人民公园`（北京市平谷区平谷府前西街5号），收起后 `人民公园`；`#咖啡`、`#栗子蛋糕` 均原位关联 | `xiaohongshu-video.log` |
| `xiaohongshu upload-note` | 同上 | 同上；停在发布按钮前 | `xiaohongshu-note.log` |
| `rednote upload-video` | 同上 | AI 回读「笔记含AI合成内容」；地点所点行 `人民公园`（成都市青羊区小南街8号(人民公园地铁站B口步行250米)），收起后 `人民公园`；两个话题均原位关联 | `rednote-video.log` |
| `rednote upload-note` | 同上 | 同上；停在发布按钮前 | `rednote-note.log` |
| `instagram upload-video` | `--ai-generated --location Shanghai`，配文含 `#color #study` | `status=prepared`；`ai_generated=set`；`location=set`，`candidate_name=Shanghai`、`candidate_index=1`；`#color #study` 为文本证据 | `instagram-video.log`、`instagram-video.json` |
| `instagram upload-note` | `--no-ai-generated --location Shanghai`，配文含 `#color #study` | `status=prepared`；`ai_generated=default_off`；`location=set`（同上）；话题为文本证据 | `instagram-note.log`、`instagram-note.json` |
| `tiktok upload-video` | `--no-aigc --location "London Eye"`，配文 `Field notes #coffee, after rain.` | 地点所点行 `London Eye`（Riverside Building, County Hall, Westminster Bridge Rd, London SE1 7PB, United Kingdom），收起后 `London Eye`；AI `default_off`；`#coffee` 原位关联 | `tiktok-video.log` |
| `tiktok upload-note` | 同上（Photos） | 地点、AI、`#coffee` 关联均通过；停在 Post 按钮前 | `tiktok-note.log` |

## 话题边界

- 配文中的 `#咖啡，` 与 `#咖啡。` 只把 `咖啡` 计为话题；中文逗号/句号保留在配文原位。
- `#coffee,` 只把 `coffee` 计为话题；逗号保留在配文原位。
- 链接中的 `#片段` 不计为话题；链接原样保留。
- YouTube 简介候选查找使用同一解析规则；`#hit,` 只查 `#hit`，URL 片段不查候选。

## 修复记录

- 首次 XHS 实机发现 AI 声明回读读取了选择后已清空的入口占位节点；改为读取声明包装层内的 `.d-select-description` 后复跑通过。
- 首次 TikTok Photos 实机发现地点候选列表被标记 `list_not_collapsed`；改为按 combobox 的 `aria-controls` 限定列表并读取按钮的 `aria-expanded` 后复跑通过。
