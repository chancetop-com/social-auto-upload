# Independent Standards review

Pinned HEAD: `cc23b9d3631bfd85980bae4f8885ffadc8233eeb`
Baseline: `47cc1850ede44ca822dbc7fa949970f4eed919bc`
Diff: `git diff 47cc1850ede44ca822dbc7fa949970f4eed919bc...HEAD`

Read `review-common.md` and `review-snapshot.md` first. Applied the latest user amendments, including browser-kind-first paths, removal of the superseded flows, ordinary/creator Instagram support, and six no-publish summaries. This review used the complete changed-file inventory and diff, CodeGraph-first source inspection, and targeted current-source reads where the graph did not return the relevant section. No other review-axis report was read. No repository, account, browser Profile, or git metadata was changed; no tests or real platform operations were run. All locations below are current pinned-HEAD locations.

## Result

No P0/P1/P2 standards blocker established. Three P3 documented-standard findings and three optional design-smell findings follow. The latter are explicitly judgment calls, not policy failures or demonstrated runtime defects. Related occurrences are grouped so one rule is not reported as several independent defects.

## Documented-standard findings

### S1 — [P3] Keep the Douyin Profile instructions in one authoritative place

**Files/hunks:** `skills/douyin-upload/SKILL.md:65–67` and `skills/douyin-upload/references/cli-contract.md:115–117` (both added in this diff).

**Rule:** `/Users/chancetio/.agents/skills/writing-for-agents/SKILL.md`, Pruning: “Keep each meaning in a **single source of truth**: one authoritative place, so changing the behaviour is a one-place edit.” The same skill recommends disclosing reference material behind a context pointer.

**Evidence:** Both files contain the same two full paragraphs, verbatim, starting:

> 抖音 login/check/视频/图文及直接 uploader 使用 `browser_profiles/<chrome|chromium>/douyin/<原始别名>/`。默认系统 Chrome、有头；`LOCAL_CHROME_PATH` 非空优先...

and:

> 只有 login 引导扫码或验证；缺少 Profile、明确未登录/验证退出 `10`，网络、权限和页面故障退出 `1`...

They duplicate the entire browser selection, configuration precedence, login recovery, reset, and submission-result contract. A later change must edit both copies; the main skill already has pointers to its packaged references. Independent installation does not require duplication here: both files live inside the same installable skill directory.

**Action:** Keep the complete contract in one in-package reference, and replace the duplicate main-skill paragraphs with a short, conditional pointer identifying when to read it. Keep the essential platform-specific workflow steps visible in the main skill. This is a direct documented writing-rule breach, not merely a preference for shorter prose.

### S2 — [P3] Restore the shared managed-mode contract pointer instead of copying its rules

**Primary hunk:** `skills/kuaishou-upload/SKILL.md:80–81`.

**Other new/expanded occurrences:** `skills/weibo-upload/SKILL.md:42,44`; `skills/tencent-upload/SKILL.md:40`; `skills/meta-upload/SKILL.md:45`; `skills/tiktok-upload/SKILL.md:116`; `skills/xiaohongshu-upload/references/cli-contract.md:117`.

**Rule:** `docs/skill-distribution.md:41`: “Skill 不复制共同契约：退出码（含 `11` 请求过于频繁）、部署前提、调度责任、身份风险与安全说明统一指向 `docs/CLI.md` 的‘托管浏览器模式（通用）’。”

**Evidence:** Kuaishou replaces the former shared-contract pointer with new duplicated rules:

> 两个凭据同时设置退出 `1`；请求限流退出 `11`，交给调度层退避，CLI 不重试。

> MLX / AdsPower 需与 CLI 同机、桌面客户端和本地 API 可用；AdsPower 需付费版与 Chromium Profile。

Weibo also newly restates deployment/payment and throttling/ownership rules; the other listed hunks add the common managed `11`/backoff contract beside a pointer that already delegates that subject to `docs/CLI.md`. Local Profile-specific errors and recovery instructions are not the subject of this finding.

**Action:** Retain platform-specific local/browser/headless behavior, restore Kuaishou's pointer, and route common provider exit-code, deployment, ownership/backoff responsibilities through the documented shared source. Remove only the newly duplicated common clauses. This is a direct repository-standard breach; it does not imply the copied statements are currently wrong.

### S3 — [P3] Replace deleted-name test guards with observations at the approved boundary

**Primary hunk:** `tests/test_adspower_article_identity_platforms.py:793,810–815`.

