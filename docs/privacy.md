# Publication privacy

This repository was prepared from an explicit source allowlist in a fresh Git repository. It does not carry earlier workspace history.

Excluded content includes local game/profile fixtures, saves, screenshots, raw runtime logs and reports, device information, process IDs, compiled caches, archives, game binaries/assets and decompiled game source. Source configuration accepts a game directory at runtime rather than embedding a personal machine path.

Commit attribution uses the requested GitHub account and its GitHub no-reply address. No personal email is required.

Building and launching creates local paths, diagnostics, downloaded datasets and a game profile under `build/` and `work/`. Both folders are ignored. Inspect staged files before committing future changes; do not force-add those generated folders or publish raw diagnostics without reviewing them.
