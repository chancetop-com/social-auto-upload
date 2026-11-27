# Build and install a desktop release

Build on a native macOS ARM64, macOS x86_64 or Windows x86_64 runner. Use Python 3.11.11, Git, uv 0.11.32, a clean copy of the relocatable python-build-standalone CPython 3.11.11 tree for that target, and read access to the selected repository revision. The runner needs access to the dependency index or a populated uv cache. The desktop needs the trusted repository bootstrap scripts, read access to the resulting ZIP, its approved revision and SHA-256, and a prepared BitBrowser window or AdsPower profile. macOS uses its bundled shell, Perl Archive::Zip and shasum. Windows uses PowerShell 5.1 or later and .NET ZIP support. Installation runs as the browser user.

## Produce the artifact

Verify the runtime input against the distributor's trusted download or provision it on the build runner using uv's verified Python download. For example, `uv python install --no-config --no-bin --install-dir runtime-input 3.11.11` installs the standalone tree. Record its immutable tree pin using `python desktop/build.py runtime-digest PATH_TO_STANDALONE_TREE`. Use the recorded value on subsequent builds. Do not use a venv.

From a checkout of the selected commit, run the following on each matching runner. Supply the full Git commit and the approved tree pin. On Windows use `windows-x86_64` as the target. The other macOS target is `macos-x86_64`.

```sh
python desktop/build.py build --revision "$REVISION" --target macos-arm64 --runtime "$RUNTIME" --runtime-sha256 "$RUNTIME_SHA256" --out "$ARTIFACT_DIR"
```

The builder extracts the CLI and worker sources from that commit, checks the runtime architecture and installs wheels with the hashes in `desktop/requirements.lock`. It starts the private interpreter and verifies the imported native dependencies and matched project versions. It writes `sau-desktop-REVISION-TARGET.zip` and its `.sha256` sidecar. Publish the ZIP on the approved artifact share and communicate the digest through the trusted release configuration. Keep together the bootstrap scripts from that repository revision, including `expand-package.ps1`. This workflow uses a local or mounted artifact directory and works without a GitHub Release.

To refresh the dependency lock deliberately, export the standalone CLI's pins with `uv export --frozen --no-dev --no-emit-project --no-hashes --output-file cli-constraints.txt` and run `uv pip compile --no-config --python-version 3.11 --universal --generate-hashes --no-header --no-annotate -c cli-constraints.txt pyproject.toml cli-service/pyproject.toml -o desktop/requirements.lock`. Review the resulting versions and wheel hashes.

## Bootstrap and check

Set `SAU_DESKTOP_TOKEN` to the fleet's desktop token. Select `SAU_PROVIDERS=bitbrowser`, `adspower`, or `bitbrowser,adspower`. The installer infers selected providers from the supplied keys when this variable is absent and defaults to BitBrowser on a new machine. Set each selected provider's `BITBROWSER_API_KEY` or `ADSPOWER_API_KEY`, or enter the missing key at the local non-echoing prompt. The corresponding `*_API_BASE` variables select a loopback URL. Use `WORKER_MAX_CONCURRENCY` to override the default capacity of one. `SAU_GATEWAY_URL` defaults to `https://social-media-web-api.connexup-dev.net`. An explicit gateway URL, selected providers, local keys and capacity are saved in the private install state and reused across bootstrap. The service environment takes precedence on startup.

```sh
./desktop/bootstrap.sh "$REVISION" "$SHA256" "$ARTIFACT_DIR" "$INSTALL_ROOT"
"$INSTALL_ROOT/cli-service" check --provider bitbrowser --profile-id "$WINDOW_ID" --platform tiktok
```

```powershell
& .\desktop\bootstrap.ps1 -Revision $Revision -Sha256 $Digest -ArtifactDir $ArtifactDir -InstallRoot $InstallRoot
& (Join-Path $InstallRoot 'cli-service.cmd') check --provider bitbrowser --profile-id $WindowId --platform tiktok
```

Omit the installation-root argument for `~/Library/Application Support/social-auto-upload` or `%LOCALAPPDATA%\social-auto-upload`. Both commands accept a root containing spaces. The stable launcher runs `program/runtime/bin/python3.11` or `program\runtime\python.exe` and invokes the installed CLI module by its private interpreter. The application writes CLI data under `state/cli`. It keeps operator-installed CLI executables and their data separate. Repeating the bootstrap for the same release reuses its worker. A user-level OS lock prevents claiming from two install roots. Bootstrap rejects an occupied root containing a different package digest. The managed upgrade flow owns release switches.

A successful bootstrap prints the worker's install root and PID. The self-check prints the Gateway occurrence, the selected profile and the receipt. A valid session reports `cloudConnected=true`, `profileVisible=true`, `cliInvoked=true` and `platformLogin="valid"`. An unavailable Local API prints the selected provider name on standard error. A hidden profile reports no CLI invocation. A login challenge reports `platformLogin="login-required"`. The self-check has no publish step.

## Local verification

Run `PYTHONPATH=cli-service python -m pytest -q desktop/tests cli-service/tests`. Set `SAU_TEST_PWSH` to a portable PowerShell executable if PowerShell is outside PATH. The Windows fixtures run the actual PowerShell ZIP extraction, digest and root selection with synthetic Windows files. A Windows native runtime and interactive user session are required for a field install.

On an ARM64 or Intel Mac, set `SAU_TEST_DESKTOP_ARTIFACT` to the absolute path to its built ZIP and run the Gateway process fixture from [the Gateway README](../gateway/README.md). With `SAU_TEST_PAIRED_CHECK=1`, `python -m pytest -q gateway/tests/test_paired_check.py` exercises two temporary browser users, default and space-containing roots, two installations per root, the actual private CLI, capacity and receipts through PostgreSQL, a local TLS Gateway and an offline provider/browser fixture. Only the fixture's OS account lookup is redirected to its fake home for the browser-sharing lock.
