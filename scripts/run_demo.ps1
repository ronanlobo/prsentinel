# Starts the PRSentinel demo app on your own machine and leaves it running.
#
#     .\scripts\run_demo.ps1
#     .\scripts\run_demo.ps1 -Port 9000
#
# Nothing here reaches a network. The page works out of the box because its
# first choice is saved tests, which need no AI and no key.
#
# To stop the app, press Ctrl+C in the window this started, or close it.

[CmdletBinding()]
param(
    [int] $Port = 8000,
    [switch] $Check
)

$ErrorActionPreference = "Stop"

# Work out the project root from this script's own location, so the script can
# be started from anywhere.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$project = Split-Path -Parent $here

Set-Location $project

$python = Join-Path $project ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host ""
    Write-Host "No virtual environment found at $python" -ForegroundColor Red
    Write-Host "Create it first:"
    Write-Host ""
    Write-Host "    python -m venv .venv"
    Write-Host "    .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    Write-Host "    .\.venv\Scripts\python.exe -m pip install -e ."
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host "PRSentinel demo app" -ForegroundColor Cyan
Write-Host "  address     http://127.0.0.1:$Port"
Write-Host "  bound to    127.0.0.1 only, so nothing on your network can reach it"
Write-Host "  first mode  Saved tests, which needs no key and no AI"
Write-Host ""

if ($Check) {
    Write-Host "Checking that the app starts and serves its page, then stopping." -ForegroundColor Cyan
    Write-Host ""

    $job = Start-Job -ScriptBlock {
        param($root, $port)
        Set-Location $root
        & (Join-Path $root ".venv\Scripts\python.exe") -m prsentinel.app --port $port
    } -ArgumentList $project, $Port

    try {
        $answer = $null
        for ($i = 0; $i -lt 40; $i++) {
            Start-Sleep -Milliseconds 500
            try {
                $answer = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 3
                break
            } catch {
                $answer = $null
            }
        }

        if ($null -eq $answer) {
            Write-Host "The page never answered." -ForegroundColor Red
            exit 1
        }

        Write-Host ("  GET /            " + $answer.StatusCode + "  " +
                    $answer.RawContentLength + " bytes")
        Write-Host ("  page looks right " +
                    $(if ($answer.Content -match "<!DOCTYPE html>") { "yes" } else { "NO" }))

        $demos = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/demos"
        Write-Host ("  cases offered    " + $demos.demos.Count)
        foreach ($one in $demos.demos) {
            Write-Host ("     " + $one.name.PadRight(24) + $one.test_file)
        }
        Write-Host ("  run limit        " + $demos.timeout_seconds + " seconds")
    }
    finally {
        Stop-Job $job -ErrorAction SilentlyContinue
        Remove-Job $job -Force -ErrorAction SilentlyContinue
    }

    Write-Host ""
    Write-Host "Check finished. To actually show it, run this again without -Check." -ForegroundColor Cyan
    Write-Host ""
    exit 0
}

Write-Host "Press Ctrl+C to stop the app." -ForegroundColor Yellow
Write-Host ""

& $python -m prsentinel.app --port $Port