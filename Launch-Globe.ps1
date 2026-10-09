param([Parameter(Mandatory)][string]$GameDirectory)
$ErrorActionPreference='Stop'
$taskGame=[IO.Path]::GetFullPath($GameDirectory)
$taskBuild=Join-Path $PSScriptRoot 'build\hoi4-globe-prototype'
$taskFixture=Join-Path $PSScriptRoot 'work\game'
$taskProfile=Join-Path $PSScriptRoot 'work\profile'
$taskExe=Join-Path $taskFixture 'hoi4.exe'
if (@(Get-Process -Name hoi4 -ErrorAction SilentlyContinue).Count) { throw 'HOI4 is already running. Save and exit it before launching this profile.' }
$taskManifest=Get-Content -LiteralPath (Join-Path $taskBuild 'build-manifest.json') -Raw | ConvertFrom-Json
$taskShader=Get-Content -LiteralPath (Join-Path $taskBuild 'shader-validation.json') -Raw | ConvertFrom-Json
if (-not $taskShader.passed -or $taskShader.programs -ne 37) { throw 'Complete Build.ps1 successfully before launching.' }
if ((Get-FileHash -LiteralPath (Join-Path $taskGame 'hoi4.exe') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskManifest.game_executable_sha256) { throw 'This executable version is unsupported.' }
foreach ($taskFile in $taskManifest.native_bridge.files) {
    if ((Get-FileHash -LiteralPath (Join-Path $taskBuild $taskFile.path) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskFile.sha256) { throw "Native file changed: $($taskFile.path)" }
}
New-Item -ItemType Directory -Path $taskFixture,(Join-Path $taskProfile 'mod') -Force | Out-Null
# Copy only required local game files. Everything remains inside ignored work/.
foreach ($taskName in @('hoi4.exe','hoi4.exe.manifest','PDXSDK.dll','steam_api64.dll','tbb.dll','tbb_debug.dll','icudtl.dat','steam_appid.txt','launcher-settings.json','settings-layout.json')) {
    $taskSource=Join-Path $taskGame $taskName
    if (Test-Path -LiteralPath $taskSource) { Copy-Item -LiteralPath $taskSource -Destination (Join-Path $taskFixture $taskName) -Force }
}
foreach ($taskDirectory in Get-ChildItem -LiteralPath $taskGame -Directory) {
    $taskLink=Join-Path $taskFixture $taskDirectory.Name
    if (Test-Path -LiteralPath $taskLink) {
        $taskExisting=Get-Item -LiteralPath $taskLink
        if ($taskExisting.LinkType -ne 'Junction' -or @($taskExisting.Target)[0] -ne $taskDirectory.FullName) { throw "An existing fixture directory has a different target: $($taskDirectory.Name)" }
    } else { New-Item -ItemType Junction -Path $taskLink -Target $taskDirectory.FullName | Out-Null }
}
$taskSettingsPath=Join-Path $taskFixture 'launcher-settings.json'
$taskSettings=Get-Content -LiteralPath $taskSettingsPath -Raw | ConvertFrom-Json
$taskSettings.gameDataPath=$taskProfile.Replace('\','/')
$taskSettings | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $taskSettingsPath -Encoding utf8
$taskDescriptor=Get-Content -LiteralPath (Join-Path $taskBuild 'mod\descriptor.mod') -Raw
$taskModPath=(Join-Path $taskBuild 'mod').Replace('\','/')
if ($taskModPath.Contains('"')) { throw 'The repository path cannot contain a quotation mark.' }
[IO.File]::WriteAllText((Join-Path $taskProfile 'mod\hoi4_globe_prototype.mod'),$taskDescriptor+"`npath=`"$taskModPath`"`n",[Text.UTF8Encoding]::new($false))
@{enabled_mods=@('mod/hoi4_globe_prototype.mod');disabled_dlcs=@()} | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $taskProfile 'dlc_load.json') -Encoding utf8
$taskOutput=& (Join-Path $taskBuild 'native\globe_launcher.exe') $taskExe (Join-Path $taskBuild 'native\hoi4_globe_native.dll') play
if ($LASTEXITCODE -ne 0) { throw "Native launcher failed ($LASTEXITCODE)." }
$taskMatch=[regex]::Match(($taskOutput -join "`n"),'LAUNCHED_PID=(\d+)')
if (-not $taskMatch.Success) { throw 'The launcher did not return its new process ID.' }
$taskProcess=Get-Process -Id ([int]$taskMatch.Groups[1].Value)
$taskInstalled=$false
for ($taskAttempt=0;$taskAttempt -lt 100;$taskAttempt++) {
    try {
        $taskStatus=Get-Content -LiteralPath (Join-Path $taskBuild 'native\bridge-status.json') -Raw | ConvertFrom-Json
        if ($taskStatus.pid -eq $taskProcess.Id -and $taskStatus.installed -and $taskStatus.heightmap_loaded) { $taskInstalled=$true;break }
    } catch { }
    Start-Sleep -Milliseconds 100
}
if (-not $taskInstalled) {
    $taskCurrent=Get-Process -Id $taskProcess.Id -ErrorAction SilentlyContinue
    if ($taskCurrent -and $taskCurrent.Path -eq $taskExe -and $taskCurrent.StartTime -eq $taskProcess.StartTime) { Stop-Process -Id $taskCurrent.Id }
    throw 'This new launch refused the bridge. Check the local build/native bridge log.'
}
Write-Output "Globe profile launched (PID $($taskProcess.Id))."
