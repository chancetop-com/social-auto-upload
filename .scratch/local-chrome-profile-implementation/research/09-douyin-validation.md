# 09 Douyin validation — 2026-11-17

Worktree `/private/tmp/sau-local-profile-09`, branch `codex/local-profile-09`; base integration `821e161` (01–08 resolved). `conf.py` and `sau_cli` import from this worktree; BASE_DIR verified as this worktree. No real account, provider service, publication or deletion was used.

## Delivered paths

Formal login, check, upload-video, upload-note, reset-profile; direct `douyin_setup`, `douyin_cookie_gen`, `cookie_auth`, both uploader wrappers and injected `BrowserSession` paths. Local preflight and business share the same persistent session and real Profile lock. No storage_state import/export, old file gate, fixed internal headless, stealth or geolocation permission on local launch. Historical managed hints/logs remain. Direct legacy `douyin_<alias>.json` positional names identify only an alias; the file is never accessed.

The local probe distinguishes missing/expired login and visible/redirected verification (10) from HTTP/network/unknown page failures (1), requiring a positive upload entry. Only login guides authentication. Local publishing stops on verification; managed SMS behavior remains. Post-submit login/verification retain reason and publish_attempted through dispatch and failed cleanup. Disconnection after a possibly dispatched click is unknown (9), with at most one click. Ordinary declaration failures and successful outcomes survive failed cleanup. Cancellation propagates; context close is bounded; local probe pages belong to the context owner.

## TDD observations

Approved seams: real CLI dispatch/config/Profile/session orchestration with browser/platform/provider boundary fakes; existing injected session API; public Profile acquisition. Shared config/session implementations were not replaced by mocks.

- Initial check with valid Profile and broken old JSON failed with exit 1; after replacing the old file gate it passed and launched exactly one native persistent Chrome context.
- Verification initially produced generic login guidance; classification test failed until reason/guidance and positive entry checks were added.
- Login initially entered the old temporary browser path and failed on that browser fake. After migration, repeated login used one Profile per kind, preserving explicit False and config True.
- Public video/note initially failed the old Cookie existence gate. After migration, each used one context for probe + actual fake-page editing/submission; public lock acquisition was rejected at both page-creation boundaries.
- Mid-edit verification initially allowed a publish click; red asserted 1 vs expected 0. Guards now stop before dispatch. A field failure during verification initially exited 1; wrapper classification now preserves 10.
- Synthetic QR deletion failure initially changed successful login to exit 1; cleanup is now secondary.
- Browser disconnection after dispatch initially exited 1; red asserted expected 9. The local submission wrapper now retains unknown outcome, including when the page can no longer be queried.
- Legacy local launch/JSON-writeback assertions were replaced with persistent public behavior tests; borrowed-session and existing managed upload/outcome tests remain. Humanize/ambiguity fixtures now script the new visible login/verification probes.

## Offline verification

Interpreter: `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python`, cwd this worktree.

```
python -m unittest tests.test_douyin_profile_cli tests.test_douyin_upload_seam tests.test_douyin_mlx_check tests.test_douyin_declaration tests.test_douyin_humanize tests.test_publish_cleanup tests.test_sau_browser_cli tests.test_local_profile tests.test_multilogin_cli tests.test_adspower_cli tests.test_adspower_platform_contract tests.test_adspower_video_platforms tests.test_humanize.PlatformWideGateTests tests.test_publish_ambiguity tests.test_publish_gate tests.test_review_regressions tests.test_runtime_defaults tests.test_time_arguments -q
```

234 passed in 17.824s. After adding a final public declaration-failure replacement and explicit lock observation, `python -m unittest tests.test_douyin_profile_cli -q`: 14 passed in 1.042s. This covers browser configuration/path kind/headless, absent optional setting, no fallback, old files untouched, reset precision and occupancy, real cross-process Profile tests, provider ownership/ignored local config/logs, faults/cancellation/hanging cleanup, video/note editing, success/unknown/login/verification and no repeat submit. Managed check plus full note upload exercised both FakeManagedProvider modes with real session orchestration. `git diff --check` passed.

## Controlled real browser

```
python -m unittest tests.test_douyin_profile_dom -q
```

2 passed in 15.057s, system Chrome 157.0.8103.79, headless, temporary persistent Profile, no_viewport. All requests intercepted with synthetic HTML. The real video flow read back title/body, scrolled below fold, opened/closed the self-declaration dialog, removed a blocking overlay, and recorded one synthetic submit. The real probe rejected blank content and classified a visible verification field. Early fixture runs failed because Chinese HTML lacked explicit UTF-8, then because a counter in the page's main JavaScript world was read from Patchright's isolated world; the corrected fixture declares UTF-8 and observes a DOM attribute. Those were fixture defects, not real-platform results.

Shared lifecycle/config code did not change, so the full 02 real browser source/persistence matrix was not repeated. The final local failure-classification changes were exercised offline and did not alter the verified happy-path DOM interactions.

## Scope limits

No real Douyin login/upload/publication, no MLX/AdsPower service requests, no old-account migration. Ticket 19 and the four-platform no-publish acceptance in 20 remain separate. At this branch baseline, Kuaishou/Tencent/Baijiahao and tickets 13–18 remain on their previous paths; concurrent tickets integrate independently. Douyin has no no-publish option; controlled DOM does not claim real platform publishing evidence. No unresolved ticket blocker.

Final integration check: `git merge codex/local-chrome-profile` reported already up to date at `821e161`. Post-merge `python -m unittest tests.test_douyin_profile_cli tests.test_douyin_upload_seam tests.test_local_profile tests.test_runtime_defaults -q`: 52 passed in 3.739s; working tree clean before this evidence update.
