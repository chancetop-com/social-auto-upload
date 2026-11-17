from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
LOCAL_CHROME_PATH = ""  # optional, e.g. C:/Program Files/Google/Chrome/Application/chrome.exe
LOCAL_BROWSER = "chrome"  # migrated platforms: chrome or chromium; custom path above wins
LOCAL_CHROME_HEADLESS = False  # migrated CLI + direct calls; explicit flags/bools win
# Instagram local login/check/uploads/verify/delete use these migrated settings.
# Keep an existing conf.py value (including True) when upgrading.
# Platforms awaiting Profile migration retain their existing CLI defaults.
# Optional proxy for the YouTube uploader. Where youtube.com is blocked, direct
# connections time out and the (patchright) chromium does NOT use the system proxy.
# Point this at your local proxy port, e.g. "http://127.0.0.1:7890". None = no proxy.
YT_PROXY = None
