"""Projection-v2 numerical audit. Does not inject code into the game."""
import csv
import json
import math
import random
from pathlib import Path

WIDTH, HEIGHT, SEA = 5632.0, 2048.0, 9.5
RADIUS = WIDTH / (2 * math.pi)
SOUTH, NORTH = (0.17 - 0.5) * math.pi, (0.93 - 0.5) * math.pi
MS = 1.25 * math.log(math.tan(math.pi / 4 + 0.4 * SOUTH))
MN = 1.25 * math.log(math.tan(math.pi / 4 + 0.4 * NORTH))
EQUATOR = 672.0


def cropped_offset_latitude(z):
    t = min(1, max(0, z / HEIGHT))
    y = MS + (MN - MS) * t
    return 2.5 * math.atan(math.exp(0.8 * y)) - 0.625 * math.pi


def latitude(z):
    y = (min(HEIGHT, max(0, z)) - EQUATOR) / RADIUS
    return 2.5 * math.atan(math.exp(0.8 * y)) - 0.625 * math.pi


def normal(x, z, focus):
    lat, fl = latitude(z), latitude(focus[1])
    lon = (x - focus[0]) * 2 * math.pi / WIDTH
    cl, sl, cf, sf, cd = math.cos(lat), math.sin(lat), math.cos(fl), math.sin(fl), math.cos(lon)
    return cl * math.sin(lon), cl * cd * cf + sl * sf, sl * cf - cl * cd * sf


def position(x, y, z, focus):
    n = normal(x, z, focus)
    c = focus[0], SEA - RADIUS, focus[1]
    return tuple(ca + na * (RADIUS + y - SEA) for ca, na in zip(c, n))


def smoothstep(a, b, t):
    t = min(1, max(0, (t - a) / (b - a)))
    return t * t * (3 - 2 * t)


def footprint_ratio(camera_height):
    altitude = max(0, camera_height - SEA)
    d0 = altitude + RADIUS
    pullback = altitude * 0.5 * smoothstep(180, 650, altitude)
    d1 = d0 + pullback
    # Perspective silhouette size for a camera looking down at the focus.
    return math.sqrt(d0 * d0 - RADIUS * RADIUS) / math.sqrt(d1 * d1 - RADIUS * RADIUS)


def far_depth(depth, w=1):
    if w > .00001 and depth > .995:
        tail = depth - .995
        return .995 + tail / (1 + 200 * tail)
    return depth


