param(
    [switch]$SkipBuild,
    [switch]$UseExistingArchive
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VersionSource = Get-Content -LiteralPath (Join-Path $ProjectRoot "anime_watcher\__init__.py") -Raw
$VersionMatch = [regex]::Match($VersionSource, '__version__\s*=\s*"(\d+\.\d+\.\d+)"')
if (-not $VersionMatch.Success) {
    throw "anime_watcher/__init__.py does not contain a semantic __version__."
}
$Version = $VersionMatch.Groups[1].Value
$SourceAudit = & python (Join-Path $ProjectRoot "release_audit.py") --source
if ($LASTEXITCODE -ne 0) {
    throw "The source privacy/security audit failed.`n$($SourceAudit -join [Environment]::NewLine)"
}
if (-not $SkipBuild) {
    & (Join-Path $ProjectRoot "build.ps1") -Stage
    if ($LASTEXITCODE -ne 0) {
        throw "The staged Windows build failed."
    }
}
$PackageRoot = Join-Path $ProjectRoot "dist-stage-youtube-series\Anime Watcher"
$Executable = Join-Path $PackageRoot "Anime Watcher.exe"
if (-not (Test-Path -LiteralPath $Executable)) {
    throw "The staged Anime Watcher package is missing."
}
$ReleaseRoot = Join-Path $ProjectRoot "release"
New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
$SourceAudit | Set-Content -LiteralPath (Join-Path $ReleaseRoot "release-audit-source-v$Version.json") -Encoding UTF8
$AssetName = "Anime-Watcher-v$Version-Windows.zip"
$Archive = Join-Path $ReleaseRoot $AssetName
if ($UseExistingArchive) {
    if (-not (Test-Path -LiteralPath $Archive)) {
        throw "The requested existing release archive is missing: $Archive"
    }
} else {
    if (Test-Path -LiteralPath $Archive) {
        throw "Release archive already exists: $Archive"
    }
    Compress-Archive -LiteralPath $PackageRoot -DestinationPath $Archive -CompressionLevel Optimal
}
$Entries = @(tar -tf $Archive)
if (-not $Entries -or $Entries[0] -notlike "Anime Watcher/*") {
    throw "The release archive does not have the required Anime Watcher root folder."
}
$ArchiveAudit = & python (Join-Path $ProjectRoot "release_audit.py") --archive $Archive
if ($LASTEXITCODE -ne 0) {
    throw "The packaged privacy/security audit failed.`n$($ArchiveAudit -join [Environment]::NewLine)"
}
$ArchiveAudit | Set-Content -LiteralPath (Join-Path $ReleaseRoot "release-audit-package-v$Version.json") -Encoding UTF8
$Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash.ToLowerInvariant()
$Manifest = [ordered]@{
    version = $Version
    tag = "v$Version"
    asset = $AssetName
    size = (Get-Item -LiteralPath $Archive).Length
    sha256 = $Hash
    github_repository = "CaptainKeat/anime-watcher"
}
$Manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ReleaseRoot "release-manifest-v$Version.json") -Encoding UTF8
$Manifest | ConvertTo-Json
