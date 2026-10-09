param([string]$Compiler='zig',[switch]$RunTests)
$ErrorActionPreference='Stop'
$taskCompiler=(Get-Command $Compiler -ErrorAction Stop).Source
$taskSource=Join-Path $PSScriptRoot 'native\src'
$taskOutput=Join-Path $PSScriptRoot 'build\hoi4-globe-prototype\native'
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
    Invoke-GlobeCompiler ($taskCommon+@('-shared','globe_native.c','-o',(Join-Path $taskOutput 'hoi4_globe_native.dll')))
    Invoke-GlobeCompiler ($taskCommon+@('-municode','globe_launcher.c','-lbcrypt','-o',(Join-Path $taskOutput 'globe_launcher.exe')))
    if ($RunTests) {
        foreach ($taskName in @('globe_geometry_test','globe_province_test')) {
            $taskTest=Join-Path $taskTests "$taskName.exe"
            Invoke-GlobeCompiler ($taskCommon+@("$taskName.c",'-o',$taskTest))
            & $taskTest
            if ($LASTEXITCODE -ne 0) { throw "$taskName failed ($LASTEXITCODE)." }
        }
    }
} finally { Pop-Location }
Write-Output 'Native bridge and launcher built.'
