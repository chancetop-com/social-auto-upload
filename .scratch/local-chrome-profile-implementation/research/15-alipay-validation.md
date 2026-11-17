# 15 — Alipay persistent Profile validation

Date: 2026-11-17. Worktree: `/private/tmp/sau-local-profile-15`. Source baseline `b8be345`; latest integrated baseline during this record: `25e0f0f` (Weibo and Hupu). `conf.__file__` and `conf.BASE_DIR` were verified to bind the worker, not the user's main checkout. Tests override BASE_DIR with isolated temporary directories.

## Delivered boundaries

- Formal `sau alipay login/check/upload-video/reset-profile`; direct `login_alipay_account`, `check_alipay_account`, `upload_alipay_video`, `cookie_auth`, `alipay_setup`, `alipay_cookie_gen`, `AlipayVideo.upload/alipay_upload_video/main`; injected local/managed sessions remain owned by their caller.
- One persistent local session/lease covers upload preflight and business actions. Login alone creates a Profile and guides QR login; the native iframe QR screenshot/callback survives, and a content-creation anchor confirms completion. Temporary QR cleanup does not mask callback failure.
- Existing JSON is not checked, restored, exported, migrated or removed. An old positional `alipay_<alias>.json` path identifies only the alias. Browser identity remains per platform/raw alias/actual browser kind; no real-account binding is introduced.
- Real shared resolver/session/ownership code selects Chrome by default, reads optional config dynamically, preserves explicit False, supports Chromium/custom paths, launches with no_viewport, and never falls back. No local stealth, locale, UA, geolocation permission or fixed-window option is passed. The unused historical geolocation constant was removed; managed calls already passed `context_kwargs=None`.
- Clear login URL/iframe and verification remain exit 10; verification carries reason=verification. Missing entry, wrong origin, HTTP/network/timeout and required cover/collection failures remain faults. An explicit HTTP failure takes precedence over incidental iframe markup.
- Upload login/verification classification retains the dispatch phase. Observational browser failures after dispatch return unknown (9). Local main submit and quality release each dispatch at most once; AIGC observations do not trigger another local publish click. Historical managed AIGC behavior remains unchanged. Existing humanizer, request/response listeners, publish budget and not-before remain active.
- Managed MLX/AdsPower retains provider routing, parameters, ignored-option logs, CDP ownership and rate limit behavior; only approved headless resolution changes. It does not inspect or acquire local browser resources.

## TDD evidence

All new seams follow the approved spec: real CLI dispatch/config/Profile/session orchestration with browser, page, provider and filesystem boundary doubles. No whole-session replacement is used for the new local behavior tests.

Observed red → green slices in `tests/test_alipay_profiles.py`:

1. Login/check initially failed with `Use the persistent Profile`; after migration, both launch the same persistent leaf and ignore malformed old JSON.
2. Video dispatch initially failed on the removed legacy account-file path; it now uses one selected session for probe and submission.
3. Redirect during navigation and pre/post-submit iframe/verification initially misclassified; now exit 10 with accurate phase/reason. One early post-submit red run entered the old unbounded observation window and was explicitly terminated; subsequent unknown-result cases use a controlled clock.
4. Explicit cover failure initially returned success; now fails before dispatch. HTTP 503 with a stale positive anchor also initially published; now fails, including when the error page carries login markup.
5. QR image unlink failure initially replaced a callback ValueError; now preserves the callback failure and closes the context.
6. An AIGC signal initially caused two local publish clicks; now one click and exit 9 when the result remains unknown.
7. Post-dispatch observation loss, including a closed page, initially returned 1; now returns 9 without retry.
8. A persistent quality overlay initially received two release clicks and a collection failure was swallowed; each now follows the required single-dispatch/fault behavior.

Further checks cover optional settings absent, custom-path classification and failed launch without fallback, independent browser Profiles, exact reset/occupied lease/history preservation, direct caller defaults/explicit False, injected owner lifetime, cancellation/hung cleanup, provider 429/login/reset routing, success and errors surviving cleanup faults, QR positive proof and not-before retaining the Profile lease.

## Offline executions

Interpreter: `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python`; cwd always the assigned worktree.

```sh
python -m unittest tests.test_alipay_profiles tests.test_mlx_alipay_weibo tests.test_alipay_humanize tests.test_publish_cleanup tests.test_local_profile tests.test_local_browser_session tests.test_browser_session tests.test_adspower_video_platforms tests.test_adspower_platform_contract tests.test_sau_browser_cli tests.test_multilogin_cli tests.test_adspower_cli tests.test_adspower_browser_session tests.test_weibo_profiles -q
```

After merging Weibo: **303 passed in 11.313s**. The Alipay-specific CLI matrix contains **22 passing tests**, including not-before. Earlier platform/managed/cleanup regressions passed 108, then 278 tests; obsolete Alipay JSON/double-close assertions were replaced by persistent-session boundary checks. Shared lists and AdsPower guards include both migrated Weibo and Alipay.

## Real controlled browser evidence

```sh
python -m unittest tests.test_alipay_profile_dom -v
```

Ran outside the sandbox because existing browser-launch restrictions require it. The fixture intercepts **all** browser requests and uses temporary Profiles/files. No real account, upload, publish or delete operation occurs.

- Chrome **157.0.8103.79**, headed: natural content window **1200×682** initially / **1200×683** in the repeat, actual scroll **586**.
- Complete Chromium **156.0.8078.4**, headless with `channel=chromium`: natural content window **756×469**, actual scroll **584** in the repeat.
- Each case executes formal login then upload in a second session for the same Profile, with positive anchor, SPA navigation, video input, title/description input, cover crop overlay, collection dropdown, AI radio and the off-screen publish button/quality overlay.
- Both locally intercepted payloads contain the expected title/description, video/cover filenames, selected collection, AI flag, and **one** main publish click. Four launches use no_viewport and no fixed viewport; all contexts disconnect at completion. No cookie directory is created.
- Initial execution: **1 test / 2 browser configurations passed in 86.262s**. After the local quality-release safeguard and integration merge: **1 test / 2 configurations passed in 83.224s**.

This is genuine browser execution on synthetic pages, not Alipay service acceptance or a real-account no-publish run. Qiankun itself is not live-tested; its necessary no-stealth condition is preserved and asserted at the browser boundary.

## Remaining rollout scope

No ticket-15 blockers. After merging Hupu, Dayu, Zhihu and Xueqiu remain outside the delivered platform scope. One-time legacy cleanup is ticket 19; final four-platform real-account no-publish acceptance is ticket 20. Alipay has no no-publish CLI action, and this ticket did not submit a real video or operate a user account.
