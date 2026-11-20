# TikTok Studio 的视频和图片帖分别怎样确认地点可用并选中？

Type: task
Label: wayfinder:task
Status: resolved

## Question

分别打开视频和 Photos 编辑页，记录地点入口、候选列表、唯一命中和选中后的可见值。若没有入口，记录卡在哪一步，以及页面是否明确说明资格限制。账号缺少 Photos 页签、编辑器未加载、地点入口缺失和地点无匹配是不同的观察结果。

交接报告给出了地区和年龄条件的资料；判断当前运行时能做什么，还需要对应帖型的页面证据。已有两种帖型的 AI、标签验收可直接引用。[TikTok 本地验收](../../tiktok-browser-parity/acceptance-local.md)

## Answer

2026-11-20，本地 Chrome 账号 `lukechen` 的英文 TikTok Studio 在视频和 Photos 编辑器中都可搜索并选中地点。`Details` 下的 `Location` 初始可见，展开高级设置之前即可操作。两次均使用中性测试素材，停在发布前。两个页面的可见性默认显示 `Followers`，高级设置有私有账号的复用提示。本次未独立核验账号类型、地区或年龄，地点控件也未显示资格限制提示。

| CLI 入口 | 确认已进入对应编辑器的信号 | 点击后的可见值 | 证据 |
| --- | --- | --- | --- |
| `sau tiktok upload-video` | 通过 `Select video` 选择测试视频，编辑器显示文件名、时长和 `Cover` | `London Eye`，右侧有清除按钮 | [视频候选与回读](../research/tiktok-location-2026-11-20/video.json) · [控件截图](../research/tiktok-location-2026-11-20/video-closed.png) |
| `sau tiktok upload-note` | Photos 页签可用，选择两张测试图片后，编辑器显示 `2 photos uploaded` 和排序提示 | `London Eye`，右侧有清除按钮 | [图片帖候选与回读](../research/tiktok-location-2026-11-20/photos.json) · [控件截图](../research/tiktok-location-2026-11-20/photos-closed.png) |

两种帖型均在 `[data-e2e="poi_container"]` 内的 `Search locations` 输入框搜索。下拉列表的角色是 `listbox`，每条 `option` 分行显示名称和地址。搜索 `London Eye` 时，两次都显示 10 条候选，其中有两条名称完全相同。一条的地址是 `Riverside Building, County Hall, Westminster Bridge Rd, London SE1 7PB, United Kingdom`，另一条是 `Dolgoprudnyy, Moscow, Russia`。英国地址在本次列表中唯一，两次都点击了该行。

点击后，地点组合框的 `aria-expanded` 从 `true` 变为 `false`，候选消失。收起后从输入框的 `value` 读到 `London Eye`，截图只显示名称和清除按钮。要确认选中的是英国地点，需要保留点击时的地址。

选中地点前，两种帖型还分别搜索了 `Qzx974631zz`。各出现 10 条建议，名称精确命中均为零，两次均未点选。当前两个 CLI 入口都没有地点参数。地点请求如何表达地址、如何报告无精确匹配，由[一条地点请求怎样匹配候选并报告选中的地点？](09-location-match-and-result.md)决定。[TikTok CLI 参数](../../../sau_commands/tiktok.py)
