# Kronos Web UI - cai dat va chay local tren Windows
# Cach dung (PowerShell):  .\setup_windows.ps1
# Tuy chon: .\setup_windows.ps1 -Target "E:\Working data\Claude\BTC_Forecast"
param(
    [string]$Target = "E:\Working data\Claude\BTC_Forecast",
    [string]$Branch = "claude/exciting-fermi-qiuxl1"
)
$ErrorActionPreference = "Stop"

foreach ($cmd in "git", "python") {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "Chua cai '$cmd'. Hay cai Git va Python 3.10+ (tick 'Add to PATH') roi chay lai."
    }
}

$repo = Join-Path $Target "Kronos"
New-Item -ItemType Directory -Force -Path $Target | Out-Null
if (-not (Test-Path $repo)) {
    git clone https://github.com/pippit2hn/Kronos.git $repo
}
Set-Location $repo
git fetch origin $Branch
git checkout $Branch
git pull origin $Branch

if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt -r webui\requirements.txt

New-Item -ItemType Directory -Force -Path "data" | Out-Null

# Tao file khoi dong nhanh, chi cho truy cap tu may nay
@"
@echo off
cd /d "%~dp0webui"
set HOST=127.0.0.1
set FLASK_DEBUG=0
start "" http://localhost:7070
"%~dp0.venv\Scripts\python.exe" app.py
"@ | Set-Content -Encoding ASCII (Join-Path $repo "run_kronos.bat")

Write-Host "`nXong. Dat file CSV/Feather vao: $repo\data"
Write-Host "Chay webapp bang: $repo\run_kronos.bat  (mo http://localhost:7070)"
