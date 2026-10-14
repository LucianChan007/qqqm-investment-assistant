$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Dashboard = Join-Path $Root 'gui\dashboard.py'
$LogDir = Join-Path $Root 'reports\intraday_learning_cycle'
$LauncherLog = Join-Path $LogDir 'launcher.log'

if (-not (Test-Path $Python)) {
    throw "Project Python was not found: $Python"
}
if (-not (Test-Path (Join-Path $Root 'scripts\run_intraday_learning_cycle.py'))) {
    throw "Cycle script was not found under project root: $Root"
}
if (-not (Test-Path $Dashboard)) {
    throw "Dashboard was not found: $Dashboard"
}
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
Add-Content -LiteralPath $LauncherLog -Encoding UTF8 -Value "[$stamp] Launcher started. Checking if a catch-up run is needed."

Write-Host ''
Write-Host 'QQQM Investment Assistant' -ForegroundColor Cyan
Write-Host 'Checking missed forecast/review run. If already done or the U.S. market is active, the cycle will safely skip.'
Write-Host ''
& $Python -m scripts.run_intraday_learning_cycle --catch-up-on-open
$CycleExitCode = $LASTEXITCODE
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
Add-Content -LiteralPath $LauncherLog -Encoding UTF8 -Value "[$stamp] Cycle check finished with exit code $CycleExitCode."
if ($CycleExitCode -ne 0) {
    Write-Warning "Catch-up cycle returned code $CycleExitCode. Launching the dashboard anyway; check reports\intraday_learning_cycle\latest_status.json."
}

Write-Host ''
Write-Host 'Starting Dashboard at http://localhost:8501 ...' -ForegroundColor Green
& $Python -m streamlit run $Dashboard
$GuiExitCode = $LASTEXITCODE
if ($GuiExitCode -ne 0) {
    Write-Warning "Streamlit exited with code $GuiExitCode. Check the terminal output above."
}
exit $GuiExitCode
