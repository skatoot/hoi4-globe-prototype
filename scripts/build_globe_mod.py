"""Generate a version-specific, reversible HOI4 spherical rendering experiment."""
import hashlib
import json
import re
import struct
from pathlib import Path
from globe_style_patch import patch_style, STYLE_SUMMARY
from globe_sky_patch import patch_sky

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
from project_config import ROOT as BASE, GAME, OUT
MOD = OUT / 'mod'
EXPECTED = '7dc947be34970da1e1c787bcddbe7f62b610ff258aebf8f06aa8b348f3a031d5'

FILES = [
    'gfx/FX/pdxmap.shader', 'gfx/FX/pdxwater.shader', 'gfx/FX/border.shader',
    'gfx/FX/mapname.shader', 'gfx/FX/maparrow.shader', 'gfx/FX/river.shader',
    'gfx/FX/strait.shader', 'gfx/FX/traderoute.shader', 'gfx/FX/tree.shader',
    'gfx/FX/pdxmesh.shader', 'gfx/FX/particle.shader', 'gfx/models/supply/railroad.shader',
]

def matching_paren(text, start):
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return i
    raise ValueError('Unbalanced projection expression')

def replace_projection(text):
    # Match the exact camera matrix identifier, never WorldViewProjectionMatrix used by GUI.
    pattern = re.compile(r'\bmul\s*\(\s*ViewProjectionMatrix\s*,\s*')
    edits = []
    for match in pattern.finditer(text):
        open_pos = text.index('(', match.start())
        end = matching_paren(text, open_pos)
        # Shadow variants receive light camera matrices and must retain flat-space shadows.
        previous_main = list(re.finditer(r'\bMainCode\s+(\w+)', text[:match.start()]))
        name = previous_main[-1].group(1) if previous_main else ''
        if 'Shadow' in name:
            continue
        edits.append((match.start(), end + 1, 'HOI4GlobeProject(' + text[match.end():end].strip() + ')'))
    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    # Depth bias must use the same sphere as clip-space x/y/w.
    bias = re.compile(r'dot\(\s*vDistortedPos\s*,\s*float4\(\s*GetMatrixData\(\s*ViewProjectionMatrix,\s*2,\s*0\s*\),\s*GetMatrixData\(\s*ViewProjectionMatrix,\s*2,\s*1\s*\),\s*GetMatrixData\(\s*ViewProjectionMatrix,\s*2,\s*2\s*\),\s*GetMatrixData\(\s*ViewProjectionMatrix,\s*2,\s*3\s*\)\s*\)\s*\)')
    text, biases = bias.subn('HOI4GlobeProject(vDistortedPos).z', text)
    return text, len(edits), biases


def clip_world_overlays(relative, text):
    """Reject map-only overlay pixels occluded by the globe, never shared HUD meshes.

    These version-checked varyings already contain original world coordinates.
    Preserve their interfaces and stock material/alpha logic.
    """
    layouts = {
        'gfx/FX/maparrow.shader': [('VS_OUTPUT_MAPARROW', 'Input', 'Input.prepos', 2),
                                   ('VS_OUTPUT_MAPSYMBOL', 'Input', 'Input.prepos', 1)],
        'gfx/FX/river.shader': [('VS_OUTPUT', 'Input', 'Input.vPrePos_Fade.xyz', 1)],
        'gfx/FX/strait.shader': [('VS_OUTPUT', 'v', 'v.vPos', 1)],
        'gfx/FX/traderoute.shader': [('VS_OUTPUT', 'v', 'v.vPos', 2)],
        'gfx/models/supply/railroad.shader': [('VS_OUTPUT', 'Input', 'Input.vPos_Height.xyz', 1)],
    }
    for struct_name, input_name, position, expected in layouts.get(relative, []):
        signature = re.compile(r'(float4\s+main\(\s*' + struct_name + r'\s+' + input_name
                               + r'\s*\)\s*:\s*PDX_COLOR\s*\{)')
        replacement = r'\1\n            clip( HOI4GlobeOverlayVisibility( ' + position + ' ) );'
        text, count = signature.subn(replacement, text)
        if count != expected:
            raise ValueError(f'Unexpected world overlay pixel layout in {relative}: {count} != {expected}')
    return text


def repair_legacy_trade_material(relative, text):
    """Use current supported fog helpers in the shipped legacy trade-route pixels."""
    if relative != 'gfx/FX/traderoute.shader':
        return text
    old = 'float vAlphaEnd = vInfo.x - (v.vTexCoord.x+TRADEROUTE_FADE_END);'
    if text.count(old) != 2:
        raise ValueError('Unexpected trade-route alpha layout')
    # The first route entry references TI without declaring it. Both samplers
    # and GetFoW are already present in the original shader/includes.
    text = text.replace(old, 'float TI = GetFoW( v.vPos, FoWTexture );\n\t\t\t' + old, 1)
    old_fog = 'float TI = GetTI( vFoWColor );'
    if text.count(old_fog) != 1:
        raise ValueError('Unexpected obsolete trade-route fog helper')
    text = text.replace(old_fog, 'float TI = GetFoW( v.vPos, FoWTexture );', 1)
    old_light = 'vColor.rgb = CalculateLighting( vColor.rgb, normalize( tex2D( NormalMap, vTexCoord ).rbg - 0.5f ) );'
    if text.count(old_light) != 1:
        raise ValueError('Unexpected obsolete trade-route lighting helper')
    text = text.replace(old_light, '''// The shipped legacy CalculateLighting helper is absent in this build.
            float3 globeView = normalize( HOI4GlobeCameraPosition() - HOI4GlobePosition( v.vPos ) );
            float3 globeSun = normalize( globeView + float3( -0.50f, 0.45f, -0.18f ) );
            vColor.rgb *= 0.58f + 0.42f * saturate( dot( HOI4GlobeSurfaceNormal( v.vPos ), globeSun ) );''', 1)
    return text

