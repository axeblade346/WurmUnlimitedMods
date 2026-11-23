"""glTF (.glb) export of a WOM model + skeleton + animations, and import of
animations from a .glb back into WOM animation files."""
import json
import os
import struct

import numpy as np

# ------------------------------------------------------------------ math
def mat_to_quat(R):
    """3x3 rotation -> quaternion (x, y, z, w)"""
    m = R
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        w = 0.25 * s; x = (m[2, 1] - m[1, 2]) / s; y = (m[0, 2] - m[2, 0]) / s; z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w = (m[2, 1] - m[1, 2]) / s; x = 0.25 * s; y = (m[0, 1] + m[1, 0]) / s; z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w = (m[0, 2] - m[2, 0]) / s; x = (m[0, 1] + m[1, 0]) / s; y = 0.25 * s; z = (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w = (m[1, 0] - m[0, 1]) / s; x = (m[0, 2] + m[2, 0]) / s; y = (m[1, 2] + m[2, 1]) / s; z = 0.25 * s
    q = np.array([x, y, z, w]); return q / np.linalg.norm(q)


def quat_to_mat(q):
    x, y, z, w = q / np.linalg.norm(q)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def decompose(M):
    """4x4 -> (t, q, s); handles scale, assumes no shear"""
    t = M[:3, 3].copy()
    A = M[:3, :3]
    s = np.linalg.norm(A, axis=0)
    if np.linalg.det(A) < 0:
        s[0] = -s[0]
    R = A / np.where(s == 0, 1, s)
    return t, mat_to_quat(R), s


def compose(t, q, s):
    M = np.eye(4)
    M[:3, :3] = quat_to_mat(np.asarray(q, float)) * np.asarray(s, float)
    M[:3, 3] = t
    return M


def slerp(a, b, f):
    d = np.dot(a, b)
    if d < 0:
        b = -b; d = -d
    if d > 0.9995:
        r = a + f * (b - a); return r / np.linalg.norm(r)
    th = np.arccos(d)
    return (np.sin((1 - f) * th) * a + np.sin(f * th) * b) / np.sin(th)


# ------------------------------------------------------------------ writer
class GLB:
    def __init__(self):
        self.bin = bytearray()
        self.j = {'asset': {'version': '2.0', 'generator': 'wom_tool.py'},
                  'buffers': [], 'bufferViews': [], 'accessors': [], 'nodes': [], 'meshes': [],
                  'materials': [], 'textures': [], 'images': [], 'samplers': [], 'skins': [],
                  'animations': [], 'scenes': [{'nodes': []}], 'scene': 0}

    def accessor(self, arr, ctype, atype, target=None, minmax=False, normalized=False):
        arr = np.ascontiguousarray(arr)
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin); raw = arr.tobytes(); self.bin += raw
        bv = {'buffer': 0, 'byteOffset': off, 'byteLength': len(raw)}
        if target:
            bv['target'] = target
        self.j['bufferViews'].append(bv)
        ncomp = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[atype]
        acc = {'bufferView': len(self.j['bufferViews']) - 1, 'componentType': ctype,
               'count': int(arr.size // ncomp), 'type': atype}
        if normalized:
            acc['normalized'] = True
        if minmax:
            a2 = arr.reshape(-1, ncomp)
            acc['min'] = [float(x) for x in a2.min(0)]; acc['max'] = [float(x) for x in a2.max(0)]
        self.j['accessors'].append(acc)
        return len(self.j['accessors']) - 1

    def save(self, path):
        for k in [k for k, v in self.j.items() if v == []]:
            del self.j[k]
        while len(self.bin) % 4:
            self.bin.append(0)
        self.j['buffers'] = [{'byteLength': len(self.bin)}]
        js = json.dumps(self.j, separators=(',', ':')).encode()
        js += b' ' * ((4 - len(js) % 4) % 4)
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        with open(path, 'wb') as f:
            f.write(struct.pack('<III', 0x46546C67, 2, total))
            f.write(struct.pack('<II', len(js), 0x4E4F534A)); f.write(js)
            f.write(struct.pack('<II', len(self.bin), 0x004E4942)); f.write(self.bin)


F32, U16, U32 = 5126, 5123, 5125


def export_glb(model, anims, path, mesh_filter=None):
    """model: read_wom() result. anims: list of (name, read_anim() bones)."""
    g = GLB()
    joints = model['joints']
    jidx = {j['name']: i for i, j in enumerate(joints)}
    # --- skeleton nodes (node i == joint i)
    for j in joints:
        M = np.array(j['bind_local'], float).reshape(4, 4)
        t, q, s = decompose(M)
        node = {'name': j['name'], 'translation': [float(x) for x in t], 'rotation': [float(x) for x in q]}
        if np.abs(s - 1).max() > 1e-5:
            node['scale'] = [float(x) for x in s]
        g.j['nodes'].append(node)
    roots = []
    for i, j in enumerate(joints):
        p = jidx.get(j['parent'])
        if j['parent'] and p is not None:
            g.j['nodes'][p].setdefault('children', []).append(i)
        else:
            roots.append(i)
    skin = None
    if joints:
        inv_cache = {}
        for m in model['meshes']:
            for b in m['skin'] or []:
                inv_cache.setdefault(b['joint'], b['inverse'])
        ibm = []
        for j in joints:
            inv = inv_cache.get(j['name'])
            if inv is None:
                inv = np.linalg.inv(np.array(j['bind_world'], float).reshape(4, 4)).ravel()
            ibm.append(np.array(inv, float).reshape(4, 4).T.ravel())  # column-major
        acc = g.accessor(np.array(ibm, np.float32), F32, 'MAT4')
        # an "Armature" parent node keeps Blender's import tidy
        arm = len(g.j['nodes'])
        g.j['nodes'].append({'name': 'Armature', 'children': roots})
        g.j['skins'].append({'name': 'Skeleton', 'joints': list(range(len(joints))),
                             'inverseBindMatrices': acc, 'skeleton': roots[0]})
        skin = 0
        g.j['scenes'][0]['nodes'].append(arm)

    # --- materials
    matidx, imgidx = {}, {}
    def material(mat):
        key = mat['name'] or 'default'
        if key in matidx:
            return matidx[key]
        gm = {'name': key, 'pbrMetallicRoughness': {'metallicFactor': 0.0, 'roughnessFactor': 0.8}}
        if mat['texture']:
            if mat['texture'] not in imgidx:
                if not g.j['samplers']:
                    g.j['samplers'].append({})
                g.j['images'].append({'uri': mat['texture'].replace(' ', '%20'), 'name': mat['texture']})
                g.j['textures'].append({'source': len(g.j['images']) - 1, 'sampler': 0})
                imgidx[mat['texture']] = len(g.j['textures']) - 1
            gm['pbrMetallicRoughness']['baseColorTexture'] = {'index': imgidx[mat['texture']]}
        g.j['materials'].append(gm); matidx[key] = len(g.j['materials']) - 1
        return matidx[key]

    # --- meshes
    for m in model['meshes']:
        if mesh_filter and not mesh_filter(m['name']):
            continue
        pos = np.array([v['pos'] for v in m['verts']], np.float32)
        nrm = np.array([v['normal'] for v in m['verts']], np.float32)
        ln = np.linalg.norm(nrm, axis=1, keepdims=True); ln[ln == 0] = 1; nrm = (nrm / ln).astype(np.float32)
        uv = np.array([v['uv'] for v in m['verts']], np.float32)
        nv = len(pos)
        attrs = {'POSITION': g.accessor(pos, F32, 'VEC3', 34962, minmax=True),
                 'NORMAL': g.accessor(nrm, F32, 'VEC3', 34962),
                 'TEXCOORD_0': g.accessor(uv, F32, 'VEC2', 34962)}
        skinned = bool(m['skin']) and skin is not None
        if skinned:
            J = np.zeros((nv, 4), np.uint16); W = np.zeros((nv, 4), np.float32); n = np.zeros(nv, int)
            for b in m['skin']:
                ji = jidx[b['joint']]
                for vi, w in b['weights']:
                    if n[vi] < 4:
                        J[vi, n[vi]] = ji; W[vi, n[vi]] = w; n[vi] += 1
            s = W.sum(1, keepdims=True); s[s == 0] = 1; W = (W / s).astype(np.float32)
            attrs['JOINTS_0'] = g.accessor(J, U16, 'VEC4', 34962)
            attrs['WEIGHTS_0'] = g.accessor(W, F32, 'VEC4', 34962)
        idx = np.array(m['indices'], np.uint16 if nv < 65536 else np.uint32)
        prim = {'attributes': attrs, 'indices': g.accessor(idx, U16 if idx.dtype == np.uint16 else U32, 'SCALAR', 34963),
                'mode': 4}
        if m['materials']:
            prim['material'] = material(m['materials'][0])
        g.j['meshes'].append({'name': m['name'], 'primitives': [prim]})
        node = {'name': m['name'], 'mesh': len(g.j['meshes']) - 1}
        if skinned:
            node['skin'] = skin
        g.j['nodes'].append(node)
        g.j['scenes'][0]['nodes'].append(len(g.j['nodes']) - 1)

    # --- animations
    skipped = set()
    for aname, bones in anims:
        chans, samps = [], []
        for b in bones:
            if b['name'] not in jidx:
                if b['name'] and b['keys']:
                    skipped.add(b['name'])
                continue
            if not b['keys']:
                continue
            times = np.array([t for _, t in b['keys']], np.float32)
            T, Q = [], []
            prev = None
            for m16, _ in b['keys']:
                t, q, _s = decompose(np.array(m16, float).reshape(4, 4))
                if prev is not None and np.dot(prev, q) < 0:
                    q = -q
                prev = q; T.append(t); Q.append(q)
            ti = g.accessor(times, F32, 'SCALAR', minmax=True)
            for path_, arr, typ in (('translation', T, 'VEC3'), ('rotation', Q, 'VEC4')):
                samps.append({'input': ti, 'output': g.accessor(np.array(arr, np.float32), F32, typ),
                              'interpolation': 'LINEAR'})
                chans.append({'sampler': len(samps) - 1, 'target': {'node': jidx[b['name']], 'path': path_}})
        if chans:
            g.j['animations'].append({'name': aname, 'channels': chans, 'samplers': samps})
    g.save(path)
    return skipped


# ------------------------------------------------------------------ reader
def load_gltf(path):
    data = open(path, 'rb').read()
    if data[:4] == b'glTF':
        off = 12; js = None; binc = b''
        while off < len(data):
            ln, typ = struct.unpack_from('<II', data, off); off += 8
            chunk = data[off:off + ln]; off += ln
            if typ == 0x4E4F534A:
                js = json.loads(chunk)
            elif typ == 0x004E4942:
                binc = chunk
        buffers = [binc]
    else:
        js = json.loads(data)
        buffers = []
        import base64
        for b in js.get('buffers', []):
            uri = b.get('uri', '')
            if uri.startswith('data:'):
                buffers.append(base64.b64decode(uri.split(',', 1)[1]))
            else:
                buffers.append(open(os.path.join(os.path.dirname(path), uri), 'rb').read())
    return js, buffers


def read_accessor(js, buffers, i):
    a = js['accessors'][i]
    n = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[a['type']]
    dt = {5126: np.float32, 5123: np.uint16, 5125: np.uint32, 5121: np.uint8, 5122: np.int16, 5120: np.int8}[a['componentType']]
    if 'bufferView' not in a:
        return np.zeros((a['count'], n), dt)
    bv = js['bufferViews'][a['bufferView']]
    buf = buffers[bv.get('buffer', 0)]
    start = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    item = np.dtype(dt).itemsize * n
    stride = bv.get('byteStride', item)
    if stride == item:
        arr = np.frombuffer(buf, dt, a['count'] * n, start).reshape(a['count'], n)
    else:
        arr = np.array([np.frombuffer(buf, dt, n, start + k * stride) for k in range(a['count'])])
    arr = arr.astype(np.float64)
    if a.get('normalized'):
        arr /= {np.uint8: 255.0, np.uint16: 65535.0, np.int8: 127.0, np.int16: 32767.0}.get(dt, 1.0)
    return arr


def node_rest(node):
    if 'matrix' in node:
        return np.array(node['matrix'], float).reshape(4, 4).T
    return compose(node.get('translation', [0, 0, 0]), node.get('rotation', [0, 0, 0, 1]), node.get('scale', [1, 1, 1]))


def sample(times, values, interp, t, path):
    if len(times) == 1 or t <= times[0]:
        v = values[0] if interp != 'CUBICSPLINE' else values[1]
        return v
    if t >= times[-1]:
        return values[-1] if interp != 'CUBICSPLINE' else values[3 * (len(times) - 1) + 1]
    k = np.searchsorted(times, t) - 1
    t0, t1 = times[k], times[k + 1]
    f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
    if interp == 'STEP':
        return values[k]
    if interp == 'CUBICSPLINE':
        dt = t1 - t0
        p0, m0 = values[3 * k + 1], values[3 * k + 2] * dt
        p1, m1 = values[3 * (k + 1) + 1], values[3 * (k + 1)] * dt
        f2, f3 = f * f, f * f * f
        v = (2 * f3 - 3 * f2 + 1) * p0 + (f3 - 2 * f2 + f) * m0 + (-2 * f3 + 3 * f2) * p1 + (f3 - f2) * m1
        return v / np.linalg.norm(v) if path == 'rotation' else v
    if path == 'rotation':
        return slerp(values[k], values[k + 1], f)
    return values[k] * (1 - f) + values[k + 1] * f


def count_anims(gltf_path):
    js, _ = load_gltf(gltf_path)
    return len(js.get('animations', []))


def import_anims(gltf_path, joints, fps=None, progress=None):
    """Return list of (animation name, bones) in WOM layout for every animation in the file.
    joints: WOM skeleton (list of dicts with name/parent/bind_world)."""
    js, buffers = load_gltf(gltf_path)
    nodes = js['nodes']
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get('children', []):
            parent[c] = i
    byname = {}
    for i, n in enumerate(nodes):
        nm = n.get('name', '')
        byname.setdefault(nm, i)
    jn = {j['name']: j for j in joints}
    jnode = {}
    for j in joints:
        if j['name'] in byname:
            jnode[j['name']] = byname[j['name']]
    missing = [j['name'] for j in joints if j['name'] not in jnode]
    jnodes = set(jnode.values())
    # top of skeleton: ancestors above the highest WOM joint are ignored
    def chain(i):
        out = []
        while i is not None and i in jnodes:
            out.append(i); i = parent.get(i)
        return out[::-1]

    def world(i, local):
        M = np.eye(4)
        for k in chain(i):
            M = M @ local[k]
        return M

    rest_local = {i: node_rest(nodes[i]) for i in jnodes}
    # correction for bones whose rest orientation was changed (e.g. Blender bone axes)
    C = {}
    for name, i in jnode.items():
        Wg = world(i, rest_local)
        Ww = np.array(jn[name]['bind_world'], float).reshape(4, 4)
        C[name] = np.linalg.inv(Ww) @ Wg

    results = []
    for ai, anim in enumerate(js.get('animations', [])):
        name = anim.get('name') or 'animation_%d' % ai
        if progress:
            progress.step(name)
        tracks = {}
        alltimes = []
        for ch in anim['channels']:
            tgt = ch['target']
            if 'node' not in tgt or tgt['node'] not in jnodes or tgt['path'] not in ('translation', 'rotation', 'scale'):
                continue
            s = anim['samplers'][ch['sampler']]
            tm = read_accessor(js, buffers, s['input']).ravel()
            vals = read_accessor(js, buffers, s['output'])
            tracks[(tgt['node'], tgt['path'])] = (tm, vals, s.get('interpolation', 'LINEAR'))
            alltimes.append(tm)
        if not tracks:
            continue
        t0 = min(t[0] for t in alltimes); t1 = max(t[-1] for t in alltimes)
        if fps:
            n = int(round((t1 - t0) * fps)) + 1
            times = [t0 + k / fps for k in range(n)]
        else:
            times = sorted(set(np.round(np.concatenate(alltimes), 5)))
        frames = []
        for ti_, t in enumerate(times):
            if progress and ti_ % 10 == 0:
                progress.sub_progress(ti_ / len(times), 'frame %d/%d' % (ti_, len(times)))
            local = {}
            for i in jnodes:
                n_ = nodes[i]
                if 'matrix' in n_:
                    local[i] = rest_local[i]; continue
                tr = n_.get('translation', [0, 0, 0]); ro = n_.get('rotation', [0, 0, 0, 1]); sc = n_.get('scale', [1, 1, 1])
                if (i, 'translation') in tracks:
                    tr = sample(*tracks[(i, 'translation')], t, 'translation')
                if (i, 'rotation') in tracks:
                    ro = sample(*tracks[(i, 'rotation')], t, 'rotation')
                if (i, 'scale') in tracks:
                    sc = sample(*tracks[(i, 'scale')], t, 'scale')
                local[i] = compose(tr, ro, sc)
            Wt = {nm: world(i, local) @ np.linalg.inv(C[nm]) for nm, i in jnode.items()}
            frames.append(Wt)
        bones = []
        for j in joints:
            nm = j['name']
            if nm not in jnode:
                continue
            keys = []
            for t, Wt in zip(times, frames):
                if j['parent'] and j['parent'] in Wt:
                    L = np.linalg.inv(Wt[j['parent']]) @ Wt[nm]
                else:
                    L = Wt[nm]
                L[3] = [0, 0, 0, 1]
                keys.append(([float(x) for x in L.ravel()], float(np.float32(t - t0))))
            bones.append({'name': nm, 'keys': keys})
        results.append((name, bones))
    return results, missing
