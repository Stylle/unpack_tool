param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ReleaseName = "unpack_tool-v$Version-windows-x64"
$StageDir = Join-Path $ProjectRoot "dist\$ReleaseName"
$ArchivePath = Join-Path $ProjectRoot "dist\$ReleaseName.zip"

Set-Location -LiteralPath $ProjectRoot
$DeclaredVersion = python -c "from unpack_tool import __version__; print(__version__)"
if ($DeclaredVersion.Trim() -ne $Version) {
    throw "Version mismatch: package=$DeclaredVersion, requested=$Version"
}
python -m pytest -q tests --basetemp .test-tmp -p no:cacheprovider
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed with exit code $LASTEXITCODE"
}
python -m PyInstaller --noconfirm --clean --onefile --windowed --name unpack_tool torrent_manager.py
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if (Test-Path -LiteralPath $StageDir) {
    Remove-Item -LiteralPath $StageDir -Recurse -Force
}
New-Item -ItemType Directory -Path $StageDir | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'dist\unpack_tool.exe') -Destination $StageDir
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'links') -Destination $StageDir -Recurse
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'README.md') -Destination $StageDir
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'CHANGELOG.md') -Destination $StageDir
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'LICENSE') -Destination $StageDir

if (Test-Path -LiteralPath $ArchivePath) {
    Remove-Item -LiteralPath $ArchivePath -Force
}
Compress-Archive -LiteralPath $StageDir -DestinationPath $ArchivePath -CompressionLevel Optimal
Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256 | Format-List
Write-Output "Release artifact: $ArchivePath"
