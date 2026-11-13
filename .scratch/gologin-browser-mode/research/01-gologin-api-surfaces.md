# GoLogin API surfaces — research for a third managed-browser provider

**Scope:** can `sau` support GoLogin local + cloud runtimes without the `gologin` SDK dependency?
**Method:** read GoLogin's own docs (`gologin.com/docs`), its published OpenAPI, and the official SDK source
(`gologinapp/pygologin` @ `6d4e658`, npm `gologin@3.0.8`). No GoLogin software was installed or run.

**Reference shape in this repo:** `utils/managed_browser.py` (`probe` / `start(headless) -> cdp_url` /
`stop` / `status`) and `utils/adspower.py` (Local API V2 on `127.0.0.1:50325`, bearer key, `data.ws.puppeteer`).
GoLogin does **not** fit that shape the same way: there is no documented local API, but there *is* a real
cloud browser with a CDP endpoint.

> Authoritative entry point supplied by the owner:
> <https://gologin.com/docs/api-reference/cloud-browser/getting-started>

---

## TL;DR

| Surface | Exists? | Base | Auth | Gives a CDP URL? |
| - | - | - | - | - |
| GoLogin **local API** (desktop app) | **No documented API** | — | — | No |
| GoLogin **Cloud Browser** | **Yes** | `https://cloudbrowser.gologin.com` (connect) + `https://api.gologin.com` (control) | dev token, `?token=` on connect; `Authorization: Bearer` on REST | **Yes — `wss://…/connect?token=…&profile=…`** |
| GoLogin **REST API** (profiles/proxies) | Yes | `https://api.gologin.com` | `Authorization: Bearer <dev token>` (JWT) | No (metadata only) |
| **Local runtime** (Orbita on this machine) | Yes, but via binary spawn | `~/.gologin/browser` | token for profile download | Yes, after *you* spawn Orbita (`ws://127.0.0.1:<port>/devtools/browser/…`) |

