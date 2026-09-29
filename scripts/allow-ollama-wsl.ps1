#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu"
)

$ErrorActionPreference = "Stop"
$ruleName = "DocIntel Ollama from WSL"
$route = (& wsl.exe -d $Distro -- ip route show default | Out-String).Trim()
$addresses = (& wsl.exe -d $Distro -- hostname -I | Out-String).Trim()

if ($route -notmatch 'default via (?<gateway>\d{1,3}(?:\.\d{1,3}){3})') {
    throw "Could not determine the Windows-to-WSL gateway address."
}
$gateway = $Matches.gateway
$wslAddress = ($addresses -split '\s+' | Where-Object { $_ -match '^\d{1,3}(?:\.\d{1,3}){3}$' } | Select-Object -First 1)
if (-not $wslAddress) {
    throw "Could not determine the WSL IPv4 address."
}

$parsed = $null
if (-not [System.Net.IPAddress]::TryParse($gateway, [ref]$parsed)) {
    throw "Invalid WSL gateway address: $gateway"
}
if (-not [System.Net.IPAddress]::TryParse($wslAddress, [ref]$parsed)) {
    throw "Invalid WSL source address: $wslAddress"
}

Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule
New-NetFirewallRule `
    -DisplayName $ruleName `
    -Description "Allow DocIntel containers in the current WSL instance to reach local Ollama." `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalAddress $gateway `
    -LocalPort 11434 `
    -RemoteAddress $wslAddress `
    -Profile Any | Out-Null

Write-Host "Created '$ruleName': $wslAddress -> ${gateway}:11434"
Write-Host "Rerun this script if the WSL addresses change."
