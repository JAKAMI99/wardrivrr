# Reset the wardrivrr admin password via the API container (or local Python).
param(
    [Parameter(Position = 0)]
    [string]$Password = "",
    [switch]$Local,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ($Help) {
    Write-Host @"
Usage:
  .\scripts\reset-admin-password.ps1 [password]

Docker (default when the API container is running):
  .\scripts\reset-admin-password.ps1 'YourNewPassword'

Local (host API / debug, PostGIS reachable):
  .\scripts\reset-admin-password.ps1 -Local 'YourNewPassword'
"@
    exit 0
}

$compose = @("compose", "-f", "docker-compose.yml", "-f", "deploy/compose.car.yml")

if ($Local) {
    if ($Password) {
        python "$Root\scripts\reset_admin_password.py" $Password
    } else {
        python "$Root\scripts\reset_admin_password.py"
    }
    exit $LASTEXITCODE
}

$running = docker ps --format "{{.Names}}" 2>$null | Where-Object { $_ -eq "wardrivrr_api" }
if (-not $running) {
    Write-Error "Container wardrivrr_api is not running. Start the stack, or pass -Local."
}

if ($Password) {
    & docker @compose exec -T api python /app/scripts/reset_admin_password.py $Password
} else {
    & docker @compose exec -it api python /app/scripts/reset_admin_password.py
}
exit $LASTEXITCODE
