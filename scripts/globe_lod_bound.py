"""Native primary-only distance pyramid and conservative full-map patch bound.

Read-only mathematical reconstruction of FUN_1412812c0, no process access.
All tests use stored camera Y=25.5, minimizing the nonnegative vertical term.
Real height and near-patch skipping can only reduce the number of leaves.
"""
from pathlib import Path
import json
import math
import numpy as np


def patches(x, z):
    gx=np.arange(89,dtype=np.float64)*64
    gz=np.arange(33,dtype=np.float64)*64
    vertex=(gx[None,:]-x)**2+(gz[:,None]-z)**2
    base=np.minimum.reduce([vertex[:-1,:-1],vertex[1:,:-1],vertex[:-1,1:],vertex[1:,1:]])
    d2=base.reshape(16,2,44,2).min(axis=(1,3))
    d4=d2.reshape(8,2,22,2).min(axis=(1,3))
    d8=d4.reshape(4,2,11,2).min(axis=(1,3))
    split8=d8<=750**2
    split4=(d4<=350**2)&np.repeat(np.repeat(split8,2,axis=0),2,axis=1)
    split2=(d2<=150**2)&np.repeat(np.repeat(split4,2,axis=0),2,axis=1)
    splits=[int(split8.sum()),int(split4.sum()),int(split2.sum())]
    return 44+3*sum(splits),splits


if __name__=="__main__":
    per_level=[(int(math.floor(2*r/side))+2)**2 for r,side in [(750,512),(350,256),(150,128)]]
    assert per_level==[16,16,16]
    bound=44+3*sum(per_level)
    maximum=0; where=None; maxima=[0,0,0]; tested=0
    # Cell phase, map edge, off-map and interior coverage; not the proof itself.
    coordinates_x=np.concatenate([np.arange(-512,513,16),np.arange(2048,2561,8),np.arange(5120,6145,16)])
    coordinates_z=np.concatenate([np.arange(-512,513,32),np.arange(768,1281,8),np.arange(1536,2561,32)])
    for x in coordinates_x:
        for z in coordinates_z:
            count,splits=patches(x,z);tested+=1
            assert count<=bound and all(s<=b for s,b in zip(splits,per_level))
            maxima=[max(a,b) for a,b in zip(maxima,splits)]
            if count>maximum: maximum=count;where=[float(x),float(z)]
    out={"map_tiles":[88,32],"max_step":8,"wraps_enabled":False,
         "distance_thresholds":[750,350,150],"block_sides":[512,256,128],
         "conservative_split_bounds":per_level,"conservative_patch_bound":bound,
         "triangles_per_patch":8192,"conservative_triangles_per_pass":bound*8192,
         "sampled_camera_positions":tested,"sampled_maximum_patches":maximum,
         "sampled_maximum_position":where,"sampled_maximum_splits_by_level":maxima,
         "proof":"44 quadtree roots; each split adds 3 leaves; at most 16 blocks intersect each threshold disk's axis-aligned bounding square.",
         "limits":"Primary-only copied camera, unmodified native thresholds/maxLOD=3/map dimensions; runtime CPU/GPU cost remains unmeasured."}
    (Path(__file__).resolve().parent.parent/"work/globe-lod-bound.json").write_text(json.dumps(out,indent=2)+"\n")
    print(json.dumps(out,indent=2))
