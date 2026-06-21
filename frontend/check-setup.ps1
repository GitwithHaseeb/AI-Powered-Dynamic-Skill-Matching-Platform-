Write-Host "=== Frontend Setup Diagnostic ===" -ForegroundColor Cyan
Write-Host ""

# 1. Check .env file
Write-Host "1. Environment File:" -ForegroundColor Yellow
if (Test-Path .env) {
    Get-Content .env
    Write-Host "? .env exists" -ForegroundColor Green
} else {
    Write-Host "? .env missing" -ForegroundColor Red
}

Write-Host ""

# 2. Check package.json scripts
Write-Host "2. Package.json scripts:" -ForegroundColor Yellow
$package = Get-Content package.json -Raw | ConvertFrom-Json
$package.scripts

Write-Host ""

# 3. Check for process.env in source files
Write-Host "3. Searching for process.env in source files:" -ForegroundColor Yellow
$files = Get-ChildItem src -Recurse -Include *.js, *.jsx | Select-String -Pattern "process\.env"
if ($files) {
    Write-Host "Found in these files:" -ForegroundColor Red
    $files | ForEach-Object { Write-Host "  - $($_.Path)" }
} else {
    Write-Host "? No process.env found" -ForegroundColor Green
}

Write-Host ""

# 4. Check vite.config.js
Write-Host "4. Vite Config:" -ForegroundColor Yellow
if (Test-Path vite.config.js) {
    Write-Host "? vite.config.js exists" -ForegroundColor Green
} else {
    Write-Host "? vite.config.js missing" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Quick Fixes ===" -ForegroundColor Cyan
Write-Host "1. Run: .\fix-all-env.ps1"
Write-Host "2. Run: npm run dev -- --force"
Write-Host "3. Check browser console (F12)"
Write-Host ""
