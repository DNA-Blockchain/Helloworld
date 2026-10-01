# aws_backup_setup.ps1
# =====================
# Provisions a private S3 bucket for already-encrypted backups. It does not
# create IAM users or access keys. Use separate AWS IAM Identity Center (SSO)
# profiles for administration and narrowly scoped backup access.
#
# Creates, only after exact-name confirmation:
#   - one private, versioned S3 bucket
#   - S3-managed encryption and a TLS-only bucket policy
#   - a lifecycle rule for the configured retention period
#
# It never uploads data unless -EnableOffsite is supplied and confirmed in a
# second prompt. It never stores AWS credentials in project files.
#
# Before running, configure:
#   - AdminProfile: short-lived SSO role allowed to create/configure this bucket
#   - BackupProfile: a different short-lived SSO role granted only
#     s3:PutObject/s3:GetObject under the prefix and s3:ListBucket for that
#     prefix. This script does not grant or broaden that role's permissions.
#
# Usage:
#   .\aws_backup_setup.ps1 -AdminProfile aws-admin -BackupProfile network-os-backup
#   .\aws_backup_setup.ps1 -AdminProfile aws-admin -BackupProfile network-os-backup -EnableOffsite
#
# This creates billable AWS resources when confirmed. Check current S3 pricing:
# https://aws.amazon.com/s3/pricing/

param(
    [string]$Region = "us-east-2",
    [string]$BucketName = "network-os-backups-" + -join ((1..8) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) }),
    [Parameter(Mandatory = $true)]
    [string]$AdminProfile,
    [Parameter(Mandatory = $true)]
    [string]$BackupProfile,
    [string]$Prefix = "network-os/",
    [ValidateRange(7, 365)]
    [int]$ExpireDays = 35,
    [switch]$EnableOffsite
)

$ErrorActionPreference = "Stop"

function Get-SsoRoleIdentity([string]$Profile) {
    $output = & aws.exe sts get-caller-identity --profile $Profile --output json
    if ($LASTEXITCODE -ne 0) {
        throw "Could not resolve AWS SSO identity for profile '$Profile'. Run aws sso login --profile $Profile first."
    }
    $identity = ($output -join "`n") | ConvertFrom-Json
    if ($identity.Arn -notmatch ":assumed-role/") {
        throw "Profile '$Profile' is not using a short-lived assumed role; refusing static IAM-user credentials."
    }
    return $identity
}

if (-not (Get-Command aws.exe -ErrorAction SilentlyContinue)) {
    throw "AWS CLI v2 was not found on PATH."
}
if ($AdminProfile -eq $BackupProfile) {
    throw "Use distinct admin and backup SSO profiles."
}

