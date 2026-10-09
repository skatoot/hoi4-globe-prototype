"""Exercise exported camera validation from the actual compiled bridge DLL."""
import ctypes
import hashlib
import json
import math
from pathlib import Path

SCRIPT_DIRECTORY=Path(__file__).resolve().parent
from project_config import ROOT as BASE, GAME, OUT
DLL = OUT / 'native/hoi4_globe_native.dll'
bridge = ctypes.WinDLL(str(DLL))
Float = ctypes.c_float
bridge.GlobeTestCamera.argtypes = [ctypes.POINTER(Float), ctypes.POINTER(Float)]
bridge.GlobeTestCamera.restype = ctypes.c_int

def dot(a,b): return sum(x*y for x,y in zip(a,b))
def cross(a,b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def unit(a):
    length=math.sqrt(dot(a,a))
    return tuple(x/length for x in a)

def fixture(eye, forward):
    f=unit(forward); right=unit(cross((0,1,0),f)); up=cross(f,right)
    sx,sy,zf,zn=1.1,1.8,3000/2999.9,-.1*3000/2999.9
    matrix=(Float*72)()
    for i in range(3):
        matrix[4*i]=sx*right[i];matrix[4*i+1]=sy*up[i]
        matrix[4*i+2]=zf*f[i];matrix[4*i+3]=f[i]
    matrix[12]=-sx*dot(right,eye);matrix[13]=-sy*dot(up,eye)
    matrix[14]=-zf*dot(f,eye)+zn;matrix[15]=-dot(f,eye)
    for i in range(3):matrix[64+i]=eye[i];matrix[67+i]=eye[i]+f[i]*100
    return matrix,f

cases=[]
for eye,direction in [((2800,850,1200),(0,-1,-.2)),((1200,65,1500),(.3,-1,-.4)),((4500,3000,400),(-.2,-1,.1))]:
    matrix,f=fixture(eye,direction);out=(Float*6)()
    assert bridge.GlobeTestCamera(matrix,out)==1
    assert max(abs(out[i]-eye[i]) for i in range(3))<.001
    assert max(abs(out[i+3]-f[i]) for i in range(3))<.00001
    cases.append({'eye':eye,'accepted':True})
    matrix[64]+=100;matrix[67]+=100
    assert bridge.GlobeTestCamera(matrix,out)==0, 'stale camera must fail'
    matrix,_=fixture(eye,direction);matrix[67]=float('nan')
    assert bridge.GlobeTestCamera(matrix,out)==0
    matrix,f=fixture(eye,direction)
    for i in range(3):matrix[67+i]=eye[i]-f[i]*100
    assert bridge.GlobeTestCamera(matrix,out)==0

result={'passed':True,'scope':'Actual DLL camera ABI/matrix coherence validation with synthetic perspective fixtures; no live game visual verification',
        'accepted_camera_fixtures':cases,'stale_eye_nan_and_reversed_direction_rejected':True,
        'dll_sha256':hashlib.sha256(DLL.read_bytes()).hexdigest()}
(OUT/'native-camera-validation.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
