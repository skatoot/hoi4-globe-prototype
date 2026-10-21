param([Parameter(Mandatory)][string]$GameDirectory)
$ErrorActionPreference='Stop'
$taskGame=[IO.Path]::GetFullPath($GameDirectory)
$taskBuild=Join-Path $PSScriptRoot 'build\hoi4-earth-map-flat'
$taskFixture=Join-Path $PSScriptRoot 'work\game'
$taskProfile=Join-Path $PSScriptRoot 'work\profile'
$taskExe=Join-Path $taskFixture 'hoi4.exe'
if (@(Get-Process -Name hoi4 -ErrorAction SilentlyContinue).Count) { throw 'HOI4 is already running. Save and exit it before launching this profile.' }
$taskManifest=Get-Content -LiteralPath (Join-Path $taskBuild 'build-manifest.json') -Raw | ConvertFrom-Json
if ($taskManifest.width -ne 10240 -or $taskManifest.height -ne 5120 -or $taskManifest.globe_hooks -ne 0 -or $taskManifest.globe_shaders -ne 0) { throw 'Expected the flat Earth Map 2x build manifest.' }
if ((Get-FileHash -LiteralPath (Join-Path $taskGame 'hoi4.exe') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskManifest.game_sha256) { throw 'This executable version is unsupported.' }
foreach ($taskFile in $taskManifest.native_binaries) {
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
[IO.File]::WriteAllText((Join-Path $taskProfile 'mod\hoi4_earth_map_2x_flat.mod'),$taskDescriptor+"`npath=`"$taskModPath`"`n",[Text.UTF8Encoding]::new($false))
@{enabled_mods=@('mod/hoi4_earth_map_2x_flat.mod');disabled_dlcs=@()} | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $taskProfile 'dlc_load.json') -Encoding utf8
# HOI4 1.19.3 resolves its active playset from the Documents game directory
# even when -userdir or launcher-settings.json points to the isolated profile.
# To ensure the correct 35,189-province map loads, temporarily select this
# edition in the normal playset; always restore its original bytes on exit.
$taskDocuments=[Environment]::GetFolderPath('MyDocuments')
$taskDefaultProfile=Join-Path $taskDocuments 'Paradox Interactive\Hearts of Iron IV'
$taskDlcLoad=Join-Path $taskDefaultProfile 'dlc_load.json'
$taskDefaultMods=Join-Path $taskDefaultProfile 'mod'
if (-not (Test-Path -LiteralPath $taskDlcLoad)) { throw "Missing default mod selection file: $taskDlcLoad" }
New-Item -ItemType Directory -Path $taskDefaultMods -Force | Out-Null
$taskToken=[guid]::NewGuid().ToString('N').Substring(0,12)
$taskTempName="earth_map_flat_$taskToken.mod"
$taskTempDescriptor=Join-Path $taskDefaultMods $taskTempName
$taskBackupDir=Join-Path $PSScriptRoot 'work\playset-backups'
New-Item -ItemType Directory -Path $taskBackupDir -Force | Out-Null
$taskBackup=Join-Path $taskBackupDir "dlc_load_$taskToken.json"
$taskOriginal=[IO.File]::ReadAllBytes($taskDlcLoad)
$taskOriginalHash=(Get-FileHash -LiteralPath $taskDlcLoad -Algorithm SHA256).Hash
[IO.File]::WriteAllBytes($taskBackup,$taskOriginal)
$taskSelection='{"disabled_dlcs":[],"enabled_mods":["mod/'+$taskTempName+'"]}'
$taskSelectionBytes=[Text.UTF8Encoding]::new($false).GetBytes($taskSelection)
$taskAppliedSelection=$false
$taskRestored=$false
try {
    [IO.File]::WriteAllText($taskTempDescriptor,$taskDescriptor+"`npath=`"$taskModPath`"`n",[Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllBytes($taskDlcLoad,$taskSelectionBytes)
    $taskAppliedSelection=$true
    $taskLaunchTime=(Get-Date).ToUniversalTime()
    $taskOutput=& (Join-Path $taskBuild 'native\flat_launcher.exe') $taskExe (Join-Path $taskBuild 'native\hoi4_flat_native.dll') play
    if ($LASTEXITCODE -ne 0) { throw "Native launcher failed ($LASTEXITCODE)." }
    $taskMatch=[regex]::Match(($taskOutput -join "`n"),'LAUNCHED_PID=(\d+)')
    if (-not $taskMatch.Success) { throw 'The launcher did not return its process ID.' }
    $taskProcess=Get-Process -Id ([int]$taskMatch.Groups[1].Value) -ErrorAction Stop
    $taskInstalled=$false
    for ($taskAttempt=0;$taskAttempt -lt 60;$taskAttempt++) {
        try {
            $taskStatus=Get-Content -LiteralPath (Join-Path $taskBuild 'native\bridge-status.json') -Raw | ConvertFrom-Json
            if ($taskStatus.pid -eq $taskProcess.Id -and $taskStatus.installed -and $taskStatus.heightmap_loaded) { $taskInstalled=$true;break }
        } catch {}
        Start-Sleep -Milliseconds 250
    }
    if (-not $taskInstalled) { throw 'Flat native patches did not install.' }
    $taskGameLog=Join-Path $taskDefaultProfile 'logs\game.log'
    $taskMapLoaded=$false
    for ($taskAttempt=0;$taskAttempt -lt 240;$taskAttempt++) {
        $taskRunning=Get-Process -Id $taskProcess.Id -ErrorAction SilentlyContinue
        if (-not $taskRunning -or $taskRunning.Path -ne $taskExe) { throw 'Game exited before Earth Map 2x initialized.' }
        if (Test-Path -LiteralPath $taskGameLog) {
            $taskLog=Get-Item -LiteralPath $taskGameLog
            if ($taskLog.LastWriteTimeUtc -ge $taskLaunchTime -and
                (Select-String -LiteralPath $taskGameLog -Pattern 'Loaded 35189 provinces\.' -Quiet)) {
                $taskMapLoaded=$true
                break
            }
        }
        Start-Sleep -Seconds 1
    }
    if (-not $taskMapLoaded) { throw 'Could not confirm 35,189 Earth Map 2x provinces within four minutes.' }
    Write-Output "Flat Earth Map 2x loaded 35,189 provinces (PID $($taskProcess.Id))."
} finally {
    if ($taskAppliedSelection) {
        $taskCurrent=[IO.File]::ReadAllBytes($taskDlcLoad)
        if ([Convert]::ToBase64String($taskCurrent) -eq [Convert]::ToBase64String($taskSelectionBytes)) {
            [IO.File]::WriteAllBytes($taskDlcLoad,$taskOriginal)
            if ((Get-FileHash -LiteralPath $taskDlcLoad -Algorithm SHA256).Hash -ne $taskOriginalHash) {
                throw "Playset restoration failed; use saved backup $taskBackup"
            }
            $taskRestored=$true
        } else {
            Write-Warning "Playset was modified during launch, so no overwrite was attempted. Original is backed up at $taskBackup"
        }
    }
    if ($taskRestored -and (Test-Path -LiteralPath $taskTempDescriptor)) {
        Remove-Item -LiteralPath $taskTempDescriptor -Force
    }
}
if (-not $taskRestored) { throw "Default playset could not be restored automatically. Backup: $taskBackup" }
Write-Output 'Original Documents playset restored exactly. Flat game remains running.'
