"""Texture upscaling for Wurm Unlimited textures (.dds/.png/.jpg/.tga).

Engines
  gpu    realesrgan-ncnn-vulkan (any NVIDIA/AMD/Intel GPU via Vulkan; model realesrgan-x4plus).
         The "Install GPU engine" button downloads it next to the tool.
  cpu    the same family of AI model (realesr-general-x4v3) run with numpy. Slower; no GPU needed.
  lanczos  plain resize, no AI.

DDS files are written back as DDS with the same compression (DXT1/DXT3/DXT5 or uncompressed)
and a full mipmap chain if the original had one, so the game can load them directly.
"""
import io
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

import numpy as np
from PIL import Image

import womprogress
from womprogress import Progress

HERE = os.path.dirname(os.path.abspath(__file__))
TEX_EXT = ('.dds', '.png', '.jpg', '.jpeg', '.tga', '.bmp')
NORMAL_HINTS = ('_n.', '_nm.', '_nrm.', '_normal', 'normalmap', '_norm.', '_nor.')
GPU_ZIP = {
    'Windows': 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip',
    'Linux': 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-ubuntu.zip',
    'Darwin': 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-macos.zip',
}
CPU_WEIGHTS_URL = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth'


# ------------------------------------------------------------------ DDS info / writing
def dds_info(path):
    """(fourcc or 'RGBA', has_mips) for a .dds; None for other files"""
    with open(path, 'rb') as f:
        h = f.read(128)
    if len(h) < 128 or h[:4] != b'DDS ':
        return None
    mips = struct.unpack_from('<I', h, 28)[0]
    pf_flags = struct.unpack_from('<I', h, 80)[0]
    fourcc = h[84:88].decode('ascii', 'replace') if pf_flags & 0x4 else 'RGBA'
    return fourcc, mips > 1


def _encode_level(img, fourcc):
    b = io.BytesIO()
    if fourcc in ('DXT1', 'DXT3', 'DXT5'):
        img.save(b, 'DDS', pixel_format=fourcc)
    else:
        img.convert('RGBA').save(b, 'DDS')
    data = b.getvalue()
    hdr = 148 if data[84:88] == b'DX10' else 128
    return data[:hdr], data[hdr:]


