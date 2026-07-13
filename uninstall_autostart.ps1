# uninstall_autostart.ps1 - remove the JARVIS (and JARVIS-LHM) logon tasks.
#
# Usage:
#     powershell -ExecutionPolicy Bypass -File .\uninstall_autostart.ps1

foreach ($name in @("JARVIS", "JARVIS-LHM")) {
    try {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "[OK] Removed task '$name'."
        } else {
            Write-Host "[skip] Task '$name' not found."
        }
    } catch {
        Write-Host "[warn] Could not remove '$name': $_"
    }
}
