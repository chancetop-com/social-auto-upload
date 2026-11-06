# -*- coding: utf-8 -*-
"""TikTok Studio URLs, timings and selectors.

``uploader.tk_uploader.main_chrome`` re-exports these names, so importing them
from either module keeps working.
"""

TIKTOK_UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
TIKTOK_PHOTO_UPLOAD_URL = (
    "https://www.tiktok.com/tiktokstudio/upload?tab=photo"
)
TIKTOK_LOGIN_CHECK_URL = "https://www.tiktok.com/tiktokstudio/upload?lang=en"
TIKTOK_LOGIN_CHECK_TIMEOUT_MS = 20_000
# TikTok Studio is client-rendered; the upload shell can take >5s after login.
# Keep this within TIKTOK_LOGIN_CHECK_TIMEOUT_MS (20s total).
TIKTOK_ENTRY_WAIT_MS = 15_000
TIKTOK_LOCAL_ENTRY_WAIT_MS = 20_000
TIKTOK_OVERLAY_CLICK_TIMEOUT_MS = 5_000
TIKTOK_PUBLISH_TIMEOUT_SECONDS = 15 * 60

# Web UI photo-post limits (TikTok Studio front-end constants, research 01).
TIKTOK_MAX_IMAGE_COUNT = 35
TIKTOK_MAX_IMAGE_BYTES = 50 * 1024 * 1024
TIKTOK_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
TIKTOK_MAX_TITLE_LENGTH = 90
TIKTOK_MAX_DESCRIPTION_LENGTH = 4000
TIKTOK_MAX_HASHTAG_COUNT = 50

TIKTOK_UPLOAD_ENTRY_SELECTOR = (
    '[data-e2e="select_video_button"], '
    '[data-e2e="select_video_container"], '
    'button:has-text("Select video"), div.upload-container, '
    'iframe[data-tt="Upload_index_iframe"]'
)
TIKTOK_LOGIN_FORM_SELECTOR = (
    'input[name="username"], form[action*="login"], '
    'div[data-e2e="login-modal"], '
    'button:has-text("Use phone / email / username")'
)


class Tk_Locator(object):
    tk_iframe = '[data-tt="Upload_index_iframe"]'
    default = 'body'
