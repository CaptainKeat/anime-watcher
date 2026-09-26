$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot
$env:PYTHONPATH = "$ProjectRoot\vendor"
$PythonExe = (Get-Command python).Source

# PyInstaller resolves native dependencies from PATH. Keep unrelated developer
# toolchains (for example Poppler's ICU DLLs) out of the packaged Qt runtime.
$OriginalPath = $env:PATH
$SafePath = @(
  (Split-Path -Parent $PythonExe),
  "$ProjectRoot\vendor\bin",
  "$env:SystemRoot\System32",
  "$env:SystemRoot",
  "$env:SystemRoot\System32\Wbem"
) | Select-Object -Unique
$env:PATH = $SafePath -join ";"

try {
  & $PythonExe -m PyInstaller --noconfirm --clean --windowed --name "Anime Watcher" `
    --paths "$ProjectRoot\vendor" `
    --exclude-module customtkinter `
    --icon "$ProjectRoot\assets\anime_watcher.ico" `
    --add-data "$ProjectRoot\assets;assets" `
    --add-binary "$ProjectRoot\third_party\libass\bin;libass" `
    --add-data "$ProjectRoot\third_party\libass\licenses;licenses\libass" `
    --add-data "$ProjectRoot\third_party\libass\manifest.json;licenses\libass" `
    --distpath "$ProjectRoot\dist" `
    --workpath "$ProjectRoot\build" `
    --specpath "$ProjectRoot\build" `
    "$ProjectRoot\app.py"
  if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
  }
} finally {
  $env:PATH = $OriginalPath
}

$Executable = "$ProjectRoot\dist\Anime Watcher\Anime Watcher.exe"
$InternalRoot = "$ProjectRoot\dist\Anime Watcher\_internal"
if (Test-Path "$InternalRoot\icuuc.dll") {
  throw "Unexpected ICU DLL was bundled. Build environment contains a foreign native runtime."
}
if (-not (Test-Path "$InternalRoot\libass\libass-9.dll")) {
  throw "The packaged libass subtitle runtime is missing."
}
if (Test-Path "$InternalRoot\libass\Qt6Core.dll") {
  throw "The isolated libass directory contains an unexpected Qt runtime."
}

$AssFixture = "$ProjectRoot\tests\fixtures\libass-smoke.ass"
# Start-Process joins ArgumentList values into a command line. Preserve quotes
# around the fixture because the project path itself contains spaces.
$AssSmoke = Start-Process -FilePath $Executable `
  -ArgumentList "--ass-smoke `"$AssFixture`"" `
  -WindowStyle Hidden -PassThru
try {
  Wait-Process -Id $AssSmoke.Id -Timeout 20 -ErrorAction Stop
} catch {
  if (-not $AssSmoke.HasExited) {
    Stop-Process -Id $AssSmoke.Id
  }
  throw "Packaged libass rendering smoke test timed out."
}
$AssSmoke.Refresh()
if ($AssSmoke.ExitCode -ne 0) {
  throw "Packaged libass rendering smoke test failed with exit code $($AssSmoke.ExitCode)."
}

# A windowed PyInstaller import failure stays alive behind an error dialog, so
# merely checking the process is insufficient. Verify the dialog title too.
$PreviousQtPlatform = $env:QT_QPA_PLATFORM
$PreviousAppData = $env:APPDATA
$SmokeProcess = $null
try {
  $env:QT_QPA_PLATFORM = "offscreen"
  $env:APPDATA = Join-Path $env:TEMP "AnimeWatcherBuildSmoke-$PID"
  $SmokeProcess = Start-Process -FilePath $Executable -WindowStyle Hidden -PassThru
  Start-Sleep -Seconds 4
  $SmokeProcess.Refresh()
  if ($SmokeProcess.HasExited) {
    throw "Packaged application exited during its startup smoke test."
  }
  if ($SmokeProcess.MainWindowTitle -like "*Unhandled exception*") {
    throw "Packaged application opened an unhandled-exception dialog during startup."
  }
} finally {
  if ($SmokeProcess -and -not $SmokeProcess.HasExited) {
    Stop-Process -Id $SmokeProcess.Id
    Wait-Process -Id $SmokeProcess.Id -ErrorAction SilentlyContinue
  }
  $env:QT_QPA_PLATFORM = $PreviousQtPlatform
  $env:APPDATA = $PreviousAppData
}

Write-Host "Built and smoke-tested: $Executable"
