"""Prepare NOAA elevation geometry in work/ only; never install or mutate a mod.

Requires the bundled NumPy and Pillow. NOAA's stride-subset NetCDF3 file is
read directly, avoiding a raster/GIS dependency and a 456 MB global GeoTIFF.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import struct
import time
import urllib.request
import urllib.parse
from pathlib import Path

import numpy as np
from PIL import Image

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
from project_config import ROOT as BASE, GAME, OUT
WORK = BASE / "work"
DATASET = "ETOPO_2022_v1_60s"
ENDPOINT = "https://oceanwatch.pifsc.noaa.gov/erddap/griddap/" + DATASET
EARTH_RADIUS_METERS = 6_371_000.0
NC_TYPES = {1: ">i1", 2: "S1", 3: ">i2", 4: ">i4", 5: ">f4", 6: ">f8"}


def checked_work_path(path: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(WORK):
        raise ValueError(f"Preview/data path must stay inside work/: {path}")
    return path


def download(url: str, target: Path, max_bytes: int = 100_000_000) -> None:
    checked_work_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "Local-HOI4-DEM-preview/1.0"})
    total = 0
    start = time.monotonic()
    with urllib.request.urlopen(request, timeout=50) as response, temporary.open("wb") as out:
        if int(response.headers.get("Content-Length", "0")) > max_bytes:
            raise ValueError("Unexpectedly large response; use a coarser stride")
        while block := response.read(1024 * 1024):
            total += len(block)
            if total > max_bytes:
                raise ValueError("Response exceeded scoped download size")
            out.write(block)
    temporary.replace(target)
    print(json.dumps({"download": target.name, "bytes": total, "seconds": round(time.monotonic()-start, 1)}), flush=True)


class NetCDF3:
    """Minimal strict fixed-array reader for classic/64-bit-offset NetCDF3."""
    def __init__(self, path: Path):
        self.path = path
        self.stream = path.open("rb")
        signature = self.stream.read(4)
        if signature not in (b"CDF\x01", b"CDF\x02"):
            raise ValueError(f"Expected a NOAA NetCDF3 response; got {signature!r}")
        self.version = signature[3]
        if self.u32() != 0:
            raise ValueError("Record variables are deliberately unsupported")
        self.dimensions = self.list_header(10, self.dimension)
        self.attributes = self.list_header(12, self.attribute)
        self.variables = dict(self.list_header(11, self.variable))
        self.stream.close()

    def u32(self):
        return struct.unpack(">I", self.stream.read(4))[0]

    def name(self):
        count = self.u32()
        value = self.stream.read(count).decode("utf-8")
        self.stream.read((-count) % 4)
        return value

    def list_header(self, tag, read_item):
        actual, count = self.u32(), self.u32()
        if actual == 0 and count == 0:
            return []
        if actual != tag or count > 10_000:
            raise ValueError(f"Unexpected NetCDF header tag/count {actual}/{count}")
        return [read_item() for _ in range(count)]

    def dimension(self):
        name, size = self.name(), self.u32()
        if size == 0:
            raise ValueError("Unlimited dimension is unsupported")
        return name, size

    def attribute(self):
        name, kind, count = self.name(), self.u32(), self.u32()
        dtype = np.dtype(NC_TYPES[kind])
        raw = self.stream.read(count * dtype.itemsize)
        self.stream.read((-len(raw)) % 4)
        if kind == 2:
            return name, raw.decode("utf-8").rstrip("\0")
        values = np.frombuffer(raw, dtype=dtype).tolist()
        return name, values[0] if len(values) == 1 else values

    def variable(self):
        name = self.name()
        dimension_ids = [self.u32() for _ in range(self.u32())]
        attributes = dict(self.list_header(12, self.attribute))
        kind, size = self.u32(), self.u32()
        offset = self.u32() if self.version == 1 else struct.unpack(">Q", self.stream.read(8))[0]
        dimensions = [self.dimensions[i] for i in dimension_ids]
        return name, {"dimensions": dimensions, "attributes": attributes,
                      "dtype": NC_TYPES[kind], "vsize": size, "offset": offset}

    def array(self, name):
        var = self.variables[name]
        shape = tuple(size for _, size in var["dimensions"])
        dtype = np.dtype(var["dtype"])
        if var["offset"] + math.prod(shape) * dtype.itemsize > self.path.stat().st_size:
            raise ValueError(f"Truncated variable: {name}")
        return np.memmap(self.path, mode="r", dtype=dtype, offset=var["offset"], shape=shape)


def read_game_masks(game: Path):
    original = np.array(Image.open(game / "map/heightmap.bmp"), dtype=np.uint8)
    provinces = np.array(Image.open(game / "map/provinces.bmp"), dtype=np.uint32)
    if provinces.shape[:2] != original.shape:
        raise ValueError("Game height/province dimensions disagree")
    ids = (provinces[:, :, 0] << 16) | (provinces[:, :, 1] << 8) | provinces[:, :, 2]
    lookup = np.zeros(1 << 24, dtype=np.uint8)
    known = np.zeros(1 << 24, dtype=bool)
    with (game / "map/definition.csv").open(encoding="utf-8-sig") as stream:
        for row in csv.reader(stream, delimiter=";"):
            if len(row) < 5 or not row[0].isdigit():
                continue
            r, g, b = map(int, row[1:4])
            index = (r << 16) | (g << 8) | b
            known[index] = True
            lookup[index] = row[4] == "land"
    if not np.all(known[ids]):
        raise ValueError("Unknown province colors; do not infer water mask")
    return original, lookup[ids].astype(bool)


def inverse_miller(game_z, radius, equator_z):
    return np.degrees(2.5 * np.arctan(np.exp(0.8 * (game_z-equator_z)/radius)) - 5.0*np.pi/8.0)


def sample_dem(source: NetCDF3, width, height, greenwich_x, equator_z):
    lat = np.asarray(source.array("latitude"), dtype=np.float64)
    lon = np.asarray(source.array("longitude"), dtype=np.float64)
    elevation = source.array("z")
    if elevation.shape != (len(lat), len(lon)):
        raise ValueError("Unexpected DEM dimension order")
    if not np.all(np.diff(lat) > 0) or not np.all(np.diff(lon) > 0):
        raise ValueError("DEM axes must be ascending as NOAA advertises")
    if not np.allclose(np.diff(lat), np.diff(lat)[0], atol=1e-7) or not np.allclose(np.diff(lon), np.diff(lon)[0], atol=1e-7):
        raise ValueError("Expected a regularly strided DEM")
    radius = width / (2*np.pi)
    target_lat = inverse_miller(height - 1 - np.arange(height), radius, equator_z)
    target_lon = np.mod((np.arange(width)-greenwich_x)*360.0/width, 360.0)
    latitude_index = np.interp(target_lat, lat, np.arange(len(lat)))
    longitude_index = np.mod(target_lon-lon[0], 360.0) / np.diff(lon)[0]
    # ERDDAP index strides4/5 must divide21600 so cyclic longitude is uniform.
    if not math.isclose(len(lon)*np.diff(lon)[0], 360.0, abs_tol=1e-6):
        raise ValueError("Stride must divide21600 for seamless cyclic interpolation")
    x0 = np.floor(longitude_index).astype(int) % len(lon)
    x1 = (x0+1) % len(lon)
    fx = (longitude_index - np.floor(longitude_index)).astype(np.float32)
    output = np.empty((height, width), dtype=np.float32)
    for begin in range(0, height, 128):
        yf = latitude_index[begin:begin+128]
        y0 = np.floor(yf).astype(int)
        y1 = np.minimum(y0+1, len(lat)-1)
        fy = (yf-y0).astype(np.float32)[:, None]
        low = np.asarray(elevation[y0[:,None], x0[None,:]], dtype=np.float32)*(1-fx) + np.asarray(elevation[y0[:,None], x1[None,:]], dtype=np.float32)*fx
        high = np.asarray(elevation[y1[:,None], x0[None,:]], dtype=np.float32)*(1-fx) + np.asarray(elevation[y1[:,None], x1[None,:]], dtype=np.float32)*fx
        output[begin:begin+len(yf)] = low*(1-fy) + high*fy
    if not np.all(np.isfinite(output)) or np.min(output) <= -99_000:
        raise ValueError("Missing/non-finite NOAA elevations in game footprint")
    return output, target_lat, target_lon


def inset_distance(mask, steps):
    """Bounded Chebyshev distance, horizontally cyclic and vertically clamped."""
    remaining = mask.copy()
    distance = np.zeros(mask.shape, dtype=np.float32)
    for _ in range(steps):
        distance += remaining
        row_left, row_right = np.roll(remaining, 1, axis=1), np.roll(remaining, -1, axis=1)
        horizontal = remaining & row_left & row_right
        eroded = horizontal.copy()
        eroded[1:] &= horizontal[:-1]
        eroded[:-1] &= horizontal[1:]
        eroded[0] = eroded[-1] = False
        remaining = eroded
    return distance


def make_normals(candidate, original_land, original_normal):
    # HeightNormal is RGB at half dimensions, decoded .rbg in pdxmap.shader.
    size = original_normal.size
    native_height = Image.fromarray(candidate).resize(size, Image.Resampling.BILINEAR)
    values = np.asarray(native_height, dtype=np.float32)*0.1
    scale_x, scale_y = candidate.shape[1]/size[0], candidate.shape[0]/size[1]
    dx = (np.roll(values,-1,axis=1)-np.roll(values,1,axis=1))/(2*scale_x)
    dy = np.gradient(values, scale_y, axis=0)
    vectors = np.stack([-dx, dy, np.ones_like(dx)], axis=2)
    vectors /= np.linalg.norm(vectors, axis=2, keepdims=True)
    normal = np.clip(np.round((vectors*0.5+0.5)*255),0,255).astype(np.uint8)
    small_land = np.asarray(Image.fromarray(original_land.astype(np.uint8)*255).resize(size,Image.Resampling.NEAREST)) > 0
    original_array = np.asarray(original_normal, dtype=np.uint8)
    normal[~small_land] = original_array[~small_land]
    return Image.fromarray(normal), small_land


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game",type=Path,default=GAME)
    parser.add_argument("--stride",type=int,default=4)
    parser.add_argument("--out",type=Path,default=WORK/"dem-preview")
    parser.add_argument("--equator-z",type=float,default=672.0)
    parser.add_argument("--greenwich-x",type=float,default=2793.0)
    parser.add_argument("--vertical-exaggeration",type=float,default=8.0)
    parser.add_argument("--dem-blend",type=float,default=0.85)
    parser.add_argument("--coast-taper-pixels",type=int,default=10)
    parser.add_argument("--no-download",action="store_true")
    args = parser.parse_args()
    if args.stride < 3 or args.stride > 30 or 21600 % args.stride:
        raise ValueError("Use a stride3..30 dividing21600; default4 is ~58MB")
    if not 0 < args.vertical_exaggeration <= 12 or not 0 <= args.dem_blend <= 1:
        raise ValueError("Exaggeration/blend outside bounded preview range")
    if not 1 <= args.coast_taper_pixels <= 64:
        raise ValueError("Coast taper must be1..64pixels")
    out = checked_work_path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    data = WORK/"data/etopo"
    nc = data/f"{DATASET}_stride{args.stride}.nc"
    query = f"z[0:{args.stride}:10799][0:{args.stride}:21599]"
    source_url = ENDPOINT+".nc?"+urllib.parse.quote(query,safe=":,[]")
    if not nc.exists():
        if args.no_download:
            raise FileNotFoundError(nc)
        download(source_url,nc)
    if not (data/"metadata.das").exists() and not args.no_download:
        download(ENDPOINT+".das",data/"metadata.das",100_000)
    source = NetCDF3(nc)
    original, land = read_game_masks(args.game)
    height,width = original.shape
    if (width,height)!=(5632,2048):
        raise ValueError("This projection calibration is specific to stock5632×2048")
    dem,lat,lon = sample_dem(source,width,height,args.greenwich_x,args.equator_z)
    radius = width/(2*np.pi)
    # Verified byte-to-world conversion is0.1; meter mapping/exaggeration explicit.
    bytes_per_meter = radius/EARTH_RADIUS_METERS*args.vertical_exaggeration/0.1
    target = np.clip(95.0 + np.maximum(dem,0)*bytes_per_meter,96,254)
    game_inset = np.clip((inset_distance(land,args.coast_taper_pixels)-1)/max(1,args.coast_taper_pixels-1),0,1)
    real_inset = np.clip((inset_distance(dem>0,4)-1)/3,0,1)
    weight = args.dem_blend*game_inset*real_inset*land
    # Preserve existing low shore pixels as well as all sea/lake bytes.
    weight[original<=95] = 0
    candidate = np.clip(np.round(original.astype(np.float32)*(1-weight)+target*weight),0,255).astype(np.uint8)
    candidate[~land] = original[~land]
    if not np.array_equal(candidate[~land],original[~land]):
        raise AssertionError("Water heights changed")
    Image.fromarray(candidate).save(out/"heightmap.bmp")
    normal_source = Image.open(args.game/"map/world_normal.bmp").convert("RGB")
    normal,normal_land = make_normals(candidate,land,normal_source)
    normal.save(out/"world_normal.bmp")
    original_normal_array = np.asarray(normal_source)
    original_wet_median = np.median(original_normal_array[~normal_land],axis=0).tolist()
    # Scaled inspection images keep both original and candidate easy to review.
    Image.fromarray(original).resize((1408,512)).save(out/"original-height.png")
    Image.fromarray(candidate).resize((1408,512)).save(out/"candidate-height.png")
    shade = np.clip(np.stack([np.maximum(dem,0)/6000, np.maximum(dem,0)/3500, np.maximum(dem,0)/2200],axis=2),0,1)
    shade[~land] = [0.02,0.10,0.18]
    Image.fromarray((shade*255).astype(np.uint8)).resize((1408,512)).save(out/"sampled-elevation.png")
    checks = {
        "status":"workspace_preview_only",
        "source":"NOAA NCEI ETOPO2022 ice-surface elevation, not Google",
        "source_url":source_url,"metadata_url":ENDPOINT+".html",
        "source_sha256":hashlib.sha256(nc.read_bytes()).hexdigest(),
        "source_bytes":nc.stat().st_size,
        "source_dimensions":source.variables["z"]["dimensions"],
        "source_units":source.variables["z"]["attributes"].get("units"),
        "source_vertical_datum":source.variables["z"]["attributes"].get("vert_crs_name"),
        "game_heightmap_sha256":hashlib.sha256((args.game/"map/heightmap.bmp").read_bytes()).hexdigest(),
        "game_provinces_sha256":hashlib.sha256((args.game/"map/provinces.bmp").read_bytes()).hexdigest(),
        "projection":{"model":"natural-scale Miller","radius_map_units":radius,"greenwich_x":args.greenwich_x,"equator_z":args.equator_z,"latitude_bounds_degrees":[float(lat.min()),float(lat.max())]},
        "height_encoding":{"native_world_units_per_byte":0.1,"sea_level_byte":95,"earth_radius_meters":EARTH_RADIUS_METERS,"vertical_exaggeration_artistic":args.vertical_exaggeration,"bytes_per_meter":bytes_per_meter,"dem_blend":args.dem_blend,"coast_taper_pixels":args.coast_taper_pixels},
        "normal_encoding":{"dimensions":list(normal_source.size),"mode":"RGB","file_channels":["east/x","north/z","up/y"],"shader_channel_swizzle":"rbg","stock_wet_median_rgb":original_wet_median,"candidate_wet_median_rgb":np.median(np.asarray(normal)[~normal_land],axis=0).tolist(),"normal_derivative_spacing_map_pixels":[width/normal_source.width,height/normal_source.height]},
        "validation":{"finite_elevations":bool(np.isfinite(dem).all()),"dem_meters_min":float(dem.min()),"dem_meters_max":float(dem.max()),"water_pixels_unchanged":bool(np.array_equal(candidate[~land],original[~land])),"water_pixel_count":int((~land).sum()),"shore_bytes_below_or_equal95_unchanged":bool(np.array_equal(candidate[original<=95],original[original<=95])),"changed_land_pixels":int(np.count_nonzero(candidate!=original)),"game_land_pixels":int(land.sum()),"game_land_in_real_ocean_pixels":int(np.count_nonzero(land & (dem<=0))),"game_land_in_real_ocean_pixels_preserved":bool(np.array_equal(candidate[land & (dem<=0)],original[land & (dem<=0)])),"original_height_range":[int(original.min()),int(original.max())],"candidate_height_range":[int(candidate.min()),int(candidate.max())],"normal_water_pixels_unchanged":bool(np.array_equal(np.asarray(normal)[~normal_land],np.asarray(normal_source)[~normal_land]))},
        "game_files_modified":False,"mod_files_modified":False,
        "known_limits":["approximate stock-game projection calibration","game coastlines and province geography intentionally differ from Earth","ETOPO is elevation geometry, not satellite imagery","blend/taper retain stock geometry near shores and geographic mismatches"]}
    checks["generated_assets"] = {name:{"sha256":hashlib.sha256((out/name).read_bytes()).hexdigest(),"bytes":(out/name).stat().st_size} for name in ["heightmap.bmp","world_normal.bmp"]}
    checks["validation"]["stock_wet_up_normal_encoding_confirmed"] = original_wet_median == [128.0,128.0,255.0]
    (out/"dem-validation.json").write_text(json.dumps(checks,indent=2),encoding="utf-8")
    (out/"terrain-provenance.json").write_text(json.dumps(checks,indent=2),encoding="utf-8")
    print(json.dumps({"preview":str(out),"validation":checks["validation"]},indent=2),flush=True)


if __name__=="__main__":
    main()
