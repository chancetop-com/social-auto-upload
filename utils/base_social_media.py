from typing import List

SOCIAL_MEDIA_TIKTOK = "tiktok"


def get_supported_social_media() -> List[str]:
    return [
        "instagram", SOCIAL_MEDIA_TIKTOK, "xiaohongshu", "rednote",
        "facebook", "facebook-page", "youtube",
    ]


def get_cli_action() -> List[str]:
    return ["upload", "login", "watch"]
