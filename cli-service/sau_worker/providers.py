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


async def window_closed(client, providers, task):
    """Read the scoped Local API state after the Gateway reports the grant idle."""
    name, identifier = task["provider"], task["profileId"]
    if name not in providers:
        return False
    base, key = providers[name]
    try:
        if name == "bitbrowser":
            response = await client.post(base + "/browser/pids/alive", headers={"x-api-key": key},
                                         json={"ids": [identifier]}, timeout=5)
            response.raise_for_status()
            payload = response.json()
            return payload["success"] is True and payload["data"] in ([], {})
        response = await client.get(base + "/api/v2/browser-profile/active",
                                    headers={"Authorization": "Bearer " + key}, params={"profile_id": identifier},
                                    timeout=5)
        response.raise_for_status()
        payload = response.json()
        data = payload["data"]
        return (type(payload["code"]) is int and payload["code"] == 0 and data["status"] == "Inactive"
                and all(data.get(field, identifier) == identifier for field in ("user_id", "profile_id")))
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return False
