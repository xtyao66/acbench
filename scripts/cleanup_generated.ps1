$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot

$targets = @(
    (Join-Path $root "runs"),
    (Join-Path $root "out"),
    (Join-Path $root "demo_out"),
    (Join-Path $root "reports"),
    (Join-Path $root ".hf_cache"),
    (Join-Path $root "__pycache__")
)

foreach ($target in $targets) {
    if (Test-Path $target) {
        Write-Output "Removing $target"
        Remove-Item -Recurse -Force $target
    }
}

Get-ChildItem -Path $root -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Output "Removing $($_.FullName)"
        Remove-Item -Recurse -Force $_.FullName
    }

Get-ChildItem -Path $root -Recurse -File -Include "*.pyc" -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Output "Removing $($_.FullName)"
        Remove-Item -Force $_.FullName
    }

Write-Output "Generated artifacts cleanup completed."
