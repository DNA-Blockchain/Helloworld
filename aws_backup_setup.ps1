# aws_backup_setup.ps1
# =====================
# Creates the AWS side of offsite_s3.py -- and nothing else. Review before
# running; it creates billable resources (see "Cost" below).
#
# WHAT IT CREATES
#   1. One private S3 bucket (default name network-os-backups-<random>):
#      - Block Public Access: all four settings on
#      - Versioning on, so an overwrite or delete keeps the previous copy
#      - Default encryption SSE-S3 (the backups are already client-side
#        encrypted; this is a second layer AWS manages)
#      - Bucket policy: refuse any request not over TLS
#      - Lifecycle: backups expire 35 days after upload (5 more than the
#        local 30), replaced/deleted versions 7 days later, stale delete
#        markers and incomplete uploads cleaned up
#   2. One IAM user, network-os-backup, allowed ONLY to put, get and list
#      objects under network-os/ in that bucket. No delete, no other
#      bucket, no other AWS service. Even if this PC is compromised, its
#      key can add backups but can't erase the off-site ones.
#   3. One access key for that user, written straight into the AWS CLI
#      profile "network-os-backup" on this PC (never printed).
#   Then it points offsite_s3.py at the bucket and runs a first sync.
#
# COST (S3 Standard, us-east-2, at today's ~2 MB per backup)
#   ~35 backups kept + a few days of old versions = well under 100 MB:
#   storage ~$0.002/month, requests (~3 per night) ~$0.001/month.
#   Uploads are free; restores download free within AWS's monthly free
#   data-transfer allowance. Grows with backup size: at 1 GB per backup,
#   roughly $0.80/month. IAM is free. Check current prices at
#   https://aws.amazon.com/s3/pricing/ before running.
#
# NEEDS
#   An AWS login with rights to create S3 buckets and IAM users (your
#   admin/root session). Sign in first:  aws login   (or aws configure sso)
#   The account ID is read only to display it; it isn't stored anywhere.
#
# Usage:
#   .\aws_backup_setup.ps1                                   # us-east-2 (Ohio), random bucket name
#   .\aws_backup_setup.ps1 -Region us-east-1 -BucketName my-name -AdminProfile default

param(
    [string]$Region = "us-east-2",
    [string]$BucketName = "network-os-backups-" + -join ((1..8) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) }),
    [string]$AdminProfile = "",
    [string]$BackupProfile = "network-os-backup",
    [string]$UserName = "network-os-backup",
    [string]$Prefix = "network-os/",
    [int]$ExpireDays = 35
)

$ErrorActionPreference = "Stop"
$Admin = @(); if ($AdminProfile) { $Admin = @("--profile", $AdminProfile) }
function Invoke-Aws { & aws.exe @args; if ($LASTEXITCODE -ne 0) { throw "aws $($args[0..1] -join ' ') failed" } }
$tmp = New-Item -ItemType Directory -Force (Join-Path $env:TEMP "network-os-aws-setup")

$who = Invoke-Aws sts get-caller-identity @Admin --output json | ConvertFrom-Json
Write-Host "Signed in as: $($who.Arn)"
Write-Host "Will create bucket '$BucketName' in $Region and IAM user '$UserName'."
if ((Read-Host "Type YES to continue") -ne "YES") { Write-Host "Cancelled; nothing created."; exit 1 }

# 1. bucket
if ($Region -eq "us-east-1") { Invoke-Aws s3api create-bucket --bucket $BucketName --region $Region @Admin | Out-Null }
else { Invoke-Aws s3api create-bucket --bucket $BucketName --region $Region --create-bucket-configuration "LocationConstraint=$Region" @Admin | Out-Null }
Invoke-Aws s3api put-public-access-block --bucket $BucketName --region $Region @Admin `
    --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
Invoke-Aws s3api put-bucket-versioning --bucket $BucketName --region $Region @Admin --versioning-configuration Status=Enabled
@{ Rules = @(@{ ApplyServerSideEncryptionByDefault = @{ SSEAlgorithm = "AES256" } }) } |
    ConvertTo-Json -Depth 8 | Set-Content "$tmp\encryption.json" -Encoding ascii
Invoke-Aws s3api put-bucket-encryption --bucket $BucketName --region $Region @Admin `
    --server-side-encryption-configuration "file://$tmp\encryption.json"

