#!/usr/bin/env python3
"""
wom_tool.py - convert Wurm Unlimited .wom models to .obj and back, keeping
skeleton (joints) and skin weights so animated models still animate.

  python wom_tool.py wom2obj female_1_04.wom
      -> female_1_04.obj, female_1_04.mtl, female_1_04.womdata.json

  python wom_tool.py obj2wom female_1_04.obj
      -> female_1_04_new.wom  (uses female_1_04.womdata.json if present)

  python wom_tool.py info female_1_04.wom

Only needs Python 3.8+ and numpy (pip install numpy).

How rebuilding works
  * Each WOM mesh is exported as one OBJ object with the same name.
  * The .womdata.json sidecar keeps what OBJ can't hold: skeleton, skin
    weights, material settings, tangent flags, mesh order.
  * A mesh you didn't touch is written back exactly as it was.
  * A mesh you edited gets its skin weights from the nearest vertex of the
    original mesh with the same name.
  * A NEW mesh (e.g. new hair) gets weights in one of two ways:
      - name it  myHairMesh@Head   -> every vertex 100% on joint "Head"
        (the "@Head" part is removed from the final mesh name)
      - otherwise weights are copied from the nearest vertex of the
        original model's skinned meshes (or only the meshes named in
        --weights-from).
  * Materials: if the OBJ material name matches one in the original model,
    its settings are reused. Otherwise it is built from the .mtl
    (map_Kd -> texture file name, Ns/Ks/Ke) or copied from --material-like.
"""
import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from womlib import read_wom, write_wom, read_anim, write_anim, is_anim  # noqa: E402
import womgltf  # noqa: E402
import womtex  # noqa: E402
import wommap  # noqa: E402
from womprogress import Progress, Spinner  # noqa: E402
import womprogress  # noqa: E402
import re  # noqa: E402

TAIL_MESHES = ('pickingBoxMesh', 'boundingBoxMesh')
quiet_flag = [False]


def fmt(x):
    return repr(float(np.float32(x)))


# ---------------------------------------------------------------- placing attachments (hair, helmets)
def read_offset_to_null(wom_path, bone):
    """<offsetToNull><bone> values for this file from the properties.xml next to it, or {}"""
    import xml.etree.ElementTree as ET
    d = os.path.dirname(os.path.abspath(wom_path))
    px = next((os.path.join(d, f) for f in os.listdir(d) if f.lower() == 'properties.xml'), None)
    if not px:
        return {}
    try:
        root = ET.parse(px).getroot()
    except Exception:
        return {}
    name = os.path.basename(wom_path).lower()
    for el in root:
        if el.tag.lower() == name:
            o = el.find('offsetToNull')
            n = o.find(bone) if o is not None else None
            if n is not None:
                out = {}
                for v in n:
                    try:
                        out[v.tag] = float(v.text)
                    except (TypeError, ValueError):
                        pass
                return out
    return {}


def placement_matrix(body_path, bone, wom_path):
    """4x4 that moves an attachment (modelled around a Null bone) onto the body's bind pose.
    Same maths as the viewer: bone bind pose x translate(offset) x rotate X, Y, Z (degrees)."""
    body = read_wom(open(body_path, 'rb').read())
    j = next((j for j in body['joints'] if j['name'] == bone), None)
    if j is None:
        raise ValueError('%s has no bone %s' % (os.path.basename(body_path), bone))
    B = np.array(j['bind_world'], float).reshape(4, 4)
    o = read_offset_to_null(wom_path, bone)
    T = np.eye(4); T[:3, 3] = [o.get('xPos', 0), o.get('yPos', 0), o.get('zPos', 0)]
    ax, ay, az = [np.radians(o.get(k, 0)) for k in ('xRot', 'yRot', 'zRot')]
    Rx = np.array([[1, 0, 0], [0, np.cos(ax), -np.sin(ax)], [0, np.sin(ax), np.cos(ax)]])
    Ry = np.array([[np.cos(ay), 0, np.sin(ay)], [0, 1, 0], [-np.sin(ay), 0, np.cos(ay)]])
    Rz = np.array([[np.cos(az), -np.sin(az), 0], [np.sin(az), np.cos(az), 0], [0, 0, 1]])
    R = np.eye(4); R[:3, :3] = Rx @ Ry @ Rz
    return B @ T @ R, {'body': os.path.basename(body_path), 'bone': bone, 'offset': o}


# ---------------------------------------------------------------- WOM -> OBJ
def write_mtl(model, path, tex_map=None):
    tex_map = tex_map or {}
    mats = {}
    for m in model['meshes']:
        for mat in m['materials']:
            mats.setdefault(mat['name'] or 'default', mat)
    with open(path, 'w', newline='\n') as f:
        f.write('# Exported by wom_tool.py\n')
        for mname, mat in mats.items():
            f.write('\nnewmtl %s\n' % mname)
            if mat.get('shininess') is not None:
                f.write('Ns %s\n' % fmt(mat['shininess'][0]))
            f.write('Kd 1 1 1\n')
            if mat.get('specular') is not None:
                f.write('Ks %s %s %s\n' % tuple(fmt(v) for v in mat['specular'][:3]))
            if mat.get('emissive') is not None:
                f.write('Ke %s %s %s\n' % tuple(fmt(v) for v in mat['emissive'][:3]))
            if mat['texture']:
                f.write('map_Kd %s\n' % tex_map.get(mat['texture'], mat['texture']))

def wom2obj(path, out_base=None, tex_map=None, model=None, place=None):
    """place = (4x4 matrix, info) to show an attachment (hair/helmet) on the body in Blender"""
    model = model or read_wom(open(path, 'rb').read())
    M = np.array(place[0], float) if place else None
    xf_p = (lambda p: (M @ np.append(np.asarray(p, float), 1.0))[:3]) if place else (lambda p: p)
    xf_n = (lambda n: M[:3, :3] @ np.asarray(n, float)) if place else (lambda n: n)
    tex_map = tex_map or {}
    base = out_base or os.path.splitext(path)[0]
    name = os.path.basename(base)

    mats = {}
    for m in model['meshes']:
        for mat in m['materials']:
            mats.setdefault(mat['name'] or 'default', mat)

    write_mtl(model, base + '.mtl', tex_map)

    with open(base + '.obj', 'w', newline='\n') as f:
        f.write('# Exported by wom_tool.py from %s\n' % os.path.basename(path))
        f.write('mtllib %s.mtl\n' % name)
        off = 1
        for m in model['meshes']:
            f.write('o %s\n' % m['name'])
            for v in m['verts']:
                f.write('v %s %s %s\n' % tuple(fmt(c) for c in xf_p(v['pos'])))
            for v in m['verts']:
                f.write('vt %s %s\n' % (fmt(v['uv'][0]), fmt(1.0 - np.float32(v['uv'][1]))))
            for v in m['verts']:
                f.write('vn %s %s %s\n' % tuple(fmt(c) for c in xf_n(v['normal'])))
            mat = m['materials'][0] if m['materials'] else None
            f.write('usemtl %s\n' % ((mat['name'] or 'default') if mat else 'default'))
            f.write('s 1\n')
            idx = m['indices']
            for t in range(0, len(idx) - 2, 3):
                a, b, c = (idx[t] + off, idx[t + 1] + off, idx[t + 2] + off)
                f.write('f %d/%d/%d %d/%d/%d %d/%d/%d\n' % (a, a, a, b, b, b, c, c, c))
            off += len(m['verts'])

    side = {'source': os.path.basename(path), 'model': dict(model)}
    if place:
        side['placement'] = {'matrix': M.tolist(), **place[1]}
    json.dump(side, open(base + '.womdata.json', 'w'), separators=(',', ':'))
    if not quiet_flag[0]:
        print('Wrote %s.obj, %s.mtl, %s.womdata.json  (%d meshes, %d joints, %d skinned)' % (
            base, base, base, len(model['meshes']), len(model['joints']),
            sum(1 for m in model['meshes'] if m['skin'])))
        if place:
            print('  shown on %s at bone %s%s; obj2wom moves it back automatically' % (
                place[1]['body'], place[1]['bone'], ' with offset %s' % place[1]['offset'] if place[1]['offset'] else ''))


