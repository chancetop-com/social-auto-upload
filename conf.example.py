from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
# Applies to all local browser platforms.
# A compatible custom executable wins over --local-browser / LOCAL_BROWSER.
LOCAL_CHROME_PATH = ""  # e.g. C:/Program Files/Google/Chrome/Application/chrome.exe
LOCAL_BROWSER = "chrome"  # chrome or chromium; explicit --local-browser wins
# Explicit --headed / --headless (or direct-call bool) wins over this default.
# Preserve an existing conf.py value, including True, when upgrading.
LOCAL_CHROME_HEADLESS = False
# All three browser settings are optional. Omitted values use the defaults above.
# Managed actions only use the headless setting and ignore local browser sources.

# Optional YouTube proxy, applied consistently to local login/check/upload.
# Example: "http://127.0.0.1:7890"; None means no proxy.
YT_PROXY = None
