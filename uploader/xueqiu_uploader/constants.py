"""雪球当前长文表单已展开核验的固定文案。"""

from conf import LOCAL_CHROME_PATH


XUEQIU_HOME_URL = "https://mp.xueqiu.com/"
XUEQIU_ARTICLE_URL = "https://mp.xueqiu.com/writeV2/"
XUEQIU_VISIBILITY = ("公开", "私人")
XUEQIU_DECLARATIONS = ("不添加创作声明", "本文包含AI生成内容")
# 两个上传控件实测 accept 相同；不扩展到未观察过的 WebP/SVG。
XUEQIU_IMAGE_SUFFIXES = (".gif", ".jpg", ".jpeg", ".png")

# Golden local-mode browser options; Multilogin mode ignores them and uses the
# Profile's own fingerprint/timezone.
XUEQIU_LAUNCH_KWARGS = {"executable_path": LOCAL_CHROME_PATH or None, "channel": "chrome"}
XUEQIU_CONTEXT_KWARGS = {}
