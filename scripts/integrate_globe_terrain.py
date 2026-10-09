"""Install the validated NOAA terrain candidate into the separate workspace mod."""
import hashlib
import json
import shutil
from pathlib import Path
from PIL import Image

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
from project_config import ROOT as BASE, GAME, OUT
PREVIEW = BASE / 'work/dem-preview'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    provenance = json.loads((PREVIEW / 'terrain-provenance.json').read_text(encoding='utf-8'))
    checks = provenance['validation']
    for key in ['finite_elevations', 'water_pixels_unchanged', 'shore_bytes_below_or_equal95_unchanged',
                'game_land_in_real_ocean_pixels_preserved', 'normal_water_pixels_unchanged',
                'stock_wet_up_normal_encoding_confirmed']:
        if checks.get(key) is not True:
            raise ValueError(f'Terrain candidate has not passed {key}')
    if checks['changed_land_pixels'] <= 0:
        raise ValueError('Terrain candidate did not change any land')
    if digest(GAME / 'map/heightmap.bmp') != provenance['game_heightmap_sha256']:
        raise ValueError('Installed heightmap differs from the validated source')
    if digest(GAME / 'map/provinces.bmp') != provenance['game_provinces_sha256']:
        raise ValueError('Installed provinces differ from the validated source')
    manifest_path = OUT / 'build-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if digest(GAME / 'hoi4.exe') != manifest['game_executable_sha256']:
        raise ValueError('Installed game version changed')
    assets = []
    for name, size, mode in [('heightmap.bmp', (5632, 2048), 'L'), ('world_normal.bmp', (2816, 1024), 'RGB')]:
        source = PREVIEW / name
        if digest(source) != provenance['generated_assets'][name]['sha256']:
            raise ValueError(f'Candidate hash changed: {name}')
        with Image.open(source) as bitmap:
            if bitmap.size != size or bitmap.mode != mode:
                raise ValueError(f'Unexpected candidate image format: {name}')
        target = OUT / 'mod/map' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        assets.append({'path': 'map/' + name, 'original_sha256': digest(GAME / 'map' / name),
                       'generated_sha256': digest(target), 'bytes': target.stat().st_size})
    provenance['status'] = 'installed_in_separate_workspace_mod'
    provenance['mod_files_modified'] = True
    provenance['game_files_modified'] = False
    provenance['terrain_assets'] = assets
    provenance['source_choice'] = 'Public NOAA ETOPO2022 elevation; no Google content used'
    (OUT / 'terrain-provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    manifest['terrain_assets'] = assets
    manifest['terrain_data_source'] = 'NOAA NCEI ETOPO2022, stride4 ice-surface elevation'
    manifest['terrain_vertical_exaggeration'] = provenance['height_encoding']['vertical_exaggeration_artistic']
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'mod': str(OUT / 'mod'), 'terrain_assets': assets, 'checks': checks}, indent=2))

if __name__ == '__main__':
    main()
