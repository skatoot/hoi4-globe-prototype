param(
  [Parameter(Mandatory=$true)][int]$ProcessId,
  [Parameter(Mandatory=$true)][string]$ExpectedExecutable
)
$ErrorActionPreference='Stop'
$expectedExe=[IO.Path]::GetFullPath($ExpectedExecutable)
$game=Get-Process -Id $ProcessId -ErrorAction Stop
if($game.Path -ne $expectedExe){throw 'Unexpected HOI4 process path'}
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class EarthRead {
 [DllImport("kernel32.dll", SetLastError=true)]
 public static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
 [DllImport("kernel32.dll", SetLastError=true)]
 [return: MarshalAs(UnmanagedType.Bool)]
 public static extern bool ReadProcessMemory(IntPtr process, IntPtr address, byte[] buffer, UIntPtr size, out UIntPtr transferred);
 [DllImport("kernel32.dll")]
 [return: MarshalAs(UnmanagedType.Bool)]
 public static extern bool CloseHandle(IntPtr process);
}
'@
$handle=[EarthRead]::OpenProcess(0x10,$false,[uint32]$ProcessId)
if($handle -eq [IntPtr]::Zero){throw 'Cannot open game for read-only patch inspection'}
try {
  $imageBase=$game.MainModule.BaseAddress.ToInt64()
  $patches=@(
    @{Name='Texture size cap';Rva=0x2407CE3;Expected=4},
    @{Name='Coarse writer X';Rva=0x1282205;Expected=9},
    @{Name='Coarse writer Y';Rva=0x1282212;Expected=9},
    @{Name='Map indexer X';Rva=0x1B26926;Expected=9},
    @{Name='Map indexer Y';Rva=0x1B2693B;Expected=9}
  )
  foreach($patch in $patches){
    $value=New-Object byte[] 1
    $transferred=[UIntPtr]::Zero
    $ok=[EarthRead]::ReadProcessMemory($handle,[IntPtr]($imageBase+$patch.Rva),$value,[UIntPtr]::new([uint32]1),[ref]$transferred)
    if(-not $ok -or $transferred.ToUInt64() -ne 1 -or $value[0] -ne $patch.Expected){
      throw "$($patch.Name): unexpected byte $(if($ok){'{0:X2}' -f $value[0]}else{'read failed'})"
    }
    Write-Output "$($patch.Name) RVA 0x$('{0:X}' -f $patch.Rva): $('{0:X2}' -f $value[0]) PASS"
  }
  # Every globe-specific CALL instruction must remain exactly unchanged.
  $nativeCalls=@(
    @{Name='Icon projection';Rva=0x163FE26;Bytes='E8-95-0B-B5-FF'},
    @{Name='Terrain visibility';Rva=0x127DB2C;Bytes='E8-8F-37-00-00'},
    @{Name='Province A';Rva=0xB5BCB3;Bytes='E8-88-5A-FF-FF'},
    @{Name='Province B';Rva=0xB4EF9A;Bytes='E8-A1-27-00-00'},
    @{Name='Province C';Rva=0xB4EFEF;Bytes='E8-4C-27-00-00'},
    @{Name='Province D';Rva=0xB5C659;Bytes='E8-E2-50-FF-FF'},
    @{Name='Country names';Rva=0xB58172;Bytes='E8-89-21-AF-00'}
  )
  foreach($call in $nativeCalls) {
    $bytes=New-Object byte[] 5
    $transferred=[UIntPtr]::Zero
    $ok=[EarthRead]::ReadProcessMemory($handle,[IntPtr]($imageBase+$call.Rva),$bytes,[UIntPtr]::new([uint32]5),[ref]$transferred)
    if(-not $ok -or $transferred.ToUInt64() -ne 5 -or [BitConverter]::ToString($bytes) -ne $call.Bytes){throw "$($call.Name) was modified by the flat injector"}
    Write-Output "$($call.Name): native renderer CALL preserved PASS"
  }
} finally {
  [EarthRead]::CloseHandle($handle)|Out-Null
}
