# Gateway and desktop publishing

Build the Gateway from this directory and the desktop service from `cli-service/`. Both have a Python wheel and a console entry point. Install the CLI from the repository root into the worker’s private Python environment. The Gateway requires FastAPI, psycopg and PostgreSQL. The desktop initiates HTTPS requests and uses the two providers’ loopback Local APIs.

## Start the services

Set `GATEWAY_DATABASE_URL` to the Gateway account’s PostgreSQL database. Set separate `GATEWAY_DESKTOP_TOKEN` and `GATEWAY_INTERNAL_TOKEN` values in the service environment. Set `POSTIZ_INTERNAL_URL` to the internal Postiz API base, including its API prefix, for example `http://postiz-backend:3000/api`. Postiz must accept the same internal bearer token on its authorize-start route. Run `social-media-web-api migrate` with that database account, then `social-media-web-api serve`. The default listener is port 8080. Terminate HTTPS at the ingress and expose only the desktop routes listed below. The readiness probe `GET /health-check` reads the migrated database and returns `{"status":"ready"}`.

Set `SAU_DESKTOP_TOKEN` on the desktop to the Gateway’s desktop token. `SAU_GATEWAY_URL` defaults to `https://social-media-web-api.connexup-dev.net`. For local verification, set an explicit loopback URL. A private HTTPS fixture CA can be supplied via `SAU_GATEWAY_CA_FILE`. The worker’s default CLI argument vector starts with its absolute interpreter and `-I -X utf8 -m sau_cli`. Alternatively, pin `SAU_CLI_PYTHON` to a private absolute interpreter or `SAU_CLI_PATH` to its installed absolute `sau` entry. Paths containing spaces are supported. Set `SAU_HOME` for writable CLI data. `sau --version` must report the worker package version for it to advertise capabilities.

