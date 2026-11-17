# Independent Spec review

Reviewed pinned HEAD `cc23b9d3631bfd85980bae4f8885ffadc8233eeb` against baseline `47cc1850ede44ca822dbc7fa949970f4eed919bc` using `git diff 47cc1850ede44ca822dbc7fa949970f4eed919bc...HEAD`.

Read `review-common.md` and `review-snapshot.md` first, then the current specification, user amendments and relevant implementation/validation records. The browser-kind-first layout, expressly requested historical-code removal, ordinary/creator Instagram compatibility and clearer local/managed no-publish summaries are authorized requirements, not scope creep. No other review axis was consulted.

## Findings

### S1 — P2: Preserve explicit HTTP faults before applying authentication diagnosis

**Spec:** `.scratch/local-chrome-profile/spec.md:128`: “网络、页面结构、权限、必需字段提取或 Profile 运行故障退出 `1`，不折叠成 invalid。” The exit table at line 155 also requires faults to “保留实际原因；不自动清空、回退或解释为失效。”

**Affected current source:** `uploader/weibo_uploader/main.py:185–193`, particularly line 188; `uploader/baijiahao_uploader/main.py:319–327`, particularly line 322. Both are additions in the reviewed diff. `_check_local_response` first raises for HTTP >=400, but the encompassing `except Exception` diagnoses login again and replaces that explicit HTTP failure with `LoginRequiredError` whenever the returned page contains a login control or authentication URL.

**Trigger and consequence:** Run local `check` (or the same preflight before upload) with a valid owned synthetic Profile, and have navigation return HTTP 503 or 403 with a visible login entry. An outage/permission failure is reported as expired authentication, exit 10, with the original HTTP diagnostic lost and an inappropriate instruction to log in. The problem also exists on the business page's similar exception boundary; protect known page/HTTP failures rather than treating all exceptions as an opportunity to replace their classification.

**Reproduction:** Both Weibo and Baijiahao public CLI returned 10 for each `http503-plus-login` and `http403-plus-login` scenario. Alipay served as a control and returned 1 with the original HTTP status. Existing tests cover HTTP errors and login markers separately, which misses their combination.

**Expected correction:** Preserve classified HTTP/page/permission failures as exit 1; retain login reclassification for interrupted navigation only when supported by platform authentication evidence. Add combined HTTP+login cases at the public CLI boundary.

### S2 — P2: Require a recognized platform origin before classifying auth URLs

**Spec:** `.scratch/local-chrome-profile/spec.md:124`: “在 Profile 未建立或明确未登录时退出 `10`”; line 128: “网络、页面结构、权限、必需字段提取或 Profile 运行故障退出 `1`，不折叠成 invalid。”

**Affected current source:** `uploader/alipay_uploader/main.py:246–255`, particularly lines 248–253; `uploader/baijiahao_uploader/main.py:343–359`, particularly lines 344–347. These new local classifiers search the entire URL for login/verification substrings before the caller checks the hostname. Consequently the caller's unexpected-host fault is unreachable for those URLs.

**Trigger and consequence:** Local `check` navigation is redirected by a proxy/network gateway to `https://proxy.example/login` or `https://proxy.example/verify`, with no platform authentication UI. Both platforms return exit 10; `/verify` additionally claims `reason=verification`. This is not evidence that the selected platform account is logged out or requires verification. A network/interstitial failure is hidden behind platform login guidance. URL queries containing these substrings can produce the same false classification.

**Reproduction:** Both Alipay and Baijiahao public CLI returned 10 for both foreign URLs. Weibo served as a control and returned 1 with an explicit unexpected-page diagnostic. Hupu's current classifier also demonstrates the intended hostname-first boundary.

**Expected correction:** Parse URLs and allow only known platform/authentication origins before inspecting relevant paths or platform DOM evidence. Preserve valid Alipay/Baidu authentication/verification redirects and classify unrelated origins as faults. Cover foreign `/login` and `/verify` routes at the public CLI boundary.

## Evidence and isolation

