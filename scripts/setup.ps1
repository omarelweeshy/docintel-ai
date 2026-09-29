[CmdletBinding()]
param(
    [switch]$Gpu,
    [switch]$SkipModelPull
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Assert-Command {
    param([Parameter(Mandatory)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found. Install Docker Desktop with Compose v2, then retry."
    }
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments)][string[]]$Arguments)
    $files = @("-f", "docker-compose.yml", "-f", "docker-compose.local-ai.yml")
    if ($Gpu) {
        $files += @("-f", "docker-compose.gpu.yml")
    }
    & docker compose @files @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed with exit code $LASTEXITCODE."
    }
}

Assert-Command docker
& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker is installed but the engine is unavailable. Start Docker Desktop, wait until it is ready, then retry."
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from safe local defaults."
}

Write-Host "Starting PostgreSQL and the self-contained Ollama service..."
Invoke-Compose up -d db ollama --wait --wait-timeout 180

if (-not $SkipModelPull) {
    Write-Host "Provisioning qwen3.5:4b. The first download is several gigabytes..."
    Invoke-Compose exec -T ollama ollama pull qwen3.5:4b
    Write-Host "Provisioning qwen3-embedding:0.6b..."
    Invoke-Compose exec -T ollama ollama pull qwen3-embedding:0.6b
}

Write-Host "Building and starting DocIntel AI..."
Invoke-Compose up -d --build --wait --wait-timeout 600

$ready = Invoke-RestMethod -Uri "http://localhost:8000/health/ready" -TimeoutSec 15
$web = Invoke-WebRequest -Uri "http://localhost:3000" -UseBasicParsing -TimeoutSec 15
if (-not $ready.ready -or $web.StatusCode -ne 200) {
    throw "The stack started but failed its final readiness check. Run docker compose logs for details."
}

Write-Host ""
Write-Host "DocIntel AI is ready."
Write-Host "Application: http://localhost:3000"
Write-Host "API docs:    http://localhost:8000/docs"
Write-Host "Samples:     $repoRoot\sample-documents"
Write-Host ""
Write-Host "Stop without deleting data: docker compose -f docker-compose.yml -f docker-compose.local-ai.yml down"
