"""Build a continuous geographic BGRA8 cubemap candidate for the globe sky pass.

Writes only the requested candidate folder. Does not install or modify game/mod assets.
Geographic directions are +Y north, +Z Greenwich, +X 90 degrees east.
"""
import argparse
import csv
import hashlib
import json
import math
import struct
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCRIPT = Path(__file__).resolve().parent
from project_config import ROOT as BASE, GAME, OUT
PREVIEW = BASE / 'work/backdrop-preview'
SOURCE_URL = 'https://assets.science.nasa.gov/content/dam/science/esd/eo/images/bmng/bmng-base/january/world.200401.3x5400x2700.jpg'
SOURCE_PAGE = 'https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/base-map/'
CREDIT_PAGE = 'https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/'
USAGE_PAGE = 'https://www.nasa.gov/nasa-brand-center/images-and-media/'
SOURCE_SHA256 = '99f5faad74efe985fbf1714c8be7296ca9999759a1215b65f99b7f1df278dde5'
FACE_NAMES = ['px', 'nx', 'py', 'ny', 'pz', 'nz']
OCEAN = np.array([0.0035, 0.028, 0.066], dtype=np.float32)
COLOR_SCALE = np.array([0.91, 1.03, 0.90], dtype=np.float32)
GREENWICH_X = 2793.0
EQUATOR_Z = 672.0
# HOI4 1.19.3.0 FUN_142407cb0 allows texture file lengths <= 0x1000000.
# This is a file buffer limit, distinct from the DDS face dimensions.
NATIVE_TEXTURE_FILE_LIMIT = 16_777_216


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def smoothstep(start, end, value):
    fraction = np.clip((value-start)/(end-start), 0, 1)
    return fraction*fraction*(3-2*fraction)


def face_direction(face, u, v):
    """Direct3D top-to-bottom image UVs, with a right-handed geographic basis."""
    s, t = 2*np.asarray(u)-1, 2*np.asarray(v)-1
    one = np.ones_like(s)
    axes = [(one, -t, -s), (-one, -t, s), (s, one, t),
            (s, -one, -t), (s, -t, one), (-s, -t, -one)]
    direction = np.stack(axes[face], axis=-1)
    return direction/np.linalg.norm(direction, axis=-1, keepdims=True)


def direction_face_uv(direction):
    x, y, z = np.asarray(direction, dtype=np.float64)
    major = int(np.argmax(np.abs([x, y, z])))
    if major == 0:
        face, s, t = (0, -z/x, -y/x) if x >= 0 else (1, z/-x, -y/-x)
    elif major == 1:
        face, s, t = (2, x/y, z/y) if y >= 0 else (3, x/-y, -z/-y)
    else:
        face, s, t = (4, x/z, -y/z) if z >= 0 else (5, -x/-z, -y/-z)
    return face, (s+1)*0.5, (t+1)*0.5


def geographic_direction(longitude, latitude):
    lon, lat = np.radians(longitude), np.radians(latitude)
    return np.array([np.cos(lat)*np.sin(lon), np.sin(lat), np.cos(lat)*np.cos(lon)])


def bilinear(image, x, y, wrap_x=True):
    height, width = image.shape[:2]
    x = np.mod(x, width) if wrap_x else np.clip(x, 0, width-1)
    y = np.clip(y, 0, height-1)
    x0, y0 = np.floor(x).astype(np.int32), np.floor(y).astype(np.int32)
    x1 = (x0+1) % width if wrap_x else np.minimum(x0+1, width-1)
    y1 = np.minimum(y0+1, height-1)
    ax = np.asarray(x-x0, dtype=np.float32)[..., None]
    ay = np.asarray(y-y0, dtype=np.float32)[..., None]
    return ((image[y0, x0]*(1-ax)+image[y0, x1]*ax)*(1-ay)
            + (image[y1, x0]*(1-ax)+image[y1, x1]*ax)*ay)


def read_land_mask(game):
    provinces = np.array(Image.open(game/'map/provinces.bmp'), dtype=np.uint8)
    ids = (provinces[:, :, 0].astype(np.uint32) << 16)
    ids |= provinces[:, :, 1].astype(np.uint32) << 8
    ids |= provinces[:, :, 2]
    del provinces
    known, land = np.zeros(1 << 24, bool), np.zeros(1 << 24, bool)
    with (game/'map/definition.csv').open(encoding='utf-8-sig') as stream:
        for row in csv.reader(stream, delimiter=';'):
            if len(row) < 5 or not row[0].isdigit():
                continue
            red, green, blue = map(int, row[1:4])
            index = (red << 16) | (green << 8) | blue
            known[index], land[index] = True, row[4] == 'land'
    if not np.all(known[ids]):
        raise ValueError('Unknown province color; sea mask cannot be inferred safely')
    return land[ids]