# ---------------------------------------------------------------- OBJ parsing
def parse_mtl(path):
    mats, cur = {}, None
    if not os.path.exists(path):
        return mats
    for line in open(path, encoding='utf-8', errors='replace'):
        p = line.strip().split()
        if not p or p[0].startswith('#'):
            continue
        k = p[0]
        if k == 'newmtl':
            cur = ' '.join(p[1:]); mats[cur] = {}
        elif cur is None:
            continue
        elif k == 'map_Kd':
            mats[cur]['texture'] = os.path.basename(line.strip()[len('map_Kd'):].strip().split(' ')[-1].replace('\\', '/'))
        elif k in ('Ns',):
            mats[cur]['Ns'] = float(p[1])
        elif k in ('Ks', 'Ke'):
            mats[cur][k] = [float(x) for x in p[1:4]]
    return mats


def parse_obj(path):
    V, VT, VN = [], [], []
    objects, cur = [], None
    mtllib, curmat = None, None

    def start(name):
        nonlocal cur
        cur = {'name': name, 'faces': [], 'material': curmat}
        objects.append(cur)

    for line in open(path, encoding='utf-8', errors='replace'):
        p = line.split()
        if not p or p[0].startswith('#'):
            continue
        k = p[0]
        if k == 'v':
            V.append([float(x) for x in p[1:4]])
        elif k == 'vt':
            VT.append([float(x) for x in p[1:3]] if len(p) > 2 else [float(p[1]), 0.0])
        elif k == 'vn':
            VN.append([float(x) for x in p[1:4]])
        elif k == 'o' or (k == 'g' and (cur is None or not cur['faces'])):
            nm = line.strip()[1:].strip()
            if cur is not None and not cur['faces']:
                cur['name'] = nm
            else:
                start(nm)
        elif k == 'g':
            pass  # group inside an object: ignore
        elif k == 'mtllib':
            mtllib = line.strip()[len('mtllib'):].strip()
        elif k == 'usemtl':
            curmat = line.strip()[len('usemtl'):].strip()
            if cur is None:
                start('mesh')
            if cur['faces'] and cur['material'] != curmat:
                # several materials in one object -> split into sub-meshes
                start(cur['name'].split('#')[0] + '#' + curmat)
            cur['material'] = curmat
        elif k == 'f':
            if cur is None:
                start('mesh')
            poly = []
            for tok in p[1:]:
                s = tok.split('/')
                vi = int(s[0]); vi = vi - 1 if vi > 0 else len(V) + vi
                ti = None
                if len(s) > 1 and s[1]:
                    ti = int(s[1]); ti = ti - 1 if ti > 0 else len(VT) + ti
                ni = None
                if len(s) > 2 and s[2]:
                    ni = int(s[2]); ni = ni - 1 if ni > 0 else len(VN) + ni
                poly.append((vi, ti, ni))
            for i in range(1, len(poly) - 1):
                cur['faces'].append((poly[0], poly[i], poly[i + 1]))
    return np.array(V, float).reshape(-1, 3), np.array(VT, float).reshape(-1, 2), \
        np.array(VN, float).reshape(-1, 3), [o for o in objects if o['faces']], mtllib


def build_mesh_arrays(obj, V, VT, VN):
    """Turn OBJ faces into unique WOM vertices + triangle indices."""
    keys = sorted({c for tri in obj['faces'] for c in tri},
                  key=lambda k: (k[0], -1 if k[1] is None else k[1], -1 if k[2] is None else k[2]))
    remap = {k: i for i, k in enumerate(keys)}
    pos = np.array([V[k[0]] for k in keys])
    uv = np.array([[VT[k[1]][0], 1.0 - VT[k[1]][1]] if k[1] is not None else [0.0, 0.0] for k in keys])
    idx = np.array([[remap[c] for c in tri] for tri in obj['faces']], dtype=np.int64)
    if all(k[2] is not None for k in keys):
        return pos, np.array([VN[k[2]] for k in keys]), uv, idx
    else:
        nrm = np.zeros_like(pos)
        fn = np.cross(pos[idx[:, 1]] - pos[idx[:, 0]], pos[idx[:, 2]] - pos[idx[:, 0]])
        for j in range(3):
            np.add.at(nrm, idx[:, j], fn)
        # smooth across vertices that share a position
        _, inv = np.unique(np.round(pos, 6), axis=0, return_inverse=True)
        acc = np.zeros((inv.max() + 1, 3)); np.add.at(acc, inv, nrm); nrm = acc[inv]
    ln = np.linalg.norm(nrm, axis=1, keepdims=True); ln[ln == 0] = 1
    return pos, nrm / ln, uv, idx


def compute_tangents(pos, nrm, uv, idx):
    tan = np.zeros_like(pos); bit = np.zeros_like(pos)
    p0, p1, p2 = pos[idx[:, 0]], pos[idx[:, 1]], pos[idx[:, 2]]
    w0, w1, w2 = uv[idx[:, 0]], uv[idx[:, 1]], uv[idx[:, 2]]
    e1, e2 = p1 - p0, p2 - p0
    d1, d2 = w1 - w0, w2 - w0
    r = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(r) < 1e-12, 1.0, 1.0 / np.where(r == 0, 1, r))[:, None]
    sd = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r
    td = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * r
    for j in range(3):
        np.add.at(tan, idx[:, j], sd); np.add.at(bit, idx[:, j], td)
    tan = tan - nrm * np.sum(nrm * tan, 1, keepdims=True)
    ln = np.linalg.norm(tan, axis=1, keepdims=True); ln[ln == 0] = 1; tan /= ln
    b = np.cross(nrm, tan)
    b *= np.where(np.sum(b * bit, 1, keepdims=True) < 0, -1.0, 1.0)
    return tan, b


def nearest(src, dst, chunk=2048):
    """index into src of the nearest point for every point in dst"""
    out = np.empty(len(dst), dtype=np.int64)
    for s in range(0, len(dst), chunk):
        d = dst[s:s + chunk]
        dist = ((d[:, None, :] - src[None, :, :]) ** 2).sum(-1)
        out[s:s + chunk] = dist.argmin(1)
    return out


def closest_on_triangles(P, A, B, C):
    """closest point of each P[i] on triangle (A[i],B[i],C[i]); returns (dist2, barycentric (N,3))"""
    ab, ac, ap = B - A, C - A, P - A
    d1 = (ab * ap).sum(-1); d2 = (ac * ap).sum(-1)
    bp = P - B; d3 = (ab * bp).sum(-1); d4 = (ac * bp).sum(-1)
    cp = P - C; d5 = (ab * cp).sum(-1); d6 = (ac * cp).sum(-1)
    va = d3 * d6 - d5 * d4; vb = d5 * d2 - d1 * d6; vc = d1 * d4 - d3 * d2
    n = len(P); bary = np.zeros((n, 3)); done = np.zeros(n, bool)
    def put(mask, u, v, w):
        m = mask & ~done
        bary[m, 0] = u[m] if np.ndim(u) else u; bary[m, 1] = v[m] if np.ndim(v) else v
        bary[m, 2] = w[m] if np.ndim(w) else w; done[m] = True
    one, zero = np.ones(n), np.zeros(n)
    put((d1 <= 0) & (d2 <= 0), one, zero, zero)
    put((d3 >= 0) & (d4 <= d3), zero, one, zero)
    put((d6 >= 0) & (d5 <= d6), zero, zero, one)
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.nan_to_num(d1 / (d1 - d3)); put((vc <= 0) & (d1 >= 0) & (d3 <= 0), 1 - t, t, zero)
        t = np.nan_to_num(d2 / (d2 - d6)); put((vb <= 0) & (d2 >= 0) & (d6 <= 0), 1 - t, zero, t)
        t = np.nan_to_num((d4 - d3) / ((d4 - d3) + (d5 - d6))); put((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), zero, 1 - t, t)
        den = va + vb + vc; den = np.where(den == 0, 1, den)
        v = vb / den; w = vc / den; put(np.ones(n, bool), 1 - v - w, v, w)
    Q = bary[:, :1] * A + bary[:, 1:2] * B + bary[:, 2:3] * C
    return ((P - Q) ** 2).sum(-1), bary


