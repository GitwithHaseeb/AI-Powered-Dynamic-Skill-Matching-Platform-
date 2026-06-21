Write-Host "Fixing process.env references..." -ForegroundColor Green

$files = Get-ChildItem src -Recurse -Include *.js, *.jsx

foreach ($file in $files) {
    $content = Get-Content $file.FullName -Raw
    $original = $content
    
    # Fix process.env.REACT_APP_ to import.meta.env.VITE_
    $content = $content -replace 'process\.env\.REACT_APP_', 'import.meta.env.VITE_'
    
    # Fix generic process.env references
    $content = $content -replace 'process\.env\.NODE_ENV', 'import.meta.env.MODE'
    
    if ($original -ne $content) {
        Set-Content $file.FullName $content -Encoding UTF8
        Write-Host "? Fixed: $($file.FullName)" -ForegroundColor Yellow
    }
}

Write-Host "Done! All files updated." -ForegroundColor Green