class BackdropMaterial:
    def __init__(self, game, nasa_path):
        self.game = game
        self.land = read_land_mask(game)
        self.height, self.width = self.land.shape
        if (self.width, self.height) != (5632, 2048):
            raise ValueError('Installed map dimensions differ from the inspected calibration')
        self.radius = self.width/(2*math.pi)
        self.stock = np.asarray(Image.open(game/'map/terrain/colormap_rgb_cityemissivemask_a.dds').convert('RGB'))
        self.nasa = np.asarray(Image.open(nasa_path).convert('RGB'))
        if self.nasa.shape != (2700, 5400, 3):
            raise ValueError('NASA source dimensions differ from the verified January asset')

    def coordinates(self, direction):
        direction = np.asarray(direction)
        longitude = np.arctan2(direction[..., 0], direction[..., 2])
        latitude = np.arcsin(np.clip(direction[..., 1], -1, 1))
        map_x = np.mod(GREENWICH_X + self.radius*longitude, self.width)
        projected = np.log(np.tan(math.pi/4 + latitude*0.4))/0.8
        map_z = EQUATOR_Z + self.radius*projected
        return longitude, latitude, map_x, map_z

    def sample(self, direction):
        longitude, latitude, map_x, map_z = self.coordinates(direction)
        nx = (longitude/(2*math.pi)+0.5)*self.nasa.shape[1]-0.5
        ny = (0.5-latitude/math.pi)*self.nasa.shape[0]-0.5
        nasa_gamma = bilinear(self.nasa, nx, ny)/255.0
        nasa_color = np.power(np.clip(nasa_gamma, 0, 1), 2.2)
        # BMNG's dark blue ocean is replaced by the shader's exact material albedo.
        nasa_sea = ((nasa_gamma[..., 2] > np.maximum(nasa_gamma[..., 0], nasa_gamma[..., 1])*1.7)
                    & (nasa_gamma[..., 2] > 0.04))
        nasa_color = np.where(nasa_sea[..., None], OCEAN, nasa_color)

        stock_x = (map_x+0.5)*self.stock.shape[1]/self.width-0.5
        stock_y = (self.height-map_z-0.5)*self.stock.shape[0]/self.height-0.5
        stock_color = bilinear(self.stock, stock_x, stock_y)/255.0*COLOR_SCALE
        stock_color = np.maximum(stock_color, [0.006, 0.009, 0.004])
        ix = np.floor(map_x+0.5).astype(np.int32) % self.width
        iy = np.clip(np.floor(self.height-1-map_z+0.5), 0, self.height-1).astype(np.int32)
        stock_color = np.where(self.land[iy, ix][..., None], stock_color, OCEAN)
        # Match the native band exactly. Extend only its edge colors 32 map units
        # outside the cropped art, then transition smoothly to real polar geography.
        distance_outside = np.maximum(np.maximum(-map_z, map_z-self.height), 0)
        stock_weight = 1-smoothstep(0, 32, distance_outside)
        return np.clip(stock_color*stock_weight[..., None] + nasa_color*(1-stock_weight[..., None]), 0, 1)


def rgba_bytes(material):
    rgb = np.rint(np.clip(material, 0, 1)*255).astype(np.uint8)
    return np.concatenate([rgb, np.full(rgb.shape[:2]+(1,), 255, np.uint8)], axis=2)


def dds_header(size, mip_count):
    words = [124, 0x2100f, size, size, size*4, 0, mip_count] + [0]*11
    words += [32, 0x41, 0, 32, 0xff0000, 0xff00, 0xff, 0xff000000]
    words += [0x401008, 0xfe00, 0, 0, 0]
    if len(words) != 31:
        raise AssertionError('Invalid DDS header word count')
    return b'DDS ' + struct.pack('<31I', *words)


