# install_backup_task.ps1
# ========================
# Registers the nightly encrypted backup as a Task Scheduler task for the
# current user. It runs the same command you can run by hand:
#
#     python backup.py run --apply-retention --audit system_audit.jsonl
#
# daily at 02:30, and as soon as possible afterwards if the PC was off or
# asleep then. It runs as you (only while you're signed in), because the
# backup passphrase is DPAPI-protected for your Windows account.
#
# Run `python backup.py init` first, once, to set the passphrase.
#
# Usage (admin NOT required):
#     .\install_backup_task.ps1                 # install / update
#     .\install_backup_task.ps1 -At 03:15       # different time
#     .\install_backup_task.ps1 -Remove         # uninstall
#
# Afterwards:
#     Start-ScheduledTask -TaskName "NetworkOSNightlyBackup"      # run one now
#     Get-ScheduledTaskInfo -TaskName "NetworkOSNightlyBackup"    # last run / result

param(
    [string]$At = "02:30",
    [string]$ProjectRoot = $PSScriptRoot,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$TaskName = "NetworkOSNightlyBackup"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed $TaskName (existing backups are untouched)."
    exit 0
}

$ProjectDir = $PSScriptRoot
$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    Write-Host "[ERROR] python was not found on PATH. Install it first." -ForegroundColor Red
    exit 1
}
$KeyFile = Join-Path $env:APPDATA "network-os\backup_passphrase.dpapi"
if (-not (Test-Path $KeyFile) -and -not $env:NETWORK_OS_BACKUP_PASSPHRASE) {
    Write-Host "[ERROR] No backup passphrase yet. Run:  python backup.py init" -ForegroundColor Red
    exit 1
}

$LogPath = Join-Path $ProjectDir "backup_task.log"
$Action = New-ScheduledTaskAction -Execute "cmd.exe" -WorkingDirectory $ProjectDir `
    -Argument "/c `"`"$($PythonCmd.Source)`" backup.py --root ""$ProjectRoot"" run --apply-retention --audit ""$ProjectRoot\system_audit.jsonl"" >> `"$LogPath`" 2>&1`""
$Trigger = New-ScheduledTaskTrigger -Daily -At $At
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10)
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Principal $Principal -Description "Encrypted nightly backup of network-os-project state (backup.py)" -Force | Out-Null
Write-Host "Installed ${TaskName}: daily at $At, output appended to $LogPath"