The worker discovers providers with a configured `BITBROWSER_API_KEY` or `ADSPOWER_API_KEY`. Set `SAU_PROVIDERS=bitbrowser,adspower` to choose providers explicitly. Use `BITBROWSER_API_BASE` and `ADSPOWER_API_BASE` for local port overrides. Enumeration starts at page 0 for BitBrowser and page 1 for AdsPower. Only profile IDs and names go into Gateway reports. The selected check receives its own provider configuration. [BitBrowser Local API](https://doc.bitbrowser.net/api-docs/browser-profiles) · [AdsPower Local API](https://localapi-doc-en.adspower.com/docs/Query-Profile-V2)

`cli-service run` advertises current inventory and waits for work. `WORKER_MAX_CONCURRENCY` defaults to 1. To check a specific local identity, run the following command in the installed desktop environment.

```sh
cli-service check --provider bitbrowser --profile-id WINDOW_ID --platform tiktok
```

The command starts a dedicated in-memory session, queues a session-specific check, claims it and prints the acknowledged Gateway record. Its process exit code is zero for a valid login. A missing profile produces `profileVisible=false`, `cliInvoked=false` and `platformLogin="unknown"`. A login challenge can produce `profileVisible=true`, `cliInvoked=true`, `exitCode=10` and `platformLogin="login-required"`. A failed Gateway request prints connectivity and acknowledgement evidence. Self-checks only invoke the paired CLI’s version and platform check actions.

## HTTP contract, version 1

Send JSON and an `Authorization: Bearer …` header. The desktop token authenticates the trusted worker fleet. Keep the internal token in the cluster.

| Scope | Method and path | Request and response |
| --- | --- | --- |
| Desktop | `POST /session` | Replace the full session report. Returns `sessionId` and database-generated `lastContactAt`. |
| Desktop | `POST /session/{sessionId}/self-check` | Select `{provider,profileId,platform}` for a dedicated self-check session. Returns its pending occurrence. |
| Desktop | `POST /publish-task/claim` | Send `{sessionId,waitSeconds}` with a 0–30 second wait. Returns `{"task":null}` or `{"task": occurrence}` after claim commit. |
| Desktop | `POST /publish-task/start` | Send `{workflowId,sessionId}` once for a claimed publish occurrence. A successful grant returns `{task: latestAuthorizedTask}`. |
| Desktop | `POST /publish-task/result` | Send `{sessionId,workflowId,receipt}`. An original claimant gets the stored occurrence after commit. An unrelated session gets 409. |
| Internal | `POST /internal/occurrences` | Send the task below. The workflow ID identifies the original occurrence on repeated delivery. |
| Internal | `GET /internal/occurrences/{workflowId}` | Return the occurrence, including its original claimant and receipt. URL-encode the workflow ID. |
| Internal | `GET /internal/sessions/{sessionId}` | Return the latest full report, including the observed CLI version, provider availability and last contact. |

A normal session uses `mode="worker"`. The operator command uses `mode="self-check"`. Reconnection preserves the process’s UUID. A new process creates a different one. A report contains `sessionId`, `mode`, `contractVersion`, `release`, `cliRelease`, `capacity`, `freeSlots`, `capabilities` and `providers`. Each capability is a `{platform,action}` pair. Each provider is `{provider,available,profiles:[{profileId,name}]}`. An unavailable provider has an empty list. The four check platforms are `rednote`, `xiaohongshu`, `tiktok` and `instagram`.

An internally queued check can be claimed by any matching available worker.

```json
{
  "workflowId": "operator-check-314",
  "contractVersion": 1,
  "requiredCapability": "tiktok.check",
  "release": "0.1.0",
  "provider": "bitbrowser",
  "profileId": "prepared-window-id",
  "platform": "tiktok",
  "action": "check"
}
```

The occurrence response wraps that task in `{workflowId,state,sessionId,task,receipt}`. Check states are `pending`, `claimed`, `succeeded` and `failed`. A successful check receipt is `{"cloudConnected":true,"cliInvoked":true,"profileVisible":true,"platformLogin":"valid","exitCode":0}`. An unobserved exit code is null. Only the first result updates a claimed occurrence. Lost claim and result acknowledgements can be inspected using the internal lookup.

## Scheduled TikTok video

For a publish occurrence, use the same contract, release, target and workflow ID fields as the check example. Set `platform="tiktok"`, `action="upload-video"` and `requiredCapability="tiktok.upload-video"`. Include these fields in the same object.

```json
{
  "organizationId": "shop",
  "bindingId": "binding-1",
  "postId": "post-1",
  "channelId": "channel-1",
  "caption": "The entire TikTok caption, including #topics",
  "settings": {},
  "media": [
    {"id": "video-1", "url": "https://media.example/video.mp4", "role": "video"},
    {"id": "cover-2", "url": "https://media.example/cover.jpg", "role": "cover"}
  ],
  "earliestPublishAt": "2027-01-01T10:00:00Z",
  "noPublish": false
}
```

Use one video and an optional cover. This release implements basic videos with empty author settings. A UTC second-precision instant becomes the CLI's `--not-before` argument. Send `null` for an immediate post. The worker passes the current media URLs and the complete caption to its absolute paired executable. Its CLI task ID is the lower-case hexadecimal SHA-256 of the UTF-8 workflow ID.

A claim reserves the session slot and profile/platform pair. On start, the Gateway rechecks worker eligibility and contacts `POST ${POSTIZ_INTERNAL_URL}/internal/browser-publishing/authorize-start` with its internal bearer token and `{workflowId,postId,organizationId}`. Postiz returns the latest task directly. The Gateway validates its identity and persists the edited task and `started` state before granting the worker its single invocation. A duplicate request receives 409. A revoked or stale occurrence receives a failed, uninvoked receipt. If authorization is interrupted, the occurrence remains claimed for reconciliation.

A publish receipt contains `outcome`, `cliInvoked` and `exitCode`. Outcomes are `published`, `prepared`, `failed` and `unknown`. The Gateway stores `published` as state `succeeded` and uses the outcome name for the other states. A successful preparation requires `noPublish=true`. The receipt retains no raw CLI output, caption, signed URL or unverified platform post ID.

For a development Chrome test account, enable and select its explicit local Chrome binding in Postiz. Set `SAU_DEV_CHROME_ALIASES` on the desktop to a comma-separated list of the approved local account aliases. The sender must specify `provider="local-chrome"` and `profileId` equal to a listed alias. The desktop invokes `--account=ALIAS --local-browser=chrome` with managed credentials removed. Use `noPublish=true` for a preparation run and an independently scheduled occurrence for formal publishing.

## Reproduce the local fixture

Use Python 3.11, uv, OpenSSL, a disposable PostgreSQL database and the Patchright Chromium matching the CLI. Run these commands from the repository root in an activated test environment. Export `GATEWAY_TEST_DATABASE_URL` for an account that can create schemas in that database.

```sh
uv pip install . ./gateway ./cli-service pytest pytest-asyncio
python -m patchright install chromium
python -m pytest -q cli-service/tests
python -m pytest -q tests/test_worker_cli_release.py
SAU_TEST_PAIRED_CHECK=1 python -m pytest -q gateway/tests
```

The POSIX process fixture builds independent wheels, installs into directories containing spaces, migrates a random schema, starts a TLS-verified loopback Gateway and registers a new simulated OS account with each CLI fixture. A disposable Chromium maps the TikTok hostname to a local fixture page. The tests cover a valid login, a login redirect and a missing profile, and read the durable receipt through the internal API. The lighter worker tests exercise both paginated provider responses, changed inventory, availability and reconnects.

## Linux Gateway image

From the paired SAU source checkout, build the Gateway alone with `docker build --platform linux/amd64 --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" -t gateway-local:verify gateway`. The non-root container entrypoint accepts `migrate` or `serve` (default), serves one application process on port 8080, and accepts SIGTERM. Idle claims return an empty response during drain. Allow at least 45 seconds of Pod termination grace for the 20-second HTTP shutdown budget and cleanup.

The built-image test requires Docker Desktop, OpenSSL, the Gateway test dependencies and a disposable PostgreSQL administrator that can create databases and roles. Set `GATEWAY_TEST_DATABASE_URL` to that admin's local URL. `GATEWAY_TEST_PG_HOST` and `GATEWAY_TEST_PG_PORT` can override the PostgreSQL address visible inside Docker (defaults to `host.docker.internal` and the admin URL port). Run `GATEWAY_TEST_IMAGE=gateway-local:verify python -m pytest -q gateway/tests/test_linux_image.py`. The test migrates a fresh database twice as its non-superuser owner, probes readiness, sends desktop requests through a temporary loopback TLS terminator, disconnects and stops active long polls, restarts the container, and checks the durable self-check receipt.

### Desktop media preparation and retention

Postiz may send an expiring media manifest to `POST /internal/preparations`. An eligible desktop that includes `acceptPreparation: true` in its claim request can receive `operation: prepare`. The desktop invokes `sau media predownload` with the occurrence's SHA-256 task ID and ordered URLs. An offer can expire or be lost. It grants no publish right, and the eventual publish command fetches its own current manifest. The worker schedules the existing lock-aware `sau media cleanup` at the next 03:00 local time. Managed downloads and publishes retain active files; seven idle days make them eligible for deletion.

The paired CLI accepts positive numbers of seconds in `SAU_DOWNLOAD_CONNECT_SECONDS` (10), `SAU_DOWNLOAD_IDLE_READ_SECONDS` (30), `SAU_DOWNLOAD_ENQUEUE_SECONDS` (10), and `SAU_BROWSER_PUBLISH_SECONDS` (900). The enqueue budget covers acceptance by the local media queue. File completion can take as long as data continues arriving. Intentional waiting for the earliest click extends the browser budget.
