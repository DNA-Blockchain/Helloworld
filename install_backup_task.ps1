# ============================================================================
#  SPDX-License-Identifier: UPL-1.0
#
#  Copyright (c) 2026 Chase Allen Ringquist
#
#  This file is part of an operating system, software, and network Work
#  conceived and authored by Chase Allen Ringquist. The Author retains
#  copyright and authorship. Use of this file is licensed as follows.
#
#  ----------------------------------------------------------------------------
#  The Universal Permissive License (UPL), Version 1.0
#
#  Subject to the condition set forth below, permission is hereby granted to
#  any person obtaining a copy of this software, associated documentation
#  and/or data (collectively the "Software"), free of charge and under any
#  and all copyright rights in the Software, and any and all patent rights
#  owned or freely licensable by each licensor hereunder covering either
#  (i) the unmodified Software as contributed to or provided by such
#  licensor, or (ii) the Larger Works (as defined below), to deal in both
#
#  (a) the Software, and
#
#  (b) any piece of software and/or hardware listed in the lrgrwrks.txt file
#  if one is included with the Software (each a "Larger Work" to which the
#  Software is contributed by such licensors),
#
#  without restriction, including without limitation the rights to copy,
#  create derivative works of, display, perform, and distribute the Software
#  and make, use, sell, offer for sale, import, export, have made, and have
#  sold the Software and the Larger Work(s), and to sublicense the foregoing
#  rights on either these or other terms.
#
#  This license is subject to the following condition:
#
#  The above copyright notice and either this complete permission notice or
#  at a minimum a reference to the UPL must be included in all copies or
#  substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
#  ----------------------------------------------------------------------------
#
#  Do not remove or alter this notice or any record of origin.
#  See NOTICE.md in the project root for authorship and ownership terms.
#
#  Contact:  ringquistchase@gmail.com  |  (918) 845-0940
#            Bixby, OK, United States
# ============================================================================

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
