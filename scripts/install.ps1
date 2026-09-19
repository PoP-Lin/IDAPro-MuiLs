[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $PluginsDirectory
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SourcePackage = Join-Path $ProjectRoot "src\ida_modern_ui"
$SourceLoader = Join-Path $ProjectRoot "ida_modern_ui_loader.py"
$DestinationRoot = [IO.Path]::GetFullPath($PluginsDirectory)
$DestinationPackage = Join-Path $DestinationRoot "ida_modern_ui"
$DestinationLoader = Join-Path $DestinationRoot "ida_modern_ui_loader.py"
$Token = [Guid]::NewGuid().ToString("N")
$StagingRoot = Join-Path $DestinationRoot ".ida_modern_ui.install.stage.$Token"
$BackupRoot = Join-Path $DestinationRoot ".ida_modern_ui.install.backup.$Token"
$StagedPackage = Join-Path $StagingRoot "ida_modern_ui"
$StagedLoader = Join-Path $StagingRoot "ida_modern_ui_loader.py"
$BackupPackage = Join-Path $BackupRoot "ida_modern_ui"
$BackupLoader = Join-Path $BackupRoot "ida_modern_ui_loader.py"

if (-not (Test-Path -LiteralPath $SourcePackage -PathType Container)) {
    throw "Package source was not found: $SourcePackage"
}
if (-not (Test-Path -LiteralPath $SourceLoader -PathType Leaf)) {
    throw "Plugin loader was not found: $SourceLoader"
}
$SourcePackageItem = Get-Item -LiteralPath $SourcePackage -Force
$SourceLoaderItem = Get-Item -LiteralPath $SourceLoader -Force
if (($SourcePackageItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "Package source root is a reparse point: $SourcePackage"
}
if (($SourceLoaderItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "Plugin loader is a reparse point: $SourceLoader"
}

New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null
$DestinationRoot = (Resolve-Path -LiteralPath $DestinationRoot).Path.TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
)
$RootPrefix = $DestinationRoot + [IO.Path]::DirectorySeparatorChar

function Assert-DirectChild([string] $Path, [string] $ExpectedName) {
    $FullPath = [IO.Path]::GetFullPath($Path)
    $Parent = [IO.Path]::GetDirectoryName($FullPath).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    if (-not $Parent.Equals($DestinationRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to update a path outside the plugins directory: $FullPath"
    }
    if ([IO.Path]::GetFileName($FullPath) -ne $ExpectedName) {
        throw "Unexpected destination name: $FullPath"
    }
    return $FullPath
}

$DestinationPackage = Assert-DirectChild $DestinationPackage "ida_modern_ui"
$DestinationLoader = Assert-DirectChild $DestinationLoader "ida_modern_ui_loader.py"
$StagingRoot = Assert-DirectChild $StagingRoot ([IO.Path]::GetFileName($StagingRoot))
$BackupRoot = Assert-DirectChild $BackupRoot ([IO.Path]::GetFileName($BackupRoot))

$ReparsePoints = @(Get-ChildItem -LiteralPath $SourcePackage -Recurse -Force | Where-Object {
    ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
})
if ($ReparsePoints.Count -ne 0) {
    throw "Package source contains a reparse point: $($ReparsePoints[0].FullName)"
}

$SourcePackageRoot = [IO.Path]::GetFullPath($SourcePackage).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
)
$SourceFiles = @(Get-ChildItem -LiteralPath $SourcePackageRoot -Recurse -File -Force | Where-Object {
    $Relative = $_.FullName.Substring($SourcePackageRoot.Length + 1)
    $Parts = $Relative -split "[\\/]"
    -not ($Parts -contains "__pycache__") -and $_.Extension -notin @(".pyc", ".pyo")
})

$BackedUpPackage = $false
$BackedUpLoader = $false
$InstalledPackage = $false
$InstalledLoader = $false
$InstallSucceeded = $false

try {
    New-Item -ItemType Directory -Path $StagedPackage -Force | Out-Null
    New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

    foreach ($SourceFile in $SourceFiles) {
        $Relative = $SourceFile.FullName.Substring($SourcePackageRoot.Length + 1)
        $Target = [IO.Path]::GetFullPath((Join-Path $StagedPackage $Relative))
        $StagedPrefix = [IO.Path]::GetFullPath($StagedPackage).TrimEnd("\") + "\"
        if (-not $Target.StartsWith($StagedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing unsafe staged path: $Target"
        }
        $TargetParent = [IO.Path]::GetDirectoryName($Target)
        New-Item -ItemType Directory -Path $TargetParent -Force | Out-Null
        Copy-Item -LiteralPath $SourceFile.FullName -Destination $Target -Force
    }
    Copy-Item -LiteralPath $SourceLoader -Destination $StagedLoader -Force

    if (Test-Path -LiteralPath $DestinationPackage) {
        Move-Item -LiteralPath $DestinationPackage -Destination $BackupPackage
        $BackedUpPackage = $true
    }
    if (Test-Path -LiteralPath $DestinationLoader) {
        Move-Item -LiteralPath $DestinationLoader -Destination $BackupLoader
        $BackedUpLoader = $true
    }

    Move-Item -LiteralPath $StagedPackage -Destination $DestinationPackage
    $InstalledPackage = $true
    Move-Item -LiteralPath $StagedLoader -Destination $DestinationLoader
    $InstalledLoader = $true

    $InstalledFiles = @(Get-ChildItem -LiteralPath $DestinationPackage -Recurse -File -Force)
    if ($InstalledFiles.Count -ne $SourceFiles.Count) {
        throw "Installed package file count mismatch: expected $($SourceFiles.Count), got $($InstalledFiles.Count)"
    }
    foreach ($SourceFile in $SourceFiles) {
        $Relative = $SourceFile.FullName.Substring($SourcePackageRoot.Length + 1)
        $InstalledFile = Join-Path $DestinationPackage $Relative
        if (-not (Test-Path -LiteralPath $InstalledFile -PathType Leaf)) {
            throw "Installed package file is missing: $Relative"
        }
        $SourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SourceFile.FullName).Hash
        $InstalledHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $InstalledFile).Hash
        if ($SourceHash -ne $InstalledHash) {
            throw "Installed package hash mismatch: $Relative"
        }
    }
    $SourceLoaderHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SourceLoader).Hash
    $InstalledLoaderHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $DestinationLoader).Hash
    if ($SourceLoaderHash -ne $InstalledLoaderHash) {
        throw "Installed loader hash mismatch"
    }

    $InstallSucceeded = $true
}
catch {
    $InstallError = $_
    try {
        if ($InstalledLoader -and (Test-Path -LiteralPath $DestinationLoader)) {
            Remove-Item -LiteralPath $DestinationLoader -Force
        }
        if ($InstalledPackage -and (Test-Path -LiteralPath $DestinationPackage)) {
            Remove-Item -LiteralPath $DestinationPackage -Recurse -Force
        }
        if ($BackedUpPackage -and (Test-Path -LiteralPath $BackupPackage)) {
            Move-Item -LiteralPath $BackupPackage -Destination $DestinationPackage
        }
        if ($BackedUpLoader -and (Test-Path -LiteralPath $BackupLoader)) {
            Move-Item -LiteralPath $BackupLoader -Destination $DestinationLoader
        }
    }
    catch {
        throw "Installation failed and rollback was incomplete. Backup retained at '$BackupRoot'. Original error: $InstallError. Rollback error: $_"
    }
    throw $InstallError
}
finally {
    if (Test-Path -LiteralPath $StagingRoot) {
        Remove-Item -LiteralPath $StagingRoot -Recurse -Force
    }
    if ($InstallSucceeded -and (Test-Path -LiteralPath $BackupRoot)) {
        Remove-Item -LiteralPath $BackupRoot -Recurse -Force
    }
    elseif (-not $InstallSucceeded -and (Test-Path -LiteralPath $BackupRoot)) {
        $RemainingBackup = @(Get-ChildItem -LiteralPath $BackupRoot -Force)
        if ($RemainingBackup.Count -eq 0) {
            Remove-Item -LiteralPath $BackupRoot -Force
        }
    }
}

Write-Host "IDAPro-MuiLs installed and verified at: $DestinationRoot" -ForegroundColor Green
