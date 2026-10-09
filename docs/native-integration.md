# Native bridge

The bridge targets only the executable SHA256 in the README. It patches process memory, never the executable file. Each instruction and target prefix is checked before installation.

| Purpose | CALL RVA | Original target RVA |
| --- | --- | --- |
| Shared map-icon projection | `0x163fe26` | `0x11909c0` |
| Terrain visibility/LOD builder | `0x127db2c` | `0x12812c0` |
| Province worker | `0xb5bcb3` | `0xb51740` |
| Province worker | `0xb4ef9a` | `0xb51740` |
| Province worker | `0xb4efef` | `0xb51740` |
| Province worker | `0xb5c659` | `0xb51740` |
| Country-label visibility | `0xb58172` | `0x164a300` |

Map anchors sample the generated heightmap and use the same spherical camera, relief and occlusion formulas as the shader helper. Terrain uses a private camera copy with full-map side bounds while preserving native LOD and stitching. A runtime patch-count guard reverts expansion if the proven 188-patch bound is exceeded.

Province workers retain native gameplay eligibility, original camera pointers and exclusive province ranges. Reusable per-thread storage and visibility caches avoid repeated allocation and geometry work. Bounded atomic reservations merge private update records into the original lists. The cache relies on the native joined task-group object lifetime; identity and input changes trigger revalidation.

Installation and restoration suspend only sibling threads in the newly created game process, reject instruction pointers inside changed CALLs, verify all bytes, restore page protections and flush the instruction cache. `GlobeUninstall` restores all seven original calls. Relay/DLL memory stays mapped until process exit so in-flight callbacks cannot jump into freed code.

Local diagnostics are written beside the generated bridge under ignored `build/`. They are not part of the repository.
