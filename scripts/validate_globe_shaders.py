"""Compile vertex and changed pixel programs with real D3DCompiler SM5.

Translates wrapper texture slots and effect defines; checks HLSL compatibility,
not the game's wrapper parser, runtime, or visual output.
"""
import ctypes
import json
import re
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
from project_config import ROOT as BASE, GAME, OUT
MOD = OUT / 'mod'
WORK = BASE / 'work/globe-shader-check'
PIXEL_PATHS = {'gfx/fx/pdxmap.shader', 'gfx/fx/pdxwater.shader',
               'gfx/fx/mapname.shader', 'gfx/fx/border.shader', 'gfx/fx/sky.shader',
               'gfx/fx/maparrow.shader', 'gfx/fx/river.shader', 'gfx/fx/strait.shader',
               'gfx/fx/traderoute.shader', 'gfx/models/supply/railroad.shader'}


def brace_end(text, start):
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if not depth:
                return i
    raise ValueError('Unbalanced shader wrapper')


def read_shader(relative):
    path = MOD / relative
    if not path.exists():
        path = GAME / relative
    text = path.read_text(encoding='utf-8-sig')
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'(?m)^\s*#\s*$', '', text)
    return re.sub(r'(?m)^(\s*)@(ifdef|ifndef|else|endif)', r'\1#\2', text)


def parse_samplers(text):
    result = []
    for match in re.finditer(r'\bSamplers\s*=\s*\{', text):
        opening = text.index('{', match.start())
        block = text[opening + 1:brace_end(text, opening)]
        cursor = 0
        while sampler := re.search(r'\b(\w+)\s*=\s*\{', block[cursor:]):
            name = sampler.group(1)
            opening = cursor + sampler.end() - 1
            ending = brace_end(block, opening)
            settings = block[opening + 1:ending]
            index = re.search(r'\bIndex\s*=\s*(\d+)', settings)
            if not index:
                raise ValueError(f'Sampler {name} is missing its wrapper Index')
            kind = re.search(r'\bType\s*=\s*"([^"]+)"', settings)
            result.append({'name': name, 'index': int(index.group(1)),
                           'type': kind.group(1) if kind else '2D'})
            cursor = ending + 1
    return result


def parse_effects(text):
    result = []
    for match in re.finditer(r'\bEffect\s+(\w+)\s*\{', text):
        opening = text.index('{', match.start())
        block = text[opening + 1:brace_end(text, opening)]
        row = {'name': match.group(1), 'defines': []}
        for stage in ('VertexShader', 'PixelShader'):
            binding = re.search(r'\b' + stage + r'\s*=\s*"([^"]+)"', block)
            if binding:
                row[stage] = binding.group(1)
        defines = re.search(r'\bDefines\s*=\s*\{([^}]*)\}', block)
        if defines:
            row['defines'] = re.findall(r'"([^"]+)"', defines.group(1))
        result.append(row)
    return result


def decode_file(relative, visited, declarations, entries, samplers):
    if relative in visited:
        return
    visited.add(relative)
    text = read_shader(relative)
    includes = re.search(r'Includes\s*=\s*\{(.*?)\}', text, re.S)
    if includes:
        for filename in re.findall(r'"([^"]+)"', includes.group(1)):
            decode_file('gfx/FX/' + filename, visited, declarations, entries, samplers)
    samplers.extend(parse_samplers(text))
    context, cursor, pending = [], 0, None
    token = re.compile(r'\b(?:VertexShader|PixelShader|Code|MainCode|VertexStruct|ConstantBuffer)\b|[{}]')
    while match := token.search(text, cursor):
        key, cursor = match.group(), match.end()
        stage = next((item for item in reversed(context)
                      if item in ('VertexShader', 'PixelShader')), None)
        if key in ('VertexShader', 'PixelShader'):
            pending = key
        elif key == '{':
            context.append(pending)
            pending = None
        elif key == '}':
            if context:
                context.pop()
        elif key == 'VertexStruct':
            name = re.match(r'\s*(\w+)', text[cursor:]).group(1)
            start = text.index('{', cursor)
            end = brace_end(text, start)
            declarations.append((None, 'struct ' + name + text[start:end + 1] + ';'))
            cursor = end + 1
        elif key == 'ConstantBuffer':
            start = text.index('{', cursor)
            end = brace_end(text, start)
            declarations.append((stage, f'cbuffer Buffer{len(declarations)} ' + text[start:end + 1] + ';'))
            cursor = end + 1
        elif key in ('Code', 'MainCode'):
            start = text.index('[[', cursor)
            end = text.index(']]', start)
            body = text[start + 2:end]
            if key == 'MainCode':
                name = re.match(r'\s*(\w+)', text[cursor:]).group(1)
                entries.append({'name': name, 'stage': stage, 'body': body, 'source': relative})
            else:
                declarations.append((stage, body))
            cursor = end + 2


