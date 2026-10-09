param([Parameter(Mandatory)][string]$GameDirectory,[string]$Python='python',[string]$Compiler='zig')
$ErrorActionPreference='Stop'
$taskGame=[IO.Path]::GetFullPath($GameDirectory)
if (-not (Test-Path -LiteralPath (Join-Path $taskGame 'hoi4.exe'))) { throw 'GameDirectory must contain hoi4.exe.' }
if (@(Get-Process -Name hoi4 -ErrorAction SilentlyContinue | Where-Object Path -eq (Join-Path $PSScriptRoot 'work\game\hoi4.exe')).Count) { throw "Exit this repository's globe process before rebuilding." }
$taskOldGame=$env:HOI4_GAME_DIR
$taskOldBytecode=$env:PYTHONDONTWRITEBYTECODE
$env:HOI4_GAME_DIR=$taskGame
$env:PYTHONDONTWRITEBYTECODE='1'
function Invoke-GlobePython([string]$Script,[string[]]$Arguments=@()) {
    & $Python (Join-Path $PSScriptRoot "scripts\$Script") @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Script failed ($LASTEXITCODE)." }
}
try {
    Invoke-GlobePython 'build_globe_mod.py'
    Invoke-GlobePython 'globe_dem_import.py'
    Invoke-GlobePython 'integrate_globe_terrain.py'
    Invoke-GlobePython 'globe_backdrop_import.py'
    Invoke-GlobePython 'integrate_globe_backdrop.py'
    & (Join-Path $PSScriptRoot 'Build-Native.ps1') -Compiler $Compiler -RunTests
    Invoke-GlobePython 'finish_build.py'
    Invoke-GlobePython 'native_bridge_checks.py'
    Invoke-GlobePython 'projection_v3_math.py'
    Invoke-GlobePython 'validate_globe_shaders.py'
} finally {
    $env:HOI4_GAME_DIR=$taskOldGame
    $env:PYTHONDONTWRITEBYTECODE=$taskOldBytecode
}
Write-Output 'Build complete. Use Launch-Globe.ps1 -GameDirectory with the same installation.'