def surface_weights(src_pos, src_tris, src_table, dst_pos, k=8, chunk=512):
    """Bone weights for dst_pos, blended from the closest point on the source surface."""
    src_pos = np.asarray(src_pos, float); dst_pos = np.asarray(dst_pos, float)
    src_tris = np.asarray(src_tris, np.int64).reshape(-1, 3)
    if len(src_tris) == 0:
        nn = nearest(src_pos, dst_pos)
        return [list(src_table[j]) for j in nn]
    inc = [[] for _ in range(len(src_pos))]
    for t, tri in enumerate(src_tris):
        for v in tri:
            inc[v].append(t)
    k = min(k, len(src_pos))
    out = []
    for s in range(0, len(dst_pos), chunk):
        D = dst_pos[s:s + chunk]
        d2 = ((D[:, None, :] - src_pos[None, :, :]) ** 2).sum(-1)
        knn = np.argpartition(d2, k - 1, axis=1)[:, :k]
        for i, p in enumerate(D):
            cand = sorted({t for v in knn[i] for t in inc[v]})
            if not cand:
                out.append(list(src_table[knn[i][np.argmin(d2[i, knn[i]])]])); continue
            tri = src_tris[cand]
            P = np.repeat(p[None], len(cand), 0)
            dist, bary = closest_on_triangles(P, src_pos[tri[:, 0]], src_pos[tri[:, 1]], src_pos[tri[:, 2]])
            b = int(np.argmin(dist))
            acc = {}
            for corner in range(3):
                f = bary[b, corner]
                if f <= 1e-6:
                    continue
                for jn, w in src_table[tri[b, corner]]:
                    acc[jn] = acc.get(jn, 0.0) + f * w
            if not acc:
                acc = dict(src_table[tri[b, int(np.argmax(bary[b]))]])
            out.append(list(acc.items()))
    return out


def skin_table(mesh, nverts):
    """per-vertex list of (joint, weight) from a WOM mesh's skin"""
    t = [[] for _ in range(nverts)]
    for b in mesh['skin'] or []:
        for vi, w in b['weights']:
            if vi < nverts:
                t[vi].append((b['joint'], w))
    return t


def make_skin(per_vertex, joints, inverse_cache):
    order = {j['name']: i for i, j in enumerate(joints)}
    jmap = {j['name']: j for j in joints}
    by_joint = {}
    for vi, infl in enumerate(per_vertex):
        infl = sorted(infl, key=lambda x: -x[1])[:4]
        s = sum(w for _, w in infl)
        if s <= 0:
            continue
        for jn, w in infl:
            by_joint.setdefault(jn, []).append((vi, float(np.float32(w / s))))
    bones = []
    for jn in sorted(by_joint, key=lambda n: order[n]):
        W = jmap[jn]['bind_world']
        inv = inverse_cache.get(jn)
        if inv is None:
            inv = [float(x) for x in np.linalg.inv(np.array(W, float).reshape(4, 4)).ravel()]
        bones.append({'joint': jn, 'matrix': W, 'inverse': inv, 'weights': by_joint[jn]})
    return bones


def default_material(src=None, mtl=None, name='material'):
    mat = {'texture': '', 'name': name, 'enabled': 1,
           'emissive': [0.0, 0.0, 0.0, 1.0], 'shininess': [2.0],
           'specular': [0.0, 0.0, 0.0, 1.0], 'transparency': [0.0, 0.0, 0.0, 1.0]}
    if src:
        mat.update({k: (list(v) if isinstance(v, list) else v) for k, v in src.items()})
        mat['name'] = name
    if mtl:
        if 'texture' in mtl: mat['texture'] = mtl['texture']
        if 'Ns' in mtl: mat['shininess'] = [mtl['Ns']]
        if 'Ks' in mtl: mat['specular'] = mtl['Ks'] + [1.0]
        if 'Ke' in mtl: mat['emissive'] = mtl['Ke'] + [1.0]
    return mat