**Related changed guards:** `tests/test_adspower_article_identity_platforms.py:263`; `tests/test_adspower_cli.py:537`; `tests/test_mlx_meta.py:1131,1302`; `tests/test_multilogin_cli.py:440`. These changes add `create=True` to patches of `resolve_account_file` after the production command modules stopped exposing that helper. `tests/test_mlx_tencent_baijiahao.py:745–747` instead redirects the old guard onto the internal configuration resolver while the test still replaces the session factory and uploader.

**Rules:** `/Users/chancetio/.agents/skills/tdd/SKILL.md`: tests verify behavior through public interfaces, not implementation details; `/Users/chancetio/.agents/skills/tdd/mocking.md`: mock system boundaries, not internal collaborators. The approved repository specification, `.scratch/local-chrome-profile/spec.md:207–209`, explicitly requires real configuration/resource orchestration with browser/provider boundary fakes and says not to replace the whole session and merely assert parsing.

**Evidence:** The primary changed test fabricates the removed helper and asserts the internal calling convention:

```python
patch.object(module, "resolve_account_file", new=resolve, create=True)
...
self.assertEqual(helper.await_args.kwargs['account_name'], 'creator')
resolve.assert_not_called()
```

The surrounding fixture replaces the actual local works helper with `AsyncMock(return_value={})` and replaces `browser_session`. Thus it cannot establish that the real verify/delete implementation avoids managed/local credential I/O; it primarily establishes which internal helper/keyword the adapter uses. The new `create=True` keeps a removed-name assertion passing instead of moving its negative guarantee to the current boundary. The newly added platform Profile suites already demonstrate the stronger testing pattern, so this is not a claim that the feature lacks behavioral coverage.

**Action:** Remove these redundant internal-name guards/assertions where the new public-flow suite already covers the guarantee, or exercise the actual action with an isolated temporary root plus FakePlaywright/provider/file-boundary observations. Do not revive deleted production symbols to satisfy the tests, and do not broaden this into rewriting unrelated, unchanged historical tests. The standard violation is the retained/adapted implementation-coupled hunk; no inference about whether the historical work actually followed red-before-green is made.

## Optional baseline-smell findings

### H1 — Possible Duplicated Code: seventeen legacy filename-to-alias adapters

**Representative hunks:** `uploader/alipay_uploader/main.py:234–243`, `uploader/baijiahao_uploader/main.py:217–226`, `uploader/hupu_uploader/main.py:102–111`, `uploader/meta_uploader/facebook_uploader/main.py:134–142`, `uploader/meta_uploader/facebook_page_uploader/main.py:221–230`, `uploader/meta_uploader/insgraph_uploader/main.py:457–466`, and `uploader/zhihu_uploader/session.py:71–80`.

**Other new implementations of the same compatibility shape:** `uploader/douyin_uploader/main.py:155`; `uploader/ks_uploader/main.py:396`; `uploader/rednote_uploader/main.py:1465`; `uploader/tencent_uploader/main.py:196`; `uploader/tk_uploader/main_chrome.py:1062`; `uploader/weibo_uploader/main.py:199`; `uploader/xiaohongshu_uploader/main.py:1539`; `uploader/youtube_uploader/main.py:116`; `uploader/dayu_uploader/session.py:158`; `uploader/xueqiu_uploader/session.py:70`.

**Quoted representative hunk:**

```python
if account_name is not None:
    return account_name
if account_file is None:
    raise UsageError("本地调用需要 account_name 账号别名。")
name = Path(str(account_file)).name
if name.startswith("facebook_") and name.endswith(".json"):
    return name[len("facebook_"):-len(".json")]
return str(account_file)
```

The same name-only compatibility policy was added separately to every platform. Small differences have already appeared: TikTok/XHS strip a `.json` suffix without requiring the platform prefix, while Xueqiu always uses `Path(...).stem`. These differences are not established defects here, because the compatibility inputs may differ, but a policy correction now requires auditing seventeen functions.

**Suggestion:** Share the common name-only adapter and pass the platform prefix; explicitly retain any genuinely required platform-specific compatibility rule at its boundary. Preserve raw explicit `account_name` unchanged and preserve result-path compatibility where separately required. This suggestion does not propose restoring legacy credential I/O or removing supported direct-call signatures.

### H2 — Possible Duplicated Code / Shotgun Surgery: six copies of the exact no-publish sentence

**Hunks:** `sau_commands/tiktok.py:569,593`; `sau_commands/rednote.py:486,519`; `sau_commands/xiaohongshu.py:481,514`.

**Quoted hunk at all six sites:**

```python
print("素材已上传，发布前检查已通过；已停止，未点击发布按钮。")
```

This is one user-specified cross-platform output contract copied into six branches. Another wording amendment requires the same six edits and can leave one media action behind. The current text and stop semantics are correct; this is a maintenance judgment only.

