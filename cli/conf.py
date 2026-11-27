"""Resolve the CLI's data independently of its working or installation directory."""
import os
from pathlib import Path


def _data_root():
    if os.environ.get("SAU_HOME"):
        return Path(os.environ["SAU_HOME"]).expanduser().resolve()
    source = Path(__file__).resolve().parent
    if source.name == "cli" and (source.parent / "conf.example.py").is_file():
        return source.parent
    return Path.home() / ".social-auto-upload"


BASE_DIR = _data_root()
BASE_DIR.mkdir(parents=True, exist_ok=True)
LOCAL_CHROME_PATH = ""
LOCAL_BROWSER = "chrome"
LOCAL_CHROME_HEADLESS = False
YT_PROXY = None

# Keep the existing Python config format, including paths relative to __file__.
_config = BASE_DIR / "conf.py"
if _config.is_file():
    import runpy
    globals().update({key: value for key, value in runpy.run_path(str(_config)).items()
                      if not key.startswith("_")})