def save_dds(img, path, fourcc='DXT1', mipmaps=True):
    if fourcc not in ('DXT1', 'DXT3', 'DXT5', 'RGBA'):
        fourcc = 'DXT5' if img.mode == 'RGBA' else 'DXT1'
    img = img.convert('RGBA') if (fourcc != 'DXT1' or img.mode == 'RGBA') else img.convert('RGB')
    header, payload = _encode_level(img, fourcc)
    if not mipmaps:
        open(path, 'wb').write(header + payload); return
    levels = [payload]
    w, h = img.size
    lvl = img
    while w > 1 or h > 1:
        w, h = max(1, w // 2), max(1, h // 2)
        lvl = lvl.resize((w, h), Image.LANCZOS)
        enc = lvl if (w >= 4 and h >= 4) else lvl.resize((max(4, w), max(4, h)), Image.NEAREST)
        _, p = _encode_level(enc, fourcc)
        if fourcc in ('DXT1', 'DXT3', 'DXT5') and (w < 4 or h < 4):
            p = p[:((w + 3) // 4) * ((h + 3) // 4) * (8 if fourcc == 'DXT1' else 16)]
        elif fourcc == 'RGBA' and (w < 4 or h < 4):
            p = np.asarray(lvl.convert('RGBA'))[:, :, [2, 1, 0, 3]].tobytes()
        levels.append(p)
    hb = bytearray(header)
    struct.pack_into('<I', hb, 8, struct.unpack_from('<I', hb, 8)[0] | 0x20000)   # DDSD_MIPMAPCOUNT
    struct.pack_into('<I', hb, 28, len(levels))
    struct.pack_into('<I', hb, 108, struct.unpack_from('<I', hb, 108)[0] | 0x400008)  # COMPLEX | MIPMAP
    open(path, 'wb').write(bytes(hb) + b''.join(levels))


# ------------------------------------------------------------------ engines
class LanczosEngine:
    name = 'lanczos'

    def run(self, rgb, scale):
        w, h = rgb.size
        return rgb.resize((w * scale, h * scale), Image.LANCZOS)


class CpuEngine:
    """realesr-general-x4v3 (SRVGGNetCompact) implemented with numpy."""
    def __init__(self, weights=None):
        weights = weights or os.path.join(HERE, 'realesr-general-wdn-x4v3.npz')
        self.weights = weights
        self.name = 'cpu (%s)' % os.path.splitext(os.path.basename(weights))[0]
        if not os.path.exists(weights):
            raise FileNotFoundError('CPU model weights not found: %s' % weights)
        p = np.load(weights)
        n = len([k for k in p.files if k.endswith('.bias')])
        self.layers = []
        i = 0
        while 'body.%d.weight' % i in p.files:
            w = p['body.%d.weight' % i]
            if w.ndim == 4:
                self.layers.append(('conv', w.astype(np.float32), p['body.%d.bias' % i].astype(np.float32)))
            else:
                self.layers.append(('prelu', w.astype(np.float32)))
            i += 1
        del n

    @staticmethod
    def _conv(x, w, b):
        # x: (C,H,W)  w: (O,C,3,3)
        c, hh, ww = x.shape
        xp = np.pad(x, ((0, 0), (1, 1), (1, 1)))
        out = np.empty((w.shape[0], hh, ww), np.float32)
        out[:] = b[:, None, None]
        wm = w.reshape(w.shape[0], c, 9)
        for k in range(9):
            dy, dx = divmod(k, 3)
            out += np.tensordot(wm[:, :, k], xp[:, dy:dy + hh, dx:dx + ww], axes=(1, 0))
        return out

    def _net(self, x):
        h = x
        for layer in self.layers:
            if layer[0] == 'conv':
                h = self._conv(h, layer[1], layer[2])
            else:
                a = layer[1][:, None, None]
                h = np.where(h >= 0, h, h * a)
        c, hh, ww = h.shape          # pixel shuffle x4
        r = 4
        h = h.reshape(3, r, r, hh, ww).transpose(0, 3, 1, 4, 2).reshape(3, hh * r, ww * r)
        return h + np.repeat(np.repeat(x, r, 1), r, 2)

    def run(self, rgb, scale, tile=96, pad=10):
        a = np.asarray(rgb.convert('RGB'), np.float32).transpose(2, 0, 1) / 255.0
        _, H, W = a.shape
        out = np.zeros((3, H * 4, W * 4), np.float32)
        ntiles = ((H + tile - 1) // tile) * ((W + tile - 1) // tile); k = 0
        for y in range(0, H, tile):
            for x in range(0, W, tile):
                womprogress.sub(k / ntiles, 'AI tile %d/%d' % (k + 1, ntiles)); k += 1
                y0, x0 = max(0, y - pad), max(0, x - pad)
                y1, x1 = min(H, y + tile + pad), min(W, x + tile + pad)
                r = self._net(a[:, y0:y1, x0:x1])
                ty, tx = min(tile, H - y), min(tile, W - x)
                out[:, y * 4:(y + ty) * 4, x * 4:(x + tx) * 4] = \
                    r[:, (y - y0) * 4:(y - y0 + ty) * 4, (x - x0) * 4:(x - x0 + tx) * 4]
        img = Image.fromarray((np.clip(out, 0, 1).transpose(1, 2, 0) * 255 + 0.5).astype(np.uint8))
        return img if scale == 4 else img.resize((W * scale, H * scale), Image.LANCZOS)


def find_gpu_exe(explicit=None):
    names = ['realesrgan-ncnn-vulkan.exe', 'realesrgan-ncnn-vulkan']
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for d in [os.path.join(HERE, 'realesrgan'), HERE]:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


class GpuEngine:
    def __init__(self, exe, model='realesrgan-x4plus', gpu_id=None):
        self.exe, self.model = exe, model
        self.gpu_id = parse_gpu_ids(gpu_id, exe)   # None (engine picks), or a list of GPU numbers
        self.name = 'gpu (%s)' % model

    def run(self, rgb, scale):
        native = 2 if model_is_x2(self.model) else 4
        with tempfile.TemporaryDirectory() as td:
            i, o = os.path.join(td, 'in.png'), os.path.join(td, 'out.png')
            rgb.convert('RGB').save(i)
            cmd = [self.exe, '-i', i, '-o', o, '-n', self.model, '-s', str(native)]
            mdir = os.path.join(os.path.dirname(self.exe), 'models')
            if os.path.isdir(mdir):
                cmd += ['-m', mdir]
            if self.gpu_id:
                cmd += ['-g', str(self.gpu_id[0])]   # one picture: one GPU
            pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            tail = []
            for ln in pr.stdout:
                ln = ln.strip()
                tail = (tail + [ln])[-6:]
                if ln.endswith('%'):
                    try:
                        womprogress.sub(float(ln[:-1]) / 100.0, 'GPU')
                    except ValueError:
                        pass
            pr.wait()
            if pr.returncode != 0 or not os.path.exists(o):
                raise RuntimeError('realesrgan-ncnn-vulkan failed: %s' % ' | '.join(tail)[-400:])
            out = Image.open(o).convert('RGB'); out.load()
        w, h = rgb.size
        return out if out.size == (w * scale, h * scale) else out.resize((w * scale, h * scale), Image.LANCZOS)


def model_is_x2(model):
    return model.endswith('x2') or 'x2' in model.split('-')[-1]


class FallbackEngine:
    """GPU engine that switches to the CPU engine if the GPU run fails (driver/Vulkan problems)."""
    def __init__(self, gpu, cpu_weights=None):
        self.cur = gpu; self.name = gpu.name; self.cpu_weights = cpu_weights

    def run(self, rgb, scale):
        try:
            return self.cur.run(rgb, scale)
        except RuntimeError as e:
            if not isinstance(self.cur, GpuEngine):
                raise
            womprogress.log('  GPU engine failed (%s). Switching to the CPU engine.' % str(e).splitlines()[-1][:120])
            try:
                self.cur = CpuEngine(self.cpu_weights)
            except FileNotFoundError:
                self.cur = LanczosEngine()
            self.name = self.cur.name
            return self.cur.run(rgb, scale)


def make_engine(kind='auto', exe=None, model='realesrgan-x4plus', gpu_id=None, cpu_model=None):
    cpu_w = os.path.join(HERE, cpu_model + '.npz') if cpu_model else None
    if kind in ('auto', 'gpu'):
        p = find_gpu_exe(exe)
        if p:
            g = GpuEngine(p, model, gpu_id)
            return FallbackEngine(g, cpu_w) if kind == 'auto' else g
        if kind == 'gpu':
            sys.exit('realesrgan-ncnn-vulkan not found. Use the "Install GPU engine" button on the page.')
        print('GPU engine not found (use the "Install GPU engine" button to install it); using the CPU engine.')
    if kind in ('auto', 'cpu'):
        try:
            return CpuEngine(cpu_w)
        except FileNotFoundError as e:
            if kind == 'cpu':
                sys.exit(str(e))
            print('%s; using plain Lanczos resize.' % e)
    return LanczosEngine()


def list_gpus(exe=None):
    """[(number, name)] of the GPUs the engine can use, from a quick test run (or [] if it can't run)"""
    return _probe(exe)[0]


def parse_gpu_ids(value, exe=None):
    """--gpu-id: None, 3, '1', '0,1' or 'all' -> None or a list of GPU numbers"""
    if value is None or value == '':
        return None
    if isinstance(value, int):
        return [value]
    if isinstance(value, (list, tuple)):
        return [int(v) for v in value]
    v = str(value).strip().lower()
    if v == 'all':
        ids = [int(i) for i, _ in list_gpus(exe)]
        return ids or None
    return [int(x) for x in v.replace(' ', '').split(',') if x != '']


def _probe(exe=None):
    import tempfile, subprocess
    exe = exe or find_gpu_exe()
    if not exe:
        return [], False, 'GPU engine not installed (use the "Install GPU engine" button)'
    d = tempfile.mkdtemp()
    src, dst = os.path.join(d, 'in.png'), os.path.join(d, 'out.png')
    Image.new('RGB', (16, 16), (128, 96, 64)).save(src)
    try:
        r = subprocess.run([exe, '-i', src, '-o', dst, '-s', '4', '-n', 'realesrgan-x4plus'], capture_output=True, text=True, timeout=180,
                           cwd=os.path.dirname(exe))
        log = (r.stdout or '') + (r.stderr or '')
    except Exception as e:
        log = str(e)
    names = []
    for l in log.splitlines():
        l = l.strip()
        if l.startswith('[') and ']' in l:
            m = l[1:l.index(']')].split(' ', 1)
            if len(m) == 2 and m[0].isdigit() and (m[0], m[1]) not in names:
                names.append((m[0], m[1]))
    ok = os.path.exists(dst)
    import shutil as _sh; _sh.rmtree(d, ignore_errors=True)
    return names, ok, log


def gpu_check(exe=None):
    """Run the engine once on a tiny picture and show which GPUs it found (NVIDIA, AMD Radeon, Intel Arc
    and built-in graphics all work through Vulkan). Use --gpu-id with a number to pick one, several
    numbers (0,1) or "all" to share the work between GPUs."""
    if not (exe or find_gpu_exe()):
        print('GPU engine not installed (use the "Install GPU engine" button)'); return False
    names, ok, log = _probe(exe)
    if names:
        print('GPUs the engine can use (Vulkan):')
        for i, n in names:
            print('  --gpu-id %s   %s' % (i, n))
        if len(names) > 1:
            print('Several GPUs: --gpu-id %s (or --gpu-id all) shares the work between them.' % ','.join(i for i, _ in names))
    print('Test upscale: %s' % ('OK' if ok else 'FAILED - update your graphics driver (NVIDIA / AMD Radeon / Intel Arc), then try again'))
    if not ok and log.strip():
        print(log.strip()[-800:])
    return ok


def setup_gpu():
    import urllib.request
    url = GPU_ZIP.get(platform.system())
    if not url:
        sys.exit('No prebuilt engine for %s' % platform.system())
    dest = os.path.join(HERE, 'realesrgan')
    os.makedirs(dest, exist_ok=True)
    zpath = os.path.join(dest, 'engine.zip')
    print('Downloading %s ...' % url)
    urllib.request.urlretrieve(url, zpath)
    with zipfile.ZipFile(zpath) as z:
        for m in z.namelist():
            name = m.split('/')[-1] if '/' in m and not m.split('/')[-2] == 'models' else m
            if m.endswith('/'):
                continue
            parts = m.split('/')
            if 'models' in parts:
                tgt = os.path.join(dest, 'models', parts[-1])
            elif parts[-1].startswith('realesrgan-ncnn-vulkan') or parts[-1].lower().endswith(('.dll', '.dylib', '.so')):
                tgt = os.path.join(dest, parts[-1])
            else:
                continue
            os.makedirs(os.path.dirname(tgt), exist_ok=True)
            with z.open(m) as src, open(tgt, 'wb') as out:
                out.write(src.read())
    os.remove(zpath)
    exe = find_gpu_exe()
    if exe and not exe.endswith('.exe'):
        os.chmod(exe, 0o755)
    print('Installed: %s' % exe)
    gpu_check(exe)
    print('Models: %s' % ', '.join(sorted({os.path.splitext(f)[0] for f in os.listdir(os.path.join(dest, "models"))})))


# ------------------------------------------------------------------ one texture
def is_normal_map(path):
    n = os.path.basename(path).lower()
    return any(h in n for h in NORMAL_HINTS)


def ai_resize(engine, rgb, s, size=None, keep_color=True, strength=1.0):
    """AI upscale by s, optionally to an exact size; keep_color = AI on brightness only (no colour fringes);
    strength < 1 blends back towards a plain Lanczos resize (keeps fine fabric/noise detail)."""
    up = engine.run(rgb, s)
    size = size or up.size
    if up.size != size:
        up = up.resize(size, Image.LANCZOS)
    if isinstance(engine, LanczosEngine) or (not keep_color and strength >= 1):
        return up
    lz = rgb.resize(size, Image.LANCZOS)
    if keep_color:
        y = up.convert('YCbCr').getchannel(0)
        _, cb, cr = lz.convert('YCbCr').split()
        up = Image.merge('YCbCr', (y, cb, cr)).convert('RGB')
    if strength < 1:
        up = Image.blend(lz, up, max(0.0, strength))
    return up


def part_name(dst):
    """the file a texture is written to first (x.part.dds); renamed to dst only once it is complete,
    so a run that is cut off never leaves a half-written texture under its real name"""
    base, ext = os.path.splitext(dst)
    return base + '.part' + ext


def save_like(img, dst, src_info, alpha_used):
    ext = os.path.splitext(dst)[1].lower()
    tmp = part_name(dst)
    if ext == '.dds':
        fourcc, mips = src_info if src_info else ('DXT5' if alpha_used else 'DXT1', True)
        save_dds(img, tmp, fourcc, mips)
    elif ext in ('.jpg', '.jpeg'):
        img.convert('RGB').save(tmp, quality=95)
    else:
        img.save(tmp, format=Image.registered_extensions().get(ext, 'PNG'))
    os.replace(tmp, dst)


def copy_atomic(src, dst):
    tmp = part_name(dst)
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def upscale_file(src, dst, engine, scale=2, max_size=4096, ai_normals=False, ai_alpha=False,
                 keep_color=True, strength=1.0):
    info = dds_info(src)
    img = Image.open(src)
    img.load()
    w, h = img.size
    s = scale
    while s > 1 and max(w, h) * s > max_size:
        s //= 2
    if s <= 1:
        copy_atomic(src, dst) if os.path.abspath(src) != os.path.abspath(dst) else None
        return 'skipped (already %dx%d, max %d)' % (w, h, max_size)
    has_alpha = img.mode in ('RGBA', 'LA', 'P') and 'A' in img.convert('RGBA').getbands()
    rgba = img.convert('RGBA')
    alpha = rgba.getchannel('A')
    alpha_used = has_alpha and alpha.getextrema()[0] < 255
    rgb = rgba.convert('RGB')
    eng = engine if (ai_normals or not is_normal_map(src)) else LanczosEngine()
    up = ai_resize(eng, rgb, s, None, keep_color and eng is engine, strength)
    eng_name = getattr(eng, 'name', '?')
    if alpha_used:
        a = (engine.run(Image.merge('RGB', (alpha, alpha, alpha)), s).getchannel('R').resize(up.size, Image.LANCZOS)
             if ai_alpha else alpha.resize(up.size, Image.LANCZOS))
        up = up.convert('RGBA'); up.putalpha(a)
    save_like(up, dst, info, alpha_used)
    return '%dx%d -> %dx%d (%s)%s' % (w, h, up.size[0], up.size[1], eng_name,
                                     ' +alpha' if alpha_used else '')


TIERS = ('256', '512', '1024', '2048', '4096')


def tier_key(rel):
    parts = rel.replace('\\', '/').split('/')
    for i, p in enumerate(parts):
        if p in TIERS:
            return '/'.join(parts[:i] + ['*'] + parts[i + 1:]).lower(), int(p)
    return None, None


def tier_shift_file(src_self, src_higher, dst):
    """Give a lower tier the real art of the tier above, resized to 2x its own size, in its own format."""
    info = dds_info(src_self)
    me = Image.open(src_self); me.load()
    hi = Image.open(src_higher).convert('RGBA'); hi.load()
    size = (me.size[0] * 2, me.size[1] * 2)
    img = hi if hi.size == size else hi.resize(size, Image.LANCZOS)
    alpha_used = img.getchannel('A').getextrema()[0] < 255
    save_like(img if alpha_used else img.convert('RGB'), dst, info, alpha_used)
    return '%dx%d -> %dx%d (real art from the %s folder)' % (me.size[0], me.size[1], size[0], size[1],
                                                  (tier_key(src_higher.replace(os.sep, '/'))[1] or '?'))


def tier_pairs(files, root):
    """{file: same texture in the next higher resolution folder} for files under 256/512/1024/2048 folders"""
    groups, higher = {}, {}
    for s in files:
        k, r = tier_key(os.path.relpath(s, root))
        if k:
            groups.setdefault(k, []).append((r, s))
    for lst in groups.values():
        lst.sort()
        for (r, s), (r2, s2) in zip(lst, lst[1:]):
            higher[s] = s2
    return higher


def upscale_path(path, out=None, engine=None, scale=2, max_size=4096, ai_normals=False, ai_alpha=False, to_png=False,
                 keep_color=True, strength=1.0, tiers=True, cpu_jobs=None, gpu_jobs=None, tile=None, redo=False, repair=False,
                 cpu_cores='all'):
    import womfast
    path = os.path.abspath(path)
    jobs = []
    if os.path.isdir(path):
        out = os.path.abspath(out or path.rstrip('/\\') + '_upscaled')
        files = []
        for dp, dns, fs in os.walk(path):
            dns.sort()
            if os.path.abspath(dp).startswith(out):
                continue
            files += [os.path.join(dp, f) for f in sorted(fs) if f.lower().endswith(TEX_EXT)]
        higher = tier_pairs(files, path) if (tiers and scale == 2) else {}
        if higher:
            print('Resolution folders found (256/512/1024/2048): lower tiers get the real art of the tier above; '
                  'only the top tier is AI-upscaled. (--no-tiers to AI-upscale every file)')
        for s in files:
            d = os.path.join(out, os.path.relpath(s, path))
            d = os.path.splitext(d)[0] + '.png' if to_png else d
            j = {'src': s, 'dst': d, 'name': os.path.relpath(s, path)}
            if s in higher:
                j.update(kind='shift', higher=higher[s])
            else:
                j['kind'] = 'ai'
            jobs.append(j)
    else:
        d = out or os.path.splitext(path)[0] + '_x%d%s' % (scale, '.png' if to_png else os.path.splitext(path)[1])
        jobs.append({'src': path, 'dst': d, 'kind': 'ai', 'name': os.path.basename(path)})
    opts = dict(scale=scale, max_size=max_size, ai_normals=ai_normals, ai_alpha=ai_alpha, keep_color=keep_color,
                strength=strength, cpu_jobs=cpu_jobs, gpu_jobs=gpu_jobs, tile=tile, redo=redo, repair=repair, png=to_png,
                cpu_cores=cpu_cores)
    womfast.upscale_many(jobs, engine, opts)
    return out
