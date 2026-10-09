No executable is provided check the code yourself for how to run it as it's a silly idea to run code you haven't checked yourself.

Goes for all projects not just this one.


# HOI4 globe prototype

An experimental 3D planet renderer for Hearts of Iron IV. V3 curves the map around Earth, adds elevation-based relief and a continuous geographic backdrop, restores political colors and labels, and projects map-icon anchors onto terrain.

This repository contains the authored source and rebuild tools. Game files, decompiled game code, generated textures, binaries, local profiles, logs, and screenshots are excluded. The build reads an existing installation and writes a separate local mod.

## Supported build

Windows x64, HOI4 **1.19.3.0**, with executable SHA256:

```
7dc947be34970da1e1c787bcddbe7f62b610ff258aebf8f06aa8b348f3a031d5
```

Other executable builds are refused. Native addresses and calling conventions must be verified again after a game update.

## Build and launch

Install Python 3.12 or newer, the dependencies in `requirements.txt`, and Zig 0.15.2. Run from PowerShell on Windows:

```powershell
python -m pip install -r requirements.txt
$game = Read-Host 'Full path to the HOI4 installation'
.\Build.ps1 -GameDirectory $game
.\Launch-Globe.ps1 -GameDirectory $game
```

Use `-Python` and `-Compiler` on `Build.ps1` when those tools are not on PATH. `Compiler` is the Zig executable. The first build downloads roughly 60 MB of public NOAA/NASA source data; later builds reuse the ignored local cache. Generated files go under `build/` and `work/`.

The launcher creates an isolated game profile and local fixture linked to the installed asset directories. It validates the executable and bridge hashes, then loads the bridge only into its newly created process. It refuses to launch while another HOI4 process is running. The installed executable and normal playset remain unchanged.

## Current behavior

- Approximate inverse Miller projection with a wider orbital view and smooth close-range relief.
- NOAA elevation blended with the game's altered geography. The base 8× vertical exaggeration increases to about 14.8× at close zoom; matching slope normals emphasize ridges and valleys.
- Native political colors, occupation stripes and country names, with globe visibility and horizon clipping.
- Deep blue water and a NASA/native geographic cubemap for the cropped map's polar gaps.
- Seven version-checked native CALL redirects for icon grounding/projection, terrain LOD visibility, province visibility and country-label culling.
- Reused per-thread visibility buffers and caches that invalidate when camera, frustum, bounds or object identity change.

## Limits

This is a rendering prototype. Mouse picking and order painting still need integration. Gameplay adjacency, distances and routes keep their original rules. Shared model/particle and other projection paths retain limitations. The polar backdrop adds color coverage, not playable polar provinces or detailed polar geometry. The game map's alignment with real geography is approximate, and the sampled elevation has roughly 7.4 km spacing at the equator.

All 37 modified Direct3D programs compiled in the tested build. Native geometry, conservative visibility, concurrency and reversible hook checks passed. Automated campaign visual inspection and campaign frame-rate measurements were not performed. See [validation](docs/validation.md) and [native integration](docs/native-integration.md).

## Data and privacy

Terrain uses NOAA ETOPO2022 and polar imagery uses NASA Blue Marble Next Generation. No Google Maps tiles are included. Attribution and source hashes are in [credits](docs/credits.md).

Only source files and non-personal project documentation are committed. Local paths, profiles, runtime identifiers, hardware details and compiler diagnostics stay in ignored output folders. See [privacy](docs/privacy.md).