def write_dds(path, faces):
    size = faces[0].shape[0]
    mip_count = size.bit_length()
    records = []
    with path.open('wb') as stream:
        stream.write(dds_header(size, mip_count))
        for face_index, face in enumerate(faces):
            image = Image.fromarray(face, 'RGBA')
            for level in range(mip_count):
                pixels = np.asarray(image)
                data = pixels[:, :, [2, 1, 0, 3]].tobytes()
                records.append({'face': FACE_NAMES[face_index], 'level': level,
                                'size': image.width, 'sha256': hashlib.sha256(data).hexdigest()})
                stream.write(data)
                if image.width > 1:
                    image = image.resize((image.width//2, image.height//2), Image.Resampling.BOX)
    return records


def verify_dds(path, faces, records):
    data = path.read_bytes()
    words = struct.unpack('<31I', data[4:128])
    assert data[:4] == b'DDS ' and words[27] == 0xfe00
    assert words[2] == words[3] == faces[0].shape[0]
    assert words[19] == 0x41 and words[22:26] == (0xff0000, 0xff00, 0xff, 0xff000000)
    offset = 128
    for record in records:
        length = record['size']**2*4
        chunk = data[offset:offset+length]
        assert hashlib.sha256(chunk).hexdigest() == record['sha256']
        if record['level'] == 0:
            decoded = np.frombuffer(chunk, np.uint8).reshape(record['size'], record['size'], 4)
            assert np.array_equal(decoded[:, :, [2, 1, 0, 3]], faces[FACE_NAMES.index(record['face'])])
        offset += length
    assert offset == len(data)
    with Image.open(path) as decoded:
        assert decoded.mode == 'RGBA' and decoded.size == (words[3], words[2])
        assert np.array_equal(np.asarray(decoded), faces[0])
    return {'all_face_mip_hashes_match': True, 'base_faces_roundtrip_exact': True,
            'pillow_base_face_roundtrip_exact': True, 'caps2': '0xfe00', 'bytes': len(data)}


def verify_mapping(material, faces):
    rng = np.random.default_rng(1936)
    maximum = 0.0
    for direction in rng.normal(size=(2000, 3)):
        direction /= np.linalg.norm(direction)
        face, u, v = direction_face_uv(direction)
        maximum = max(maximum, float(np.max(np.abs(face_direction(face, u, v)-direction))))
    assert maximum < 1e-12
    axis_signs = np.array([1, -1, 1, -1, 1, -1])[:, None]
    for face, axis in enumerate(np.eye(3)[[0, 0, 1, 1, 2, 2]]*axis_signs):
        assert np.allclose(face_direction(face, 0.5, 0.5), axis)
    landmarks = {'Berlin': (13.4, 52.5), 'Cairo': (31.2, 30.0), 'Amazon interior': (-60.0, -5.0),
                 'Greenland interior': (-42.0, 75.0), 'Antarctica': (0.0, -85.0),
                 'Atlantic ocean': (-25.0, 0.0)}
    samples = []
    maximum_color_error = 0.0
    for name, (longitude, latitude) in landmarks.items():
        direction = geographic_direction(longitude, latitude)
        face, u, v = direction_face_uv(direction)
        value = bilinear(faces[face][:, :, :3], np.asarray(u*faces[face].shape[1]-0.5),
                         np.asarray(v*faces[face].shape[0]-0.5), wrap_x=False)/255.0
        expected = material.sample(direction)
        error = float(np.max(np.abs(value-expected)))
        maximum_color_error = max(maximum_color_error, error)
        _, _, x, z = material.coordinates(direction)
        samples.append({'name': name, 'longitude': longitude, 'latitude': latitude,
                        'face': FACE_NAMES[face], 'uv': [float(u), float(v)],
                        'map_xz': [float(x), float(z)], 'rgb': value.tolist(),
                        'material_sampling_error': error})
    assert maximum_color_error < 0.10
    return {'random_direction_roundtrips': 2000, 'max_direction_error': maximum,
            'axis_centers_verified': True, 'landmarks': samples,
            'max_landmark_color_sampling_error': maximum_color_error}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', type=int, choices=[512, 1024], default=512)
    parser.add_argument('--game', type=Path, default=GAME)
    parser.add_argument('--out', type=Path, default=PREVIEW)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    source = args.out/'world.200401.3x5400x2700.jpg'
    if not source.exists():
        request = urllib.request.Request(SOURCE_URL, headers={'User-Agent': 'HOI4-local-globe-backdrop/1.0'})
        with urllib.request.urlopen(request, timeout=60) as response, source.open('wb') as target:
            while chunk := response.read(1024*1024):
                target.write(chunk)
    if digest(source) != SOURCE_SHA256:
        raise ValueError('NASA January source hash differs from the inspected official asset')
    material = BackdropMaterial(args.game, source)
    coordinate = (np.arange(args.size, dtype=np.float64)+0.5)/args.size
    u, v = np.meshgrid(coordinate, coordinate)
    faces = [rgba_bytes(material.sample(face_direction(face, u, v))) for face in range(6)]
    target = args.out/'reflection.dds'
    records = write_dds(target, faces)
    validation = verify_dds(target, faces, records)
    validation.update(verify_mapping(material, faces))
    validation['native_texture_file_size_limit_bytes'] = NATIVE_TEXTURE_FILE_LIMIT
    validation['within_native_texture_file_size_limit'] = target.stat().st_size <= NATIVE_TEXTURE_FILE_LIMIT
    sheet = Image.new('RGB', (1536, 1072), (8, 12, 20))
    draw, font = ImageDraw.Draw(sheet), ImageFont.load_default(size=24)
    for index, face in enumerate(faces):
        Image.fromarray(face, 'RGBA').save(args.out/f'face_{FACE_NAMES[index]}.png')
        display = np.rint(np.power(face[:, :, :3]/255.0, 1/2.2)*255).astype(np.uint8)
        preview = Image.fromarray(display).resize((512, 512), Image.Resampling.LANCZOS)
        position = ((index % 3)*512, (index//3)*536)
        sheet.paste(preview, (position[0], position[1]+24))
        draw.text(position, FACE_NAMES[index], font=font, fill=(230, 237, 245))
    sheet.save(args.out/'face-contact-sheet.png')
    # Global material preview: display gamma only, DDS stores scene albedo values.
    longitude, latitude = np.meshgrid(np.linspace(-180, 180, 1800, endpoint=False),
                                     np.linspace(90, -90, 900))
    lon, lat = np.radians(longitude), np.radians(latitude)
    direction = np.stack([np.cos(lat)*np.sin(lon), np.sin(lat), np.cos(lat)*np.cos(lon)], axis=-1)
    global_rgb = np.rint(np.power(material.sample(direction), 1/2.2)*255).astype(np.uint8)
    Image.fromarray(global_rgb).save(args.out/'global-material-preview.png')
    provenance = {'status': 'workspace_candidate_not_installed', 'kind': 'color_backdrop_not_terrain_geometry',
        'credit': 'NASA Earth Observatory / NASA Goddard Space Flight Center / Reto Stöckli',
        'source_url': SOURCE_URL, 'source_page': SOURCE_PAGE, 'credit_page': CREDIT_PAGE,
        'usage_guidelines': USAGE_PAGE, 'source_sha256': digest(source),
        'source_dimensions': [5400, 2700], 'source_month': 'January 2004',
        'stock_sources': {path: digest(args.game/path) for path in ['map/terrain/reflection.dds',
            'map/terrain/colormap_rgb_cityemissivemask_a.dds', 'map/provinces.bmp', 'map/definition.csv']},
        'projection': {'radius': material.radius, 'greenwich_x': GREENWICH_X,
            'equator_z': EQUATOR_Z, 'model': 'natural-scale Miller', 'outside_edge_blend_map_units': 32},
        'cube': {'size': args.size, 'format': 'BGRA8_UNORM', 'caps2': '0xfe00',
            'face_order': FACE_NAMES, 'mip_count': args.size.bit_length(),
            'geographic_basis': {'north': '+Y', 'greenwich': '+Z', 'east_90': '+X'},
            'sha256': digest(target), 'bytes': target.stat().st_size},
        'material_encoding': 'Stock biome bytes scaled like globe materials; NASA RGB converted from display gamma with power2.2; sea material albedo supplied directly.',
        'validation': validation, 'game_files_modified': False, 'mod_files_modified': False,
        'native_texture_file_limit': {'bytes': NATIVE_TEXTURE_FILE_LIMIT,
            'inspected_function': 'FUN_142407cb0',
            'condition': 'file length < 0x1000001',
            'runtime_evidence': '1024-face 33,554,552-byte candidate rejected by texturehandler.cpp:233; 512-face candidate uses 8,388,728 bytes'},
        'limitations': ['Static January color backdrop does not create missing province geography or terrain relief.',
            'Native dynamic political fills and weather/snow cannot be reconstructed in this static cubemap.',
            'Game geography is artistic, so the transition to real NASA polar coastlines is approximate.',
            'reflection.dds can be shared by other model reflection paths; verify after parent integration.']}
    (args.out/'backdrop-provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    print(json.dumps({'candidate': str(target), 'face_size': args.size, 'bytes': target.stat().st_size,
                      'sha256': digest(target), 'direction_error': validation['max_direction_error'],
                      'landmark_sampling_error': validation['max_landmark_color_sampling_error']}, indent=2))


if __name__ == '__main__':
    main()