# ---------------------------------------------------------------- OBJ -> WOM
def obj2wom(obj_path, data_path=None, out_path=None, weights_from=None,
            material_like=None, tangents=None, keep_missing=False, quiet=False):
    if not quiet:
        sp = Spinner('Reading %s' % os.path.basename(obj_path))
    V, VT, VN, objects, mtllib = parse_obj(obj_path)
    if not quiet:
        sp.done('%d objects' % len(objects))
    mtls = parse_mtl(os.path.join(os.path.dirname(os.path.abspath(obj_path)), mtllib)) if mtllib else {}

    if data_path is None:
        cand = os.path.splitext(obj_path)[0] + '.womdata.json'
        data_path = cand if os.path.exists(cand) else None
    side = json.load(open(data_path)) if data_path else {}
    orig = side.get('model', {'meshes': [], 'joints': []})
    placed = side.get('placement')
    if placed:
        Mi = np.linalg.inv(np.array(placed['matrix'], float))
        if len(V):
            V = (Mi @ np.c_[V, np.ones(len(V))].T).T[:, :3]
        if len(VN):
            VN = (Mi[:3, :3] @ VN.T).T
        if not quiet:
            print('  moving it back from %s / %s to its own origin' % (placed.get('body'), placed.get('bone')))
    joints = orig['joints']
    jnames = {j['name'] for j in joints}
    omeshes = {m['name']: m for m in orig['meshes']}
    omats = {}
    inverse_cache = {}
    for m in orig['meshes']:
        for mat in m['materials']:
            omats.setdefault(mat['name'], mat)
        for b in m['skin'] or []:
            inverse_cache.setdefault(b['joint'], b['inverse'])

    # pool used to give weights to brand-new meshes
    pool_names = [m['name'] for m in orig['meshes'] if m['skin']]
    if weights_from:
        pool_names = [n for n in weights_from if n in omeshes]
        missing = [n for n in weights_from if n not in omeshes]
        if missing:
            sys.exit('--weights-from: no mesh named %s in original model' % ', '.join(missing))
    pool_pos, pool_w, pool_tris = [], [], []
    for n in pool_names:
        m = omeshes[n]
        t = skin_table(m, len(m['verts']))
        off = len(pool_pos)
        pool_pos += [v['pos'] for v in m['verts']]; pool_w += t
        pool_tris += [i + off for i in m['indices']]
    pool_pos = np.array(pool_pos, float).reshape(-1, 3)

    any_tangents = any(m['tangents'] for m in orig['meshes'])
    new_meshes, report = [], []
    mp = None if quiet else Progress(len(objects), 'Rebuilding meshes')
    for oi, o in enumerate(objects):
        if mp:
            mp.step(o['name'])
        else:
            womprogress.sub(oi / max(1, len(objects)), o['name'])
        raw = o['name']
        rigid = None
        if '@' in raw:
            raw, rigid = raw.split('@', 1)
            rigid = rigid.split('#')[0].strip()
            if rigid not in jnames:
                sys.exit('Mesh "%s": no joint named "%s". Joints: %s' % (o['name'], rigid, ', '.join(sorted(jnames))))
        name = raw.split('#')[0]
        if name not in omeshes:  # Blender style "Object_MeshData"
            for on in omeshes:
                if name.startswith(on + '_') or name.startswith(on + '.'):
                    name = on; break
        src = omeshes.get(name)

        pos, nrm, uv, idx = build_mesh_arrays(o, V, VT, VN)
        if len(pos) > 65535:
            sys.exit('Mesh %s has %d vertices; WOM allows at most 65535 per mesh. Split it.' % (name, len(pos)))

        # unchanged mesh -> keep original bytes exactly
        if src and rigid is None and len(src['verts']) == len(pos) and len(src['indices']) == idx.size:
            sp = np.array([v['pos'] for v in src['verts']]); sn = np.array([v['normal'] for v in src['verts']])
            su = np.array([v['uv'] for v in src['verts']])
            tol = 2e-4 if placed else 1e-5
            if (np.abs(sp - pos).max() < tol and np.abs(sn - nrm).max() < max(1e-4, tol) and np.abs(su - uv).max() < 1e-5
                    and list(idx.ravel()) == src['indices']
                    and (o['material'] is None or not src['materials'] or o['material'] == src['materials'][0]['name'])):
                new_meshes.append(src); report.append((src['name'], 'unchanged')); continue

        has_t = tangents if tangents is not None else (src['tangents'] if src else any_tangents)
        mesh = {'tangents': int(has_t), 'binormals': int(has_t), 'colors': 0,
                'name': name, 'indices': [int(i) for i in idx.ravel()]}
        if has_t:
            tan, bit = compute_tangents(pos, nrm, uv, idx)
        verts = []
        for i in range(len(pos)):
            v = {'pos': [float(x) for x in pos[i]], 'normal': [float(x) for x in nrm[i]],
                 'uv': [float(x) for x in uv[i]]}
            if has_t:
                v['tangent'] = [float(x) for x in tan[i]]; v['binormal'] = [float(x) for x in bit[i]]
            verts.append(v)
        mesh['verts'] = verts

        # material
        mname = o['material'] or (src['materials'][0]['name'] if src and src['materials'] else 'material')
        if mname in omats:
            mat = default_material(omats[mname], None, mname)
        else:
            like = omats.get(material_like) if material_like else None
            if like is None and src and src['materials']:
                like = src['materials'][0]
            mat = default_material(like, mtls.get(mname), mname)
        mesh['materials'] = [mat]

        # skinning
        how = 'static'
        mesh['skin'] = None
        if rigid:
            mesh['skin'] = make_skin([[(rigid, 1.0)]] * len(pos), joints, inverse_cache); how = 'rigid on ' + rigid
        elif src and src['skin']:
            sp = np.array([v['pos'] for v in src['verts']], float)
            st = skin_table(src, len(src['verts']))
            mesh['skin'] = make_skin(surface_weights(sp, src['indices'], st, pos), joints, inverse_cache)
            how = 'edited, weights blended from original surface'
        elif src is None and len(pool_pos):
            mesh['skin'] = make_skin(surface_weights(pool_pos, pool_tris, pool_w, pos), joints, inverse_cache)
            how = 'NEW, weights blended from %d mesh(es)' % len(pool_names)
        elif src is None:
            how = 'NEW, static'
        else:
            how = 'edited, static'
        new_meshes.append(mesh); report.append((name, how))

    # keep original order; new meshes go before picking/bounding boxes
    present = {m['name'] for m in new_meshes}
    dropped = [m['name'] for m in orig['meshes'] if m['name'] not in present]
    if keep_missing:
        for n in dropped:
            new_meshes.append(omeshes[n]); report.append((n, 'kept (not in OBJ)'))
        dropped = []
    rank = {m['name']: i for i, m in enumerate(orig['meshes'])}
    first_tail = min([rank[n] for n in TAIL_MESHES if n in rank] or [len(rank)])
    keyed = []
    for i, m in enumerate(new_meshes):
        r = rank.get(m['name'])
        keyed.append(((r if r is not None else first_tail - 0.5), i, m))
    keyed.sort(key=lambda k: (k[0], k[1]))
    names = [k[2]['name'] for k in keyed]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        print('WARNING: duplicate mesh names: %s' % ', '.join(sorted(dupes)))

    if mp:
        mp.done()
    model = {'meshes': [k[2] for k in keyed], 'joints': joints}
    out = out_path or os.path.splitext(obj_path)[0] + '_new.wom'
    open(out, 'wb').write(write_wom(model))
    if quiet:
        ch = ['%s (%s)' % (n, how) for n, how in report if how != 'unchanged']
        if dropped:
            ch.append('removed: ' + ', '.join(dropped))
        return '; '.join(ch)
    for n, how in report:
        if how != 'unchanged':
            print('  %-28s %s' % (n, how))
    print('  %d mesh(es) unchanged' % sum(1 for _, h in report if h == 'unchanged'))
    if dropped:
        print('  removed (not in OBJ): %s' % ', '.join(dropped))
    print('Wrote %s  (%d meshes, %d joints)' % (out, len(model['meshes']), len(joints)))



# ---------------------------------------------------------------- animations
def to_glb(model_path, anim_paths, out, mesh_regex=None):
    model = read_wom(open(model_path, 'rb').read())
    anims = []
    ap_ = Progress(len(anim_paths), 'Reading animations') if len(anim_paths) > 3 else None
    for p in anim_paths:
        if ap_:
            ap_.step(os.path.basename(p))
        d = open(p, 'rb').read()
        if not is_anim(d):
            sys.exit('%s is not an animation file' % p)
        anims.append((os.path.splitext(os.path.basename(p))[0], read_anim(d)))
    if ap_:
        ap_.done()
    flt = re.compile(mesh_regex).search if mesh_regex else None
    sp = Spinner('Writing %s' % os.path.basename(out))
    skipped = womgltf.export_glb(model, anims, out, flt)
    sp.done()
    nm = sum(1 for m in model['meshes'] if not flt or flt(m['name']))
    print('Wrote %s  (%d meshes, %d joints, %d animation(s))' % (out, nm, len(model['joints']), len(anims)))
    if skipped:
        print('  note: bones in the animations that this skeleton lacks were left out: %s' % ', '.join(sorted(skipped)))


def from_glb(glb_path, model_path, outdir=None, only=None, template=None, fps=30, include_null=False):
    model = read_wom(open(model_path, 'rb').read())
    if not model['joints']:
        sys.exit('%s has no skeleton' % model_path)
    js_count = womgltf.count_anims(glb_path)
    ip = Progress(js_count, 'Reading animations from %s' % os.path.basename(glb_path))
    results, missing = womgltf.import_anims(glb_path, model['joints'], fps, progress=ip)
    ip.done()
    if not results:
        sys.exit('No animations found in %s' % glb_path)
    if missing:
        print('  note: these skeleton bones were not found in the glTF and are left out: %s' % ', '.join(missing))
    tmpl = read_anim(open(template, 'rb').read()) if template else None
    outdir = outdir or os.path.dirname(os.path.abspath(glb_path))
    os.makedirs(outdir, exist_ok=True)
    wrote = 0
    for name, bones in results:
        if only and name not in only:
            continue
        for b in bones:
            b['keys'] = [(m, round(t, 3)) for m, t in b['keys']]
        if tmpl:
            byn = {b['name']: b for b in bones}
            out_b = []
            for tb in tmpl:
                if tb['name'] in byn:
                    out_b.append(byn[tb['name']])
                else:
                    out_b.append({'name': tb['name'], 'keys': []})
            bones = out_b
        elif not include_null:
            bones = [b for b in bones if not b['name'].startswith('Null')]
        safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', name)
        path = os.path.join(outdir, safe + '.wom')
        open(path, 'wb').write(write_anim(bones))
        nk = max(len(b['keys']) for b in bones) if bones else 0
        print('Wrote %s  (%d bones, %d keys, %.3f s)' % (path, len(bones), nk, max(b['keys'][-1][1] for b in bones if b['keys']) if nk else 0))
        wrote += 1
    if only and not wrote:
        sys.exit('No animation named %s. Found: %s' % (', '.join(only), ', '.join(n for n, _ in results)))