- Reproduction script: `/private/tmp/sau-local-profile-notes/review-spec-repro.py`.
- Results: `/private/tmp/sau-local-profile-notes/review-spec-repro.jsonl` (12 synthetic scenarios; 8 mismatches, 4 controls).
- Runtime logs: `/private/tmp/sau-local-profile-notes/review-spec-repro.stderr`.
- Snapshot: `/private/tmp/sau-spec-review-repro`, created with `git archive` of the pinned HEAD; its `conf.py` was copied from the tracked example. The script asserts this cwd, uses the repository's existing FakePlaywright/page/provider boundary fixtures, and creates only temporary synthetic Profiles. It does not run a browser, contact a platform, read real Profile data or modify original configuration/data/git/repository files.
- Command: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/private/tmp/sau-spec-review-repro <original>/.venv/bin/python /private/tmp/sau-local-profile-notes/review-spec-repro.py` from the snapshot directory.
- Source discovery used CodeGraph first. Relevant diff and current source were checked, along with selected boundary tests and 20–24 evidence. A runtime source inventory found the sole persistent launch in `utils/local_browser_session.py`, and only the approved Dayu anonymous contexts; no active storage-state restore/export or old Firefox launch remained in `sau_commands`, `uploader`, or `utils`.
- Ordinary Instagram remains controlled DOM evidence only; the creator's live video/note evidence and four relocated Profile checks were treated within their stated limits. No actual publication/deletion was required or performed.

No additional missing/partial requirements or unauthorized scope additions were identified. The two findings concern incorrectly implemented error classification, not the approved amendments. No fixes made.

## Implementer disposition — 2026-11-17

The independent report above is preserved against pinned `cc23b9d3631bfd85980bae4f8885ffadc8233eeb`. One fresh fix worker addressed both review axes on `codex/local-profile-review-fixes`, cwd `/private/tmp/sau-local-profile-review-fixes`. The latest `codex/local-chrome-profile` was merged before this record (`Already up to date`, still the pinned HEAD). The implementation and regression work below is complete; the original reviewers' focused candidate recheck, integration merge and root-owned worktree cleanup are still pending.

| Finding | Disposition | Observable coverage |
| --- | --- | --- |
| Spec S1 / P2 | Fixed. `PageCheckError` identifies an already diagnosed local HTTP/page fault. Weibo and Baijiahao preserve it across probe and business-page exception boundaries, including the original HTTP reason. Their existing interrupted-navigation auth diagnosis and post-submit uncertainty handling remain active. | Each platform's public CLI test covers `check`, upload preflight and business-page navigation; HTTP 403/503 combined with login/verification markers yields exit 1, retains the HTTP status, closes the owned context and never clicks submit. |
| Spec S2 / P2 | Fixed. Alipay recognizes only `c.alipay.com`, `auth.alipay.com`, `captcha.alipay.com`; Baijiahao recognizes `baijiahao.baidu.com`, `passport.baidu.com`, on HTTP(S). Auth routes use the parsed path plus recognized auth hosts; DOM auth evidence is examined only on those hosts. Query strings cannot establish authentication state. | Public `check` and upload preflight reject foreign `/login`, `/verify`, login-like DOM, lookalike hosts and embedded trusted URLs as exit 1. A valid platform page with login/verify words only in its query remains valid. Trusted login/verification and interrupted navigation retain exit 10. Foreign redirects during a possibly dispatched click retain exit 9 with one click, while trusted verification after dispatch retains exit 10 and `publish_attempted=true`. |

Managed detection paths and provider lifecycle/logging were not changed. The new classified page error is raised only by these explicit local checks before submission; post-submit generic failures still follow the prior attempted/unknown handling.

### Red/green evidence

Tests run through `sau_cli.main`, real configuration resolution, actual temporary Profile ownership/locking and the real persistent-session orchestration. Fakes replace the external Playwright/browser/page boundary only. No real account, browser Profile, upload or user configuration was touched.

Commands below used `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest` from the isolated fix worktree:

| Test | RED before production fix | GREEN after fix |
| --- | --- | --- |
| `tests.test_weibo_profiles.WeiboProfilesTests.test_http_fault_with_auth_markers_preserves_reason_before_publish` | 12 subcases returned 10 instead of 1 | 1 method / all 12 subcases passed |
| `tests.test_baijiahao_profiles.BaijiahaoProfilesTests.test_http_fault_with_auth_markers_preserves_reason_before_publish` | 12 subcases returned 10 instead of 1 | 1 method / all 12 subcases passed |
| `tests.test_alipay_profiles.AlipayProfilesTests.test_unrelated_origin_or_query_is_not_platform_authentication` | 11 subcases misclassified auth | 3 methods passed including existing trusted auth and pre/post-submit controls |
| `tests.test_baijiahao_profiles.BaijiahaoProfilesTests.test_unrelated_origin_or_query_is_not_platform_authentication` | 13 subcases misclassified auth | 3 methods passed including existing trusted auth and post-submit controls |

External logs are under `/private/tmp/sau-local-profile-notes/review-fix-s1-{weibo,baijiahao}-{red,green}.log` and `review-fix-s2-{alipay,baijiahao}-{red,green}.log`. The committed public regression tests are the reproducible evidence; the external logs are retained execution records.

An intermediate 76-method three-platform run caught an overbroad Weibo exception exclusion introduced while fixing S1: trusted verification after submission returned 9 instead of 10. The exclusion was narrowed to `PageCheckError`; the affected submission and HTTP regression methods both passed (`review-fix-weibo-submit-green.log`). The final cumulative run below includes these controls and both new foreign-post-submit tests. Counts from overlapping runs are not added together.

### Evidence limits

The review fixes alter error classification and compatibility/presentation helpers, not browser launch, Profile storage, Humanizer interactions or Instagram composer selectors. The 98 already validated real-browser cases and earlier live evidence remain separately referenced in [20 cumulative validation](20-final-validation.md). They were not rerun here. Ordinary Instagram still has controlled DOM evidence only; the creator account's earlier live no-publish evidence does not imply a second live account. No actual publication or works deletion was performed.

See [Standards review and disposition](final-review-standards.md) for the other axis and shared cleanup.

### Final cumulative offline result

```sh
# cwd: /private/tmp/sau-local-profile-review-fixes
PYTHONDONTWRITEBYTECODE=1 /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python /private/tmp/sau-local-profile-notes/run-review-fix-offline.py
```

The runner uses standard unittest discovery and the same prior selection as ticket 20: the 80 baseline browser cases, 12 `*_profile_dom` cases and all 6 Instagram account-UI methods remain listed separately. It does not replace sessions or exclude new failures. It collected **2,129**, selected **2,031** offline tests and deferred the same **98** separately validated browser tests.

**Final result: 2,031 tests in 126.637s; 2,029 passed, 2 existing opt-in MLX/AdsPower live-service smoke skips, 0 failures, 0 errors.** Full log: `/private/tmp/sau-local-profile-notes/review-fix-offline.log`; selection manifest: `/private/tmp/sau-local-profile-notes/review-fix-offline-manifest.json`. The first cumulative run's stale-test errors are retained in `review-fix-offline-first.log`, not erased or counted as a pass. The net increase from 2,025 is ten added regression/characterization methods minus four redundant internal-mock methods.

The ignored worker configuration and temporary test roots are isolated; no real user configuration, login state or historical results were changed. The candidate is ready for the original reviewers' focused recheck; this report does not yet claim that recheck, integration merge or cleanup completed.
