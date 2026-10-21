param(
    [Parameter(Mandatory)][string]$GameDirectory,
    [Parameter(Mandatory)][string]$SourceModDirectory,
    [string]$Compiler='zig',
    [switch]$UsePrebuiltNative
)
$ErrorActionPreference='Stop'
$game=[IO.Path]::GetFullPath($GameDirectory)
$source=[IO.Path]::GetFullPath($SourceModDirectory)
$output=Join-Path $PSScriptRoot 'build\hoi4-earth-map-flat'
$mod=Join-Path $output 'mod'
$expectedHash='7dc947be34970da1e1c787bcddbe7f62b610ff258aebf8f06aa8b348f3a031d5'
if (-not (Test-Path -LiteralPath (Join-Path $source 'map\provinces.bmp'))) {throw 'SourceModDirectory must contain the original Earth Map 2x mod.'}
if (-not (Test-Path -LiteralPath (Join-Path $source 'gfx\FX\standardfuncsgfx.fxh'))) {throw 'Missing original Earth Map 2x shader includes.'}
if ((Get-FileHash (Join-Path $game 'hoi4.exe') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {throw 'Only HOI4 1.19.3.0 is supported.'}
if (Get-Process -Name hoi4 -ErrorAction SilentlyContinue) {throw 'Exit HOI4 before rebuilding.'}

$map=[IO.File]::OpenRead((Join-Path $source 'map\provinces.bmp'))
try {
    $reader=[IO.BinaryReader]::new($map)
    $map.Position=18
    $width=$reader.ReadInt32()
    $height=[Math]::Abs($reader.ReadInt32())
    if ($width -ne 10240 -or $height -ne 5120) {throw "Unexpected map size $width x $height (expected 10240 x 5120)."}
} finally {$map.Dispose()}

New-Item -ItemType Directory -Force -Path $mod | Out-Null
& robocopy.exe $source $mod /E /R:0 /W:0 /NFL /NDL /NJH /NJS /NC /NS /NP
if ($LASTEXITCODE -gt 7) {throw "Earth Map 2x asset copy failed: $LASTEXITCODE"}

# The flat version resolves original engine materials. Ensure no leftover
# generated spherical shaders, orbital camera file, or polar cubemap is loaded.
$sphereFiles=@(
    'gfx\FX\hoi4_globe.fxh','gfx\FX\pdxmap.shader','gfx\FX\pdxwater.shader',
    'gfx\FX\border.shader','gfx\FX\mapname.shader','gfx\FX\maparrow.shader',
    'gfx\FX\river.shader','gfx\FX\strait.shader','gfx\FX\traderoute.shader',
    'gfx\FX\tree.shader','gfx\FX\pdxmesh.shader','gfx\FX\particle.shader',
    'gfx\models\supply\railroad.shader','gfx\FX\sky.shader',
    'common\defines\zz_globe_camera.lua','map\terrain\reflection.dds'
)
foreach($rel in $sphereFiles) {
    if(Test-Path -LiteralPath (Join-Path $source $rel)) {throw "Source contains a globe-generated file: $rel. Supply the original flat Earth Map 2x files."}
    $stale=Join-Path $mod $rel
    if(Test-Path -LiteralPath $stale) {Remove-Item -LiteralPath $stale -Force}
}
$descriptor=Join-Path $mod 'descriptor.mod'
$body=Get-Content -LiteralPath $descriptor -Raw
$body=[regex]::Replace($body,'(?m)^name=.*$','name="Earth Map 2x - Flat Edition"')
$body=[regex]::Replace($body,'(?m)^version=.*$','version="0.5-flat"')
[IO.File]::WriteAllText($descriptor,$body,[Text.UTF8Encoding]::new($false))

if (-not $UsePrebuiltNative) {
    & (Join-Path $PSScriptRoot 'Build-Native.ps1') -Compiler $Compiler -RunTests
}

$binaries=@('flat_launcher.exe','hoi4_flat_native.dll')
$hashes=@()
foreach($file in $binaries) {
    $path=Join-Path (Join-Path $output 'native') $file
    if(-not(Test-Path -LiteralPath $path)) {throw "Missing native binary $file"}
    $hashes+=@{path="native/$file";sha256=(Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()}
}
$manifest=@{
    edition='Earth Map 2x - Flat Edition'
    version='0.5-flat'
    projection='stock flat HOI4 renderer'
    width=$width
    height=$height
    game_sha256=$expectedHash
    atlas_tile_pixels=512
    atlas_entries=200
    atlas_capacity=256
    globe_hooks=0
    globe_shaders=0
    scratch_capacity_bytes=268435456
    native_binaries=$hashes
    original_mod_assets='Earth Map 2x source provided locally by user'
    output_game_files_modified=$false
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $output 'build-manifest.json') -Encoding UTF8
Write-Output "Flat Earth 2x build complete: $output"
