# SENTINEL - one command on Windows: the API and the web console.
#
#   powershell -ExecutionPolicy Bypass -File start_app.ps1
#
# API + docs:            http://localhost:8000/docs
# Fault-injection lab:   http://localhost:3000/console/lab
# Blind benchmark:       http://localhost:3000/console/benchmark
# Ctrl-C stops both. Everything runs locally; nothing is sent to a cloud service.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

# The console and the dashboard read data/; generate it on a clean checkout.
if (-not (Test-Path "data\burnin_wide.csv")) { & $py src\generate_burnin_dataset.py }

$procs = @()
$procs += Start-Process -FilePath $py -ArgumentList "-m", "uvicorn", "src.api:app", "--port", "8000" `
    -PassThru -NoNewWindow
if (Test-Path "web\node_modules") {
    $procs += Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev", "--", "--port", "3000" `
        -WorkingDirectory "web" -PassThru -NoNewWindow
} else {
    Write-Host "web console skipped: run 'cd web; npm install' once to enable it"
}

Write-Host ""
Write-Host "API      http://localhost:8000/docs"
Write-Host "Lab      http://localhost:3000/console/lab"
Write-Host "Ctrl-C to stop"
try {
    Wait-Process -Id $procs[0].Id
} finally {
    # npm spawns node as a child; /T takes the whole tree down.
    foreach ($p in $procs) { if (-not $p.HasExited) { taskkill /T /F /PID $p.Id | Out-Null } }
}
