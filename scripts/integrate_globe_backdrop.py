"""Install the verified geographic color cubemap in the separate workspace mod.

This fills missing artwork/culling gaps with continuous Earth color. It does not
create playable provinces or terrain geometry outside the game's map band.
"""
import hashlib
import json
import shutil
import struct
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
from project_config import ROOT as BASE, GAME, OUT
PREVIEW = BASE / 'work/backdrop-preview'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    provenance = json.loads((PREVIEW / 'backdrop-provenance.json').read_text(encoding='utf-8'))
    checks = provenance['validation']
    for key in ('all_face_mip_hashes_match', 'base_faces_roundtrip_exact',
                'pillow_base_face_roundtrip_exact', 'axis_centers_verified'):
        if checks.get(key) is not True:
            raise ValueError(f'Backdrop candidate has not passed {key}')
    if checks['random_direction_roundtrips'] < 2000 or checks['max_direction_error'] > 1e-6:
        raise ValueError('Geographic cube direction validation is incomplete')
    for relative, expected in provenance['stock_sources'].items():
        if digest(GAME / relative) != expected:
            raise ValueError(f'Installed backdrop source changed: {relative}')
    source = PREVIEW / 'reflection.dds'
    cube = provenance['cube']
    if digest(source) != cube['sha256'] or source.stat().st_size != cube['bytes']:
        raise ValueError('Backdrop candidate hash or size changed')
    # Confirmed native loader file-buffer limit for the pinned 1.19.3 executable.
    if source.stat().st_size > 16_777_216:
        raise ValueError('Backdrop exceeds the native 16 MiB texture file limit')
    if checks.get('within_native_texture_file_size_limit') is not True:
        raise ValueError('Backdrop native file-limit validation is missing')
    with source.open('rb') as stream:
        header = stream.read(128)
    if header[:4] != b'DDS ' or struct.unpack_from('<I', header, 4)[0] != 124:
        raise ValueError('Expected a legacy DDS header')
    height, width = struct.unpack_from('<II', header, 12)
    mip_count = struct.unpack_from('<I', header, 28)[0]
    caps2 = struct.unpack_from('<I', header, 112)[0]
    if (width, height, mip_count, caps2) != (cube['size'], cube['size'], cube['mip_count'], 0xfe00):
        raise ValueError('Backdrop cubemap dimensions, mip chain or face flags changed')
    manifest_path = OUT / 'build-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if digest(GAME / 'hoi4.exe') != manifest['game_executable_sha256']:
        raise ValueError('Installed executable version changed')
    target = OUT / 'mod/map/terrain/reflection.dds'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    asset = {'path': 'map/terrain/reflection.dds',
             'original_sha256': provenance['stock_sources']['map/terrain/reflection.dds'],
             'generated_sha256': digest(target), 'bytes': target.stat().st_size}
    provenance['status'] = 'installed_in_separate_workspace_mod'
    provenance['mod_files_modified'] = True
    provenance['game_files_modified'] = False
    provenance['backdrop_assets'] = [asset]
    (OUT / 'backdrop-provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    manifest['backdrop_assets'] = [asset]
    manifest.setdefault('polar_backdrop', 'Continuous geographic cubemap with native map biome colors in the game band and NASA Blue Marble January polar imagery beyond it; color only')
    manifest.setdefault('backdrop_data_source', {'name': 'NASA Blue Marble Next Generation, January 2004',
                                               'page': provenance['source_page'], 'credit': provenance['credit']})
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'asset': asset, 'checks_passed': True, 'geometry_created': False}, indent=2))


if __name__ == '__main__':
    main()
