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
    if (-not (Test-Path -LiteralPath $python)) {
        # The standalone archive does not modify an existing system Python installation.
        $archive = Get-Dependency 'python.tar.gz'
        Run-Checked (Join-Path $env:SystemRoot 'System32\tar.exe') @('-xzf',$archive,'-C',$runtime)
        if (-not (Test-Path -LiteralPath $python)) { throw 'Python extraction did not create the private runtime.' }
    }
    # PyTorch/CTranslate2 require Microsoft's C++ runtime. This installer may request elevation.
    $vcKey = 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'
    $vcInfo = Get-ItemProperty $vcKey -ErrorAction SilentlyContinue
    $vcVersion = [version]'0.0'
    if ($vcInfo -and $vcInfo.Version) { $vcVersion = [version]($vcInfo.Version -replace '^v','') }
    if (-not $vcInfo -or $vcInfo.Installed -ne 1 -or $vcVersion -lt [version]'14.44.35211.0') {
        Install-Exe (Get-Dependency 'vc_redist.exe') @('/install','/quiet','/norestart')
    }
    $bin = Join-Path $runtime 'bin'
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    foreach ($pair in @(@('ffmpeg.zip','ffmpeg'),@('adb.zip','adb'),@('codex.zip','codex'),@('deno.zip','deno'))) {
        $zip = Get-Dependency $pair[0]
        $out = Join-Path $runtime $pair[1]
        Expand-Archive -LiteralPath $zip -DestinationPath $out -Force
    }
    $codex = Join-Path $runtime 'codex\codex-x86_64-pc-windows-msvc.exe'
    if (-not (Test-Path -LiteralPath $codex)) { throw 'Codex archive did not contain its main executable.' }
    Copy-Item -Path (Join-Path $runtime 'codex\*') -Destination $bin -Recurse -Force
    Copy-Item -LiteralPath $codex -Destination (Join-Path $bin 'codex.exe') -Force
    Run-Checked (Join-Path $bin 'codex.exe') @('--version')
    $yt = Join-Path $tools 'vendor\yt-dlp'
    New-Item -ItemType Directory -Force -Path $yt | Out-Null
    Copy-Item -LiteralPath (Get-Dependency 'yt-dlp.exe') -Destination (Join-Path $yt 'yt-dlp.exe') -Force
    $env:PATH = "$bin;$(Join-Path $runtime 'deno');$env:PATH"
    foreach ($item in @(@('.venv','requirements.txt'),@('.worker','requirements-worker.txt'))) {
        $venv = Join-Path $tools $item[0]
        if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) { Run-Checked $python @('-m','venv',$venv) }
        $vp = Join-Path $venv 'Scripts\python.exe'
        Run-Checked $vp @('-m','pip','install','--disable-pip-version-check','--upgrade','pip')
        if ($item[0] -eq '.worker') {
            Write-Host 'Installing local audio analysis dependencies (CPU build; generation uses VoiceStudio separately)...'
            Run-Checked $vp @('-m','pip','install','torch==2.6.0','torchaudio==2.6.0','--index-url','https://download.pytorch.org/whl/cpu')
        }
        Run-Checked $vp @('-m','pip','install','-r',(Join-Path $tools $item[1]))
        Run-Checked $vp @('-m','pip','check')
    }
    $voiceStudio = Join-Path $env:LOCALAPPDATA 'Programs\VoiceStudio\VoiceStudio.exe'
    if (-not (Test-Path -LiteralPath $voiceStudio)) { Install-Exe (Get-Dependency 'VoiceStudio.exe') @('/S') }
    if (-not (Test-Path -LiteralPath $voiceStudio)) { throw 'VoiceStudio was not found after installation. Install it in the default per-user folder, then rerun dependency setup.' }
    Run-Checked (Join-Path $tools '.venv\Scripts\python.exe') @('-c','import tkinter, requests, blackboxprotobuf; import pack_builder_gui')
    Run-Checked (Join-Path $tools '.worker\Scripts\python.exe') @('-c','import torch, torchaudio, faster_whisper, speechbrain, soundfile')
    Write-Host 'Audio runtime imports passed.'
    @{version=(Get-Content -LiteralPath (Join-Path $AppRoot 'VERSION.txt') -Raw).Trim();completed=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $ready -Encoding UTF8
    Write-Host 'Dependencies installed. Open VoiceStudio once to complete its runtime and model setup. Use Sign in to Codex for automatic reference review.'
} catch {
    Write-Host "SETUP FAILED: $_" -ForegroundColor Red
    Write-Host "Log: $log. Use Repair dependency setup from the Start menu to retry. Your voices are preserved."
    Stop-Transcript | Out-Null
    exit 1
}
Stop-Transcript | Out-Null
exit 0
