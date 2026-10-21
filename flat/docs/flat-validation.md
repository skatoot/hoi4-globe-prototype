# Flat edition verification

## Source and visual assets

- Original Earth Map 2x `provinces.bmp`: 10240×5120.
- Preserve original `gfx/FX/constants.fxh` and `gfx/FX/standardfuncsgfx.fxh`.
- No generated `HOI4GlobeProject` shader overrides, `hoi4_globe.fxh`, `sky.shader`, `zz_globe_camera.lua` or `map/terrain/reflection.dds`.
- Preserve original states, provinces, supply, gameplay history, map defines and `replace_path` directive list.

## Crash fixes

| Fix | Instruction RVA | Effect |
|---|---|---|
| Startup scratch buffer | `0x222D70A` initializer | 50 MiB → 256 MiB before the child resumes |
| Texture file size | `0x2407CDF` | 16 MiB → 64 MiB |
| Terrain marker writer X | `0x1282205` | Shift 8 → 9 |
| Terrain marker writer Y | `0x1282212` | Shift 8 → 9 |
| Terrain bucket generator X | `0x1B26926` | Shift 8 → 9 |
| Terrain bucket generator Y | `0x1B2693B` | Shift 8 → 9 |

The four shift patches have been tested successfully in the original globe build and avoid the same 800-entry overrun in flat rendering.

## What has been checked

- Isolated flat game was created and started with the supported executable.
- Native DLL loaded and reported `installed=true`.
- Debugging confirmed the test loaded **35,189 provinces** and began the **1936** campaign.
- User visually tested and confirmed the flat version worked.
- Original Documents `dlc_load.json` was restored byte-for-byte after the test initialized.
- Log confirmed the original renderer callbacks were preserved and the terrain-grid/texture guards applied.
- No globe shader, polar cubemap or camera override appears in the flat mod.

## Additional testing recommended

For ongoing releases: move around the flat map, check coastlines, political
colors and labels, select provinces, issue orders and attempt save/reload.
The separate test confirmed basic playability; long-running multiplayer,
savegame compatibility and later HOI4 builds are outside this test.