**Load-bearing verdict: YES — the cloud runtime can be driven with plain HTTP + `playwright.chromium.connect_over_cdp`,
with no GoLogin SDK.** GoLogin documents the endpoint as "a standard CDP endpoint… no proprietary SDK"
(<https://gologin.com/docs/api-reference/cloud-browser/what-is-gologin-cloud-browser.md>) and ships a
first-party Playwright example that calls `connect_over_cdp` on it
(<https://gologin.com/docs/api-reference/cloud-browser/getting-started>).
The **local** runtime is the opposite: there is no local API to call, so "no SDK" means reimplementing the SDK's
Orbita download + spawn + fingerprint-file generation.

---

## 1. LOCAL API

### 1.1 Is there a local HTTP API at all?

**No documented local API exists.** This is a negative finding, established three ways:

1. The complete docs index (<https://gologin.com/docs/llms.txt>) has an "Automation & API" section listing only
   REST API reference, Node/Python SDKs, Cloud Browser, CLI tools and MCP. There is no "Local API" page.
   Direct probes of plausible URLs return 404:
   `https://gologin.com/docs/api-reference/local-api.md`,
   `https://gologin.com/docs/api-reference/introduction/local-api.md`.
2. The official OpenAPI (`https://docs-download.gologin.com/openapi.json`, also linked from the docs index as
   "OpenAPI Specs") has exactly **57 paths, all under `https://api.gologin.com`**, and none of them is a
   localhost/desktop endpoint. Server block:

   ```json
   "servers": [{ "url": "https://api.gologin.com" }]
   ```

3. Neither official SDK ever calls a localhost HTTP API. In `gologin@3.0.8`, `127.0.0.1` appears only as
   (a) a port-availability probe, (b) the CDP endpoint of the browser *it spawned itself*, and (c) a
   `ws://` → `wss://` rewrite for cloud:
   - `src/gologin.js:868` — `isPortReachable(port, { host: 'localhost' })`
   - `src/gologin.js:1217` — `http://127.0.0.1:${remote_debugging_port}/json/version`
   - `src/gologin.js:1706` — `wsUrl.replace('ws://','wss://').replace('127.0.0.1', remoteOrbitaUrlWithoutProtocol)`
   - `src/utils/sentry.js:35` — an error-string match for `ECONNREFUSED 127.0.0.1:`

   The Python SDK is the same: its only `127.0.0.1` reference is the default `address` for the browser it
   spawns (`gologin/gologin.py:57`, `self.address = options.get('address', '127.0.0.1')`) and the same rewrite
   at `gologin.py:744`. This was already true in the oldest published releases we checked (`gologin 2.0.1`).

**Consequence for the design:** the port `36912` that circulates in third-party write-ups is **not attested by any
GoLogin primary source we could find**. Do not build a provider on it. (Recorded as UNVERIFIED below.)

### 1.2 Base URL / port / auth / no-auth mode

Not applicable — there is no local API, therefore:

- **Base URL / port:** none documented; not fixed, not configurable.
- **Authentication:** none to describe; no token header, no query param, no localhost no-auth mode.
- **Start/stop endpoints, status endpoint, health/version endpoint:** none.
- **Error envelope, HTTP status codes, 429, rate limits, documented failure modes:** none.

What *does* exist locally is process orchestration, described in §3.

### 1.3 Local headless mode

There is **no first-class headless flag** on any local API (because there is no local API). The SDKs pass it as a
raw Chromium flag:

- Python: `extra_params: ["--headless"]` — <https://gologin.com/docs/api-reference/introduction/headless.md>
  ("SDK will prepare the browser and will start it on your machine then you can control it with puppeteer";
  the Python sample sets `"extra_params": ["--headless"]`).
- Node: `extra_params: ['--headless']` in the same page; CLI equivalent `GOLOGIN_HEADLESS=true`
  (<https://gologin.com/docs/cli-tools/local-agent-browser.md>).

Cloud is different: `isHeadless` is a real typed field (§2.3).

### 1.4 Firefox?

**No. Chromium only.** Verbatim, from the Orbita page:

> "Gologin profiles run only in Orbita, which is based on Chromium. Firefox-based profiles aren't available, and a
> profile can't be converted to another browser."

— <https://gologin.com/docs/orbita-browser.md>

This is good news for a CDP-attach design: every GoLogin runtime is CDP-capable.

---

## 2. CLOUD RUNTIME (the critical question)

### 2.1 Does a cloud-hosted browser really exist?

**Yes.** It is called **Gologin Cloud Browser**, and the browser process runs on GoLogin infrastructure:

> "Gologin Cloud Browser lets you run a Gologin (Orbita) browser **in the cloud** and control it from your
> automation code (Puppeteer / Playwright) using a single **connection URL**."
> "It is a headless browser … hosted and managed by Gologin"

— <https://gologin.com/docs/api-reference/cloud-browser/what-is-gologin-cloud-browser.md>

Entry point (owner-supplied, authoritative):
<https://gologin.com/docs/api-reference/cloud-browser/getting-started>

### 2.2 Distinguishing the three "cloud" things

| # | Meaning | GoLogin product | Evidence |
| - | - | - | - |
| (a) | Cloud-stored profile + **local** browser | GoLogin desktop app / web app profile sync | "All profile data is synced between desktop and web versions" — <https://gologin.com/docs/general/gologin-web-and-chrome-os.md> |
| (b) | **Cloud-hosted browser** + remote attach | **Cloud Browser** (`cloudbrowser.gologin.com`) | "run a browser session **in the cloud**… using a single connection URL" — <https://gologin.com/docs/api-reference/cloud-browser/getting-started> |
| (c) | Cloud phones / other products | Cloud Android, Web Unlocker, Scraping API | <https://gologin.com/docs/cloud-android/overview.md>, <https://gologin.com/docs/what-is-web-unlocker.md> |

So GoLogin is **not** one of the vendors where "cloud" only means metadata. (b) is real and public.

### 2.3 Exact Cloud Browser endpoints

#### Connect (the CDP endpoint)

```
https://cloudbrowser.gologin.com/connect?token=${token}&profile=${profileId}
```

Verbatim from <https://gologin.com/docs/api-reference/cloud-browser/getting-started>:

> "Use this URL in your automation library as a remote browser endpoint"
> "`token` — your Gologin **dev token**."
> "`profile` — **profile ID** (optional): if provided, Gologin will run this profile in the cloud; if omitted,
> Gologin will create a new profile for the session."
> "Note: This URL is used as a **WebSocket connection endpoint** by automation libraries (for example
> `browserWSEndpoint` in Puppeteer)."

And explicitly:

> "The `/connect` endpoint starts the browser session automatically — **no separate API call needed before
> connecting**."

— <https://gologin.com/docs/ai/cloud-browser-with-agents.md>

There is **no JSON response carrying the CDP URL** — the URL is *constructed by the client*. This is the key
difference from AdsPower (`data.ws.puppeteer`) and Multilogin (`data.port`).

Scheme: the docs' Puppeteer example uses `https://…/connect`, the Playwright example uses `wss://…/connect`.
Both are accepted (Puppeteer converts http→ws; Playwright's `connect_over_cdp` accepts `ws(s)://` directly).

#### Start / stop via REST (control plane)

OpenAPI: `POST /browser/{id}/web` and `DELETE /browser/{id}/web`
(<https://docs-download.gologin.com/openapi.json>, mirrored at
<https://gologin.com/docs/api-reference/profile/run-profile-in-the-cloud.md>).

**Start** — `POST https://api.gologin.com/browser/{id}/web`, `Authorization: Bearer <token>`

```yaml
requestBody:
  required: true
  content:
    application/json:
      schema:
        $ref: '#/components/schemas/IPostWebBrowser'
responses:
  '202':
    description: ''
```

```yaml
IPostWebBrowser:
  type: object
  properties:
    workspaceId:
      type: string
      description: Workspace id. Defaults to user default workspace.
    isHeadless:
      type: boolean
      default: false
      description: Run profile in headless mode.
    maxLifeTimeMinutes:
      type: number
      default: 15
      description: Maximum cloud session lifetime in minutes. Defaults to 15.
```

> Note the asymmetry: the OpenAPI documents **no response body** for the 202, only the status. The Python SDK
> nevertheless reads `remoteOrbitaUrl` out of the body (§3.3) — an undocumented field. Treat that as
> SDK-observed, not contract.

**Stop** — `DELETE https://api.gologin.com/browser/{id}/web` → `204`. Verbatim doc example
(<https://gologin.com/docs/api-reference/cloud-browser/getting-started>):

```javascript
const STOP_PROFILE_URL = `https://api.gologin.com/browser/${profileId}/web`;

async function stopProfile() {
  await fetch(STOP_PROFILE_URL, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  });
}
```

#### Auth

- **Connect URL:** dev token as a **query parameter** (`?token=`). No header. Docs: "`token` — your Gologin
  **dev token**" (<https://gologin.com/docs/api-reference/cloud-browser/getting-started>).
- **REST:** `Authorization: Bearer <dev token>`, described in OpenAPI as
  `bearer` / `bearerFormat: JWT` / `type: http`, and in
  <https://gologin.com/docs/api-reference/introduction/quickstart.md> ("Send your token in the `Authorization`
  header of every request to `https://api.gologin.com`").
- Token creation: app → *API & MCP* → *API* → *New Token*
  (<https://app.gologin.com/personalArea/TokenApi>).
- **Security note for the design:** a bearer/query token in a URL will appear in logs and exception text. The
  repo's AdsPower client deliberately keeps the key out of `repr`/messages (`utils/adspower.py:84-89`); a GoLogin
  provider must redact the `token=` query param the same way.

#### Error shape on connect

There is no JSON error envelope on `/connect`; the documented signal is a header on a failed preflight GET:

```python
response = await session.get(CLOUD_BROWSER_URL.replace('wss://', 'https://'))
if response.status >= 400:
    error_reason = response.headers.get('X-Error-Reason', response.reason)
    raise RuntimeError(f'Failed to start cloud browser: {error_reason}')
```

— <https://gologin.com/docs/api-reference/cloud-browser/getting-started>

REST error envelope is **not** in the OpenAPI at all (no 4xx/5xx responses and no error schema are declared for
any of the 57 paths). The Python SDK infers `{statusCode, error, message}` from behaviour
(`gologin.py:425-426`): `if data.get("statusCode") == 404: raise Exception(data.get("error") + ": " + data.get("message"))`.

### 2.4 Is the returned endpoint directly usable by Playwright?

**Yes — this is documented first-party.** Verbatim Python sample from the authoritative entry point
(<https://gologin.com/docs/api-reference/cloud-browser/getting-started>):

```python
CLOUD_BROWSER_URL = f'wss://cloudbrowser.gologin.com/connect?token={token}&profile={profile_id}'
...
async with async_playwright() as p:
    browser = await p.chromium.connect_over_cdp(CLOUD_BROWSER_URL)
```

Supporting statements:

- "Gologin Cloud Browser is a standard CDP endpoint. Your Puppeteer or Playwright code connects to it the same
  way it would connect to any remote Chrome instance — **no proprietary SDK**, no custom API to learn."
  — <https://gologin.com/docs/api-reference/cloud-browser/what-is-gologin-cloud-browser.md>
- "Gologin Cloud Browser is built on top of this same protocol — your Puppeteer or Playwright code connects to a
  remote browser over CDP and controls it the same way it would a local one."
  — <https://gologin.com/docs/api-reference/cloud-browser/what-is-headless-browser.md>
- "**Only the `/connect` endpoint works for Puppeteer/Playwright.** The Live View URL returns an HTML streaming
  interface and cannot be used as a `browserWSEndpoint`."
  — <https://gologin.com/docs/ai/cloud-browser-with-agents.md>

### 2.5 Session lifecycle

| Aspect | Documented behaviour | Source |
| - | - | - |
| **Create/start** | `connect` to `/connect` (implicit start, no prior API call), or `POST /browser/{id}/web` (202) | getting-started; run-profile-in-the-cloud |
| **Status** | **No status endpoint documented.** OpenAPI has no `GET /browser/{id}/web`. Only usage aggregates: `GET /cloud-usage/stats?days=&workspaceId=` and `GET /cloud-usage/profile/{browserId}/stats` ("total usage in minutes and hours") | openapi.json |
| **Keepalive** | None documented. Session stays active 15 min after the last action; closing the automation connection may end the session ("depends on your workflow and plan limits") | faq-web-app-and-cloud-browser; live.md |
| **Idle timeout** | "Cloud browser will stay active for **15 minutes** after any action or after you close the profile tab without hitting Stop" | <https://gologin.com/docs/faq-web-app-and-cloud-browser.md> |
| **Max session duration** | `maxLifeTimeMinutes`, default **15**, set on `POST /browser/{id}/web` | IPostWebBrowser schema |
| **Stop** | `DELETE /browser/{id}/web` → 204, or `browser.close()` | getting-started; manage-a-browser-session |
| **Concurrency** | 1 / 2 / 3 / 4 parallel sessions on Professional / Business / Enterprise / Custom; buy more at $2/session/month | what-is-gologin-cloud-browser; cloud-browser-usage |
| **Reconnect semantics** | "Each `puppeteer.connect()` or `connect_over_cdp()` call starts a new session." Reuse one connection; do not connect to the same profile from multiple processes | <https://gologin.com/docs/api-reference/cloud-browser/manage-a-browser-session.md> |

**Design consequence:** a 15-minute default lifetime is a real risk for long video uploads. Either send
`POST /browser/{id}/web` with a larger `maxLifeTimeMinutes` before connecting, or budget for reconnects. Whether
the `/connect` URL honours a `maxLifeTimeMinutes` previously set via POST is **not documented** (see gaps).

### 2.6 Plan gating

- "Cloud browser profiles and extra cloud limits are available on **paid plans only**."
  — <https://gologin.com/docs/general/account-and-billing/cloud-browser-usage.md>
- "Running profiles in the cloud requires a paid plan." — <https://gologin.com/docs/general/troubleshooting/common-errors.md>
- "The trial and Forever Free plans don't include API access." — <https://gologin.com/docs/api-reference/limitations/rate-limits.md>
- Failure mode when over the limit: `"You've reached max parallel cloud launches limit"` / `"You've hit your
  parallel launch limit"` — same Common Errors page.
- "Local launches are not limited by your plan." — same page.

### 2.7 Rate limits and 429

| Plan | Requests/min |
| - | -: |
| Professional | 300 |
| Business | 500 |
| Enterprise | 800 |
| Custom | 1,200 |

> "When you exceed the rate limit and receive an HTTP 429 response, **your API token is automatically
> invalidated**. This means your token becomes permanently unusable and you must generate a new one. This is not
> a temporary cooldown — the token is revoked."

— <https://gologin.com/docs/api-reference/limitations/rate-limits.md>

Also documented: Cloudflare 1015 HTML error pages instead of JSON when an IP bursts, and ~300 profile
creations/day for new accounts. This is materially harsher than AdsPower's 429 handling (`RateLimitedError`,
retry-later), so the provider must never retry blindly and must surface a distinct "token revoked" message.

### 2.8 Kernel and headless

- Kernel: **Chromium (Orbita)**. "Gologin Cloud Browser runs **Orbita** — a modified Chromium…"
  (<https://gologin.com/docs/api-reference/cloud-browser/what-is-gologin-cloud-browser.md>); Firefox is not
  available (<https://gologin.com/docs/orbita-browser.md>).
- Headless: **yes, a typed parameter** — `isHeadless` (boolean, default `false`) on `POST /browser/{id}/web`.
  The `/connect` URL itself has **no** headless parameter documented; it is headless-by-nature as a product
  ("It is a headless browser"), but the typed control lives on the REST start call.

### 2.9 Plain HTTP without the SDK

Two explicit statements plus the working example:

1. "**no vendor lock-in** … a standard CDP endpoint … **no proprietary SDK**, no custom API to learn. Switch in or
   out with a single URL change." — what-is-gologin-cloud-browser.md
2. "The `/connect` endpoint starts the browser session automatically — **no separate API call needed** before
   connecting." — cloud-browser-with-agents.md
3. The Playwright sample uses only `aiohttp` + `playwright` — no `gologin` import — getting-started.

---

## 3. THE OFFICIAL SDK (`gologinapp/pygologin`, PyPI `gologin`)

Version at time of writing: **2026.6.24**, commit
[`6d4e6589eaaa08a395216b45547be20cc8f182d8`](https://github.com/gologinapp/pygologin/commit/6d4e6589eaaa08a395216b45547be20cc8f182d8)
(PyPI JSON: `https://pypi.org/pypi/gologin/json`).

### 3.1 What `start()` actually does — step by step

`start()` (`gologin/gologin.py:250`) is only:

```python
def start(self):
    try:
        profile_path = self.createStartup()
        if self.spawn_browser == True:
            return self.spawnBrowser()
        return profile_path
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise e
```

There is **no local-API call and no fallback chain**. It does not "try the desktop app, then download". The
sequence is always:

1. **`createStartup()`** (`gologin.py:753`)
   - `self.profile = self.getProfile()`
   - derive the Orbita major version from the profile's UA:
     `uaVersion.split('Chrome/')[1].split(' ')[0]` → `orbita_major_version`
   - `BrowserManager().get_orbita_path(browserMajorVersion)` → download/extract if missing
   - if `local == False` and the profile is not new: `downloadProfileZip()`; if new: `createEmptyProfile()`
   - `updatePreferences()` — writes `Default/Preferences` (fingerprint mapping) and `orbita.config`
   - if `writeCookiesFromServer` and the profile has cookies: `downloadCookies()`
2. **`spawnBrowser()`** (`gologin.py:186`) — `subprocess.Popen` with:

   ```python
   params = [
       self.executablePath,
       '--remote-debugging-port='+str(self.port),
       '--password-store=basic',
       '--gologin-profile='+self.profile_name,
       '--lang=en-US',
       '--webrtc-ip-handling-policy=default_public_interface_only',
       '--disable-features=PrintCompositorLPAC',
       '--window-size='+str(screenWidth)+','+str(screenHeight),
       '--user-data-dir='+self.profile_path,
   ]
   ```
   then polls `http://127.0.0.1:<port>/json` up to ~100 s and returns the **string** `"127.0.0.1:<port>"`
   (a Selenium `debuggerAddress`, *not* a `ws://` URL).

### 3.2 What it downloads, and from where

`BrowserManager` (`gologin/browserManager/browserManager.py:23,43`), install root `~/.gologin/browser`:

| Platform | URL |
| - | - |
| Linux | `https://orbita-browser-linux.gologin.com/orbita-browser-latest-{major}.tar.gz` |
| macOS (Intel) | `https://orbita-browser-mac.gologin.com/orbita-browser-latest-{major}.tar.gz` |
| macOS (arm64) | `https://orbita-browser-mac-arm.gologin.com/orbita-browser-latest-{major}.tar.gz` |
| Windows | `https://orbita-browser-windows.gologin.com/orbita-browser-latest-{major}.zip` |

Executable paths: `chrome.exe` (win) / `Orbita-Browser.app/Contents/MacOS/Orbita` (mac) / `chrome` (linux).

Profile data (separate from the binary) comes from the SDK's own gateway constant:

```python
API_URL = 'https://api.gologin.com'
PROFILES_URL = 'https://gprofiles-new.gologin.com/'
GET_TIMEZONE_URL = 'https://geo.myip.link'
FILES_GATEWAY = 'https://storage-worker-test.gologin.com'
```

`gologin.py:40-43`; profile zip `GET {FILES_GATEWAY}/download` with header `browserId: <profile_id>`
(`gologin.py:442`), commit `PUT {FILES_GATEWAY}/upload` (`gologin.py:323`).

### 3.3 Does the SDK have a cloud path?

**Yes** — `startRemote()` / `stopRemote()` (`gologin.py:909`, `:928`):

```python
http_response = make_request(
    'POST',
    API_URL + '/browser/' + self.profile_id + '/web',
    headers=self.headers(),
    json_data={'isNewCloudBrowser': self.is_new_cloud_browser, 'isHeadless': self.is_cloud_headless}
)
response = json.loads(responseJson)
remote_orbita_url = 'https://' + self.profile_id + '.orbita.gologin.com'
if self.is_new_cloud_browser:
    if not response['remoteOrbitaUrl']:
        raise Exception('Couldn\' start the remote browser')
    remote_orbita_url = response['remoteOrbitaUrl']
return self.waitDebuggingUrl(delay_s, remote_orbita_url=remote_orbita_url)
```

`waitDebuggingUrl()` (`:887`) polls `{remoteOrbitaUrl}/json/version`, takes `webSocketDebuggerUrl`, then rewrites
`ws://`→`wss://` and `127.0.0.1`→host. So the SDK's cloud path is a *second* mechanism (REST + `/json/version`
discovery, legacy host `https://<profile_id>.orbita.gologin.com`) alongside the documented `/connect` URL.
Note `is_cloud_headless` defaults to **True** (`gologin.py:74`).

So: the SDK is **not** local-only, but its cloud path is not needed — the documented `/connect` route is simpler
and is what GoLogin's own docs recommend.

### 3.4 Dependencies

`requirements.txt` (read directly; identical to PyPI `requires_dist`):

```
requests
psutil
webdriver_manager>=4.0.0
selenium>=4.11.0
sentry-sdk>=2.29.1
```

Notably it drags in **selenium** and **webdriver-manager** even for Playwright/CDP use, plus **Sentry telemetry
on by default** ("The SDK sends anonymous error reports… set `DISABLE_TELEMETRY=true`",
<https://gologin.com/docs/api-reference/sdks/python-sdk.md>). For a CLI that must not phone home, that is a
strong argument against the dependency.

npm `gologin@3.0.8` for comparison: `puppeteer-core@^2`, `sqlite3`, `archiver`, `decompress`, `adm-zip`,
`@sentry/node`, etc. (`https://registry.npmjs.org/gologin/latest`).

### 3.5 `create()` / profile creation / `getProfile()` against `api.gologin.com`

All use `Authorization: Bearer <token>` plus `User-Agent: Selenium-API` (`headers()`, `gologin.py:870`):

| Method | Request |
| - | - |
| `getProfile()` | `GET /browser/features/{id}/info-for-run` — **not in the public OpenAPI** |
| `create()` | `GET /browser/fingerprint?os={os}` then `POST /browser` |
| `createProfileRandomFingerprint()` | `POST /browser/quick` with `{os, osSpec, name}` |
| `createProfileWithCustomParams()` | `POST /browser/custom` |
| `delete()` | `DELETE /browser/{id}` |
| `addGologinProxyToProfile()` | `GET /users-proxies/geolocation/traffic` then `POST /users-proxies/mobile-proxy` |
| Orbita param token | `GET /browser/features/{id}/profile-params-for-orbita-token` — **not in the public OpenAPI** |

The two `features/...` endpoints being absent from the published OpenAPI matters: the SDK depends on private
routes, so "match the SDK" is not a stable contract.

### 3.6 Anything the SDK does that plain HTTP + CDP cannot?

**Cloud runtime: essentially nothing.** Connect URL + `DELETE /browser/{id}/web` covers start/attach/stop.
The only SDK extras are conveniences (profile creation, proxy attach, usage) that are all public REST.

**Local runtime: yes, a lot.** To run locally without the SDK you must reproduce:

- Orbita version selection from the profile UA and the binary download/extract (per-OS URLs above);
- profile zip download/extract from `FILES_GATEWAY`, and re-upload on stop (`PUT /upload`) to persist cookies;
- generation of `Default/Preferences` (~150 lines of fingerprint mapping in `getGologinPreferences()` /
  `updatePreferences()`) **and** `orbita.config` containing `intl` + `gologin.profile_token`;
- fetching `profile-params-for-orbita-token` (private endpoint) for newer Orbita versions;
- cookie DB import (`CookiesManager`), extension download, cache sanitisation;
- spawning with the exact flag set and discovering `webSocketDebuggerUrl` from `/json/version`.

That is a re-implementation of the SDK, not a thin client — and it is undocumented surface.

---

## 4. CLOUD API (`api.gologin.com`)

- **Base URL:** `https://api.gologin.com` (OpenAPI `servers`).
- **Auth:** `Authorization: Bearer <dev token>`; scheme declared as `bearer`, `bearerFormat: JWT`
  (OpenAPI `components.securitySchemes`; quickstart).
- **Relevant endpoints:**

| Method + path | Purpose | Response |
| - | - | - |
| `GET /browser/v2` | list profiles (30/page, `?page=`) | `{profiles: [...], allProfilesCount: n}` |
| `GET /browser/{id}` | full profile (`?currentWorkspace=`) | `OBrowser` |
| `POST /browser/{id}/web` | run profile in cloud | `202`, no documented body |
| `DELETE /browser/{id}/web` | stop cloud profile | `204` |
| `POST /browser/quick` | create profile w/ random fingerprint | profile object incl. `id` |
| `POST /browser` / `POST /browser/custom` | create profile | profile |
| `GET /cloud-usage/profile/{browserId}/stats` | usage minutes/hours | 200 |
| `GET /cloud-usage/stats?days=&workspaceId=` | workspace usage, limits | 200 |

- **Profile id format:** 24-char lowercase hex, Mongo ObjectId style. Confirmed by example values in the
  OpenAPI (`60a763f86501b3abcdc54b21`, `6200f55e7685342e170dc531`) and by the SDK's direct interpolation into
  path segments. Validate with `^[0-9a-f]{24}$` before URL-building.
- **Rate limits / errors:** see §2.7. No error schema is published; only status codes. The SDK's observed
  envelope is `{statusCode, error, message}` (`gologin.py:425-427`) — treat as UNVERIFIED contract.

---

## 5. Official statements on CDP / Playwright / Puppeteer per runtime and kernel

| Runtime | Kernel | CDP attach documented? | Official example |
| - | - | - | - |
| **Cloud Browser** | Orbita (Chromium) | **Yes, explicitly** — `connect_over_cdp` / `puppeteer.connect` | getting-started (Puppeteer + Python Playwright) |
| **Local Orbita** | Orbita (Chromium) | Yes, via `--remote-debugging-port`; SDK returns `wsUrl` (Node) or `127.0.0.1:<port>` (Python) | python-sdk.md (Selenium `debuggerAddress`); nodejs-sdk.md (`const { status, wsUrl } = await GL.start()`) |
| **Firefox** | — | **Not available** | orbita-browser.md |

Node SDK local `start()` returns a real CDP WebSocket URL:

```javascript
const { status, wsUrl } = await GL.start();
// Connect Puppeteer or Playwright using wsUrl
```

— <https://gologin.com/docs/api-reference/sdks/nodejs-sdk.md>; implementation fetches
`http://127.0.0.1:<port>/json/version` and returns `webSocketDebuggerUrl` (`gologin@3.0.8` `src/gologin.js:1217`).

Python SDK local `start()` returns `"127.0.0.1:<port>"` (no scheme), which Playwright accepts as
`http://127.0.0.1:<port>` — but GoLogin does not document that combination; their Python docs pair local with
Selenium.

---

## 6. Fit against this repo's provider protocol

`utils/managed_browser.py` requires `probe()`, `start(headless) -> url`, `stop()`, `status()`.

**Cloud provider (fits cleanly):**

| Method | Implementation | HTTP needed? |
| - | - | - |
| `probe` | `GET https://api.gologin.com/browser/{id}` with bearer → 200 / 401 / 404 | yes (1 call) |
| `start(headless)` | optionally `POST /browser/{id}/web {isHeadless, maxLifeTimeMinutes}`; return `wss://cloudbrowser.gologin.com/connect?token=…&profile=…` | optional |
| `stop` | `DELETE /browser/{id}/web` | yes |
| `status` | **no endpoint** — return `"unknown"` / derive from last connect or `/cloud-usage/profile/{id}/stats` | n/a |

Note `start()` in this repo returns a URL that `browser_session` hands to `connect_over_cdp`, so a `wss://`
string is exactly the right shape — no port juggling as with Multilogin.

**Local provider (does not fit):** there is no local API, so `probe()`/`start()` would have to own Orbita
download + spawn + config generation. Realistic options, in order of cost:

1. **Cloud-only provider** — smallest, fully documented, no new dependency.
2. **Local via reimplementation** — large, undocumented surface, high maintenance.
3. **Local via SDK** — contradicts the "no `gologin` dependency" goal and adds selenium + Sentry telemetry.
4. **Local via `gologin-agent-browser` CLI daemon (port 44778)** — adds an npm/Node 20 dependency and is itself
   just a wrapper over the Node SDK (<https://gologin.com/docs/cli-tools/local-agent-browser.md>).

---

## 7. Confidence & gaps

### CONFIRMED (official doc or official source read directly)

- Cloud Browser is a real cloud-hosted Chromium/Orbita browser, publicly documented, with a CDP endpoint.
- Connect URL shape and query params: `https://cloudbrowser.gologin.com/connect?token=&profile=`.
- Playwright `connect_over_cdp` works on that URL — first-party Python example.
- REST start `POST /browser/{id}/web` (202) with `isHeadless` (default false) and `maxLifeTimeMinutes`
  (default 15); stop `DELETE /browser/{id}/web` (204).
- Auth: `?token=` on connect, `Authorization: Bearer` on REST; JWT bearer scheme in OpenAPI.
- 15-minute idle/lifetime behaviour; 1–4 concurrent sessions by plan; paid-plan gating.
- 300–1200 req/min limits and **429 ⇒ token permanently revoked**.
- Chromium only; Firefox profiles do not exist.
- Profile ids are 24-hex ObjectIds.
- No documented local API (docs index, OpenAPI, both SDKs).
- Python SDK `start()` downloads Orbita from `orbita-browser-*.gologin.com` and spawns it with
  `--remote-debugging-port`; it never calls a local HTTP API.
- Python SDK has `startRemote()`/`stopRemote()`; it is not local-only.
- SDK dependency list, incl. selenium/webdriver-manager and Sentry telemetry on by default.
- Local Orbita paths, download URLs, and spawn flags (from SDK source).

### INFERRED (reasoned, not stated verbatim)

- Playwright also works against the **local** runtime via `http://127.0.0.1:<port>` — true of any Chromium CDP
  endpoint, but GoLogin documents local only with Selenium/Puppeteer.
- The `POST /browser/{id}/web` response body contains `remoteOrbitaUrl` — observed in SDK source, absent from
  OpenAPI.
- REST error envelope `{statusCode, error, message}` — observed in SDK parsing only.

### UNVERIFIED / open gaps

1. **`127.0.0.1:36912`** — no GoLogin primary source attests a local API or this port. Do not use.
2. **Session status** — no documented live-status endpoint. Whether `GET /browser/{id}/web` exists
   (undocumented) is unknown; OpenAPI declares only POST/DELETE.
3. **`maxLifeTimeMinutes` vs `/connect`** — whether a POST-set lifetime applies to a subsequent `/connect`
   session, and whether `/connect` has any query param for lifetime/headless, is undocumented.
4. **Preflight double-session risk** — the docs' Playwright example does a GET preflight *and* then connects,
   while "each `connect_over_cdp()` call starts a new session". Whether the preflight consumes a session slot /
   starts billing is not stated. Safest: skip the preflight or accept the ambiguity.
5. **Stop semantics for state persistence** — whether `DELETE /browser/{id}/web` commits cookies/storage back to
   the profile (as `gl.stop()` does locally) is not documented. Cloud docs claim profile persistence across
   sessions but do not tie it to the DELETE call.
6. **Cloud `isHeadless=false` + Playwright** — attaching to a headed cloud session is presumably fine, but the
   examples are all effectively headless; no doc discusses the interaction.
7. **Connect URL error status codes** — docs only show `>= 400` + `X-Error-Reason`; the actual code set
   (401/402/409/429) is not enumerated.
8. **Rate limit on `/connect`** — the published per-plan RPM limits are described for "the Gologin API"; whether
   the Cloudflare/429 token-revocation rule also applies to `/connect` requests is not explicit.

---

## 8. Verdict on the load-bearing question

**Can the cloud runtime be driven without the GoLogin SDK, using only plain HTTP + Playwright's
`connect_over_cdp`? → YES.**

Evidence, strongest first:

1. GoLogin's authoritative Cloud Browser entry point ships a **Playwright** example that imports only `aiohttp`
   and `playwright`, builds `wss://cloudbrowser.gologin.com/connect?token=…&profile=…`, and calls
   `p.chromium.connect_over_cdp(CLOUD_BROWSER_URL)` — no `gologin` import anywhere.
   <https://gologin.com/docs/api-reference/cloud-browser/getting-started>
2. GoLogin states the product is "a standard CDP endpoint… **no proprietary SDK**, no custom API to learn."
   <https://gologin.com/docs/api-reference/cloud-browser/what-is-gologin-cloud-browser.md>
3. "The `/connect` endpoint starts the browser session automatically — no separate API call needed before
   connecting." <https://gologin.com/docs/ai/cloud-browser-with-agents.md>
4. Stop is a single documented REST call: `DELETE https://api.gologin.com/browser/{id}/web` with a bearer token.
5. The SDK's own cloud path (`startRemote`) adds nothing that plain HTTP cannot do — it merely POSTs the same
   endpoint and discovers `webSocketDebuggerUrl` from `/json/version`.

**Corollary:** the same is **not** true for the **local** runtime. GoLogin exposes no local API, so a local
provider without the SDK means reimplementing Orbita download/spawn/fingerprint-file generation. If the design
must keep "no `gologin` dependency" *and* support local, the local path is a build-it-yourself subsystem, not an
API integration — and the cloud path is the only thin one.

---

## 9. ADDENDUM (2026-11-13, after owner pushback) — the Agent Browser CLI daemon

The owner asked whether GoLogin has a "Local REST API". The first pass answered "no local API" for the **desktop app**,
which is still correct. But there **is** a documented local HTTP surface — it belongs to the **Agent Browser CLI**,
not the desktop app. This addendum records it so the spec does not overstate the negative finding.

Source: <https://gologin.com/docs/cli-tools/local-agent-browser.md>,
<https://gologin.com/docs/cli-tools/agent-browser.md>,
<https://github.com/GologinLabs/agent-browser>

### What exists

- npm package `gologin-agent-browser-cli`, **Node.js 20+** for the local runtime (18+ for cloud).
- Two runtimes: `cloud` and `local`, selected by `--runtime` or `GOLOGIN_AGENT_BROWSER_RUNTIME`.
- A **persistent local daemon per runtime**:
  - Unix socket `${TMPDIR:-/tmp}/gologin-agent-browser.sock`
  - localhost HTTP `127.0.0.1:${GOLOGIN_DAEMON_PORT:-44777}` (cloud) / `44778` (local)
- The daemon owns the live browser session: it connects to Cloud Browser or local Orbita **through Playwright
  `connectOverCDP`**, keeps the active page in memory, builds snapshots, resolves refs, tracks session metadata.

### Why it does not fit this repo

- It is a **command surface** (`open`, `snapshot`, `click`, `fill`, `upload`, `cookies`, ...), not a CDP proxy.
  The docs never expose the underlying CDP endpoint; `sessions` / `current` return session metadata only.
  Driving it would mean rewriting all 16 platform uploaders from Playwright calls to CLI commands.
- The local runtime still needs the **Gologin Node SDK** to launch Orbita, so it is not an SDK-free path either —
  it just moves the dependency from Python to Node.
- It adds a second runtime (Node 20 + npm) to a Python CLI.

### What this changes in the verdict

Nothing about the load-bearing conclusion:

- **Cloud**: still zero-dependency, standard CDP, `connect_over_cdp` on `wss://cloudbrowser.gologin.com/connect`.
- **Local**: the only SDK-free *shape* that fits this repo is spawning Orbita ourselves (reimplementation, §3.6).
  The practical alternative remains the Python SDK as a launcher (`gl.start()` → `127.0.0.1:<port>` → patchright
  `connect_over_cdp`), which keeps the repo's Playwright uploaders unchanged.
- The `44778` daemon is a fifth option, but it is a rewrite of the automation layer, not an integration.

### 9.1 Route-level confirmation (source read, 2026-11-13)

Read `src/local-agent/daemon/server.ts` and `src/local-agent/lib/types.ts` at `main` (`17f2889`):

- Routes: `GET /health`, `GET|POST /profiles*`, `GET /sessions`, `GET /sessions/current`,
  `POST /sessions/open`, and per-session `POST /sessions/{id}/{tabs,tabopen,tabfocus,tabclose,snapshot,click,type,
  fill,hover,focus,dblclick,select,check,uncheck,press,wait,scroll,scrollintoview,get,cookies,cookies-import,
  cookies-clear,storage-export,storage-import,storage-clear,eval,find,screenshot,upload,pdf,close}`.
- `OpenSessionResponse` = `{sessionId, profileId?, url, liveViewUrl?, proxy?, idleTimeoutMs?}`.
- `SessionSummary` = `{sessionId, profileId?, url, active, hasSnapshot, staleSnapshot, liveViewUrl?, proxy?,
  createdAt?, lastActivityAt?, idleTimeoutMs?, lastScreenshotPath?, lastPdfPath?}`.
- `connectUrl` exists only on the daemon-internal `SessionRecord`; it is never serialized to a client.

**Conclusion:** the 44778 daemon exposes a **page-command API**, not a CDP endpoint. It cannot hand a Playwright
client a browser. Using it from this repo would mean rewriting the uploaders, not integrating the provider seam.

### 9.2 Third-party claims of a desktop-app local API on 36912 (UNVERIFIED)

Two secondary sources claim the **desktop app** exposes an unauthenticated local HTTP API on `127.0.0.1:36912`:

- <https://antidetectreview.org/blog/anti-detect-browser-api-automation-comparing-multilogin-adspower-gologin>
  (2026-05-19): `POST /browser/start` with `{"profileId": "<id>"}` →
  `{"status":"success","wsUrl":"ws://localhost:<port>/devtools/browser/<guid>"}`; also `PUT /browser/{id}` to set a
  proxy. Claims "no auth token is required for local calls" and that GoLogin "has changed port numbers".
- <https://mmo4me.com/threads/chia-se-cac-buoc-tao-profile-gologin-su-dung-offline.449942/page-2> (forum):
  `POST /browser/start-profile` with `{"profileId": "<id>", "sync": false}`.

**Why this cannot go into the spec as-is**

1. No GoLogin primary source (docs index, OpenAPI, SDK source) attests it — see §1.1.
2. The two sources disagree on the endpoint path (`/browser/start` vs `/browser/start-profile`).
3. One source itself notes GoLogin has changed port numbers across versions, and that its errors are terse.
4. The response shape is claimed, not reproduced.

**Disposition:** recorded as UNVERIFIED. [Ticket 10](../issues/10-verify-gologin-local-api.md) is a HITL probe
that captures the real contract (or `ECONNREFUSED`) before the runtime decision is made.

---

## 10. DECISIVE FINDING (2026-11-13, static analysis of the shipped app)

The owner's GoLogin desktop app is installed at `/Applications/Gologin.app`. Its Electron `app.asar`
(404 MB, includes an unminified server bundle + source map at `src/electron/server/src/...`) contains the
**complete local HTTP server**. This supersedes §1.1's "no local API" for the *desktop app*: the API exists,
it is simply **undocumented publicly**.

### 10.1 Port

```ts
// src/electron/server/src/index.ts
let port = 36912;
let isPortBusy = await isPortReachable(port);
while (isPortBusy) {
  isPortBusy = await isPortReachable(++port);
}
const server = app.listen(port, () => { console.log(`Local server started on port ${port}`); });
global.appPort = port;
```

- Default `36912`, **incremented while busy** → the port is *not* fixed.
- Discovery: probe `http://127.0.0.1:<port>/service/check-server` from 36912 upward.
- CORS: `cors({origin: /.*/, optionsSuccessStatus: 200})`; body limit `10mb`.

### 10.2 Routes (extracted, exhaustive)

| Method | Path | Behaviour |
| - | - | - |
| GET | `/service/check-server` | `200 {status: true}` |
| POST | `/service/credentials` | body `{access, api, twoFa}` → sets `global.credentials`, echoes it |
| POST | `/browser/start-profile` | body `{profileId, sync}`; 400 `Invalid params` if no id |
| POST | `/browser/stop-profile` | body `{profileId}` → `killProfile(id)`, `204`; 400 if no id |
| GET | `/cookies/:id` | reads cookies via the cloud API |
| POST | `/cookies/:id` | writes cookies via the cloud API |
| POST | `/cookies/:id/cookies_stats` | cookie stats |
| GET | `/session/ready` | empty 200 |
| GET | `/timer/update/:id` | empty 200 |
| GET | `/close/:id` | macOS: SIGTERM the Orbita process; empty 200 |

### 10.3 `start-profile` exact semantics

```js
router.post('/browser/start-profile', async (req, res) => {
  const { profileId = '', sync = false } = req.body;
  if (!profileId) return res.status(400).send('Invalid params').end();
  let debuggingPort = 0;
  if (sync) debuggingPort = await getFreePort();          // e1()
  const remoteApiOptions = {
    cb: async (err = {}) => {
      if (err) { const { status = 400, message = '' } = err; return res.status(status).send(message).end(); }
      let wsUrl = '';
      if (debuggingPort) {
        const v = await fetch(`http://127.0.0.1:${debuggingPort}/json/version`).json().catch(() => null);
        if (v) wsUrl = v.webSocketDebuggerUrl;
      }
      res.status(200).json({ status: 'success', wsUrl });
    },
    sync,
    debuggingPort,
  };
  await loadProfile({ profileId, iconBase64: '', channel: global.channel,
                      remoteApiOptions, launchViaRestApi: true }).catch(() => null);
});
```

**Critical:** `sync: true` is required to get a non-empty `wsUrl`. With `sync` false/omitted the app allocates no
debugging port and returns `{"status":"success","wsUrl":""}`. Both third-party examples cited in §9.2 get this
wrong (one omits `sync`, one passes `sync:false`).

### 10.4 Consequences for the provider

- `probe()` → GET `/service/check-server` on the discovered port.
- `start(headless)` → POST `/browser/start-profile` `{profileId, sync: true}` → `wsUrl`
  (`ws://127.0.0.1:<debugPort>/devtools/browser/<guid>`).
- `stop()` → POST `/browser/stop-profile` `{profileId}` → 204.
- `status()` → no status route; return `"unknown"` (diagnostic only).
- **Zero new dependencies.** `requests` is already in `pyproject.toml`.
- `headless` is not a parameter of the local API → local runtime launches the app's normal (headed) Orbita.
- The API is undocumented and ships with the desktop app → pin/regress against an app version; fail with a clear
  message if `/service/check-server` is absent on every probed port.
