"""V3 inverse, horizon/occlusion, relief audit plus standalone SM5 helper compile."""
import ctypes
import json
import math
import random
from pathlib import Path

from projection_v2_math import WIDTH, HEIGHT, SEA, RADIUS, EQUATOR, latitude, normal


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def smoothstep(a, b, t):
    t = min(1, max(0, (t - a) / (b - a)))
    return t * t * (3 - 2 * t)


def relief(camera_height):
    return 1.85 - .85 * smoothstep(180, 650, max(0, camera_height - SEA))


def center(focus):
    return focus[0], SEA - RADIUS, focus[1]


def position(flat, focus, camera_height, base_height=None):
    x, y, z = flat
    base = y if base_height is None else base_height
    altitude = base - SEA
    altitude = altitude * relief(camera_height) if altitude > 0 else altitude
    if base_height is not None:
        altitude += y - base
    n, c = normal(x, z, focus), center(focus)
    return tuple(cv + nv * (RADIUS + altitude) for cv, nv in zip(c, n))


def inverse(point, focus):
    r = sub(point, center(focus))
    length = math.sqrt(dot(r, r))
    r = tuple(v / length for v in r)
    fl = latitude(focus[1])
    sf, cf = math.sin(fl), math.cos(fl)
    lat = math.asin(max(-1, min(1, r[1] * sf + r[2] * cf)))
    lon = math.atan2(r[0], r[1] * cf - r[2] * sf)
    x = (focus[0] + lon * RADIUS) % WIDTH
    z = EQUATOR + RADIUS * 1.25 * math.log(math.tan(math.pi / 4 + .4 * lat))
    return x, SEA, z


def ray_hit(eye, ray, c, radius=RADIUS):
    length = math.sqrt(dot(ray, ray))
    if length <= 1e-5:
        return None
    ray = tuple(v / length for v in ray)
    offset = sub(eye, c)
    along = dot(offset, ray)
    disc = along * along - dot(offset, offset) + radius * radius
    if disc < 0:
        return None
    distance = -along - math.sqrt(max(0, disc))
    if distance <= 0:
        return None
    return tuple(e + v * distance for e, v in zip(eye, ray)), distance


def overlay_visible(point, eye, c):
    delta = sub(point, eye)
    distance = math.sqrt(dot(delta, delta))
    hit = ray_hit(eye, delta, c, RADIUS - .25)
    return hit is None or hit[1] - distance + .75 >= 0


def compile_helper():
    """Compile both stages without changing output mod or its validation files."""
    compiler = ctypes.WinDLL('d3dcompiler_47.dll')
    compiler.D3DCompile.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    compiler.D3DCompile.restype = ctypes.c_long

    def blob_bytes(ptr):
        vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        address = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(vtable[3])(ptr)
        size = ctypes.WINFUNCTYPE(ctypes.c_size_t, ctypes.c_void_p)(vtable[4])(ptr)
        return ctypes.string_at(address, size)

    def release(ptr):
        if ptr.value:
            table = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])(ptr)

    helper = Path(__file__).with_name('globe_projection_v3.fxh').read_text(encoding='utf-8')
    helper = helper[helper.index('[[') + 2:helper.rindex(']]')]
    prefix = f'''static const float MAP_SIZE_X={WIDTH};
static const float MAP_SIZE_Y={HEIGHT};
static const float WATER_HEIGHT={SEA};
cbuffer TestCamera {{float3 vCamPos; float3 vCamLookAtDir; float4x4 ViewProjectionMatrix;}}
'''
    entries = {
        'vs_5_0': '''float4 main(float4 p:POSITION):SV_Position {
            float3 q=HOI4GlobeObjectPosition(p.xyz,20);
            return HOI4GlobeProject(p)+0.000001*HOI4GlobeProjectWorld(q); }''',
        'ps_5_0': '''float4 main(float4 p:SV_Position):SV_Target {
            float4 h=HOI4GlobeRaySurface(p.xyz-vCamPos);
            float3 q=HOI4GlobeMapFromSurface(h.xyz);
            return float4(HOI4GlobeSurfaceVisibility(q),HOI4GlobeOverlayVisibility(q),
                HOI4GlobeSurfaceFade(q),HOI4GlobeReliefScale()); }'''
    }
    results = []
    for target, entry in entries.items():
        data = (prefix + helper + entry).encode()
        output, error = ctypes.c_void_p(), ctypes.c_void_p()
        hr = compiler.D3DCompile(data, len(data), b'globe_projection_v3.fxh', None, None,
                                 b'main', target.encode(), 1 << 11, 0,
                                 ctypes.byref(output), ctypes.byref(error))
        diagnostics = blob_bytes(error).decode(errors='replace') if error.value else ''
        results.append({'target': target, 'ok': hr >= 0,
                        'bytecode_bytes': len(blob_bytes(output)) if output.value else 0,
                        'diagnostics': diagnostics})
        release(output)
        release(error)
        assert hr >= 0, diagnostics
    return results


