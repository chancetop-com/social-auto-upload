[CmdletBinding(DefaultParameterSetName='Pinned')]
param(
    [Parameter(Mandatory,ParameterSetName='Pinned')][ValidatePattern('^[0-9a-f]{40}$')][string]$Revision,
    [Parameter(Mandatory,ParameterSetName='Pinned')][ValidatePattern('^[0-9a-f]{64}$')][string]$Sha256,
    [Parameter(Mandatory,ParameterSetName='Pinned')][string]$ArtifactDir,
    [Parameter(Mandatory,ParameterSetName='Approved')][switch]$Approved,
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'social-auto-upload')
)
$ErrorActionPreference = 'Stop'
$nativeCpu = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
if ($nativeCpu -ne 'AMD64') { throw "Unsupported Windows architecture: $nativeCpu" }
if ($Approved) {
    . (Join-Path $PSScriptRoot 'approved.ps1')
    Install-Approved $InstallRoot
    return
}
$target = 'windows-x86_64'
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
[void][IO.Directory]::CreateDirectory($InstallRoot)
$stage = Join-Path $InstallRoot ('.bootstrap.' + [Guid]::NewGuid())
$image = Join-Path $stage 'image'
[void][IO.Directory]::CreateDirectory($image)
try {
    $zip = Join-Path $stage 'package.zip'
    [IO.File]::Copy((Join-Path $ArtifactDir "sau-desktop-$Revision-$target.zip"), $zip)
    if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne $Sha256) { throw 'Package SHA-256 mismatch' }
    . (Join-Path $PSScriptRoot 'expand-package.ps1')
    Expand-DesktopPackage $zip $image
    & (Join-Path $image 'runtime/python.exe') -I -B -m sau_worker.desktop install $InstallRoot $Revision $Sha256 $target
    if ($LASTEXITCODE -ne 0) { throw "Worker installation failed ($LASTEXITCODE)" }
} finally {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
