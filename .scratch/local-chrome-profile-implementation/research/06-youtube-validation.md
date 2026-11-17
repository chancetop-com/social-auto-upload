# YouTube Profile migration validation — 2026-11-17

Worktree: `/private/tmp/sau-local-profile-06`; base: `ec6ea39` (first batch integrated).
Interpreter: original project `.venv/bin/python` (Python 3.11); runtime imports and `conf.BASE_DIR` verified inside the worktree. No credentials or real account state were read. No real upload, publication, or deletion occurred.

## Covered public paths

`youtube login/check/upload-video/reset-profile`, `youtube_setup`, compatibility `cookie_auth`/`youtube_cookie_gen`, and direct `YouTubeVideo.main/upload` all use the selected persistent Profile for local actions. Injected BrowserSession ownership remains with its caller. The upload precheck and upload hold one Profile lease in one context. Compatibility positional filenames only supply the alias; no JSON is read, written, migrated, or deleted.

Defaults/explicit options use the shared resolver; local `YT_PROXY` is preserved for login/check/upload. No local stealth or language/viewport overrides remain. Managed historical launch/context/script hints remain solely to preserve existing ignored-option logs; MLX and AdsPower otherwise only adopt headless configuration precedence. Native `--schedule` was already unsupported for YouTube and still exits 2 before launch; `--not-before`, video fields, visibility, thumbnails, playlist interactions and humanizer remain.

## TDD evidence

New tests in `tests/test_youtube_profiles.py` drive the formal parser/dispatch through real configuration, Profile ownership and session lifecycle. Only external browser/platform/provider behavior and time are replaced. Recorded red/green slices:

1. Login/check test failed on temporary-browser launch; passed after persistent setup migration. An initial exploratory run was interrupted because the old login waited on its temporary page; the browser boundary now fails promptly if that path is used.
2. Upload test failed in the removed cookie-resolution branch; passed with one persistent session, explicit Chromium/headless, actual field/visibility actions and exactly one synthetic submit.
3. HTTP 403 was incorrectly accepted, verification lacked its reason, and post-submit verification returned success. All three failures passed after local-only classification changes.
4. A possibly dispatched click followed by a login redirect omitted `publish_attempted=true`; the regression now passes with exit 10, stage evidence and one dispatch.
5. An upload-navigation timeout after an explicit login redirect incorrectly exited 1; the final local upload boundary reports 10 before any submission.

Additional coverage: absent optional settings; custom executable product identification; selected-source failure without fallback; Chrome/Chromium isolation; changed account identity under the same alias; proxy/headless propagation; missing Profile; faults and cancellation; hanging page/context cleanup; precision reset and lock rejection; direct and injected uploaders; success, pre-submit failure, unknown result and post-submit login survive cleanup failure; not-before waits while retaining the lease; both managed providers ignore invalid local config, preserve stop/disconnect ownership, retain login/reset restrictions and 429 exit 11. Shared Profile tests include real subprocess locks and reset partial-failure/ownership protection.

## Offline results

Final targeted command (all module names below are prefixed with `tests.`):

```bash
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest \
  tests.test_youtube_profiles tests.test_mlx_youtube tests.test_youtube_humanize \
  tests.test_adspower_video_platforms tests.test_publish_cleanup \
  tests.test_local_profile tests.test_local_browser_session \
  tests.test_publish_gate tests.test_publish_timeout tests.test_sau_browser_cli \
  tests.test_adspower_browser_session tests.test_browser_session tests.test_adspower_cli -q
```

Result: **240 passed**, 5.787 seconds. `git diff --check` passed. Earlier targeted iteration: 200 passed. A broader 272-test run (before final three additions) also included `tests.test_multilogin_cli` and exposed exactly two pre-existing Instagram subtest errors at line 427: the fixture still patched removed `resolve_account_file` without `create=True`. Ticket 04 owns that follow-up; this ticket does not alter those hunks. The focused YouTube/provider/shared regression is green.

Legacy YouTube assertions for temporary launch, stealth and JSON writeback were removed in favor of persistent public-path coverage. The shared legacy cleanup matrix no longer claims YouTube closes a temporary browser separately; new tests verify persistent-context ownership instead. Reset registration coverage now includes YouTube, while later-batch platform expectations remain unchanged.

## Actual browser result

Command:

```bash
PYTHONPATH=. /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python \
  .scratch/local-chrome-profile-implementation/research/06-youtube-no-viewport-smoke.py
```

The sandbox attempt failed at browser launch with EPERM/SIGABRT (same environment restriction documented by tickets 02/03/05). The reviewed outside-sandbox run passed using full Patchright Chromium **156.0.8078.4**, `headless=True`, `no_viewport=True`, a temporary synthetic Profile, and real Humanizer interactions. Every page request was fulfilled with controlled HTML; no platform request reached YouTube.

Observed natural viewport: **756 × 469**. Readback: title `Fixture title`, description `Fixture description`, playlist `Series`, visibility `public`; playlist overlay `display=none`; offscreen controls were scrolled into view; synthetic submit count **1**. The persistent context closed normally. This validates the affected scroll/overlay behavior and is not a real YouTube account or publishing result. Shared browser-source/persistence matrices were unchanged and retain ticket 02 evidence.

## Remaining scope

No YouTube-specific acceptance is blocked. Facebook and Facebook Page are parallel ticket 07/08 work; later batches remain on their existing flows. Real account operations are outside this ticket. Legacy material migration is ticket 19, and the four explicitly named real no-publish platform runs are ticket 20. YouTube does not gain a no-publish flag or native scheduling in this change.
