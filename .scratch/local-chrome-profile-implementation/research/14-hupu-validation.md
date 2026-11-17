# 14: Hupu persistent Profile validation

Date: 2026-11-17. Worktree: `/private/tmp/sau-local-profile-14`; baseline integration: `b8be345`.

## Covered entry points

- Formal `sau hupu login`, `check`, `upload-video`, and newly registered `reset-profile`.
- `login_hupu_account`, `check_hupu_account`, `upload_hupu_video` and direct `hupu_setup`, `cookie_auth`, `hupu_cookie_gen`, `HuPuVideo.main/upload/upload_in`.
- Local preflight and business operations share one persistent context and Profile lease. Injected sessions keep their owner. Historical positional `hupu_<alias>.json` arguments provide only the alias; file contents are unused.
- Removed local Cookie existence checks, browser relaunch preflight, state restore/export, UA/viewport/webdriver context replacement and fingerprint injection. QR download/display, QQ iframe/popup, native video/cover file choosers, title/description, zone dialog, declarations, humanization, budget and not-before remain.
- Managed check/upload still use provider contexts, unchanged probe navigation and ignored-option startup logs. Only the approved effective headless source changes. Local selection/path values are ignored, with no local Profile access.

## TDD evidence

`tests.test_hupu_profiles` exercises formal dispatch through real configuration, Profile ownership and persistent session code; only browser/platform/provider boundaries are faked.

Observed reds before implementation:

1. Login/check tried `chromium.launch` and failed the persistent-only browser boundary.
2. Local video route still depended on the deleted account-file resolver; the final route now launches one selected Profile for preflight and publication.
3. Verification lost its reason, HTTP 403 and misleading `hupu.com` host substrings were accepted, and navigation failure after a login redirect exited 1. The final local probe distinguishes these cases without changing managed probes.
4. QQ popup login raised login-required instead of guiding login; the final flow uses the same context and validates backend controls before success, cleaning its temporary QR artifact.
5. Redirects before, during and after submit produced 1/9/1. They now return 10, retain verification reason, and retain `publish_attempted=true` after possible dispatch, even when cleanup fails.
6. A requested cover permission error was swallowed and publishing continued. Local required interaction failures now abort; managed historical fallback behavior remains.
7. Direct alias construction still required a positional Cookie filename. The new account_name API supports omission and preserves explicit False over configured True.

Additional coverage includes optional configuration absence, custom executable identification and no fallback, separate browser kinds, same-alias relogin, exact reset without an installed binary, Profile occupancy/history protection, cancellation and bounded hung cleanup, setup/navigation failures, injected ownership, submit-at-most-once, unknown results, success despite cleanup failure, real not-before waiting while the Profile remains occupied, both managed providers and 429 behavior.

## Executed offline checks

Interpreter: `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python`, cwd this worktree.

```text
python -m unittest tests.test_hupu_profiles tests.test_hupu_humanize tests.test_mlx_hupu_dayu tests.test_local_profile tests.test_local_browser_session tests.test_browser_session tests.test_adspower_browser_session tests.test_publish_cleanup tests.test_humanize tests.test_sau_browser_cli tests.test_multilogin_cli tests.test_adspower_cli tests.test_time_arguments -q
```

Result: **323 tests passed in 17.825s**. An earlier focused run passed 217 tests. `git diff --check` passed. An isolated interpreter imported `uploader.hupu_uploader.main` with a synthetic conf module containing only `BASE_DIR`; optional browser configuration attributes were absent.

## Real controlled browser evidence

```text
python -m unittest tests.test_hupu_profile_dom -q
```

Result: **1 test passed in 90.141s**, containing two complete synthetic flows:

- System Chrome 157.0.8103.79, headed.
- Patchright full Chromium 156.0.8078.4, headless.

Each flow performed formal login, closed the context, reopened the same kind/profile for upload, and performed preflight plus the whole business flow. Four total persistent launches used `no_viewport=True` and no viewport override. Both flows proved native file choosers accepted video and cover, title/description read back exactly, the zone modal selected the expected branch, declarations applied, scrolling reached the submit target, and exactly one synthetic submission was observed. All owned browsers disconnected after context cleanup; no cookies directory was created.

All page and submission requests were fulfilled by the local browser fixture. The test used temporary Profile roots and no real credentials, accounts, external platform operations or actual publication. QQ popup/QR guidance is separately covered by offline browser boundary evidence, not claimed as a real QQ login.

## Limits and remaining rollout

No Hupu account login, real upload/publication, or work deletion was performed. Hupu has no no-publish switch. One-time old-state work belongs to ticket 19; real four-platform no-publish acceptance belongs to ticket 20. Shared browser/Profile capabilities were unchanged, so ticket 01/02 process and browser matrix evidence was reused rather than rerun.

At the initial tested integration baseline, Weibo, Alipay, Dayu, Zhihu and Xueqiu remain on their ticket-specific legacy paths; Bilibili biliup is excluded. Concurrent completed-platform docs/reset lists are unioned when merging the latest integration before delivery.
