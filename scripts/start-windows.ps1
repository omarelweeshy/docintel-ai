[CmdletBinding()]
param(
    [switch]$Build
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$dockerCandidates = @(
    (Get-Command docker -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    "D:\Apps\DockerDesktop\resources\bin\docker.exe",
    "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$docker = $dockerCandidates | Select-Object -First 1
if (-not $docker) {
    throw "Docker CLI was not found. Install Docker Desktop before running this launcher."
}

& $docker version --format "{{.Server.Version}}" *> $null
if ($LASTEXITCODE -ne 0) {
    $desktopCandidates = @(
        "D:\Apps\DockerDesktop\Docker Desktop.exe",
        "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ }
    $desktop = $desktopCandidates | Select-Object -First 1
    if (-not $desktop) {
        throw "Docker Desktop is installed but its engine is unavailable and its launcher was not found."
    }
    Start-Process -FilePath $desktop -WindowStyle Hidden
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 5
        & $docker version --format "{{.Server.Version}}" *> $null
        if ($LASTEXITCODE -eq 0) { break }
    } while ((Get-Date) -lt $deadline)
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop did not become ready within three minutes."
    }
}

$route = (& wsl.exe -d Ubuntu -- ip route show default) -join " "
if ($route -notmatch "default via (?<gateway>\d+\.\d+\.\d+\.\d+)") {
    throw "Could not determine the private WSL gateway from: $route"
}
$gateway = $Matches.gateway

$ollamaCandidates = @(
    "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
    "$repoRoot\.local\ollama\ollama.exe",
    (Get-Command ollama -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$ollama = $ollamaCandidates | Select-Object -First 1
if (-not $ollama) {
    throw "Ollama was not found. Install Ollama for Windows before running this launcher."
}

$modelStore = Join-Path $repoRoot ".local\models"
if (-not (Test-Path -LiteralPath $modelStore)) {
    $modelStore = Join-Path $env:USERPROFILE ".ollama\models"
}

$existingGatewayListeners = @(Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue | Where-Object LocalAddress -eq $gateway)
foreach ($listener in $existingGatewayListeners) {
    Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
}
if ($existingGatewayListeners.Count -gt 0) {
    $releaseDeadline = (Get-Date).AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 500
        $stillBound = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue | Where-Object LocalAddress -eq $gateway
    } while ($stillBound -and (Get-Date) -lt $releaseDeadline)
    if ($stillBound) {
        throw "The previous Ollama listener at $gateway`:11434 did not release its socket."
    }
}
$env:OLLAMA_HOST = "$gateway`:11434"
$env:OLLAMA_MODELS = $modelStore
$env:OLLAMA_MAX_LOADED_MODELS = "1"
$env:OLLAMA_NUM_PARALLEL = "1"
$env:OLLAMA_KEEP_ALIVE = "0"
$ollamaLog = Join-Path $repoRoot ".local\ollama-current.log"
$ollamaErrorLog = Join-Path $repoRoot ".local\ollama-current-error.log"
Remove-Item -LiteralPath $ollamaLog, $ollamaErrorLog -Force -ErrorAction SilentlyContinue
Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden -RedirectStandardOutput $ollamaLog -RedirectStandardError $ollamaErrorLog

$ollamaUrl = "http://$gateway`:11434"
$deadline = (Get-Date).AddSeconds(45)
do {
    Start-Sleep -Seconds 2
    try {
        $tags = Invoke-RestMethod -Uri "$ollamaUrl/api/tags" -TimeoutSec 3
        if ($tags) { break }
    } catch {
        $tags = $null
    }
} while ((Get-Date) -lt $deadline)
if (-not $tags) {
    throw "Ollama did not become ready at $ollamaUrl. A Windows Firewall rule may be required for the private WSL address."
}

$requiredModels = @("qwen3.5:4b", "qwen3-embedding:0.6b")
$installedModels = @($tags.models | ForEach-Object { $_.name })
$missingModels = @($requiredModels | Where-Object { $_ -notin $installedModels })
if ($missingModels.Count -gt 0) {
    throw "Missing Ollama models: $($missingModels -join ', '). Run the documented ollama pull commands first."
}

$envPath = Join-Path $repoRoot ".env"
if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item (Join-Path $repoRoot ".env.example") $envPath
}
$envLines = @(Get-Content -LiteralPath $envPath)
$replacement = "OLLAMA_BASE_URL=$ollamaUrl"
$found = $false
$envLines = @($envLines | ForEach-Object {
    if ($_ -match "^OLLAMA_BASE_URL=") {
        $found = $true
        $replacement
    } else {
        $_
    }
})
if (-not $found) { $envLines += $replacement }
Set-Content -LiteralPath $envPath -Value $envLines -Encoding utf8

$composeArguments = @("compose", "up", "-d", "--wait", "--wait-timeout", "600")
if ($Build) { $composeArguments = @("compose", "up", "-d", "--build", "--wait", "--wait-timeout", "600") }
& $docker @composeArguments
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose failed with exit code $LASTEXITCODE."
}

$ready = Invoke-RestMethod -Uri "http://localhost:8000/health/ready" -TimeoutSec 15
$web = Invoke-WebRequest -Uri "http://localhost:3000" -UseBasicParsing -TimeoutSec 15
if ($ready.status -ne "ready" -or $web.StatusCode -ne 200) {
    throw "The stack started but failed its final readiness check."
}

Write-Host "DocIntel AI is ready at http://localhost:3000"
Write-Host "API documentation: http://localhost:8000/docs"
Write-Host "Ollama endpoint: $ollamaUrl"
