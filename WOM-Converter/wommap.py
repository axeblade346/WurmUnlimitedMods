"""Match the game's mappings.txt against a folder, and build texture/material variants.

mappings.txt lines:   key = path/to/file.wom?MatName.texture=x.dds&MatName.specular=r,g,b,a&MatName.shininess=n
Comments start with # or //. One .wom is often reused with different textures per item ("variants").
"""
import os
import re

PROPS = ('texture', 'specular', 'shininess', 'emissive')


def parse_mappings(path):
    """-> list of dicts: line_no, raw, key, file, overrides{mat:{prop:value}}, section"""
    out, section = [], ''
    with open(path, encoding='utf-8', errors='replace') as f:
        for n, raw in enumerate(f, 1):
            line = raw.rstrip('\r\n')
            s = line.strip()
            if not s:
                continue
            if s.startswith('#') or s.startswith('//'):
                t = s.lstrip('#/ ').strip(' -#')
                if t and '=' not in s and not re.match(r'^[a-z]+(\.[\w-]+)+$', t):
                    section = s
                continue
            if '=' not in s:
                continue
            key, val = s.split('=', 1)
            key, val = key.strip(), val.strip()
            file_, _, q = val.partition('?')
            ov = {}
            if q:
                for part in q.split('&'):
                    if '=' not in part:
                        continue
                    k, v = part.split('=', 1)
                    mat, _, prop = k.strip().rpartition('.')
                    ov.setdefault(mat, {})[prop] = v.strip()
            out.append({'line': n, 'raw': line, 'key': key, 'file': file_.strip().replace('\\', '/'),
                        'overrides': ov, 'section': section})
    return out


def index_folder(root):
    """lowercase relative path -> real relative path (forward slashes)"""
    idx = {}
    for dp, dns, fs in os.walk(root):
        for f in fs:
            rel = os.path.relpath(os.path.join(dp, f), root).replace(os.sep, '/')
            idx[rel.lower()] = rel
    return idx


def best_prefix(entries, idx):
    """The folder may be a sub-folder of the game root (e.g. 'player'): find the mapping-path prefix
    that, once removed, makes the most mapping files exist in the folder."""
    counts = {}
    for e in entries:
        parts = e['file'].split('/')
        for i in range(len(parts)):
            pre = '/'.join(parts[:i]) + ('/' if i else '')
            if '/'.join(parts[i:]).lower() in idx:
                counts[pre.lower()] = counts.get(pre.lower(), 0) + 1
    if not counts:
        return None, 0
    pre = max(counts, key=lambda p: (counts[p], -len(p)))
    return pre, counts[pre]


def match(entries, root, prefix=None):
    idx = index_folder(root)
    if prefix is None:
        prefix, _ = best_prefix(entries, idx)
    prefix = (prefix or '').lower()
    matched, missing = [], []
    for e in entries:
        f = e['file'].lower()
        if not f.startswith(prefix):
            continue
        rel = idx.get(f[len(prefix):])
        if rel:
            matched.append(dict(e, rel=rel))
        elif '/' in e['file'] or prefix == '':
            missing.append(e)
    return prefix, matched, missing


def write_reports(root, out_dir, mapping_path, prefix, matched, missing, per_folder=True):
    os.makedirs(out_dir, exist_ok=True)
    head = '// Lines from %s whose files exist in %s\n// path prefix removed when matching: "%s"\n' % (
        os.path.basename(mapping_path), root, prefix)
    p = os.path.join(out_dir, 'mappings_matched.txt')
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(head)
        sec = None
        for e in matched:
            if e['section'] != sec:
                sec = e['section']
                if sec:
                    f.write('\n%s\n' % sec)
            f.write(e['raw'] + '\n')
    pm = os.path.join(out_dir, 'mappings_missing.txt')
    with open(pm, 'w', encoding='utf-8', newline='\n') as f:
        f.write('// Lines under "%s" whose file is NOT in the folder\n' % prefix)
        for e in missing:
            f.write(e['raw'] + '\n')
    files = []
    if per_folder:
        byd = {}
        for e in matched:
            byd.setdefault(os.path.dirname(e['rel']), []).append(e)
        for d, lst in byd.items():
            fp = os.path.join(out_dir, d, '_mappings.txt')
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, 'w', encoding='utf-8', newline='\n') as f:
                f.write('// mappings.txt lines for files in this folder\n')
                for e in sorted(lst, key=lambda x: (x['rel'].lower(), x['line'])):
                    f.write(e['raw'] + '\n')
            files.append(fp)
    return p, pm, files


def variant_name(key, model_rel):
    """short, file-safe name for a variant: the mapping key without the leading 'model.'"""
    k = key[6:] if key.startswith('model.') else key
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', k)


def floats(v, n):
    vals = [float(x) for x in v.replace(' ', '').split(',') if x != '']
    if n == 4 and len(vals) == 3:
        vals.append(1.0)
    return vals[:n]


def apply_overrides(model, overrides):
    """Return a copy of model['meshes'] materials with mappings overrides applied (by material name,
    case-insensitive). Returns (model copy, list of material names that weren't found)."""
    import copy
    m = copy.deepcopy(model)
    found = set()
    lower = {k.lower(): v for k, v in overrides.items()}
    for mesh in m['meshes']:
        for mat in mesh['materials']:
            ov = lower.get((mat['name'] or '').lower())
            if not ov:
                continue
            found.add(mat['name'].lower())
            for prop, v in ov.items():
                try:
                    if prop == 'texture':
                        mat['texture'] = v
                    elif prop == 'shininess':
                        mat['shininess'] = floats(v, 1)
                    elif prop in ('specular', 'emissive'):
                        mat[prop] = floats(v, 4)
                except ValueError:
                    pass
    missing = [k for k in overrides if k.lower() not in found]
    return m, missing


def short_variant_names(matched):
    """key -> short name: the part of the key that differs between the items sharing one .wom"""
    groups = {}
    for e in matched:
        if e['overrides']:
            groups.setdefault(e['rel'].lower(), []).append(e['key'])
    out = {}
    for keys in groups.values():
        split = [k.split('.') for k in keys]
        n = 0
        if len(keys) > 1:
            while all(len(s) > n + 1 for s in split) and len({s[n] for s in split}) == 1:
                n += 1
        else:
            n = max(0, len(split[0]) - 1)
        used = set()
        for k, s in zip(keys, split):
            name = re.sub(r'[^A-Za-z0-9_.-]+', '_', '.'.join(s[n:]) or s[-1])
            base, i = name, 2
            while name.lower() in used:
                name = '%s_%d' % (base, i); i += 1
            used.add(name.lower()); out[k] = name
    return out
