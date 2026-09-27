param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ProjectRoot,

    [ValidatePattern('^(?:[01]\d|2[0-3]):[0-5]\d$')]
    [string]$ScheduleAt = '02:00',

    [string]$TaskName = 'NetworkOSNightlyBackup'
)

$ErrorActionPreference = 'Stop'
$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$backupScript = Join-Path $resolvedRoot 'backup.py'
$healthScript = Join-Path $resolvedRoot 'backup_health.py'

if (-not (Test-Path -LiteralPath $backupScript -PathType Leaf)) {
    throw "Backup script not found: $backupScript"
}
if (-not (Test-Path -LiteralPath $healthScript -PathType Leaf)) {
    throw "Backup health script not found: $healthScript"
}

$python = Get-Command python.exe -ErrorAction Stop
$action = New-ScheduledTaskAction `
    -Execute $python.Source `
    -Argument ('"{0}" run' -f $backupScript) `
    -WorkingDirectory $resolvedRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $ScheduleAt
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited
$task = Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description 'Creates and verifies a local-only Network OS project backup.' `
    -Force

python $backupScript init --project-root $resolvedRoot
if ($LASTEXITCODE -ne 0) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    throw 'Backup initialization failed; the scheduled task was removed.'
}

Write-Output "Installed scheduled task '$TaskName' at $ScheduleAt daily for $resolvedRoot."
Write-Warning 'Archives include private keys and credentials, are not encrypted, and remain local-only.'