def sampler_hlsl(samplers):
    rows, names = [], set()
    for row in samplers:
        name, index = row['name'], row['index']
        if name in names:
            raise ValueError(f'Duplicate sampler name {name}')
        names.add(name)
        cube = row['type'].lower() == 'cube'
        texture_type = 'TextureCube' if cube else 'Texture2D'
        struct_type = 'STextureSamplerCube' if cube else 'STextureSampler2D'
        rows.append(f'{texture_type} PDXTexture_{name} : register(t{index});')
        rows.append(f'SamplerState PDXSampler_{name} : register(s{index});')
        rows.append(f'static const {struct_type} {name} = '
                    + '{ PDXTexture_' + name + ', PDXSampler_' + name + ' };')
    return '\n'.join(rows)


def compiler_library():
    compiler = ctypes.WinDLL('d3dcompiler_47.dll')
    compiler.D3DCompile.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    compiler.D3DCompile.restype = ctypes.c_long
    return compiler


def blob_bytes(ptr):
    vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    address = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(vtable[3])(ptr)
    size = ctypes.WINFUNCTYPE(ctypes.c_size_t, ctypes.c_void_p)(vtable[4])(ptr)
    return ctypes.string_at(address, size)


def release(ptr):
    if ptr.value:
        vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])(ptr)


def compile_source(compiler, source, path, target):
    path.write_text(source, encoding='utf-8')
    data = source.encode('utf-8')
    output, error = ctypes.c_void_p(), ctypes.c_void_p()
    hr = compiler.D3DCompile(data, len(data), str(path).encode(), None, None, b'main',
        target.encode(), 1 << 11, 0, ctypes.byref(output), ctypes.byref(error))
    diagnostics = blob_bytes(error).decode('utf-8', errors='replace') if error.value else ''
    result = {'ok': hr >= 0, 'bytecode_bytes': len(blob_bytes(output)) if output.value else 0,
              'diagnostics': diagnostics}
    release(output)
    release(error)
    return result


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    compiler = compiler_library()
    manifest = json.loads((OUT / 'build-manifest.json').read_text())
    width, height = manifest['map_width'], manifest['map_height']
    dx11_defines = (GAME / 'gfx/FX/defines_hlsl_dx11.fxh').read_text(encoding='utf-8-sig')
    map_defines = f'#define MAP_SIZE_X {width}.0f\n#define MAP_SIZE_Y {height}.0f\n'
    for name, value in {'MAP_POW2_X': width / (1 << (width - 1).bit_length()),
                        'MAP_POW2_Y': height / (1 << (height - 1).bit_length()),
                        'FOW_POW2_X': 1.0, 'FOW_POW2_Y': 1.0}.items():
        map_defines += f'#define {name} {value}f\n'
    rows = list(manifest['files'])
    if (MOD / 'gfx/FX/sky.shader').exists() and not any(
            row['path'].lower() == 'gfx/fx/sky.shader' for row in rows):
        rows.append({'path': 'gfx/FX/sky.shader'})
    results = []
    for row in rows:
        if not row['path'].lower().endswith('.shader'):
            continue
        declarations, entries, samplers = [], [], []
        decode_file(row['path'], set(), declarations, entries, samplers)
        effects = parse_effects(read_shader(row['path']))
        for entry in entries:
            name, stage, body = entry['name'], entry['stage'], entry['body']
            if entry['source'] != row['path'] or 'Shadow' in name:
                continue
            if stage == 'VertexShader':
                variants, target = [([], ['default'])], 'vs_5_0'
            elif stage == 'PixelShader' and row['path'].lower() in PIXEL_PATHS:
                grouped = {}
                for effect in effects:
                    if effect.get(stage) == name:
                        grouped.setdefault(tuple(sorted(effect['defines'])), []).append(effect['name'])
                variants = [(list(key), effect_names) for key, effect_names in grouped.items()]
                if not variants:
                    variants = [([], ['unbound'])]
                target = 'ps_5_0'
            else:
                continue
            for effect_defines, effect_names in variants:
                configuration = ['GRADIENT_BORDERS'] + effect_defines if stage == 'PixelShader' else effect_defines
                source = map_defines + ''.join('#define ' + define + '\n' for define in configuration)
                source += dx11_defines + '\n'
                if stage == 'PixelShader':
                    source += sampler_hlsl(samplers) + '\n'
                source += '\n'.join(code for scope, code in declarations
                                    if scope is None or scope == stage) + '\n' + body
                variant = '__'.join(effect_names)
                path = WORK / (Path(row['path']).stem + '_' + name + '_' + target + '_' + variant + '.hlsl')
                record = {'path': row['path'], 'entry': name, 'target': target, 'effects': effect_names,
                          'defines': configuration, 'samplers': samplers if stage == 'PixelShader' else []}
                record.update(compile_source(compiler, source, path, target))
                results.append(record)
                print(json.dumps({key: value for key, value in record.items() if key != 'samplers'}))
    validation = {'scope': 'Direct3D 11 SM5 vertex and modified pixel HLSL compilation; '
                           'wrapper texture slots and effect defines translated; game parser/runtime not verified',
                  'passed': bool(results) and all(row['ok'] for row in results), 'programs': len(results),
                  'vertex_programs': sum(row['target'] == 'vs_5_0' for row in results),
                  'pixel_programs': sum(row['target'] == 'ps_5_0' for row in results), 'results': results}
    (OUT / 'shader-validation.json').write_text(json.dumps(validation, indent=2), encoding='utf-8')
    raise SystemExit(0 if validation['passed'] else 1)


if __name__ == '__main__':
    main()