# ---------------------------------------------------------------- folder batch
TEX_EXT = ('.dds', '.png', '.tga', '.jpg', '.jpeg', '.bmp')


def _res_rank(rel):
    """prefer textures/2048 > 1024 > 512 > 256 > anything else"""
    parts = rel.replace('\\', '/').lower().split('/')
    for i, r in enumerate(('2048', '1024', '512', '256')):
        if r in parts:
            return i
    return 4


class TextureIndex:
    def __init__(self, root):
        self.root = root
        self.by_stem = {}
        for dp, _, fs in os.walk(root):
            for f in fs:
                st, ext = os.path.splitext(f)
                if ext.lower() in TEX_EXT:
                    self.by_stem.setdefault(st.lower(), []).append(os.path.join(dp, f))

    def find(self, name, model_dir):
        st, ext = os.path.splitext(os.path.basename(name.replace('\\', '/')))
        cands = self.by_stem.get(st.lower(), [])
        if not cands:
            return None
        def key(p):
            same_dir = os.path.dirname(p) == model_dir
            same_ext = os.path.splitext(p)[1].lower() == ext.lower()
            return (not same_dir, _res_rank(os.path.relpath(p, self.root)), not same_ext, len(p))
        return sorted(cands, key=key)[0]


def _parse_properties(root):
    """{abs model path: [abs anim paths...]} from every properties.xml in the tree"""
    import xml.etree.ElementTree as ET
    out = {}
    for dp, _, fs in os.walk(root):
        for f in fs:
            if f.lower() != 'properties.xml':
                continue
            p = os.path.join(dp, f)
            try:
                r = ET.parse(p).getroot()
            except Exception as e:
                print('  ! could not read %s: %s' % (p, e)); continue
            for model in r:
                a = model.find('anim')
                if a is None:
                    continue
                files = []
                for e in a:
                    fe = e.find('file')
                    if fe is not None and fe.text:
                        files.append(os.path.normpath(os.path.join(dp, fe.text.strip().replace('\\', '/'))))
                if files:
                    out[os.path.normpath(os.path.join(dp, model.tag))] = list(dict.fromkeys(files))
    return out


def _ci_exists(path):
    """case-insensitive file lookup (game files mix case; Linux/macOS care)"""
    if os.path.exists(path):
        return path
    d, b = os.path.split(path)
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.lower() == b.lower():
                return os.path.join(d, f)
    return None


class Mirror:
    """Copy every non-.wom file of the input folder into the output folder (same layout).
    Textures can be converted to .png and/or upscaled on the way."""
    def __init__(self, in_dir, out_dir, png=False, upscale=1, engine=None, tiers=True, speed=None):
        self.in_dir, self.out_dir, self.png, self.upscale, self.engine, self.tiers = in_dir, out_dir, png, upscale, engine, tiers
        self.speed = speed or {}
        self.files = []
        for dp, dns, fs in os.walk(in_dir):
            dns.sort()
            if os.path.abspath(dp).startswith(out_dir):
                continue
            self.files += [os.path.join(dp, f) for f in sorted(fs) if not f.lower().endswith('.wom')]

    def is_tex(self, p):
        return p.lower().endswith(TEX_EXT)

    def out_path(self, src):
        rel = os.path.relpath(src, self.in_dir)
        if self.png and self.is_tex(src):
            rel = os.path.splitext(rel)[0] + '.png'
        return os.path.join(self.out_dir, rel)

    def ref(self, src, from_dir):
        """path to write in a .mtl / .glb that lives in from_dir"""
        return os.path.relpath(self.out_path(src), from_dir).replace(os.sep, '/')

    def run(self):
        import womfast
        higher = womtex.tier_pairs([f for f in self.files if self.is_tex(f)], self.in_dir) \
            if (self.upscale > 1 and self.tiers) else {}
        jobs = []
        for src in self.files:
            j = {'src': src, 'dst': self.out_path(src), 'name': os.path.relpath(src, self.in_dir)}
            if self.is_tex(src) and self.upscale > 1:
                if src in higher:
                    j.update(kind='shift', higher=higher[src])
                else:
                    j['kind'] = 'ai'
            else:
                j['kind'] = 'copy'
            jobs.append(j)
        opts = dict(scale=self.upscale, max_size=4096, ai_normals=False, ai_alpha=False, keep_color=True, strength=1.0,
                    png=self.png, **self.speed)
        engine = self.engine or womtex.LanczosEngine()
        womfast.upscale_many(jobs, engine, opts, 'Copying%s textures and other files to the output folder' %
                             (' and upscaling' if self.upscale > 1 else ''))

def place_texture(found, dst_dir, png, upscale, engine, tex_done, notes):
    """copy / convert / upscale one texture next to an .obj; returns the file name used"""
    import shutil
    st, ext = os.path.splitext(os.path.basename(found))
    out_name = st + ('.png' if png else ext)
    target = os.path.join(dst_dir, out_name)
    if (found, target) in tex_done:
        return tex_done[(found, target)]
    try:
        if upscale > 1:
            womprogress.label('upscaling ' + os.path.basename(found))
            womprogress.log('  upscaled %s: %s' % (os.path.basename(found), womtex.upscale_file(found, target, engine, upscale)))
        elif png and ext.lower() != '.png':
            from PIL import Image
            Image.open(found).save(target)
        else:
            shutil.copyfile(found, target)
    except Exception as e:
        out_name = st + ext; target = os.path.join(dst_dir, out_name)
        shutil.copyfile(found, target); notes.append('copied %s as-is (%s)' % (out_name, e))
    tex_done[(found, target)] = out_name
    return out_name


