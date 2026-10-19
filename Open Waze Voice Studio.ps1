$root = $PSScriptRoot
$python = Join-Path $root '00database\Tools\.venv\Scripts\pythonw.exe'
$launch = Join-Path $root '00database\Tools\launch.py'
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath (Join-Path $root '.runtime\ready.json'))) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show('Dependency setup is incomplete. Run Repair dependency setup from the Waze Voice Studio Start menu folder.', 'Waze Voice Studio') | Out-Null
    exit 1
}
Start-Process -FilePath $python -ArgumentList ('"' + $launch + '"') -WorkingDirectory $root -WindowStyle Hidden
