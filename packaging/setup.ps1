param([string]$AppRoot = (Split-Path $PSScriptRoot -Parent), [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# Installer hosts can pass a module path from a different PowerShell edition.
$env:PSModulePath = (Join-Path $PSHOME 'Modules') + ';' + $env:PSModulePath
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -Force
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -Force
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$AppRoot = [IO.Path]::GetFullPath($AppRoot)
$tools = Join-Path $AppRoot '00database\Tools'
$runtime = Join-Path $AppRoot '.runtime'
$cache = Join-Path $runtime 'downloads'
New-Item -ItemType Directory -Force -Path $runtime,$cache | Out-Null
$log = Join-Path $runtime 'setup.log'
Start-Transcript -Path $log -Append | Out-Null
function Run-Checked([string]$Exe, [string[]]$Arguments) {
    $previousPreference = $ErrorActionPreference
    try {
        # Convert native stderr to visible text, so failures also appear in the transcript.
        $ErrorActionPreference = 'Continue'
        & $Exe @Arguments 2>&1 | ForEach-Object { Write-Host $_.ToString() }
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($code -ne 0) { throw "Command failed ($code): $Exe" }
}
function Get-Dependency([string]$Name) {
    $entry = $script:manifest.$Name
    if (-not $entry) { throw "Unknown dependency: $Name" }
    $dest = Join-Path $cache $Name
    if ((Test-Path -LiteralPath $dest) -and ((Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash -eq $entry.sha256)) { return $dest }
    Write-Host "Downloading $Name ($([math]::Round($entry.bytes / 1MB)) MB)..."
    $partial = "$dest.part"
    Invoke-WebRequest -Uri $entry.url -OutFile $partial -UseBasicParsing
    if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $entry.sha256) { throw "Download checksum failed: $Name. Rerun setup to retry." }
    Move-Item -LiteralPath $partial -Destination $dest -Force
    return $dest
}
function Install-Exe([string]$File, [string[]]$Arguments) {
    $process = Start-Process -FilePath $File -ArgumentList $Arguments -PassThru -Wait -WindowStyle Hidden
    if ($process.ExitCode -notin @(0,3010)) { throw "Installer failed ($($process.ExitCode)): $File" }
}
function Test-PrivateRuntime([string]$Python, [string]$Kind, [string]$Requirements) {
    if (-not (Test-Path -LiteralPath $Python)) { return $false }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Python (Join-Path $PSScriptRoot 'runtime_probe.py') $Kind $Requirements 2>&1 | ForEach-Object { Write-Host $_.ToString() }
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    return $code -eq 0
}
function Test-Tool([string]$Path, [string]$VersionArgument, [string]$MinimumVersion = '') {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    try {
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $Path
        $info.Arguments = $VersionArgument
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $p = New-Object System.Diagnostics.Process
        $p.StartInfo = $info
        [void]$p.Start()
        if (-not $p.WaitForExit(15000)) { $p.Kill(); return $false }
        $text = $p.StandardOutput.ReadToEnd()
        if ($p.ExitCode -ne 0) { return $false }
        if ($MinimumVersion) {
            if ($text -notmatch '(?<!\d)(\d+\.\d+(?:\.\d+)?)') { return $false }
            return [version]$Matches[1] -ge [version]$MinimumVersion
        }
        return $true
    } catch { return $false } finally { if ($p) { $p.Dispose() } }
}
try {
    Set-Location -LiteralPath $tools
    Write-Host 'Waze Voice Studio dependency setup. Large downloads can take a while.'
    $script:manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'dependencies.json') -Raw | ConvertFrom-Json
    if ($CheckOnly) {
        foreach ($name in @('python.tar.gz','ffmpeg.zip','adb.zip','codex.zip','deno.zip','yt-dlp.exe','VoiceStudio.exe','vc_redist.exe')) {
            if (-not $manifest.$name -or $manifest.$name.sha256 -notmatch '^[a-f0-9]{64}$' -or $manifest.$name.url -notmatch '^https://') { throw "Invalid dependency manifest: $name" }
        }
        Write-Host 'Manifest valid.'
        exit 0
    }
    $ready = Join-Path $runtime 'ready.json'
    if (Test-Path -LiteralPath $ready) { Remove-Item -LiteralPath $ready }
    $python = Join-Path $runtime 'python\python.exe'
    if (-not (Test-Tool $python '--version' '3.11.0')) {
        # The standalone archive does not modify an existing system Python installation.
        $archive = Get-Dependency 'python.tar.gz'
        Run-Checked (Join-Path $env:SystemRoot 'System32\tar.exe') @('-xzf',$archive,'-C',$runtime)
        if (-not (Test-Path -LiteralPath $python)) { throw 'Python extraction did not create the private runtime.' }
    } else { Write-Host 'SKIP private Python: already installed.' }
    # PyTorch/CTranslate2 require Microsoft's C++ runtime. This installer may request elevation.
    $vcKey = 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'
    $vcInfo = Get-ItemProperty $vcKey -ErrorAction SilentlyContinue
    $vcVersion = [version]'0.0'
    if ($vcInfo -and $vcInfo.Version) { $vcVersion = [version]($vcInfo.Version -replace '^v','') }
    if (-not $vcInfo -or $vcInfo.Installed -ne 1 -or $vcVersion -lt [version]'14.44.35211.0') {
        Install-Exe (Get-Dependency 'vc_redist.exe') @('/install','/quiet','/norestart')
    } else { Write-Host 'SKIP Microsoft C++ runtime: compatible version already installed.' }
    $bin = Join-Path $runtime 'bin'
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    foreach ($pair in @(@('ffmpeg.zip','ffmpeg'),@('adb.zip','adb'),@('codex.zip','codex'),@('deno.zip','deno'))) {
        $out = Join-Path $runtime $pair[1]
        $healthy = $false
        switch ($pair[1]) {
            'ffmpeg' {
                $ff = Get-ChildItem -Path (Join-Path $out '*\bin\ffmpeg.exe') -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($ff) { $healthy = (Test-Tool $ff.FullName '-version' '4.4') -and (Test-Tool (Join-Path $ff.DirectoryName 'ffprobe.exe') '-version' '4.4') -and (Test-Tool (Join-Path $ff.DirectoryName 'ffplay.exe') '-version' '4.4') }
            }
            'adb' { $healthy = Test-Tool (Join-Path $out 'platform-tools\adb.exe') 'version' '1.0.41' }
            'codex' { $healthy = (Test-Tool (Join-Path $bin 'codex.exe') '--version' '0.163.0') -and (Test-Path -LiteralPath (Join-Path $bin 'codex-resources\codex-windows-sandbox-setup.exe')) }
            'deno' { $healthy = Test-Tool (Join-Path $out 'deno.exe') '--version' '2.9.7' }
        }
        if ($healthy) { Write-Host "SKIP $($pair[1]): existing tools passed their executable checks."; continue }
        $zip = Get-Dependency $pair[0]
        Expand-Archive -LiteralPath $zip -DestinationPath $out -Force
        if ($pair[1] -eq 'codex') {
            $codex = Join-Path $out 'codex-x86_64-pc-windows-msvc.exe'
            if (-not (Test-Path -LiteralPath $codex)) { throw 'Codex archive did not contain its main executable.' }
            Copy-Item -Path (Join-Path $out '*') -Destination $bin -Recurse -Force
            Copy-Item -LiteralPath $codex -Destination (Join-Path $bin 'codex.exe') -Force
        }
    }
    Run-Checked (Join-Path $bin 'codex.exe') @('--version')
    $yt = Join-Path $tools 'vendor\yt-dlp'
    New-Item -ItemType Directory -Force -Path $yt | Out-Null
    if (Test-Tool (Join-Path $yt 'yt-dlp.exe') '--version' '2026.8.19') { Write-Host 'SKIP yt-dlp: existing downloader passed its executable check.' }
    else { Copy-Item -LiteralPath (Get-Dependency 'yt-dlp.exe') -Destination (Join-Path $yt 'yt-dlp.exe') -Force }
    $ffmpeg = Get-ChildItem -Path (Join-Path $runtime 'ffmpeg\*\bin\ffmpeg.exe') | Select-Object -First 1
    $env:PATH = "$bin;$(Join-Path $runtime 'deno');$(Join-Path $runtime 'adb\platform-tools');$($ffmpeg.DirectoryName);$env:PATH"
    foreach ($item in @(@('.venv','requirements.txt'),@('.worker','requirements-worker.txt'))) {
        $venv = Join-Path $tools $item[0]
        $vp = Join-Path $venv 'Scripts\python.exe'
        $kind = if ($item[0] -eq '.worker') { 'worker' } else { 'gui' }
        $requirements = Join-Path $tools $item[1]
        if (Test-PrivateRuntime $vp $kind $requirements) { Write-Host "SKIP $kind packages: requirements, imports and dependency graph are healthy."; continue }
        if (-not (Test-Path -LiteralPath $vp)) { Run-Checked $python @('-m','venv',$venv) }
        Run-Checked $vp @('-m','ensurepip','--upgrade')
        Run-Checked $vp @('-m','pip','install','--disable-pip-version-check','--upgrade','pip')
        if ($item[0] -eq '.worker') {
            Write-Host 'Installing local audio analysis dependencies (CPU build; generation uses VoiceStudio separately)...'
            Run-Checked $vp @('-m','pip','install','torch==2.6.0','torchaudio==2.6.0','--index-url','https://download.pytorch.org/whl/cpu')
        }
        Run-Checked $vp @('-m','pip','install','-r',(Join-Path $tools $item[1]))
        if (-not (Test-PrivateRuntime $vp $kind $requirements)) { throw "$kind environment did not pass verification after installation." }
    }
    $guiPython = Join-Path $tools '.venv\Scripts\python.exe'
    $voiceSetup = Join-Path $PSScriptRoot 'voicestudio_setup.py'
    $voiceStudio = & $guiPython $voiceSetup --discover
    if ($LASTEXITCODE -ne 0) { Install-Exe (Get-Dependency 'VoiceStudio.exe') @('/S') }
    else { Write-Host 'SKIP VoiceStudio desktop application: an existing installation was detected.' }
    Run-Checked $guiPython @($voiceSetup,'--app-root',$AppRoot)
    Run-Checked (Join-Path $tools '.worker\Scripts\python.exe') @((Join-Path $PSScriptRoot 'prepare_models.py'),'--tools',$tools)
    Run-Checked (Join-Path $tools '.venv\Scripts\python.exe') @('-c','import tkinter, requests, blackboxprotobuf; import pack_builder_gui')
    Run-Checked (Join-Path $tools '.worker\Scripts\python.exe') @('-c','import torch, torchaudio, faster_whisper, speechbrain, soundfile')
    Write-Host 'Audio runtime imports passed.'
    if (Test-Tool (Join-Path $bin 'codex.exe') 'login status') { Write-Host 'SKIP Codex sign-in: your existing account login was detected.' }
    else { Write-Host 'Personal sign-in needed for automatic AI review: use Sign in to Codex in the Start menu. All local dependencies are installed.' }
    @{version=(Get-Content -LiteralPath (Join-Path $AppRoot 'VERSION.txt') -Raw).Trim();completed=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $ready -Encoding UTF8
    Write-Host 'Setup complete: VoiceStudio, required models and analysis models are ready. Existing healthy components were skipped. If needed, use Sign in to Codex for your personal account.'
} catch {
    Write-Host "SETUP FAILED: $_" -ForegroundColor Red
    Write-Host "Log: $log. Use Repair dependency setup from the Start menu to retry. Your voices are preserved."
    Stop-Transcript | Out-Null
    exit 1
}
Stop-Transcript | Out-Null
exit 0
