# Wait until FastAPI responds (Mongo connected). Used by start-local-demo.bat.
param(
  [string]$Url = 'http://127.0.0.1:8000/openapi.json',
  [int]$MaxAttempts = 45,
  [int]$SleepSeconds = 2
)
$ErrorActionPreference = 'SilentlyContinue'
for ($i = 0; $i -lt $MaxAttempts; $i++) {
  try {
    $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) {
      Write-Host "[OK] Backend is up ($Url)" -ForegroundColor Green
      exit 0
    }
  } catch {}
  Write-Host "  ... waiting for API ($($i + 1)/$MaxAttempts)" -ForegroundColor DarkGray
  Start-Sleep -Seconds $SleepSeconds
}
Write-Host "[ERROR] Backend did not respond at $Url within window." -ForegroundColor Red
Write-Host "        Open the SkillMap-API window: MongoDB must connect (see backend\.env)." -ForegroundColor Yellow
exit 1
