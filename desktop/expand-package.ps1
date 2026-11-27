function Expand-DesktopPackage([string]$zip, [string]$image) {
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
}