**Suggestion:** Put the shared sentence in one small CLI presentation constant/helper and use it from all six existing success branches. Keep each platform/media heading, normal publish output, result fields, and no-publish guard unchanged. A larger output abstraction is unnecessary.

### H3 — Possible Speculative Generality: private CLI builders still accept an account file that all production callers pass as None

**Representative hunks:** `sau_commands/alipay.py:89–96,118,136`; `sau_commands/douyin.py:141,169,196,212,220,236`; `sau_commands/kuaishou.py:120,140,164,180,187,203`; `sau_commands/rednote.py:264,288,345,360,373,388`; `sau_commands/xiaohongshu.py:261,286,344,359,372,387`.

**Same shape:** `sau_commands/weibo.py:89,118,135`; `sau_commands/hupu.py:84,107,124`; `sau_commands/youtube.py:95,120,137`; `sau_commands/instagram.py:228,279`; `sau_commands/facebook_page.py:132,176` (its managed call also passes `None`).

**Quoted representative hunk:**

```python
def _build_alipay_uploader(
    request: AlipayVideoUploadRequest, account_file: str | None
) -> AlipayVideo:
    ...
    account_file=account_file,
...
app = _build_alipay_uploader(request, None)
```

The migration eliminated the meaningful production choice at these private CLI adapters, but the parameter still suggests that the CLI may select a legacy credential file. This is narrower than the public uploader constructors, whose legacy positional shape may intentionally remain compatible.

**Suggestion:** Remove the private builder parameter and supply `None` at the constructor boundary, preserving public uploader compatibility. Do not remove `browser_session`'s legacy option parameters: those have an explicitly approved managed ignored-option/log contract and are not speculative generality.

## Standards and smell coverage notes

- Read the root `AGENTS.md`, `GLOSSARY.md`, all three `docs/agents` references, README contribution/license rules, `docs/skill-distribution.md`, relevant `docs/CLI.md` contracts, the TDD skill plus `tests.md`/`mocking.md`, and writing-for-agents plus `SKILL-MECHANICS.md`.
- No further concrete issue found with glossary terminology, the local issue/map layout, status conventions (including the documented `resolved` wayfinding/task convention), licensing, skill-directory inventory, or independent installation in the changed material. No new marketplace release is required by the user request.
- The amended Profile layout and obsolete-code removals are authorized. Historical 19/20 evidence paths are intentionally preserved. The ordinary Instagram controlled-DOM versus current creator live no-publish evidence is stated in the updated Instagram skill; it must not be expanded into a claim of two live accounts or advanced-option/real-publish validation.
- New CLI/Profile suites generally use real configuration/Profile orchestration with browser/provider fakes, temporary directories, and actual process-lock tests, matching the approved seams. Real browser DOM fixtures are useful independent evidence; FakePlaywright call assertions at the external browser boundary are not themselves an internal-mocking violation.
- Beyond H1–H3, no sufficiently concrete changed-hunk finding was established for possible Mysterious Name, Feature Envy, Data Clumps, Primitive Obsession, Repeated Switches, Divergent Change, Message Chains, Middle Man, or Refused Bequest. Shared session wrappers and local/managed boundary parameters have documented ownership/compatibility purposes, so their presence alone is not a smell.
- Tooling-enforced style/type issues are excluded. No broad test run was performed against original Profiles; this report is static review evidence, not new runtime validation.

## Implementer disposition — 2026-11-17

The independent report above is preserved against pinned `cc23b9d3631bfd85980bae4f8885ffadc8233eeb`. The same fresh worker handled all three P3 documented-standard findings and all three optional heuristics, together with [Spec S1/S2](final-review-spec.md). No new ticket or parallel fixer was created. Latest integration was merged before this report (`Already up to date`). Candidate recheck by the original reviewers, integration merge and final root-owned worktree cleanup remain pending.