@{ Version = "2012-10-17"; Statement = @(@{
    Sid = "DenyInsecureTransport"; Effect = "Deny"; Principal = "*"; Action = "s3:*"
    Resource = @("arn:aws:s3:::$BucketName", "arn:aws:s3:::$BucketName/*")
    Condition = @{ Bool = @{ "aws:SecureTransport" = "false" } } }) } |
    ConvertTo-Json -Depth 8 | Set-Content "$tmp\bucket-policy.json" -Encoding ascii
Invoke-Aws s3api put-bucket-policy --bucket $BucketName --region $Region @Admin --policy "file://$tmp\bucket-policy.json"

@{ Rules = @(
    @{ ID = "expire-backups"; Status = "Enabled"; Filter = @{ Prefix = "${Prefix}vault/" }
       Expiration = @{ Days = $ExpireDays } },
    @{ ID = "clean-old-versions"; Status = "Enabled"; Filter = @{ Prefix = $Prefix }
       NoncurrentVersionExpiration = @{ NoncurrentDays = 7 }
       AbortIncompleteMultipartUpload = @{ DaysAfterInitiation = 1 }
       Expiration = @{ ExpiredObjectDeleteMarker = $true } }) } |
    ConvertTo-Json -Depth 8 | Set-Content "$tmp\lifecycle.json" -Encoding ascii
Invoke-Aws s3api put-bucket-lifecycle-configuration --bucket $BucketName --region $Region @Admin `
    --lifecycle-configuration "file://$tmp\lifecycle.json"
Write-Host "[1/3] bucket $BucketName ready"

# 2. least-privilege IAM user (no delete)
Invoke-Aws iam create-user --user-name $UserName @Admin | Out-Null
@{ Version = "2012-10-17"; Statement = @(
    @{ Sid = "PutGetBackups"; Effect = "Allow"; Action = @("s3:PutObject", "s3:GetObject")
       Resource = "arn:aws:s3:::$BucketName/$Prefix*" },
    @{ Sid = "ListBackups"; Effect = "Allow"; Action = "s3:ListBucket"; Resource = "arn:aws:s3:::$BucketName"
       Condition = @{ StringLike = @{ "s3:prefix" = @("$Prefix*") } } }) } |
    ConvertTo-Json -Depth 8 | Set-Content "$tmp\user-policy.json" -Encoding ascii
Invoke-Aws iam put-user-policy --user-name $UserName --policy-name network-os-backup-put-get-list @Admin `
    --policy-document "file://$tmp\user-policy.json"
Write-Host "[2/3] IAM user $UserName ready (put/get/list only)"

# 3. its access key, straight into a local CLI profile
$key = Invoke-Aws iam create-access-key --user-name $UserName @Admin --output json | ConvertFrom-Json
& aws.exe configure set aws_access_key_id $key.AccessKey.AccessKeyId --profile $BackupProfile
& aws.exe configure set aws_secret_access_key $key.AccessKey.SecretAccessKey --profile $BackupProfile
& aws.exe configure set region $Region --profile $BackupProfile
$key = $null
Remove-Item $tmp -Recurse -Force
Write-Host "[3/3] access key stored in AWS CLI profile '$BackupProfile'"

python "$PSScriptRoot\offsite_s3.py" configure --bucket $BucketName --region $Region --profile $BackupProfile
Write-Host "Waiting 15s for the new key to become active in IAM..."
Start-Sleep 15
python "$PSScriptRoot\offsite_s3.py" sync
Write-Host "Done. Nightly backups now also go to s3://$BucketName/$Prefix"
