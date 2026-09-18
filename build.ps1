$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot
$env:PYTHONPATH = "$ProjectRoot\vendor"

python -m PyInstaller --noconfirm --clean --windowed --name "Anime Watcher" `
  --paths "$ProjectRoot\vendor" `
  --collect-all customtkinter `
  --hidden-import PIL._tkinter_finder `
  --icon "$ProjectRoot\assets\anime_watcher.ico" `
  --add-data "$ProjectRoot\assets;assets" `
  --distpath "$ProjectRoot\dist" `
  --workpath "$ProjectRoot\build" `
  --specpath "$ProjectRoot\build" `
  "$ProjectRoot\app.py"

Write-Host "Built: $ProjectRoot\dist\Anime Watcher\Anime Watcher.exe"
