param([string]$Compiler)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$build = Join-Path $root 'build'
New-Item -ItemType Directory -Force -Path $build | Out-Null
if (-not $Compiler) {
    $Compiler = Join-Path $build 'inno\ISCC.exe'
    if (-not (Test-Path -LiteralPath $Compiler)) {
        $installer = Join-Path $build 'inno-6.7.3.exe'
        Invoke-WebRequest -Uri 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe' -OutFile $installer -UseBasicParsing
        if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne '9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732') { throw 'Inno Setup checksum mismatch.' }
        if ((Get-AuthenticodeSignature -FilePath $installer).Status -ne 'Valid') { throw 'Inno Setup publisher signature is invalid.' }
        $p = Start-Process -FilePath $installer -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER',('/DIR="' + (Join-Path $build 'inno') + '"') -Wait -PassThru -WindowStyle Hidden
        if ($p.ExitCode -ne 0) { throw 'Unable to install the build compiler.' }
    }
}
& $Compiler (Join-Path $PSScriptRoot 'installer.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
$version = (Get-Content -LiteralPath (Join-Path $root 'VERSION.txt') -Raw).Trim()
$exe = Join-Path $root "dist\Waze-Voice-Studio-$version-Windows-x64-Setup.exe"
$hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $([IO.Path]::GetFileName($exe))" | Set-Content -LiteralPath (Join-Path $root 'dist\SHA256SUMS.txt') -Encoding ascii
Write-Host "Built $exe"