def main():
    executable_hash = hashlib.sha256((GAME / 'hoi4.exe').read_bytes()).hexdigest()
    if executable_hash != EXPECTED:
        raise SystemExit('Installed executable changed: inspect this build before regenerating the mod.')
    with (GAME / 'map/provinces.bmp').open('rb') as image:
        image.seek(18)
        width, height = struct.unpack('<ii', image.read(8))
    height = abs(height)
    (MOD / 'gfx/FX').mkdir(parents=True, exist_ok=True)
    helper_path = SCRIPT_DIRECTORY / 'globe_projection_v3.fxh'
    (MOD / 'gfx/FX/hoi4_globe.fxh').write_text(helper_path.read_text(encoding='utf-8'), encoding='utf-8')
    records = []
    for relative in FILES:
        source = GAME / relative
        original = source.read_text(encoding='utf-8-sig')
        changed, projections, biases = replace_projection(original)
        if projections == 0:
            raise RuntimeError(f'No expected projection found in {relative}')
        changed, includes = re.subn(r'("standardfuncsgfx\.fxh")', r'\1\n\t"hoi4_globe.fxh"', changed, count=1)
        if includes != 1:
            raise RuntimeError(f'Unexpected include layout in {relative}')
        changed = patch_style(relative, changed)
        changed = clip_world_overlays(relative, changed)
        changed = repair_legacy_trade_material(relative, changed)
        target = MOD / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(changed, encoding='utf-8')
        records.append({'path': relative, 'original_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                        'generated_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                        'spherical_projection_calls': projections, 'depth_bias_fixes': biases})
    sky_source = GAME / 'gfx/FX/sky.shader'
    sky = patch_sky(sky_source.read_text(encoding='utf-8-sig'))
    (MOD / 'gfx/FX/sky.shader').write_text(sky, encoding='utf-8')
    records.append({'path': 'gfx/FX/sky.shader', 'original_sha256': hashlib.sha256(sky_source.read_bytes()).hexdigest(),
                    'generated_sha256': hashlib.sha256((MOD / 'gfx/FX/sky.shader').read_bytes()).hexdigest(),
                    'spherical_projection_calls': 0, 'depth_bias_fixes': 0})
    camera_path = MOD / 'common/defines/zz_globe_camera.lua'
    camera_path.parent.mkdir(parents=True, exist_ok=True)
    camera_path.write_text((SCRIPT_DIRECTORY / 'globe_camera_defines.lua').read_text(encoding='utf-8'), encoding='utf-8')
    descriptor = 'version="0.3-relief-view"\nname="HOI4 Globe — Rendering Prototype"\ntags={ "Graphics" "Map" }\nsupported_version="1.19.3.*"\n'
    (MOD / 'descriptor.mod').write_text(descriptor, encoding='utf-8')
    (OUT / 'hoi4_globe_prototype.mod').write_text(descriptor + f'path="{MOD.as_posix()}"\n', encoding='utf-8')
    manifest = {'status': 'rendering_prototype_not_playable_replacement', 'game_version': '1.19.3.0',
                'game_executable_sha256': executable_hash, 'map_width': width, 'map_height': height,
                'prototype_version': '0.3-relief-view',
                'projection': 'approximate natural-scale inverse Miller; equator north-row672 and Greenwich x2793',
                'visual_materials': STYLE_SUMMARY, 'files': records,
                'world_overlay_visibility': {'clipped': ['map arrows and map symbols', 'rivers', 'straits', 'trade routes', 'railroads'],
                                             'scope': 'Existing flat-position pixel varyings only; shared model and particle materials retain their prior behavior'},
                'legacy_shader_repairs': {'gfx/FX/traderoute.shader': 'Undefined stock TI/GetTI/vFoWColor replaced with supported GetFoW and existing FoWTexture; removed stock CalculateLighting call replaced with spherical daylight'},
                'camera_defines': {'path': 'common/defines/zz_globe_camera.lua', 'sha256': hashlib.sha256(camera_path.read_bytes()).hexdigest()},
                'projection_helper': {'path': 'gfx/FX/hoi4_globe.fxh', 'sha256': hashlib.sha256((MOD / 'gfx/FX/hoi4_globe.fxh').read_bytes()).hexdigest()},
                'terrain_relief': 'Actual NOAA height shape; positive land relief scales from 1.0 in orbit to 1.85 at close range, with corresponding DEM slope normals',
                'polar_backdrop': 'Geographic six-face Earth color cubemap; run integrate_globe_backdrop.py to install the verified asset',
                'known_missing_native_features': ['Native mouse picking and order painting', 'Other screen-space projection paths and model-preview effects', 'Campaign visual inspection and frame-time measurement'],
                'game_files_modified': False}
    (OUT / 'build-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(OUT), 'map_size': [width, height], 'shader_files': len(FILES) + 1,
                      'projection_calls': sum(row['spherical_projection_calls'] for row in records)}, indent=2))

if __name__ == '__main__':
    main()
