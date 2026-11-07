# SurgiSight quality check runner
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Errors = 0

function Run-Check {
    param([string]$Name, [string]$Command)
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    Invoke-Expression $Command
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Name" -ForegroundColor Red
        $script:Errors++
    } else {
        Write-Host "PASSED: $Name" -ForegroundColor Green
    }
}

Run-Check "Ruff lint" ".venv\Scripts\ruff.exe check ."
Run-Check "Black check" ".venv\Scripts\black.exe --check ."
Run-Check "Mypy (contract, analytics, report)" ".venv\Scripts\mypy.exe surgisight/contract surgisight/analytics surgisight/report"
Run-Check "Pytest + coverage" ".venv\Scripts\pytest.exe -q --cov=surgisight --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=80"
Run-Check "Contract and analytics coverage" "python scripts\coverage_gate.py coverage.json"
Run-Check "Tracked-file security scan" "python scripts\security_check.py"
Run-Check "Synthetic online smoke harness" "python scripts\performance_harness.py --seconds 30 --warmup 5"

# Frontend checks
if (Test-Path "web\node_modules") {
    Set-Location web
    Run-Check "npm lint" "npm run lint"
    Run-Check "npm test" "npm test"
    Run-Check "npm build" "npm run build"
    Set-Location $Root
} else {
    Write-Host "Skipping frontend checks (node_modules not found -- run: cd web; npm install)" -ForegroundColor Yellow
}

if ($Errors -eq 0) {
    Write-Host "`nAll checks PASSED." -ForegroundColor Green
    exit 0
} else {
    Write-Host "`n$Errors check(s) FAILED." -ForegroundColor Red
    exit 1
}
