import httpx


DEFAULT_BASES = {"bitbrowser": "http://127.0.0.1:54345", "adspower": "http://127.0.0.1:50325"}


async def inventory(client, name, base, key):
    """Project only the profile ID and display name from each complete Local API enumeration."""
    unavailable = {"provider": name, "available": False, "profiles": []}
    if not key:
        return unavailable
    bit = name == "bitbrowser"
    path = "/browser/list" if bit else "/api/v2/browser-profile/list"
    headers = {"x-api-key": key} if bit else {"Authorization": "Bearer " + key}
    page = 0 if bit else 1
    profiles = {}
    page_size = 100
    try:
        while True:
            body = {"page": page, "pageSize" if bit else "limit": page_size}
            response = await client.post(base + path, headers=headers, json=body, timeout=5)
            response.raise_for_status()
            payload = response.json()
            if (bit and payload["success"] is not True) or (not bit and payload["code"] != 0):
                raise ValueError("Provider unavailable")
            rows = payload["data"]["list"]
            if not isinstance(rows, list):
                raise ValueError("Invalid provider response")
            count = len(profiles)
            for row in rows:
                identifier = row["id" if bit else "profile_id"]
                if not isinstance(identifier, str) or not identifier:
                    raise ValueError("Missing profile identifier")
                profiles[identifier] = {"profileId": identifier, "name": row.get("name") or ""}
            if len(rows) < page_size:
                break
            if count == len(profiles):
                raise ValueError("Provider repeated a page")
            page += 1
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return unavailable
    return {"provider": name, "available": True, "profiles": list(profiles.values())}
