param(
    [string]$Server = $env:DB_SERVER,
    [string]$Database = $env:DB_NAME,
    [string]$BackupDirectory = (Join-Path $PSScriptRoot "..\backups"),
    [int]$RetainDays = 30
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Server)) {
    throw "Set DB_SERVER or pass -Server."
}
if ([string]::IsNullOrWhiteSpace($Database)) {
    throw "Set DB_NAME or pass -Database."
}
if ($Database -notmatch '^[A-Za-z0-9_]+$') {
    throw "Database name may contain only letters, numbers, and underscores."
}
if ($RetainDays -lt 1) {
    throw "RetainDays must be at least 1."
}

$sqlcmd = Get-Command sqlcmd -ErrorAction SilentlyContinue
if (-not $sqlcmd) {
    throw "sqlcmd was not found. Install the Microsoft SQL Server command-line tools."
}

$BackupDirectory = [System.IO.Path]::GetFullPath($BackupDirectory)
New-Item -ItemType Directory -Path $BackupDirectory -Force | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = Join-Path $BackupDirectory "$Database-$timestamp.bak"
$sqlBackupPath = $backupPath.Replace("'", "''")
$sqlDatabase = $Database.Replace("]", "]]" )
$query = "BACKUP DATABASE [$sqlDatabase] TO DISK = N'$sqlBackupPath' WITH COPY_ONLY, CHECKSUM, STATS = 10; RESTORE VERIFYONLY FROM DISK = N'$sqlBackupPath' WITH CHECKSUM;"

$arguments = @("-b", "-S", $Server, "-d", "master", "-Q", $query, "-W")
$windowsAuth = [string]::IsNullOrWhiteSpace($env:DB_WINDOWS_AUTH) -or
    $env:DB_WINDOWS_AUTH -match '^(1|true|yes|on)$'
if (-not $windowsAuth) {
    if ([string]::IsNullOrWhiteSpace($env:DB_USER) -or [string]::IsNullOrWhiteSpace($env:DB_PASSWORD)) {
        throw "Set DB_USER and DB_PASSWORD for SQL authentication, or set DB_WINDOWS_AUTH=true."
    }
    $arguments += @("-U", $env:DB_USER)
    $env:SQLCMDPASSWORD = $env:DB_PASSWORD
}

try {
    & $sqlcmd.Source @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "sqlcmd failed with exit code $LASTEXITCODE."
    }
    if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
        throw "SQL Server reported success but the backup file is missing: $backupPath"
    }
    if ((Get-Item -LiteralPath $backupPath).Length -le 0) {
        throw "The backup file is empty: $backupPath"
    }
    Write-Output "Backup and RESTORE VERIFYONLY succeeded: $backupPath"
}
finally {
    if (Test-Path Env:\SQLCMDPASSWORD) {
        Remove-Item Env:\SQLCMDPASSWORD
    }
}

$cutoff = (Get-Date).AddDays(-$RetainDays)
Get-ChildItem -LiteralPath $BackupDirectory -Filter "$Database-*.bak" -File |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    Remove-Item -Force
