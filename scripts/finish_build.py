"""Record locally generated native binaries alongside the generated mod."""
import hashlib
import json
from project_config import OUT

path=OUT/'build-manifest.json'
manifest=json.loads(path.read_text(encoding='utf-8'))
files=[]
for name in ['hoi4_globe_native.dll','globe_launcher.exe']:
    binary=OUT/'native'/name
    files.append({'path':'native/'+name,'sha256':hashlib.sha256(binary.read_bytes()).hexdigest()})
manifest['native_bridge']={'version':'0.3','targeted_call_count':7,
    'scope':'Map-icon grounding/projection, terrain LOD visibility, province visibility and country-label culling',
    'gameplay_rules_changed':False,'mouse_picking_integrated':False,'files':files}
manifest['known_missing_native_features']=['Native mouse picking and order painting',
    'Other screen-space projection paths and model-preview effects',
    'Campaign visual inspection and frame-time measurement']
path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print('Recorded native build hashes; generated output stays local and ignored by Git.')