def main():
    rng = random.Random(4108)
    max_norm_error = max_seam_error = max_focus_error = 0
    for _ in range(10000):
        x, z = rng.uniform(-WIDTH, 2 * WIDTH), rng.uniform(0, HEIGHT)
        focus = rng.uniform(-WIDTH, 2 * WIDTH), rng.uniform(0, HEIGHT)
        n = normal(x, z, focus)
        max_norm_error = max(max_norm_error, abs(sum(c * c for c in n) - 1))
        a, b = position(x, SEA, z, focus), position(x + WIDTH, SEA, z, focus)
        max_seam_error = max(max_seam_error, max(abs(ca - cb) for ca, cb in zip(a, b)))
        fp = position(focus[0], SEA, focus[1], focus)
        max_focus_error = max(max_focus_error, max(abs(a - b) for a, b in zip(fp, (focus[0], SEA, focus[1]))))
    assert max_norm_error < 1e-12
    assert max_seam_error < 1e-9
    assert max_focus_error < 1e-9
    assert abs(latitude(EQUATOR)) < 1e-12
    assert -math.pi / 2 < latitude(0) < 0 < latitude(HEIGHT) < math.pi / 2
    assert all(latitude(z + 1) > latitude(z) for z in range(int(HEIGHT)))
    depth_samples = (0, .1, .5, .994, .995, .996, .999, 1, 1.0001, 1.001, 2, 100)
    remapped = [far_depth(d) for d in depth_samples]
    assert all(a < b for a, b in zip(remapped, remapped[1:]))
    assert all(far_depth(d) == d for d in (-10, -.1, 0, .5, .994, .995))
    assert all(.995 < far_depth(d) < 1 for d in (.996, .999, 1, 1.001, 2, 100))
    assert all(far_depth(d, w) == d for d in depth_samples for w in (-1, 0, .000001))
    result = {
        'cases': 10000, 'radius': RADIUS,
        'stock_lighting_offset_bounds_degrees': [math.degrees(SOUTH), math.degrees(NORTH)],
        'equator_north_z': EQUATOR,
        'latitude_bounds_degrees': [math.degrees(latitude(0)), math.degrees(latitude(HEIGHT))],
        'max_normal_length_squared_error': max_norm_error,
        'max_seam_world_error': max_seam_error, 'max_focus_world_error': max_focus_error,
        'projection_latitudes': [{'fraction': t, 'old_full_equirect_degrees': (t - 0.5) * 180,
                                 'cropped_equirect_degrees': math.degrees(SOUTH + (NORTH - SOUTH) * t),
                                 'cropped_offset_inverse_miller_degrees': math.degrees(cropped_offset_latitude(t * HEIGHT)),
                                 'natural_scale_inverse_miller_degrees': math.degrees(latitude(t * HEIGHT))}
                                for t in (0, .25, .5, .65, .75, .85, 1)],
        'north_to_east_scale_ratios': [{'latitude_degrees': d,
                  'cropped_equirect': RADIUS * (NORTH - SOUTH) / HEIGHT / math.cos(math.radians(d)),
                  'cropped_offset_inverse_miller': RADIUS * (MN - MS) * math.cos(.8 * math.radians(d)) / HEIGHT / math.cos(math.radians(d)),
                  'natural_scale_inverse_miller': math.cos(.8 * math.radians(d)) / math.cos(math.radians(d))}
                  for d in (0, 30, 45, 60, 75)],
        'overview_perspective_diameter_ratios': {str(y): footprint_ratio(y) for y in (50, 200, 350, 650, 800, 900, 1500, 3000)},
        'depth_tail_samples': [{'original': d, 'remapped': far_depth(d)} for d in depth_samples],
        'depth_tail_validation': {'strictly_monotonic': True, 'near_depth_unchanged': True,
                                  'non_positive_w_unchanged': True, 'finite_far_depth_below_one': True,
                                  'limits': 'Native CPU frustum culling remains flat; depth fix only prevents GPU far clipping'},
        'limits': ['Native flat picking, culling, and overlays unchanged',
                   'Latitude choice approximates artistic map and is not a verified geodetic projection',
                   'Artwork covers cropped latitude band, so sphere caps need an independent backdrop',
                   'Diameter estimates assume camera down at focus; actual game pitch alters silhouette']
    }
    # Optional diagnostic: embedded province centroids of recognizable landmarks.
    from project_config import GAME as game
    if (game / 'map/provinces.bmp').exists():
        import numpy as np
        from PIL import Image
        # GeoNames dataset coordinates, accessed2026-10-08; used as visual fit audit.
        landmarks = {6521: ('Berlin', 52.52437, 'https://www.geonames.org/2950159/berlin.html'),
                     11506: ('Paris', 48.85341, 'https://www.geonames.org/2988507/paris.html'),
                     6050: ('Stockholm', 59.32938, 'https://www.geonames.org/2673730/stockholm.html'),
                     6103: ('London', 51.50853, 'https://www.geonames.org/2643743/london.html'),
                     1182: ('Tokyo', 35.68950, 'https://www.geonames.org/1850147/tokyo.html'),
                     12406: ('Sydney', -33.86785, 'https://www.geonames.org/2147714/sydney.html')}
        with (game / 'map/definition.csv').open(encoding='utf-8-sig') as handle:
            colors = {int(row[0]): tuple(int(v) for v in row[1:4]) for row in csv.reader(handle, delimiter=';') if row and row[0].isdigit() and int(row[0]) in landmarks}
        raster = np.array(Image.open(game / 'map/provinces.bmp').convert('RGB'))
        rows = []
        for province, (city, geo_lat, geo_source) in landmarks.items():
            yy, xx = np.nonzero(np.all(raster == colors[province], axis=2))
            z = HEIGHT - float(yy.mean()) - .5
            rows.append({'province': province, 'landmark': city, 'raster_centroid_x': float(xx.mean()),
                         'north_z': z, 'old_latitude_degrees': (z / HEIGHT - .5) * 180,
                         'cropped_equirect_degrees': math.degrees(SOUTH + (NORTH - SOUTH) * z / HEIGHT),
                         'cropped_offset_inverse_miller_degrees': math.degrees(cropped_offset_latitude(z)),
                         'natural_scale_inverse_miller_degrees': math.degrees(latitude(z)),
                         'geonames_latitude_degrees': geo_lat, 'geonames_source': geo_source,
                         'natural_miller_centroid_latitude_error': math.degrees(latitude(z)) - geo_lat,
                         'note': 'Province centroid, not exact city coordinate; no claim of geodetic validation'})
        result['landmark_diagnostic'] = rows
        result['landmark_latitude_rmse_degrees'] = {
            'old_full_equirect': math.sqrt(sum((r['old_latitude_degrees'] - r['geonames_latitude_degrees']) ** 2 for r in rows) / len(rows)),
            'cropped_equirect': math.sqrt(sum((r['cropped_equirect_degrees'] - r['geonames_latitude_degrees']) ** 2 for r in rows) / len(rows)),
            'cropped_offset_miller': math.sqrt(sum((r['cropped_offset_inverse_miller_degrees'] - r['geonames_latitude_degrees']) ** 2 for r in rows) / len(rows)),
            'natural_scale_miller': math.sqrt(sum((r['natural_scale_inverse_miller_degrees'] - r['geonames_latitude_degrees']) ** 2 for r in rows) / len(rows))
        }
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
