# install_autostart.ps1 - start JARVIS 30s after logon via Task Scheduler.
#
# Task Scheduler (not the Startup folder) because we need a delay so the network
# stack and audio devices are up first. Runs as the current user WITHOUT admin.
# Idempotent: re-running updates the task rather than duplicating it.
#
# Usage (from the JARVIS install folder):
#     powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1
#     # optional: point at the exe and/or LibreHardwareMonitor explicitly
#     .\install_autostart.ps1 -ExePath "D:\JARVIS\dist\JARVIS\JARVIS.exe" -LhmPath "C:\Tools\LibreHardwareMonitor.exe"

param(
    [string]$ExePath = (Join-Path $PSScriptRoot "dist\JARVIS\JARVIS.exe"),
    [string]$LhmPath = ""
)

if (-not (Test-Path $ExePath)) {
    Write-Error "JARVIS exe not found at: $ExePath  (build it first, or pass -ExePath)"
    exit 1
}
$workDir = Split-Path $ExePath

# This machine denies Register-ScheduledTask to non-admins (Access is denied /
# 0x80070005), and the LHM task needs admin regardless. Require elevation.
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "Not running as Administrator. Right-click PowerShell -> 'Run as administrator', then re-run this script. (Registering scheduled tasks here needs elevation.)"
    exit 1
}

# JARVIS: at logon + 30s, current user, runs un-elevated, survive battery
$action = New-ScheduledTaskAction -Execute $ExePath -WorkingDirectory $workDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$trigger.Delay = "PT30S"
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 3
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
try {
    Register-ScheduledTask -TaskName "JARVIS" -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
    Write-Host "[OK] Registered task 'JARVIS' (logon + 30s)."
} catch {
    Write-Error "Failed to register 'JARVIS': $($_.Exception.Message)"
    exit 1
}

# LibreHardwareMonitor (optional): at logon + 10s, WITH admin, for CPU temp
if ([string]::IsNullOrWhiteSpace($LhmPath)) {
    foreach ($p in @(
        (Join-Path $PSScriptRoot "tools\LibreHardwareMonitor\LibreHardwareMonitor.exe"),
        "C:\Program Files\LibreHardwareMonitor\LibreHardwareMonitor.exe",
        "C:\Program Files (x86)\LibreHardwareMonitor\LibreHardwareMonitor.exe")) {
        if (Test-Path $p) { $LhmPath = $p; break }
    }
}
if (-not [string]::IsNullOrWhiteSpace($LhmPath) -and (Test-Path $LhmPath)) {
    $la = New-ScheduledTaskAction -Execute $LhmPath -WorkingDirectory (Split-Path $LhmPath)
    $lt = New-ScheduledTaskTrigger -AtLogOn
    $lt.Delay = "PT10S"
    $ls = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    $lp = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    try {
        Register-ScheduledTask -TaskName "JARVIS-LHM" -Action $la -Trigger $lt `
            -Settings $ls -Principal $lp -Force -ErrorAction Stop | Out-Null
        Write-Host "[OK] Registered task 'JARVIS-LHM' (logon + 10s, admin) for CPU temperature."
    } catch {
        Write-Warning "Could not register 'JARVIS-LHM': $($_.Exception.Message)"
    }
} else {
    Write-Host "[skip] LibreHardwareMonitor not found - CPU CORE temp will show N/A."
    Write-Host "       Install it, then re-run this script (or pass -LhmPath) to enable CPU temp."
}

Write-Host ""
Write-Host "Done. Reboot to test: JARVIS should appear in the tray about 30s after logon."
