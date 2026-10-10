param(
    [Parameter(Mandatory=$true)][string]$AppPath,
    [Parameter(Mandatory=$true)][ValidateRange(1024,65535)][int]$Port
)
$ErrorActionPreference = 'Stop'
$ResolvedApp = (Resolve-Path -LiteralPath $AppPath).Path
if ((Split-Path -Leaf $ResolvedApp) -ne 'Anime Watcher.exe') { throw 'Choose the packaged Anime Watcher application.' }
$Hasher = [System.Security.Cryptography.SHA256]::Create()
$Identity = [System.BitConverter]::ToString($Hasher.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($ResolvedApp))).Replace('-','').Substring(0,12)
$Hasher.Dispose()
$RuleName = "AnimeWatcher.PhoneAccess.$Identity"
$Existing = Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
if ($Existing) { Remove-NetFirewallRule -Name $RuleName }
New-NetFirewallRule -Name $RuleName -DisplayName 'Anime Watcher Phone access (local network only)' `
    -Direction Inbound -Action Allow -Program $ResolvedApp -Protocol TCP -LocalPort $Port `
    -RemoteAddress LocalSubnet -Profile Any -EdgeTraversalPolicy Block | Out-Null
