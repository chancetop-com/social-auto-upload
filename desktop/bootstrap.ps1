[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$Revision,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$Sha256,
    [Parameter(Mandatory)][string]$ArtifactDir,
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'social-auto-upload')
)
$ErrorActionPreference = 'Stop'
$nativeCpu = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
if ($nativeCpu -ne 'AMD64') { throw "Unsupported Windows architecture: $nativeCpu" }
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
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zip)
    try {
        $files = @{}
        $dirs = @{}
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName
            if (($name -cne 'release.json' -and !$name.StartsWith('runtime/')) -or
                (($entry.ExternalAttributes -shr 16) -band 0xf000) -ne 0x8000) { throw 'Unsafe package member' }
            $prefix = ''
            foreach ($part in $name.Split('/')) {
                if (!$part -or $part -match '[. ]$|[\x00-\x1f\x7f\\:<>"|*?]|^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)') {
                    throw 'Unsafe package member'
                }
                $prefix = if ($prefix) { "$prefix/$part" } else { $part }
                if ($files.ContainsKey($prefix)) { throw 'Unsafe package member' }
                if ($prefix -ne $name) { $dirs[$prefix] = $true }
            }
            if ($dirs.ContainsKey($name)) { throw 'Unsafe package member' }
            $files[$name] = $true
        }
        foreach ($entry in $archive.Entries) {
            $path = Join-Path $image $entry.FullName
            [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path))
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $path, $false)
        }
    } finally { $archive.Dispose() }
    & (Join-Path $image 'runtime/python.exe') -I -B -m sau_worker.desktop install $InstallRoot $Revision $Sha256 $target
    if ($LASTEXITCODE -ne 0) { throw "Worker installation failed ($LASTEXITCODE)" }
} finally {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