def export_mappings(mapping_path, in_dir, out_dir, variants=True, texidx=None, png=False, upscale=1, engine=None,
                    prefix=None, mirror=None):
    """Filtered mappings.txt for this folder + per-folder _mappings.txt + texture/material variants."""
    entries = wommap.parse_mappings(mapping_path)
    prefix, matched, missing = wommap.match(entries, in_dir, prefix)
    if prefix is None:
        print('No line in %s points at a file in %s' % (mapping_path, in_dir)); return []
    p, pm, per = wommap.write_reports(in_dir, out_dir, mapping_path, prefix, matched, missing)
    print('mappings: %d line(s) match files here (prefix "%s"), %d point at missing files' % (len(matched), prefix, len(missing)))
    print('  %s\n  %s\n  + %d per-folder _mappings.txt' % (p, pm, len(per)))
    lines = []
    if not variants:
        return lines
    texidx = texidx or TextureIndex(in_dir)
    models, tex_done, nvar = {}, {}, 0
    short = wommap.short_variant_names(matched)
    todo = [e for e in matched if e['rel'].lower().endswith('.wom') and e['overrides']]
    vp = Progress(len(todo), 'Writing texture/material variants')
    for e in todo:
        vp.step('%s__%s' % (os.path.splitext(os.path.basename(e['rel']))[0], short[e['key']]))
        src = os.path.join(in_dir, e['rel'])
        if src not in models:
            try:
                models[src] = read_wom(open(src, 'rb').read())
            except Exception as ex:
                models[src] = None; lines.append('variant skip %s (%s)' % (e['key'], ex))
        model = models[src]
        if model is None:
            continue
        vm, unknown = wommap.apply_overrides(model, e['overrides'])
        dst_dir = os.path.join(out_dir, os.path.dirname(e['rel']))
        os.makedirs(dst_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(e['rel']))[0]
        vbase = os.path.join(dst_dir, '%s__%s' % (base_name, short[e['key']]))
        tex_map, notes = {}, []
        for name in sorted({x['texture'] for m in vm['meshes'] for x in m['materials'] if x['texture']}):
            hit = None
            if '/' in name:
                cand = name.lower()
                if cand.startswith(prefix):
                    cand = cand[len(prefix):]
                hit = _ci_exists(os.path.join(in_dir, *cand.split('/')))
            hit = hit or texidx.find(name, os.path.dirname(src))
            if hit:
                tex_map[name] = mirror.ref(hit, dst_dir) if mirror else \
                    place_texture(hit, dst_dir, png, upscale, engine, tex_done, notes)
            else:
                notes.append('missing ' + name)
        main_obj = os.path.join(dst_dir, base_name + '.obj')
        if not os.path.exists(main_obj):
            quiet_flag[0] = True
            wom2obj(src, os.path.join(dst_dir, base_name), None, model)
            quiet_flag[0] = False
        write_mtl(vm, vbase + '.mtl', tex_map)
        with open(main_obj) as fi, open(vbase + '.obj', 'w', newline='\n') as fo:
            for ln in fi:
                fo.write('mtllib %s.mtl\n' % os.path.basename(vbase) if ln.startswith('mtllib ') else ln)
        nvar += 1
        if unknown:
            notes.append('no material named ' + ', '.join(unknown) + ' in the model')
        lines.append('variant  %s.obj  <- %s%s' % (os.path.relpath(vbase, out_dir), e['key'],
                     ('  [' + '; '.join(notes) + ']') if notes else ''))
    vp.done('%d variant(s) written as <model>__<item>.obj/.mtl' % nvar)
    return lines


def find_mappings(explicit=None):
    """explicit path, else mappings.txt next to this script (any letter case)"""
    if explicit:
        if not os.path.exists(explicit):
            sys.exit('mappings file not found: %s' % explicit)
        return explicit
    here = os.path.dirname(os.path.abspath(__file__))
    for f in os.listdir(here):
        if f.lower() == 'mappings.txt':
            return os.path.join(here, f)
    return None


def batch(in_dir, out_dir=None, png=False, textures=True, anims=True, glb_meshes=None, upscale=1, engine=None,
          mappings=None, place=True, speed=None):
    in_dir = os.path.abspath(in_dir)
    out_dir = os.path.abspath(out_dir or in_dir.rstrip('/\\') + '_obj')
    if out_dir == in_dir:
        sys.exit('Output folder must differ from the input folder.')
    quiet_flag[0] = True
    sp = Spinner('Scanning %s' % in_dir)
    texidx = TextureIndex(in_dir) if textures else None
    wom_files = []
    for dp, dns, fs in os.walk(in_dir):
        dns.sort()
        if os.path.abspath(dp).startswith(out_dir):
            continue
        wom_files += [os.path.join(dp, f) for f in sorted(fs) if f.lower().endswith('.wom')]
    sp.done('%d .wom files, %d textures' % (len(wom_files), sum(len(v) for v in texidx.by_stem.values()) if texidx else 0))
    if png or upscale > 1:
        try:
            from PIL import Image
        except ImportError:
            if upscale > 1:
                sys.exit('Upscaling needs Pillow: pip install --upgrade pillow')
            print('Pillow not installed (pip install pillow): copying textures as-is instead of PNG')
            png = False
    mirror = Mirror(in_dir, out_dir, png, upscale, engine, speed=speed) if textures else None
    if mirror:
        mirror.run()
    report = []
    n_models = n_anims = n_fail = 0
    tex_done = {}
    missing_tex = set()
    bodies = {}
    for wf in wom_files:
        b = os.path.basename(wf).lower()
        if b in ('female_1_04.wom', 'male_1_04.wom'):
            bodies[b.split('_')[0]] = wf
    prog = Progress(len(wom_files), 'Converting .wom files')
    for src in wom_files:
        dp, f = os.path.split(src)
        rel = os.path.relpath(src, in_dir)
        prog.step(rel)
        data = open(src, 'rb').read()
        try:
            model = read_wom(data)
        except Exception as e:
            if is_anim(data):
                n_anims += 1
                continue
            n_fail += 1; report.append('FAILED   %s  (%s)' % (rel, e)); prog.log('  FAILED %s (%s)' % (rel, e)); continue
        dst_dir = os.path.join(out_dir, os.path.dirname(rel))
        os.makedirs(dst_dir, exist_ok=True)
        tex_map, tex_notes = {}, []
        if texidx:
            for name in sorted({x['texture'] for m in model['meshes'] for x in m['materials'] if x['texture']}):
                found = texidx.find(name, dp)
                if not found:
                    missing_tex.add(name); tex_notes.append('missing ' + name); continue
                out_name = mirror.ref(found, dst_dir)
                tex_map[name] = out_name
        base = os.path.join(dst_dir, os.path.splitext(f)[0])
        try:
            pl = None
            parts = [p.lower() for p in rel.replace('\\', '/').split('/')[:-1]]
            if place and not model['joints'] and ('hair' in parts or 'helms' in parts) and bodies:
                body = bodies.get('female') if 'female' in f.lower() else (bodies.get('male') or bodies.get('female'))
                body = body or next(iter(bodies.values()))
                try:
                    pl = placement_matrix(body, 'NullHelmet', src)
                    tex_notes.append('shown on %s at NullHelmet%s' % (os.path.basename(body), ' + offsetToNull' if pl[1]['offset'] else ''))
                except Exception as e:
                    tex_notes.append('could not place on body: %s' % e)
            wom2obj(src, base, tex_map, model, pl)
        except Exception as e:
            n_fail += 1; report.append('FAILED   %s  (%s)' % (rel, e)); continue
        n_models += 1
        report.append('model    %s  %d meshes, %d joints%s%s' % (
            rel, len(model['meshes']), len(model['joints']),
            ', skinned' if any(m['skin'] for m in model['meshes']) else '',
            ('  [' + '; '.join(tex_notes) + ']') if tex_notes else ''))
    prog.done('%d models, %d animation files, %d failed' % (n_models, n_anims, n_fail))
    # characters + their animations -> .glb
    glbs = 0
    if anims:
        props = _parse_properties(in_dir)
        gp = Progress(len(props), 'Building character .glb files with animations')
        for mpath, apaths in sorted(props.items()):
            gp.step('%s (%d animations)' % (os.path.relpath(mpath, in_dir), len(apaths)))
            mreal = _ci_exists(mpath)
            if not mreal:
                report.append('glb skip %s (model not found)' % os.path.relpath(mpath, in_dir)); continue
            found, lost = [], []
            for a in apaths:
                ar = _ci_exists(a)
                if ar and is_anim(open(ar, 'rb').read()):
                    found.append(ar)
                else:
                    lost.append(os.path.relpath(a, in_dir))
            if not found:
                continue
            rel = os.path.relpath(mreal, in_dir)
            out = os.path.join(out_dir, os.path.splitext(rel)[0] + '_anims.glb')
            os.makedirs(os.path.dirname(out), exist_ok=True)
            model = read_wom(open(mreal, 'rb').read())
            # point the glb at the textures copied next to the .obj
            mdl_tex = {}
            if texidx:
                for name in {x['texture'] for m in model['meshes'] for x in m['materials'] if x['texture']}:
                    hit = texidx.find(name, os.path.dirname(mreal))
                    if hit:
                        mdl_tex[name] = mirror.ref(hit, os.path.dirname(out))
            for m in model['meshes']:
                for x in m['materials']:
                    x['texture'] = mdl_tex.get(x['texture'], x['texture'])
            al = []
            for k, a in enumerate(found):
                gp.sub_progress(0.5 * k / len(found), 'reading ' + os.path.basename(a))
                al.append((os.path.splitext(os.path.basename(a))[0], read_anim(open(a, 'rb').read())))
            gp.sub_progress(0.5, 'writing ' + os.path.basename(out))
            flt = re.compile(glb_meshes).search if glb_meshes else None
            womgltf.export_glb(model, al, out, flt)
            glbs += 1
            report.append('glb      %s  %d animations%s' % (os.path.relpath(out, out_dir), len(found),
                          ('  [%d listed in properties.xml but not found: %s%s]' % (len(lost), ', '.join(lost[:8]), ' ...' if len(lost) > 8 else '')) if lost else ''))
        gp.done('%d .glb file(s)' % glbs)
    quiet_flag[0] = False
    if mappings:
        print('Using %s' % mappings)
        report += export_mappings(mappings, in_dir, out_dir, True, texidx, png, upscale, engine, mirror=mirror)
    os.makedirs(out_dir, exist_ok=True)
    rp = os.path.join(out_dir, 'conversion_report.txt')
    with open(rp, 'w', encoding='utf-8') as fh:
        fh.write('Source: %s\n' % in_dir)
        fh.write('%d models converted, %d animation files, %d .glb files, %d failed\n' % (n_models, n_anims, glbs, n_fail))
        if missing_tex:
            fh.write('Textures not found anywhere in the folder: %s\n' % ', '.join(sorted(missing_tex)))
        fh.write('\n' + '\n'.join(report) + '\n')
    print('Converted %d model(s) into %s' % (n_models, out_dir))
    print('  %d animation file(s) found%s' % (n_anims, ', %d character .glb file(s) with animations' % glbs if anims else ''))
    if n_fail:
        print('  %d file(s) failed - see report' % n_fail)
    if missing_tex:
        print('  %d texture(s) not found - see report' % len(missing_tex))
    print('  Report: %s' % rp)


