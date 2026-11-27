function Install-Approved([string]$Root) {
    $Root = [IO.Path]::GetFullPath($Root)
    $state = Join-Path $Root 'state'
    [void][IO.Directory]::CreateDirectory($state)
    if (Test-Path -LiteralPath (Join-Path $Root 'release-host.ps1')) {
        & (Join-Path $Root 'cli-service.cmd') start
        if ($LASTEXITCODE -ne 0) { throw "Installed worker could not start" }
        return
    }
    $gateway = if ($env:SAU_GATEWAY_URL) { $env:SAU_GATEWAY_URL.TrimEnd('/') } else { 'https://social-media-web-api.connexup-dev.net' }
    $uri = [Uri]$gateway
    if (!$uri.IsAbsoluteUri -or !$uri.Host -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or
        ($uri.Scheme -ne 'https' -and !($uri.Scheme -eq 'http' -and $uri.Host -in @('localhost','127.0.0.1','[::1]')))) {
        throw 'Invalid Gateway origin'
    }
    if (!$env:SAU_DESKTOP_TOKEN) { throw 'Set SAU_DESKTOP_TOKEN' }
    $idPath = Join-Path $state 'machine-id'
    if (!(Test-Path -LiteralPath $idPath)) {
        $tmp = Join-Path $state ([Guid]::NewGuid().ToString())
        [IO.File]::WriteAllText($tmp, [Guid]::NewGuid().ToString())
        try { [IO.File]::Move($tmp,$idPath) } catch [IO.IOException] { if (!(Test-Path $idPath)) { throw } }
        finally { if (Test-Path $tmp) { [IO.File]::Delete($tmp) } }
    }
    $body = @{machineId=[IO.File]::ReadAllText($idPath).Trim(); target='windows-x86_64'}
    $existing = Test-Path -LiteralPath (Join-Path $Root 'program/package.sha256')
    if ($existing) {
        $body.sha256 = [IO.File]::ReadAllText((Join-Path $Root 'program/package.sha256')).Trim()
        $body.revision = ([IO.File]::ReadAllText((Join-Path $Root 'program/release.json')) | ConvertFrom-Json).revision
    }
    Add-Type -AssemblyName System.Net.Http
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseProxy = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromMinutes(15)
    $client.DefaultRequestHeaders.Authorization = [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer',$env:SAU_DESKTOP_TOKEN)
    $dir = Join-Path $Root ('.approval.' + [Guid]::NewGuid())
    [void][IO.Directory]::CreateDirectory($dir)
    $oldAssignment = $env:SAU_BOOTSTRAP_ASSIGNMENT
    try {
        $form = [Net.Http.StringContent]::new(($body | ConvertTo-Json -Compress),[Text.Encoding]::UTF8,'application/json')
        $response = $client.PostAsync("$gateway/session/release/discover",$form).GetAwaiter().GetResult()
        [void]$response.EnsureSuccessStatusCode()
        $reply = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        $a = if ($reply.assignment) { $reply.assignment } elseif (!$existing) { $reply.approved }
        if (!$a) { throw 'No eligible release yet; retry after the current batch' }
        if ($a.target -cne 'windows-x86_64' -or $a.revision -cnotmatch '^[0-9a-f]{40}$' -or
            $a.sha256 -cnotmatch '^[0-9a-f]{64}$' -or $a.url -cne ("/session/release/packages/" + $a.sha256)) {
            throw 'Invalid package source or pin'
        }
        $archive = Join-Path $dir ("sau-desktop-" + $a.revision + "-windows-x86_64.zip")
        $download = $client.GetAsync(($gateway+$a.url),[Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        [void]$download.EnsureSuccessStatusCode()
        $file = [IO.File]::Create($archive)
        try { $download.Content.CopyToAsync($file).GetAwaiter().GetResult() | Out-Null } finally { $file.Dispose(); $download.Dispose() }
        if ($reply.assignment) {
            $env:SAU_BOOTSTRAP_ASSIGNMENT = Join-Path $dir 'assignment.json'
            [IO.File]::WriteAllText($env:SAU_BOOTSTRAP_ASSIGNMENT, ($a | ConvertTo-Json -Compress))
        }
        & (Join-Path $PSScriptRoot 'bootstrap.ps1') -Revision $a.revision -Sha256 $a.sha256 -ArtifactDir $dir -InstallRoot $Root
    } catch {
        if ($reply.assignment -and $_.Exception.Message -eq 'Verified native package failed the paired worker/CLI check') {
            $defect = @{machineId=$body.machineId;releaseId=$a.releaseId;batchId=$a.batchId;phase='defect';reason=$_.Exception.Message}
            $form = [Net.Http.StringContent]::new(($defect | ConvertTo-Json -Compress),[Text.Encoding]::UTF8,'application/json')
            $report = $client.PostAsync("$gateway/session/release/progress",$form).GetAwaiter().GetResult()
            [void]$report.EnsureSuccessStatusCode()
        }
        throw
    } finally {
        $env:SAU_BOOTSTRAP_ASSIGNMENT = $oldAssignment
        $client.Dispose()
        Remove-Item -LiteralPath $dir -Recurse -Force
    }
}
