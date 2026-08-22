param(
    [switch] $Standalone
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Missing .venv. Create it and install requirements.txt first."
}

& $Python -m pip install -r (Join-Path $Root "requirements-build.txt")
& $Python (Join-Path $PSScriptRoot "write_icon.py")

$PyInstaller = Join-Path $Root ".venv\Scripts\pyinstaller.exe"
if ($Standalone) {
    Write-Host "Building standalone CUDA bundle (needs a lot of free disk)..."
    & $PyInstaller --noconfirm --clean --distpath (Join-Path $Root "dist") --workpath (Join-Path $Root "build") (Join-Path $PSScriptRoot "standalone.spec")
    Write-Host "Built dist\Sunder\Sunder.exe — keep the whole Sunder folder together."
} else {
    & $PyInstaller --noconfirm --clean --distpath (Join-Path $Root "dist") --workpath (Join-Path $Root "build") (Join-Path $PSScriptRoot "sunder.spec")
    $Built = Join-Path $Root "dist\Sunder.exe"
    $Shortcut = Join-Path $Root "Sunder.exe"
    Copy-Item $Built $Shortcut -Force
    Write-Host "Built $Shortcut"
    Write-Host "Double-click Sunder.exe (keep it next to .venv)."
}