| Finding | Disposition |
| --- | --- |
| Standards S1 / P3 | Fixed. Douyin's complete local Profile/browser/recovery contract remains in the installable skill's `references/cli-contract.md`; the main skill now has a conditional link to that packaged section. Platform commands and execution steps remain in the main skill. |
| Standards S2 / P3 | Fixed. Removed the identified newly copied common managed deployment/payment, throttling/backoff and ownership clauses from Kuaishou, Weibo, Tencent, Facebook Page, TikTok and XHS. Each affected package points to the runtime project's `docs/CLI.md` shared managed section with an online entry for independent skill installations. Local workflow, platform flags, browser selection and local fault/recovery guidance remain available in-package. |
| Standards S3 / P3 | Fixed. Removed fabricated `resolve_account_file` guards, the redirected internal resolver guard, and four redundant mocked local-works tests/assertions. Missing-account cases still exercise the public CLI and assert exit 2 and the `--account` diagnostic. No deleted production symbols were revived. Existing full public Profile-flow tests retain the managed/local isolation guarantee. |
| H1 / possible duplication | Addressed. Fifteen JSON filename adapters now delegate to `utils/local_account.py`, without credential I/O. Raw explicit aliases and prior missing-alias errors are preserved. The observed suffix-only compatibility of TikTok, XHS **and Rednote** is explicit; Dayu and Xueqiu retain their separate `Path(...).stem` boundary behavior and `ValueError` semantics. Public uploader signatures and independent result-file paths are unchanged. |
| H2 / possible duplication | Addressed. `sau_commands/output.py` holds the one exact `NO_PUBLISH_SUCCESS` sentence. The existing six TikTok/Rednote/XHS success branches use it; headings, stop conditions, normal-publish text and result fields are unchanged. |
| H3 / possible speculative generality | Addressed. Removed the always-None argument from 14 private builders in 10 command modules and their production callers; `None` is supplied only at each public uploader constructor. Public uploader signatures and managed `browser_session` compatibility hints/logging remain unchanged. Obsolete assertions of the private second argument were removed; media, option and session behavior assertions were retained. The existing publish-gate builder test now calls the current private signature. |

### Boundary coverage retained for S3

- `tests.test_instagram_profile_cli.InstagramProfileCliTests.test_works_stay_local_with_provider_env_and_use_current_author`
- `tests.test_facebook_profile_cli.FacebookProfileCliTests.test_works_remain_local_with_provider_env_and_keep_historical_evidence`
- `tests.test_facebook_page_profile_cli.FacebookPageProfileCliTests.test_works_remain_local_with_provider_env_and_keep_original_page_evidence`
- `tests.test_zhihu_profiles.ZhihuProfilesTests.test_verify_keeps_historical_subject_and_title_evidence_after_alias_switch`
- `tests.test_xueqiu_profiles.XueqiuProfilesTests.test_verify_remains_local_under_provider_environment`
- `tests.test_dayu_profiles.DayuProfilesTests.test_verify_keeps_raw_local_alias_under_provider_environment`

These tests use real command/configuration/Profile/session paths with external browser/provider fakes and isolated filesystem roots, including historical works evidence and raw alias behavior. Existing unrelated historical test architecture was not rewritten.

### Validation and inspection

Four public direct-entry characterization methods passed **before and after** the alias refactor: Weibo's legacy prefixed name, unprefixed raw `.json` alias and explicit raw override; TikTok/Rednote/XHS's unprefixed legacy JSON filename compatibility. They call public setup/check APIs and observe the actual persistent browser boundary rather than invoking the new helper directly. Logs: `/private/tmp/sau-local-profile-notes/review-fix-alias-{before,after}.log`.

The 226-method affected suite included AdsPower/MLX compatibility and all three local/managed no-publish Profile suites. It initially found stale final guard assertions in two edited missing-account tests (18 subcase `NameError`s); those were removed and the two tests passed (`review-fix-account-required-green.log`). No production adjustment was required. The first cumulative 2,031-method run then found 11 old private-builder test dependencies: ten second-argument mock assertions and one old two-argument call. The corresponding assertions/call were corrected without removing media/options coverage; the final cumulative run below includes them all.

Static source inspection confirms all 14 private builder definitions and all their production calls have the one-request signature. Each of the three no-publish command modules has exactly two uses of the shared constant. `git diff --check` passes. `pyproject.toml` uses setuptools package discovery for `utils*` and `sau_commands*`, with both package `__init__.py` files present and no exclusion; the new Python modules are therefore included by the existing package discovery. No package configuration or build was needed or claimed (the runtime venv does not itself have setuptools installed).

Documentation checks preserve the original skill frontmatter/license, keep Douyin's target within its own package and retain a reachable shared managed-contract pointer for each edited standalone skill. Historical 19/20/21/23 evidence remains intact, including the ordinary-Instagram controlled-evidence limit.

### Final cumulative result

The final broad isolated suite passed **2,031 tests / 126.637s: 2,029 passed, 2 existing opt-in service skips, 0 failures/errors**. The same 98 prior browser cases remain explicitly deferred. The command, manifest, failure history and evidence boundaries are recorded once in [Spec final cumulative evidence](final-review-spec.md#final-cumulative-offline-result). This final run includes every affected builder/provider/Profile/no-publish suite and the retained works-action boundary coverage above. No browser/live rerun or actual account operation was required by these fixes.