def batch_back(in_dir, out_dir=None):
    """every .obj with a .womdata.json next to it -> .wom"""
    in_dir = os.path.abspath(in_dir)
    out_dir = os.path.abspath(out_dir or in_dir.rstrip('/\\') + '_wom')
    n = 0
    jobs = []
    for dp, dns, fs in os.walk(in_dir):
        dns.sort()
        for f in sorted(fs):
            if f.lower().endswith('.obj'):
                src = os.path.join(dp, f)
                side = os.path.splitext(src)[0] + '.womdata.json'
                if os.path.exists(side):
                    jobs.append((src, side))
    prog = Progress(len(jobs), 'Rebuilding .wom files')
    failed = 0
    for src, side in jobs:
        rel = os.path.relpath(src, in_dir)
        prog.step(rel)
        dst = os.path.join(out_dir, os.path.relpath(os.path.splitext(src)[0] + '.wom', in_dir))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            changed = obj2wom(src, side, dst, quiet=True)
            if changed:
                prog.log('  %s: %s' % (rel, changed))
            n += 1
        except SystemExit as e:
            failed += 1; prog.log('  FAILED %s: %s' % (rel, e))
        except Exception as e:
            failed += 1; prog.log('  FAILED %s: %s' % (rel, e))
    prog.done('%d rebuilt into %s%s' % (n, out_dir, (', %d failed' % failed) if failed else ''))


