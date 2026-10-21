param([string]$Compiler='zig',[switch]$RunTests)
$ErrorActionPreference='Stop'
$taskCompiler=(Get-Command $Compiler -ErrorAction Stop).Source
$taskSource=Join-Path $PSScriptRoot 'native\src'
$taskOutput=Join-Path $PSScriptRoot 'build\hoi4-earth-map-flat\native'
$taskTests=Join-Path $PSScriptRoot 'work\native-tests'
New-Item -ItemType Directory -Path $taskOutput,$taskTests -Force | Out-Null
if (@(Get-Process -Name hoi4 -ErrorAction SilentlyContinue | Where-Object Path -eq (Join-Path $PSScriptRoot 'work\game\hoi4.exe')).Count) { throw "Exit this repository's globe process before rebuilding its native files." }
function Invoke-GlobeCompiler([string[]]$Arguments) {
    & $taskCompiler @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Native compilation failed ($LASTEXITCODE)." }
}
Push-Location $taskSource
try {
    $taskCommon=@('cc','-O2','-std=c11','-Wall','-Wextra','-Werror','-ffp-contract=off',"-ffile-prefix-map=$taskSource=.","-fdebug-prefix-map=$taskSource=.")
    Invoke-GlobeCompiler ($taskCommon+@('-shared','flat_native.c','-o',(Join-Path $taskOutput 'hoi4_flat_native.dll')))
    Invoke-GlobeCompiler ($taskCommon+@('-municode','flat_launcher.c','-lbcrypt','-o',(Join-Path $taskOutput 'flat_launcher.exe')))
    if ($RunTests) {
        # The globe geometry and province hooks are inactive in the flat build.
        # Byte guards and patch count are checked in Test-FlatBuild.ps1 and at launch.
        if (-not (Test-Path -LiteralPath (Join-Path $taskOutput 'hoi4_flat_native.dll'))) {
            throw 'Flat patch DLL missing after compilation.'
        }
        Write-Output 'Flat native compilation passed. Run Test-FlatBuild.ps1 for map and instruction guards.'
    }
} finally { Pop-Location }
Write-Output 'Flat Earth 2x runtime and launcher built.'
