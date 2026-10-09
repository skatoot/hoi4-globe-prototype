# Validation scope

The V3 prototype was checked against the exact executable hash in the README.

| Check | Result | Scope |
| --- | --- | --- |
| Direct3D SM5 compilation | 37 programs passed: 17 vertex, 20 pixel | Modified effect interfaces and defines translated into HLSL |
| Native geometry reference | 10,000 cases passed | C11 float formulas against an independent double reference |
| Conservative province visibility | 10,000 bounds, 213,734 visible samples; no false negatives | Synthetic spherical bounds and frusta |
| Cache invalidation | 5,000 warm calls passed; input changes reprobed | Camera, planes, bounds, objects and arrays |
| Concurrent worker output | 16 workers × 200 task groups passed | Moving camera and unique atomic records |
| Terrain LOD bound | At most 188 selected patches per pass | Verified native thresholds and retained LOD/stitching |
| Geographic cubemap | Faces, mip chain and direction mapping passed | 512-pixel faces, below the native 16 MiB loader limit |
| Native camera ABI | Valid matrices accepted; stale, NaN and reversed direction rejected | Compiled DLL synthetic fixtures |
| Isolated startup | Mod active; no shader, terrain or backdrop load errors | Local game startup |
| Hook installation/restoration | Seven CALLs checked and restored; code pages returned to RX | Only the newly created test process |
| Installed file integrity | Executable and source assets unchanged | SHA256 comparison |

The native geometry and province tests run as part of `Build.ps1`, along with shader compilation and camera tests. Raw local diagnostics and process information are deliberately not committed.

These checks do not establish correct campaign appearance at every zoom, accurate mouse picking, campaign frame rate, or complete compatibility with other mods. Visual campaign inspection remains outstanding.