def main():
    rng = random.Random(41083)
    max_inverse_x = max_inverse_z = 0
    for _ in range(10000):
        flat = rng.uniform(0, WIDTH), SEA, rng.uniform(0, HEIGHT)
        focus = rng.uniform(0, WIDTH), rng.uniform(0, HEIGHT)
        restored = inverse(position(flat, focus, 850), focus)
        dx = abs(restored[0] - flat[0])
        dx = min(dx, WIDTH - dx)
        max_inverse_x = max(max_inverse_x, dx)
        max_inverse_z = max(max_inverse_z, abs(restored[2] - flat[2]))
    assert max_inverse_x < 1e-8 and max_inverse_z < 1e-8
    focus = WIDTH / 2, EQUATOR
    c = center(focus)
    eye = (c[0], c[1] + RADIUS + 1250, c[2])
    visible_cases = []
    for angle, altitude in ((0, 0), (30, 0), (60, 0), (70, 0), (90, 0), (120, 0), (180, 0), (70, 100)):
        n = (math.sin(math.radians(angle)), math.cos(math.radians(angle)), 0)
        point = tuple(cv + nv * (RADIUS + altitude) for cv, nv in zip(c, n))
        visible = overlay_visible(point, eye, c)
        visible_cases.append({'angle_degrees': angle, 'altitude': altitude, 'visible': visible})
        if angle <= 60:
            assert visible
        elif altitude == 0:
            assert not visible
        else:
            assert visible
    assert ray_hit(eye, (0, 1, 0), c) is None
    assert ray_hit(eye, (0, 0, 0), c) is None
    hit = ray_hit(eye, (0, -1, 0), c)
    assert hit and abs(hit[1] - 1250) < 1e-9
    assert abs(math.sqrt(dot(sub(hit[0], c), sub(hit[0], c))) - RADIUS) < 1e-9
    assert relief(50) == 1.85 and relief(180) == 1.85
    assert relief(700) == 1 and relief(3000) == 1
    assert all(relief(y + 1) <= relief(y) for y in range(50, 3000))
    ground = position((focus[0], 20, focus[1]), focus, 50)
    model_top = position((focus[0], 30, focus[1]), focus, 50, base_height=20)
    assert abs(math.sqrt(dot(sub(model_top, ground), sub(model_top, ground))) - 10) < 1e-9
    for y in (0, 5, SEA):
        a = position((focus[0], y, focus[1]), focus, 50)
        b = position((focus[0], y, focus[1]), focus, 3000)
        assert a == b
    result = {'inverse_surface_cases': 10000, 'max_inverse_x_map_error': max_inverse_x,
              'max_inverse_z_map_error': max_inverse_z, 'overlay_occlusion_cases': visible_cases,
              'ray_hit_miss_zero_checks': True, 'relief_monotonic_close_to_orbit': True,
              'submerged_geometry_unchanged': True, 'model_local_height_preserved_with_base_helper': True,
              'relief_scales': {str(y): relief(y) for y in (50, 180, 200, 350, 650, 700, 3000)},
              'standalone_helper_shader_compile': compile_helper(),
              'limits': 'Synthetic SM5 compile and math checks; actual game effect interfaces and culling need root integration validation'}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
