# build.ps1 - package JARVIS as a --onedir Windows app.
#
# --onedir (NOT --onefile): QtWebEngine ships QtWebEngineProcess.exe plus a large
# resource bundle; onefile unpacks all of it to a temp dir on every launch (slow,
# fragile). Onedir starts fast and is easy to debug.
#
# Run from the repo root:
#     powershell -ExecutionPolicy Bypass -File .\build.ps1
# Output: dist\JARVIS\JARVIS.exe  (ship the whole dist\JARVIS folder)

$ErrorActionPreference = "Stop"
$pyi = Join-Path $PSScriptRoot ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $pyi)) {
    Write-Error "PyInstaller not found in .venv - run: pip install pyinstaller"
    exit 1
}

& $pyi --noconfirm --noconsole --onedir --name JARVIS `
    --icon config/jarvis.ico `
    --add-data "hud;hud" `
    --add-data "core/prompt.txt;core" `
    --add-data "config/jarvis.ico;config" `
    --add-data "dashboard/static;dashboard/static" `
    --collect-all PyQt6.QtWebEngineCore `
    --collect-all openwakeword `
    --collect-all onnxruntime `
    main.py

Write-Host ""
Write-Host "Built: dist\JARVIS\JARVIS.exe"
Write-Host "Keys/memory/logs live in %APPDATA%\JARVIS (safe to delete and rebuild dist\)."
