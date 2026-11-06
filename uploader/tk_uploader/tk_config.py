# -*- coding: utf-8 -*-
"""TikTok Studio URLs, timings and selectors.

``uploader.tk_uploader.main_chrome`` re-exports these names, so importing them
from either module keeps working.
"""

TIKTOK_UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
TIKTOK_LOGIN_CHECK_URL = "https://www.tiktok.com/tiktokstudio/upload?lang=en"
TIKTOK_LOGIN_CHECK_TIMEOUT_MS = 20_000
TIKTOK_ENTRY_WAIT_MS = 5_000
TIKTOK_PUBLISH_TIMEOUT_SECONDS = 15 * 60

TIKTOK_UPLOAD_ENTRY_SELECTOR = (
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
