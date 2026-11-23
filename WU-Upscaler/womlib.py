"""Reader/writer for Wurm Unlimited .wom model files.

Layout (all little-endian):
  int meshCount
  per mesh:
    u8 hasTangents, u8 hasBinormals, u8 hasColors
    str name
    int vertexCount
    per vertex: pos(3f) normal(3f) uv(2f) [color 3f] [tangent 3f] [binormal 3f]
    int indexCount, then indexCount * u16 (triangles)
    int materialCount
    per material: str texture, str name, u8 enabled,
                  [u8 has, 4f emissive] [u8 has, 1f shininess]
                  [u8 has, 4f specular] [u8 has, 4f transparency]
  int jointCount
  per joint: str parent, str name, u8 flag, 16f bindWorld, 16f bindLocal
  per mesh:
    u8 hasSkinning
    if hasSkinning:
      int boneCount
      per bone: str jointName, 16f matrix, 16f inverseMatrix,
                int weightCount, per weight: int vertexIndex, f weight
"""
import struct


class Reader:
    def __init__(self, data):
        self.d, self.p = data, 0

    def i32(self):
        v = struct.unpack_from('<i', self.d, self.p)[0]; self.p += 4; return v

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def f(self, n):
        v = list(struct.unpack_from('<%df' % n, self.d, self.p)); self.p += 4 * n; return v

    def s(self):
        n = self.i32(); v = self.d[self.p:self.p + n]; self.p += n
        return v.decode('utf-8')


class Writer:
    def __init__(self):
        self.b = bytearray()

    def i32(self, v): self.b += struct.pack('<i', v)
    def u8(self, v): self.b += bytes([v])
    def f(self, vals): self.b += struct.pack('<%df' % len(vals), *vals)

    def s(self, v):
        e = v.encode('utf-8'); self.i32(len(e)); self.b += e


MAT_PROPS = [('emissive', 4), ('shininess', 1), ('specular', 4), ('transparency', 4)]


def read_wom(data):
    r = Reader(data)
    meshes = []
    for _ in range(r.i32()):
        m = {'tangents': r.u8(), 'binormals': r.u8(), 'colors': r.u8()}
        m['name'] = r.s()
        nv = r.i32()
        verts = []
        for _ in range(nv):
            v = {'pos': r.f(3), 'normal': r.f(3), 'uv': r.f(2)}
            if m['colors']: v['color'] = r.f(3)
            if m['tangents']: v['tangent'] = r.f(3)
            if m['binormals']: v['binormal'] = r.f(3)
            verts.append(v)
        m['verts'] = verts
        ni = r.i32()
        m['indices'] = list(struct.unpack_from('<%dH' % ni, r.d, r.p)); r.p += 2 * ni
        mats = []
        for _ in range(r.i32()):
            mat = {'texture': r.s(), 'name': r.s(), 'enabled': r.u8()}
            for key, n in MAT_PROPS:
                mat[key] = r.f(n) if r.u8() else None
            mats.append(mat)
        m['materials'] = mats
        meshes.append(m)
    joints = []
    for _ in range(r.i32()):
        joints.append({'parent': r.s(), 'name': r.s(), 'flag': r.u8(),
                       'bind_world': r.f(16), 'bind_local': r.f(16)})
    for m in meshes:
        m['skin'] = None
        if r.u8():
            bones = []
            for _ in range(r.i32()):
                b = {'joint': r.s(), 'matrix': r.f(16), 'inverse': r.f(16)}
                b['weights'] = [(r.i32(), r.f(1)[0]) for _ in range(r.i32())]
                bones.append(b)
            m['skin'] = bones
    if r.p != len(data):
        raise ValueError('WOM parse ended at byte %d of %d' % (r.p, len(data)))
    return {'meshes': meshes, 'joints': joints}


def write_wom(model):
    w = Writer()
    meshes = model['meshes']
    w.i32(len(meshes))
    for m in meshes:
        w.u8(m['tangents']); w.u8(m['binormals']); w.u8(m['colors'])
        w.s(m['name'])
        w.i32(len(m['verts']))
        for v in m['verts']:
            w.f(v['pos']); w.f(v['normal']); w.f(v['uv'])
            if m['colors']: w.f(v['color'])
            if m['tangents']: w.f(v['tangent'])
            if m['binormals']: w.f(v['binormal'])
        if len(m['verts']) > 65535:
            raise ValueError('mesh %s has more than 65535 vertices' % m['name'])
        w.i32(len(m['indices']))
        w.b += struct.pack('<%dH' % len(m['indices']), *m['indices'])
        w.i32(len(m['materials']))
        for mat in m['materials']:
            w.s(mat['texture']); w.s(mat['name']); w.u8(mat['enabled'])
            for key, n in MAT_PROPS:
                if mat.get(key) is None:
                    w.u8(0)
                else:
                    w.u8(1); w.f(mat[key])
    w.i32(len(model['joints']))
    for j in model['joints']:
        w.s(j['parent']); w.s(j['name']); w.u8(j['flag'])
        w.f(j['bind_world']); w.f(j['bind_local'])
    for m in meshes:
        if not m.get('skin'):
            w.u8(0); continue
        w.u8(1); w.i32(len(m['skin']))
        for b in m['skin']:
            w.s(b['joint']); w.f(b['matrix']); w.f(b['inverse'])
            w.i32(len(b['weights']))
            for vi, wt in b['weights']:
                w.i32(vi); w.f([wt])
    return bytes(w.b)


# ------------------------------------------------------------ animation files
# Layout: int boneCount; per bone: str name, int keyCount,
#         keyCount * (16f local matrix row-major (parent-relative), f time in seconds)
def read_anim(data):
    r = Reader(data)
    bones = []
    for _ in range(r.i32()):
        name = r.s()
        keys = []
        for _ in range(r.i32()):
            m = r.f(16); t = r.f(1)[0]
            keys.append((m, t))
        bones.append({'name': name, 'keys': keys})
    if r.p != len(data):
        raise ValueError('animation parse ended at byte %d of %d' % (r.p, len(data)))
    return bones


def write_anim(bones):
    w = Writer()
    w.i32(len(bones))
    for b in bones:
        w.s(b['name']); w.i32(len(b['keys']))
        for m, t in b['keys']:
            w.f(list(m)); w.f([t])
    return bytes(w.b)


def is_anim(data):
    """True if data parses as an animation file rather than a model."""
    try:
        read_anim(data); return True
    except Exception:
        return False