def info(path):
    data = open(path, 'rb').read()
    if is_anim(data):
        a = read_anim(data)
        keyed = [b for b in a if b['keys']]
        end = max(b['keys'][-1][1] for b in keyed) if keyed else 0
        print('%s: ANIMATION, %d bones (%d keyed), %.3f s, %d keys' % (path, len(a), len(keyed), end, max(len(b['keys']) for b in a)))
        for b in a:
            print('  %-20s %d keys' % (b['name'] or '(empty)', len(b['keys'])))
        return
    m = read_wom(data)
    print('%s: %d meshes, %d joints' % (path, len(m['meshes']), len(m['joints'])))
    for x in m['meshes']:
        mat = x['materials'][0] if x['materials'] else {'texture': '', 'name': ''}
        sk = ', '.join(b['joint'] for b in x['skin']) if x['skin'] else '-'
        print('  %-26s %6d verts %6d tris  tex=%-26s mat=%-18s bones: %s' % (
            x['name'], len(x['verts']), len(x['indices']) // 3, mat['texture'], mat['name'], sk))
    if m['joints']:
        print('Joints:')
        for j in m['joints']:
            t = j['bind_world']
            print('  %-20s parent=%-18s pos=(%.3f, %.3f, %.3f)' % (j['name'], j['parent'] or '-', t[3], t[7], t[11]))


from wom_viewer import run_viewer  # noqa: E402  (viewer launcher: Steam lookup + local jar server)


def main():
    ap = argparse.ArgumentParser(description='Wurm Unlimited WOM <-> OBJ converter')
    vf = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'VERSION.txt')
    ap.add_argument('--version', action='version',
                    version=open(vf).readline().strip() if os.path.exists(vf) else 'WOM Converter (version file missing)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('wom2obj', help='convert .wom to .obj/.mtl/.womdata.json')
    a.add_argument('--attach-to', help='body .wom (e.g. female_1_04.wom): show this hair/helmet on that body\'s head in Blender')
    a.add_argument('--bone', default='NullHelmet', help='bone it hangs from (default NullHelmet, used by hair and helmets)')
    a.add_argument('wom'); a.add_argument('-o', '--out', help='output base path (no extension)')
    b = sub.add_parser('obj2wom', help='convert .obj back to .wom')
    b.add_argument('obj')
    b.add_argument('-d', '--data', help='.womdata.json from wom2obj (default: next to the .obj)')
    b.add_argument('-o', '--out', help='output .wom path (default: <obj>_new.wom)')
    b.add_argument('--weights-from', help='comma list of original meshes new meshes copy weights from, e.g. backpartMesh,upperFace0Mesh')
    b.add_argument('--material-like', help='original material name to copy settings from for new materials')
    b.add_argument('--tangents', choices=['yes', 'no'], help='force tangents on/off for rebuilt meshes')
    b.add_argument('--keep-missing', action='store_true', help='keep original meshes that are missing from the OBJ')
    g = sub.add_parser('glb', help='model .wom (+ animation .wom files) -> .glb for Blender')
    g.add_argument('model'); g.add_argument('anims', nargs='*')
    g.add_argument('-o', '--out', help='output .glb (default: <model>.glb)')
    g.add_argument('--meshes', help='regex: only include matching meshes, e.g. "00|0Mesh|backpart"')
    h = sub.add_parser('glb2anim', help='animations in a .glb -> animation .wom files')
    h.add_argument('glb'); h.add_argument('model', help='the model .wom whose skeleton the animation is for')
    h.add_argument('-o', '--outdir'); h.add_argument('--only', help='comma list of animation names to export')
    h.add_argument('--template', help='existing animation .wom to copy the bone list/order from')
    h.add_argument('--fps', type=float, default=30, help='key rate (default 30, like the game files; 0 = keep glTF keys)')
    h.add_argument('--include-null', action='store_true', help='also write Null* attachment bones')
    k = sub.add_parser('batch', help='convert every model .wom in a folder (and subfolders) to .obj, with textures and character .glb files')
    k.add_argument('folder'); k.add_argument('-o', '--out', help='output folder (default: <folder>_obj)')
    k.add_argument('--png', action='store_true', help='convert textures to .png (needs Pillow)')
    k.add_argument('--no-textures', action='store_true', help="don't copy textures")
    k.add_argument('--no-anims', action='store_true', help="don't build the character + animation .glb files")
    k.add_argument('--glb-meshes', help='regex: only these meshes in the .glb files')
    k.add_argument('--upscale', type=int, choices=[2, 4], help='also AI-upscale the copied textures 2x or 4x')
    k.add_argument('--engine', default='auto', choices=['auto', 'gpu', 'cpu', 'lanczos'])
    u = sub.add_parser('upscale', help='AI-upscale a texture file or a whole folder of textures (.dds stays .dds)')
    u.add_argument('path'); u.add_argument('-o', '--out', help='output file/folder (default: <folder>_upscaled)')
    u.add_argument('--scale', type=int, default=2, choices=[2, 4])
    u.add_argument('--engine', default='auto', choices=['auto', 'gpu', 'cpu', 'lanczos'],
                   help='auto = GPU if installed, else CPU AI')
    u.add_argument('--model', default='realesrgan-x4plus', help='GPU model name (see the realesrgan/models folder)')
    u.add_argument('--max-size', type=int, default=4096, help="don't make textures bigger than this (default 4096)")
    u.add_argument('--png', action='store_true', help='write .png instead of the original format')
    u.add_argument('--ai-normals', action='store_true', help='run normal maps through the AI too (default: plain resize)')
    u.add_argument('--ai-alpha', action='store_true', help='run the alpha channel through the AI too (default: plain resize)')
    u.add_argument('--strength', type=float, default=1.0, help='0..1: blend AI with plain resize (lower keeps more fine fabric detail)')
    u.add_argument('--full-color', action='store_true', help='let the AI change colours too (default: AI on brightness only, avoids colour fringes)')
    u.add_argument('--no-tiers', action='store_true', help="don't use the 256/512/1024/2048 folders as references; AI-upscale every file")
    u.add_argument('--cpu-model', default=None, help='CPU model: realesr-general-wdn-x4v3 (default, keeps texture) or realesr-general-x4v3 (smoother)')
    for p_ in (k, u):
        p_.add_argument('--gpu-id', help='which GPU(s): a number (see gpu-check), several like 0,1, or "all" to share the work between all GPUs')
        p_.add_argument('--gpu-jobs', help='images on each GPU at the same time (default: from its free video memory; a built-in GPU gets 1). One number, or one per GPU like 4,1')
        p_.add_argument('--cpu-jobs', type=int, help='CPU workers for reading/finishing textures (default: all threads - 1, max 16)')
        p_.add_argument('--cpu-cores', choices=['all', 'p'], default='all',
                        help='CPUs with P- and E-cores: all = use both (default, most work done); p = keep the workers on the P-cores')
        p_.add_argument('--tile', type=int, help='GPU tile size (default: automatic). Smaller uses less video memory')
        p_.add_argument('--redo', action='store_true', help='redo textures that are already done (default: skip them)')
        p_.add_argument('--repair', action='store_true', help='check finished textures against the originals and redo only damaged ones (e.g. half black after a crash)')
    sub.add_parser('setup-gpu', help='download the realesrgan-ncnn-vulkan GPU engine next to the tool')
    sub.add_parser('gpu-check', help='test the GPU engine and list the GPUs it can use (NVIDIA, AMD Radeon, Intel Arc)')
    k.add_argument('--no-place', action='store_true', help="don't move hair/helmet models onto the body's head in the .obj")
    k.add_argument('--mappings', help="mappings.txt to use (default: mappings.txt next to wom_tool.py, if present)")
    k.add_argument('--no-mappings', action='store_true', help="don't use mappings.txt")
    mp = sub.add_parser('mappings', help="find the mappings.txt lines that use files in a folder; export texture variants")
    mp.add_argument('folder')
    mp.add_argument('--file', help='mappings.txt to use (default: mappings.txt next to wom_tool.py)')
    mp.add_argument('-o', '--out', help='output folder (default: <folder>_obj)')
    mp.add_argument('--no-variants', action='store_true', help='only write the text files')
    mp.add_argument('--prefix', help='path prefix of this folder inside the game, e.g. "player/" (default: detected)')
    mp.add_argument('--png', action='store_true')
    kb = sub.add_parser('batch-back', help='convert every .obj (that has a .womdata.json) in a folder back to .wom')
    kb.add_argument('folder'); kb.add_argument('-o', '--out', help='output folder (default: <folder>_wom)')
    vw = sub.add_parser('viewer', help='open the model viewer with the game\'s graphics.jar (found through Steam) already loaded')
    vw.add_argument('--jar', help='graphics.jar to load (default: found through Steam)')
    vw.add_argument('--port', type=int, default=0, help='local port (default: any free one)')
    vw.add_argument('--no-jar', action='store_true', help='just open the page, no game files')
    c = sub.add_parser('info', help='list meshes, materials, bones of a .wom')
    c.add_argument('wom')
    args = ap.parse_args()
    if args.cmd == 'batch':
        eng = womtex.make_engine(args.engine, None, 'realesrgan-x4plus', args.gpu_id) if args.upscale else None
        if eng:
            print('Texture engine: %s' % eng.name)
        speed = dict(cpu_jobs=args.cpu_jobs, gpu_jobs=args.gpu_jobs, tile=args.tile, redo=args.redo, repair=args.repair, cpu_cores=args.cpu_cores)
        batch(args.folder, args.out, args.png, not args.no_textures, not args.no_anims, args.glb_meshes,
              args.upscale or 1, eng, None if args.no_mappings else find_mappings(args.mappings), not args.no_place, speed)
        return
    if args.cmd == 'mappings':
        fo = os.path.abspath(args.folder)
        mt = find_mappings(args.file)
        if not mt:
            sys.exit('mappings.txt not found. Put the game\'s mappings.txt next to wom_tool.py, or use --file.')
        export_mappings(mt, fo, os.path.abspath(args.out or fo.rstrip('/\\') + '_obj'),
                        not args.no_variants, None, args.png, prefix=args.prefix)
        return
    if args.cmd == 'viewer':
        run_viewer(args)
        return
    if args.cmd == 'gpu-check':
        sys.exit(0 if womtex.gpu_check() else 1)
    if args.cmd == 'setup-gpu':
        womtex.setup_gpu()
        return
    if args.cmd == 'upscale':
        eng = womtex.make_engine(args.engine, None, args.model, args.gpu_id, args.cpu_model)
        print('Engine: %s' % eng.name)
        womtex.upscale_path(args.path, args.out, eng, args.scale, args.max_size, args.ai_normals, args.ai_alpha, args.png,
                            not args.full_color, args.strength, not args.no_tiers,
                            args.cpu_jobs, args.gpu_jobs, args.tile, args.redo, args.repair, args.cpu_cores)
        return
    if args.cmd == 'batch-back':
        batch_back(args.folder, args.out)
        return
    if args.cmd == 'glb':
        to_glb(args.model, args.anims, args.out or os.path.splitext(args.model)[0] + '.glb', args.meshes)
        return
    if args.cmd == 'glb2anim':
        from_glb(args.glb, args.model, args.outdir, args.only.split(',') if args.only else None,
                 args.template, args.fps or None, args.include_null)
        return
    if args.cmd == 'wom2obj':
        place = placement_matrix(args.attach_to, args.bone, args.wom) if args.attach_to else None
        wom2obj(args.wom, args.out, place=place)
    elif args.cmd == 'info':
        info(args.wom)
    else:
        obj2wom(args.obj, args.data, args.out,
                args.weights_from.split(',') if args.weights_from else None,
                args.material_like,
                None if args.tangents is None else args.tangents == 'yes',
                args.keep_missing)


if __name__ == '__main__':
    main()
