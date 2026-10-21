# Earth Map 2x — Flat Edition

Native flat-map support for the original 10,240 × 5,120 Earth Map 2x mod on **Hearts of Iron IV 1.19.3.0 (Windows x64)**.

This edition uses HOI4's original flat map projection, stock water/terrain/sky shaders, camera and labels. The globe projection, horizon clipping, radial lighting, polar cubemap and sphere-specific rendering CALL hooks are inactive. It preserves the underlying Earth Map 2x map, provinces, state/history data and 2x visual assets.

## Why an injector is still required

The map is four times the pixel area of the original 5,120 × 2,560 game map. Two fixed-size engine assumptions cause crashes:

1. The engine's initial 50 MiB image scratch allocation is too small for the 200 MiB expanded RGBA map. The launcher changes the verified startup allocation to 256 MiB in its own suspended game process.
2. A 256-slot terrain visibility array would receive 800 entries if both X/Y axes use the stock 256-pixel cells. The DLL changes **four exact, verified instruction immediates** (writer X/Y and bucket generator X/Y) to use 512-pixel cells, giving 20 × 10 = 200 entries. A separate guarded instruction raises the texture-file-size allowance to 64 MiB.

These fixes are independent of any curved/spherical geometry. The executable on disk is never modified.

## Supported executable

HOI4 1.19.3.0, SHA256:

`7dc947be34970da1e1c787bcddbe7f62b610ff258aebf8f06aa8b348f3a031d5`

All other executable hashes are rejected by the launcher. Runtime patches are additionally protected by exact instruction-byte checks.

## Download and build

The original **Earth Map 2x** mod folder (including `map/provinces.bmp`, `map/heightmap.bmp`, `common` and `history`) must already be present. Large third-party map data, the game executable and generated binaries are not stored in the source repository.

Requires Windows PowerShell and an existing HOI4 installation. Download the
**Earth Map 2x Flat Edition** release ZIP, or obtain the source under `flat/`
in the GitHub repository. The release ZIP includes compiled Windows x64 binaries,
so Zig is optional unless you want to rebuild the native DLL.

```powershell
$game = 'C:\Program Files (x86)\Steam\steamapps\common\Hearts of Iron IV'
$earth = 'C:\Path\To\Earth_Map_2x'
.\Build-Flat.ps1 -GameDirectory $game -SourceModDirectory $earth -UsePrebuiltNative
.\Launch-Flat.ps1 -GameDirectory $game
```

To rebuild the binaries from source instead, omit `-UsePrebuiltNative` and
pass `-Compiler 'C:\Path\To\zig.exe'` (Zig 0.15.2).

The build copies the original 2x mod data into ignored `build/hoi4-earth-map-flat/mod/`,
creates a flat-edition descriptor and validates the native binaries. No spherical
shader overrides are generated. `Launch-Flat.ps1` creates a separate game
fixture. Because HOI4 1.19.3 still reads mod selection from the default
Documents directory, the script temporarily selects this mod, waits until all
35,189 provinces have loaded, then **restores the original mod selection
byte-for-byte**, leaving the running flat game alone. Backups are retained
under `work/playset-backups/`. Exit HOI4 before launching.

## Tested behavior

The live flat-edition build loaded **35,189 provinces** and initialized the
**1936 campaign**. Exact live-memory inspection verified the five large-map
fixes and that the seven original globe-related CALL instructions remained
unchanged. The user tested the resulting flat map and confirmed it worked.
Long-running campaign stability across arbitrary mods or newer HOI4 versions
has not been established.

The earlier globe build and its separate test profile remain available for comparison.
