$ErrorActionPreference = "Stop"

Write-Host "===========================================" -ForegroundColor Cyan
Write-Host " Skill Mapping Platform - Health Check" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""

function Assert-Command($name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    throw "[ERROR] Required command missing: $name"
  }
}

Assert-Command python
Assert-Command node
Assert-Command npm

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

$pythonExe = Join-Path $backend "venv312\\Scripts\\python.exe"
if (-not (Test-Path $pythonExe)) {
  $pythonExe = Join-Path $backend "venv\\Scripts\\python.exe"
}
if (-not (Test-Path $pythonExe)) {
  Write-Host "[INFO] No venv found. Creating backend\\venv..." -ForegroundColor Yellow
  Push-Location $backend
  python -m venv venv
  Pop-Location
  $pythonExe = Join-Path $backend "venv\\Scripts\\python.exe"
}

Write-Host "[1/4] Installing backend dependencies..." -ForegroundColor Yellow
Push-Location $backend
& $pythonExe -m pip install -r requirements.txt | Out-Null
Write-Host "[2/4] Running backend tests..." -ForegroundColor Yellow
& $pythonExe -m pytest -q
Pop-Location

Write-Host "[3/4] Installing frontend dependencies..." -ForegroundColor Yellow
Push-Location $frontend
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
  npm install
}
Write-Host "[4/4] Building frontend..." -ForegroundColor Yellow
npm run build
Pop-Location

Write-Host ""
Write-Host "[OK] Health check passed: backend tests + frontend build succeeded." -ForegroundColor Green
