# Run Vite dev server if Node is installed but npm is not on PATH.
# Usage: powershell -ExecutionPolicy Bypass -File .\start-dev.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Cursor/IDE terminals often keep a stale PATH after Node is installed; prepend known install dirs.
$nodeBins = @(
    "$env:ProgramFiles\nodejs",
    "${env:ProgramFiles(x86)}\nodejs",
    "$env:LOCALAPPDATA\Programs\node"
)
foreach ($dir in $nodeBins) {
    if ((Test-Path "$dir\node.exe") -and ($env:Path -notlike "*$dir*")) {
        $env:Path = "$dir;$env:Path"
    }
}

function Find-Npm {
    $cmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $paths = @(
        "$env:ProgramFiles\nodejs\npm.cmd",
        "${env:ProgramFiles(x86)}\nodejs\npm.cmd",
        "$env:LOCALAPPDATA\Programs\node\npm.cmd",
        "$env:APPDATA\nvm\*\npm.cmd"
    )
    foreach ($p in $paths) {
        $resolved = @(Resolve-Path $p -ErrorAction SilentlyContinue)
        if ($resolved.Count -gt 0) { return $resolved[0].Path }
    }
    return $null
}

$npm = Find-Npm
if (-not $npm) {
    Write-Host ""
    Write-Host "Node.js/npm was not found." -ForegroundColor Red
    Write-Host "Install Node.js LTS from https://nodejs.org/ then close and reopen the terminal."
    Write-Host "Or add the Node install folder (e.g. Program Files\nodejs) to your PATH."
    Write-Host ""
    exit 1
}

Write-Host "Using: $npm" -ForegroundColor Green
& $npm run start
