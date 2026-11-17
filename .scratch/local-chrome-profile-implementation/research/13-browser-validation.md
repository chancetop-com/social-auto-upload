# 13 — Weibo persistent Profile / native window validation

Date: 2026-11-17. Worktree: `/private/tmp/sau-local-profile-13`.

## Scope and environment

Formal CLI dispatch exercised login and upload-video using actual configuration, Profile acquisition, persistent-context lifecycle, platform selectors and Humanizer. All page requests were fulfilled by the test driver with fixture HTML. Temporary video/cover files and Profile roots were isolated. No real platform account, upload, publish, delete or user Profile was used.

Command (from the ticket worktree):

```sh
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_weibo_profile_dom -v
```

The initial sandbox attempt failed at Chrome startup with Crashpad bootstrap permission denied / SIGABRT, matching the recorded environment restriction. The authorized unsandboxed run launched installed Chrome and Chromium; no installation was needed. An initial fixture bug put the blocking mask inside the button (therefore correctly interactive as its descendant); moving the mask to a sibling made it a true hit-test blocker. The corrected fixture passed in **210.553 s**.

## Observed results

- System Chrome **157.0.8103.79**, headed. Test driver used CDP to model a user's 800×650 window resize; production launch options did not set viewport/window size or maximization.
- Patchright Chromium **156.0.8078.4**, headless, natural viewport.
- Eight persistent launches total: one login and three video runs per browser kind. Every launch used `no_viewport=True`, with no `viewport` or additional launch `args`.
- Six video scenarios: successful fixture submission, fully covered publish button, and verification redirect after submission, in each browser.
- Four fixture submissions total (success + redirect per browser), exactly one dispatch per submitted run. Both completely covered scenarios raised `ElementUnusableError` and made zero fixture submissions.
- Right-side blocker at 0.65 caused the established fallback to 0.35; no force/JavaScript publishing was added. Escape dismissed a residual overlay. Each observed submission recorded scrolling and window height below 1000 pixels.
- Video/cover file names, overwritten title, description with hashtag, 二创 selection and AI declaration matched the supplied request.
- Both redirect scenarios raised `LoginRequiredError(reason="verification", publish_attempted=True)`; no resubmission.
- Every owned browser disconnected after the context closed. No legacy cookies directory was created.

## Limits

This is real browser evidence against controlled DOM, not real Weibo account or publishing acceptance. The platform has no no-publish action. Shared browser source/persistence/process-lock contracts were unchanged; the completed tickets 01/02 evidence remains applicable. OS/browser combinations beyond those above were not rerun.
