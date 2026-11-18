from typing import List

SOCIAL_MEDIA_TIKTOK = "tiktok"


def get_supported_social_media() -> List[str]:
    return [
        "xiaohongshu", "rednote", "facebook", "facebook-page",
        "instagram", "youtube", SOCIAL_MEDIA_TIKTOK,
    ]


def get_cli_action() -> List[str]:
    return ["upload", "login", "watch"]
