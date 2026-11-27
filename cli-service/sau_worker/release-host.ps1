param([string]$Mode)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
while ($true) {
    if (Test-Path -LiteralPath '.versions/rollback') {
        if (Test-Path -LiteralPath '.versions/previous') {
            if (Test-Path -LiteralPath 'program') { [IO.Directory]::Move("$PSScriptRoot/program", "$PSScriptRoot/.versions/rejected") }
            [IO.Directory]::Move("$PSScriptRoot/.versions/previous", "$PSScriptRoot/program")
        }
    } elseif (Test-Path -LiteralPath '.versions/switch') {
        if (Test-Path -LiteralPath '.versions/next') {
            if (Test-Path -LiteralPath 'program') { [IO.Directory]::Move("$PSScriptRoot/program", "$PSScriptRoot/.versions/previous") }
            [IO.Directory]::Move("$PSScriptRoot/.versions/next", "$PSScriptRoot/program")
        }
        if ([IO.File]::ReadAllText("$PSScriptRoot/program/package.sha256") -ne [IO.File]::ReadAllText("$PSScriptRoot/.versions/switch")) {
            throw 'Installed image does not match the committed package'
        }
    }
    if ($Mode -eq 'recover') { exit 0 }
    if (Test-Path -LiteralPath '.versions/previous') {
        try {
            & "$PSScriptRoot/program/runtime/python.exe" -IB -m sau_worker.desktop _probe-install
            $ok = $LASTEXITCODE -eq 0
        } catch { $ok = $false }
        if (!$ok) {
            [IO.File]::WriteAllText("$PSScriptRoot/.versions/rollback", "")
            continue
        }
    }
    & "$PSScriptRoot/program/runtime/python.exe" -IB -m sau_worker.desktop _supervise
    if ($LASTEXITCODE -ne 75) { exit $LASTEXITCODE }
}