$adminIdentity = Get-SsoRoleIdentity $AdminProfile
$backupIdentity = Get-SsoRoleIdentity $BackupProfile
if ($adminIdentity.Arn -eq $backupIdentity.Arn) {
    throw "Admin and backup profiles resolved to the same role identity."
}
$Prefix = $Prefix.Trim("/") + "/"
$bucketArn = "arn:aws:s3:::$BucketName"
$objectsArn = "$bucketArn/*"
$prefixObjectsArn = "$bucketArn/$Prefix*"
$tempRoot = Join-Path $env:TEMP ("network-os-aws-setup-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null

try {
    Write-Host "AWS backup resources to be created:"
    Write-Host "  Bucket:       $BucketName"
    Write-Host "  Region:       $Region"
    Write-Host "  Prefix:       $Prefix"
    Write-Host "  Expiration:   $ExpireDays days (including old versions per lifecycle)"
    Write-Host "  Admin role:   $($adminIdentity.Arn)"
    Write-Host "  Backup role:  $($backupIdentity.Arn)"
    Write-Host "  Credentials:  short-lived SSO; no IAM user/access key will be created"
    Write-Host "  Data upload:  $(if ($EnableOffsite) { 'only after a separate confirmation' } else { 'disabled by this run' })"
    Write-Host "  Cost:         S3 storage, requests, and data transfer are billable; estimate from your actual backup size and current regional prices."
    if ((Read-Host "Type the exact bucket name '$BucketName' to create these resources") -cne $BucketName) {
        Write-Host "Cancelled; no AWS resources created."
        exit 1
    }

    $adminArgs = @("--profile", $AdminProfile)
    if ($Region -eq "us-east-1") {
        & aws.exe s3api create-bucket --bucket $BucketName --region $Region @adminArgs | Out-Null
    } else {
        & aws.exe s3api create-bucket --bucket $BucketName --region $Region `
            --create-bucket-configuration "LocationConstraint=$Region" @adminArgs | Out-Null
    }
    if ($LASTEXITCODE -ne 0) { throw "S3 bucket creation failed." }

    & aws.exe s3api put-public-access-block --bucket $BucketName --region $Region @adminArgs `
        --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
    if ($LASTEXITCODE -ne 0) { throw "Could not enable S3 Block Public Access." }
    & aws.exe s3api put-bucket-versioning --bucket $BucketName --region $Region @adminArgs `
        --versioning-configuration Status=Enabled
    if ($LASTEXITCODE -ne 0) { throw "Could not enable S3 versioning." }

    @{
        Rules = @(@{
            ApplyServerSideEncryptionByDefault = @{ SSEAlgorithm = "AES256" }
        })
    } | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $tempRoot "encryption.json") -Encoding ascii
    & aws.exe s3api put-bucket-encryption --bucket $BucketName --region $Region @adminArgs `
        --server-side-encryption-configuration "file://$(Join-Path $tempRoot 'encryption.json')"
    if ($LASTEXITCODE -ne 0) { throw "Could not configure default bucket encryption." }

    @{
        Version = "2012-10-17"
        Statement = @(@{
            Sid = "DenyInsecureTransport"
            Effect = "Deny"
            Principal = "*"
            Action = "s3:*"
            Resource = @($bucketArn, $objectsArn)
            Condition = @{ Bool = @{ "aws:SecureTransport" = "false" } }
        })
    } | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $tempRoot "bucket-policy.json") -Encoding ascii
    & aws.exe s3api put-bucket-policy --bucket $BucketName --region $Region @adminArgs `
        --policy "file://$(Join-Path $tempRoot 'bucket-policy.json')"
    if ($LASTEXITCODE -ne 0) { throw "Could not configure the TLS-only bucket policy." }

    @{
        Rules = @(
            @{
                ID = "expire-current-backups"
                Status = "Enabled"
                Filter = @{ Prefix = "${Prefix}vault/" }
                Expiration = @{ Days = $ExpireDays }
            },
            @{
                ID = "expire-old-versions"
                Status = "Enabled"
                Filter = @{ Prefix = $Prefix }
                NoncurrentVersionExpiration = @{ NoncurrentDays = 7 }
                AbortIncompleteMultipartUpload = @{ DaysAfterInitiation = 1 }
                Expiration = @{ ExpiredObjectDeleteMarker = $true }
            }
        )
    } | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $tempRoot "lifecycle.json") -Encoding ascii
    & aws.exe s3api put-bucket-lifecycle-configuration --bucket $BucketName --region $Region @adminArgs `
        --lifecycle-configuration "file://$(Join-Path $tempRoot 'lifecycle.json')"
    if ($LASTEXITCODE -ne 0) { throw "Could not configure S3 lifecycle retention." }

    Write-Host "Bucket configuration completed. No IAM permissions were changed."
    Write-Host "The backup SSO role must be separately granted access only to $prefixObjectsArn and list access under $Prefix."
    if ($EnableOffsite) {
        if ((Read-Host "Type UPLOAD-ENCRYPTED-BACKUPS to enable off-site backup uploads") -cne "UPLOAD-ENCRYPTED-BACKUPS") {
            Write-Host "Bucket created; local off-site configuration was not changed and no backup data was uploaded."
            exit 0
        }
        python "$PSScriptRoot\offsite_s3.py" configure --bucket $BucketName --region $Region `
            --profile $BackupProfile --prefix $Prefix
        if ($LASTEXITCODE -ne 0) { throw "Could not configure the local S3 backup destination." }
        Write-Host "Off-site destination configured. This setup did not upload a backup; run backup.py run only after reviewing the destination."
    }
} finally {
    Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
