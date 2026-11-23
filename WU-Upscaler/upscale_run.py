"""WU Upscaler worker: upscales the textures of Wurm Unlimited's graphics.jar 2x and packs them into
small .jar packs (one per mappings.txt section and top folder) that can be copied into WurmLauncher\\userpacks.

Started by the web page (wu_upscaler.py); can also be run by hand:
    python upscale_run.py --jar "<...>\\WurmLauncher\\packs\\graphics.jar" --staging "D:\\WU staging" [--plan-only]

Staging folder:
    jars\\*.jar               finished packs, each with its own mappings.txt; copy the ones you want to userpacks
    graphics\\ , pmk\\       one folder per source jar:
        plan.json          what goes in which pack (made from that jar's mappings.txt)
        source\\...         original files taken out of the jar (same folder structure as in the jar)
        work\\...           upscaled textures (same folder structure)
        mappings\\*.txt     the mappings.txt of each pack, to read without opening the jar
        state\\*.done       a pack is finished (and matches the plan)
    progress.json            where the run is, for the web page
    logs\\                    a log of every run

Stopping at any moment is safe: textures are written as name.part.dds and only renamed when complete,
packs are written as name.jar.part, and a new run checks what is already finished and carries on.
"""
import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

VERSION = '1.1'   # plan format version (a new version makes a new plan)
TEX_EXT = ('.dds', '.png', '.jpg', '.jpeg', '.tga', '.bmp')     # upscaled
TIERS = ('256', '512', '1024', '2048', '4096')
MAX_SIZE = 4096
SCALE = 2


def now():
    return time.strftime('%H:%M:%S')


def say(msg):
    print(msg, flush=True)


def fmt_time(sec):
    sec = int(max(0, sec)); h, r = divmod(sec, 3600); m, s = divmod(r, 60)
    return '%d:%02d:%02d' % (h, m, s)


def write_json(path, obj, must=True):
    """write a .json via a .part file. On Windows the rename fails while another program has the file
    open for a moment (the web page reading progress.json, a virus scanner): try again for a few seconds.
    must=False: give up quietly (progress.json is only for the page)."""
    tmp = path + '.part'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1)
    for i in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.25)
    if must:
        os.replace(tmp, path)


# ================================================================ mappings.txt
HEAD_RE = re.compile(r'^\s*(#|//)')


def heading_name(line):
    """'# Horses -----------' -> 'Horses';  '////////2048///////' -> '2048'; other comments -> None.
    A comment counts as a heading when it has a run of 3+ dashes (or slashes) and a name."""
    s = line.strip()
    if not HEAD_RE.match(s) or '=' in s:
        return None
    body = s.lstrip('#/ ').rstrip()
    if not (re.search(r'-{3,}|/{3,}', s) or re.match(r'^-{2,}\s*\S', body)):
        return None
    name = re.sub(r'\s+', ' ', re.sub(r'[-#/=*]+', ' ', body)).strip()
    return name or None


def parse_mappings(text):
    """-> [(line_no, raw_line, key, value_path, query, section)]"""
    out, section, history = [], 'General', ['General']
    for n, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s:
            continue
        if HEAD_RE.match(s):
            h = heading_name(s)
            if h and re.match(r'^end\b', h, re.I):          # '#---- END Winter Terrain Textures ----': back to what came before
                what = h[3:].strip().lower()
                k = max((i for i, x in enumerate(history) if x.lower() == what), default=None)
                section = history[k - 1] if k else section
                history.append(section)
            elif h:
                section = h
                history.append(h)
            continue
        if '=' not in s:
            continue
        key, val = s.split('=', 1)
        val = val.strip()
        path, _, query = val.partition('?')
        out.append((n, raw.rstrip(), key.strip(), path.strip().replace('\\', '/'), query.strip(), section))
    return out


def safe_name(s):
    s = re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_')
    return s[:60] or 'misc'


# ================================================================ graphics.jar index
class Jar:
    def __init__(self, path):
        self.path = path
        self.z = zipfile.ZipFile(path)
        self.info = {}
        for i in self.z.infolist():
            if not i.is_dir():
                self.info[i.filename] = i
        self.lower = {n.lower(): n for n in self.info}
        # tier groups: 'player/textures/*/base/x.dds' -> {2048: real name, ...}
        self.tiers = {}
        for n in self.info:
            k, t = tier_key(n)
            if k:
                self.tiers.setdefault(k, {})[t] = n

    def find(self, rel):
        """case-insensitive lookup of a path inside the jar -> real entry name or None"""
        rel = posixpath.normpath(rel.replace('\\', '/')).lstrip('/')
        if rel.startswith('../'):
            return None
        return self.lower.get(rel.lower())

    def read(self, name):
        return self.z.read(self.info[name])

    def extract(self, name, dst):
        """copy one entry to dst (skipped when it is already there, whole)"""
        i = self.info[name]
        try:
            if os.path.getsize(dst) == i.file_size:
                return False
        except OSError:
            pass
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + '.part'
        with self.z.open(i) as src, open(tmp, 'wb') as out:
            shutil.copyfileobj(src, out, 1 << 20)
        os.replace(tmp, dst)
        return True


def tier_key(name):
    parts = name.split('/')
    for i, p in enumerate(parts[:-1]):
        if p in TIERS:
            return '/'.join(parts[:i] + ['*'] + parts[i + 1:]).lower(), int(p)
    return None, None


def is_tex(name):
    return name.lower().endswith(TEX_EXT)


# ================================================================ what each mapping line needs
def wom_textures(data):
    """texture names of a .wom's materials (skips over the vertex data instead of reading it)"""
    import struct
    p = [0]

    def i32():
        v = struct.unpack_from('<i', data, p[0])[0]; p[0] += 4; return v

    def u8():
        v = data[p[0]]; p[0] += 1; return v

    def st():
        n = i32()
        if n < 0 or n > 4096:
            raise ValueError('bad string')
        v = data[p[0]:p[0] + n].decode('latin-1'); p[0] += n; return v
    out = set()
    try:
        nm = i32()
        if nm < 0 or nm > 10000:
            return []
        for _ in range(nm):
            tan, bi, col = u8(), u8(), u8()
            st()
            nv = i32()
            p[0] += nv * 4 * (8 + (3 if col else 0) + (3 if tan else 0) + (3 if bi else 0))
            ni = i32()
            p[0] += 2 * ni
            for _ in range(i32()):
                t = st(); st(); u8()
                for n in (4, 1, 4, 4):          # emissive, shininess, specular, transparency
                    if u8():
                        p[0] += 4 * n
                if t:
                    out.add(t)
    except (struct.error, ValueError, IndexError):
        return sorted(out)
    return sorted(out)


FILE_EXT = TEX_EXT + ('.wom', '.gif', '.xml')


def properties_files(jar, xml_name, model_file, masks):
    """properties.xml next to a model: every file it names for that model - animations (<file>),
    dye masks (<mask>, e.g. u_cm.dds) and anything else. The game looks for them next to the model
    first and then from the root of the pack, so both are tried. Masks are added to `masks`."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(jar.read(xml_name))
    except Exception:
        return []
    d = posixpath.dirname(xml_name)
    out = []
    for model in root:
        if model.tag.lower() != model_file.lower():
            continue
        for el in model.iter():
            t = (el.text or '').strip()
            if not t or not t.lower().endswith(FILE_EXT):
                continue
            hit = jar.find(posixpath.join(d, t)) or jar.find(t)
            if hit:
                out.append(hit)
                if 'mask' in el.tag.lower():
                    masks.add(hit)
    return out


def bundle_for(jar, path, query, cache, notes, masks):
    """every file one mapping line needs inside the pack (real jar entry names)"""
    hit = jar.find(path)
    if not hit:
        notes.append('missing: ' + path)
        return []
    files = [hit]
    d = posixpath.dirname(hit)
    low = hit.lower()
    if low.endswith('.wom'):
        if hit not in cache:
            texs = []
            for t in wom_textures(jar.read(hit)):
                f = jar.find(posixpath.join(d, t)) or jar.find(t)
                if f:
                    texs.append(f)
                else:
                    notes.append('%s: texture %s not found' % (hit, t))
            props = jar.find(posixpath.join(d, 'properties.xml'))
            if props:
                texs.append(props)
                texs += properties_files(jar, props, posixpath.basename(hit), masks)
            cache[hit] = texs
        files += cache[hit]
        for part in query.split('&'):     # horseMat.texture=Horse_Black_512.dds
            if '=' in part:
                k, v = part.split('=', 1)
                if k.strip().lower().endswith('.texture') and v.strip():
                    f = jar.find(posixpath.join(d, v.strip())) or jar.find(v.strip())
                    if f:
                        files.append(f)
                    else:
                        notes.append('%s: texture %s not found' % (hit, v.strip()))
    elif low.endswith('.xml') and not low.startswith('xmls/'):
        try:
            txt = jar.read(hit).decode('utf-8', 'replace')
            for m in re.finditer(r'[\w./\\-]+\.(?:dds|png|jpg|jpeg|tga)\b', txt, re.I):
                f = jar.find(posixpath.join(d, m.group(0))) or jar.find(m.group(0))
                if f:
                    files.append(f)
        except Exception:
            pass
    return list(dict.fromkeys(files))


# ================================================================ plan
# folders whose pictures are icon/sprite sheets cut by pixel position or shown at their pixel size:
# upscaling them makes the icons too large or cropped, so they get no pack at all
SKIP_TOPS = ('gui', 'tutorialimages')


def is_face_part(t):
    """player face parts (eyes, nose, eyebrows, chin...): the game paints them at fixed spots on the
    face, sized by the folder they are in (256/512/1024/2048) - they must keep their size"""
    return '/face/' in t.lower()


def make_plan(jar_path, staging, prefix='', log=say):
    t0 = time.time()
    log('[%s] Reading %s ...' % (now(), jar_path))
    jar = Jar(jar_path)
    mp = jar.find('mappings.txt')
    if not mp:
        raise SystemExit('No mappings.txt in %s' % jar_path)
    entries = parse_mappings(jar.read(mp).decode('utf-8', 'replace'))
    log('[%s] %d files in %s, %d mapping lines' % (now(), len(jar.info), os.path.basename(jar_path), len(entries)))
    cache, notes, packs, order, masks = {}, [], {}, [], set()
    skipped = set()
    for k, (n, raw, key, path, query, section) in enumerate(entries):
        if k % 500 == 0:
            log('[%s]   reading models and textures: line %d/%d' % (now(), k, len(entries)))
        files = bundle_for(jar, path, query, cache, notes, masks)
        if not any(is_tex(f) for f in files):
            continue                                   # sounds, xml, text: nothing to upscale
        top = files[0].split('/')[0] if '/' in files[0] else '(root)'
        if top.lower() in SKIP_TOPS:
            skipped.add(top)
            continue
        pid = (top.lower(), section)
        if pid not in packs:
            packs[pid] = {'top': top, 'section': section, 'lines': [], 'files': []}
            order.append(pid)
        p = packs[pid]
        p['lines'].append(raw)
        p['files'] += files
    if skipped:
        log('[%s] Not upscaled (icons and screen pictures that must keep their size): %s' % (now(), ', '.join(sorted(skipped))))
    names, out = {}, []
    for pid in order:
        p = packs[pid]
        base = 'UP_' + prefix + (safe_name(p['top']) if p['section'] == 'General' else '%s_%s' % (safe_name(p['top']), safe_name(p['section'])))
        names[base] = names.get(base, 0) + 1
        name = base if names[base] == 1 else '%s_%d' % (base, names[base])
        files = list(dict.fromkeys(p['files']))
        tex = [f for f in files if is_tex(f)]
        sig = hashlib.sha1(('\n'.join(p['lines']) + '\n' + '\n'.join(files) + VERSION
                            + ('|faces-as-is' if any(is_face_part(t) for t in tex) else '')).encode('utf-8')).hexdigest()
        out.append({'name': name, 'top': p['top'], 'section': p['section'], 'lines': p['lines'], 'files': files,
                    'textures': tex, 'sig': sig})
    # how each texture is made: AI 2x, or the real art of the next resolution folder up
    tex_plan = {}
    for p in out:
        for t in p['textures']:
            if t in tex_plan:
                continue
            k, tier = tier_key(t)
            higher = None
            if k:
                ups = sorted(r for r in jar.tiers.get(k, {}) if r > tier)
                if ups:
                    higher = jar.tiers[k][ups[0]]
            if is_face_part(t):
                tex_plan[t] = {'kind': 'copy', 'why': 'face part'}     # the face builder places them by pixel
            elif t in masks:
                tex_plan[t] = {'kind': 'copy', 'why': 'dye mask'}      # masks keep their size: the game reads them as they are
            else:
                tex_plan[t] = {'kind': 'shift', 'higher': higher} if higher else {'kind': 'ai'}
    st = os.stat(jar_path)
    plan = {'version': VERSION, 'graphics_jar': jar_path, 'jar_size': st.st_size, 'jar_mtime': int(st.st_mtime),
            'made': time.strftime('%Y-%m-%d %H:%M:%S'), 'packs': out, 'textures': tex_plan,
            'notes': notes[:2000], 'note_count': len(notes)}
    write_json(os.path.join(staging, 'plan.json'), plan)
    n_tex = len(tex_plan)
    log('[%s] Plan: %d packs, %d textures (%d AI-upscaled, %d from the next resolution folder up, %d kept as they are: dye masks, face parts), %s' % (
        now(), len(out), n_tex, sum(1 for v in tex_plan.values() if v['kind'] == 'ai'),
        sum(1 for v in tex_plan.values() if v['kind'] == 'shift'), sum(1 for v in tex_plan.values() if v['kind'] == 'copy'),
        fmt_time(time.time() - t0)))
    if notes:
        log('[%s] %d mapping/texture references could not be found in %s (listed in plan.json; the game has the same gaps)' % (now(), len(notes), os.path.basename(jar_path)))
    return plan, jar


def load_plan(jar_path, staging):
    p = os.path.join(staging, 'plan.json')
    try:
        plan = json.load(open(p, encoding='utf-8'))
        st = os.stat(jar_path)
        if plan.get('version') == VERSION and plan.get('jar_size') == st.st_size and plan.get('jar_mtime') == int(st.st_mtime) \
                and os.path.normcase(plan.get('graphics_jar', '')) == os.path.normcase(jar_path):
            faces_ok = all(v.get('kind') == 'copy' for t, v in plan['textures'].items() if is_face_part(t))
            if faces_ok and not any(p['top'].lower() in SKIP_TOPS for p in plan['packs']):
                return plan
            if not faces_ok:
                say('[%s] The plan still upscales the player face parts: making a new plan that keeps them as they are.' % now())
                return None
            say('[%s] The plan still has the gui/TutorialImages packs: making a new plan without them.' % now())
            return None
        say('[%s] graphics.jar (or the tool) changed since the last plan: making a new one.' % now())
    except (OSError, ValueError):
        pass
    return None


# ================================================================ special textures
LOOKUP_NAMES = ('suncolor', 'skycolor', 'ambientcolor', 'gradient')


def _size(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def is_lookup(name, path):
    """colour lookup tables the game reads by position (sky / sun / ambient colour through the day)"""
    base = posixpath.basename(name).lower()
    if '/' not in name and base.startswith(LOOKUP_NAMES):
        return True
    w, h = _size(path)
    return min(w, h) <= 4 and max(w, h) >= 32          # a 1-4 pixel wide strip is a colour ramp, not a picture


KEEP_BELOW = 64          # pictures smaller than this (width and height) are kept as they are (icons)


def small(path):
    w, h = _size(path)
    return 0 < w < KEEP_BELOW and 0 < h < KEEP_BELOW


# ================================================================ checking finished files
def dds_ok(path):
    """a .dds is whole when the file is at least as long as its header says"""
    import struct
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            h = f.read(148)
        if h[:4] != b'DDS ':
            return False
        hh, ww = struct.unpack_from('<II', h, 12)
        mips = max(1, struct.unpack_from('<I', h, 28)[0])
        pf_flags = struct.unpack_from('<I', h, 80)[0]
        fourcc = h[84:88]
        head = 148 if fourcc == b'DX10' else 128
        need = 0
        w, hgt = ww, hh
        for _ in range(mips):
            if pf_flags & 0x4 and fourcc in (b'DXT1', b'DXT3', b'DXT5'):
                need += max(1, (w + 3) // 4) * max(1, (hgt + 3) // 4) * (8 if fourcc == b'DXT1' else 16)
            elif pf_flags & 0x4:
                return size > head
            else:
                bpp = struct.unpack_from('<I', h, 88)[0] or 32
                need += w * hgt * bpp // 8
            w, hgt = max(1, w // 2), max(1, hgt // 2)
        return size >= head + need
    except (OSError, struct.error):
        return False


def output_ok(path):
    if not os.path.exists(path):
        return False
    if path.lower().endswith('.dds'):
        return dds_ok(path)
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        return False


def clean_parts(folder):
    """remove half-written files left by a run that was cut off"""
    n = 0
    for dp, _, fs in os.walk(folder):
        for f in fs:
            if '.part' in f:
                try:
                    os.remove(os.path.join(dp, f)); n += 1
                except OSError:
                    pass
    return n


# ================================================================ packs
def pack_done(staging, jdir, p):
    try:
        d = json.load(open(os.path.join(staging, 'state', p['name'] + '.done'), encoding='utf-8'))
        jp = os.path.join(jdir, p['name'] + '.jar')
        if d.get('sig') != p['sig'] or os.path.getsize(jp) != d.get('size'):
            return False
        return True
    except (OSError, ValueError):
        return False


def build_pack(jar, staging, jdir, p):
    os.makedirs(jdir, exist_ok=True)
    mdir = os.path.join(staging, 'mappings'); os.makedirs(mdir, exist_ok=True)
    sdir = os.path.join(staging, 'state'); os.makedirs(sdir, exist_ok=True)
    mtext = ('# WU Upscaler %s: %s / %s - textures upscaled 2x (max %d), from %s\n' % (
        VERSION, p['top'], p['section'], MAX_SIZE, os.path.basename(jar.path))) + '\n'.join(p['lines']) + '\n'
    mpath = os.path.join(mdir, p['name'] + '.txt')
    with open(mpath + '.part', 'w', encoding='utf-8', newline='\n') as f:
        f.write(mtext)
    os.replace(mpath + '.part', mpath)
    jp = os.path.join(jdir, p['name'] + '.jar')
    with zipfile.ZipFile(jp + '.part', 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr('mappings.txt', mtext)
        for f in p['files']:
            if is_tex(f):
                src = os.path.join(staging, 'work', *f.split('/'))
                if not output_ok(src):
                    raise RuntimeError('upscaled texture missing: ' + f)
                z.write(src, f, compress_type=zipfile.ZIP_STORED if f.lower().endswith(('.png', '.jpg', '.jpeg')) else zipfile.ZIP_DEFLATED)
            else:
                z.writestr(f, jar.read(f))
    os.replace(jp + '.part', jp)
    write_json(os.path.join(sdir, p['name'] + '.done'), {'sig': p['sig'], 'size': os.path.getsize(jp),
                                                          'made': time.strftime('%Y-%m-%d %H:%M:%S')})
    return os.path.getsize(jp)


def remove_old_packs(staging, jdir, plan):
    """packs this tool made before that are no longer in the plan (renamed, e.g. to UP_...): removed"""
    names = {p['name'] for p in plan['packs']}
    sdir = os.path.join(staging, 'state')
    n = 0
    for f in (os.listdir(sdir) if os.path.isdir(sdir) else []):
        if not f.endswith('.done') or f[:-5] in names:
            continue
        old = f[:-5]
        for x in (os.path.join(jdir, old + '.jar'), os.path.join(staging, 'mappings', old + '.txt'), os.path.join(sdir, f)):
            try:
                os.remove(x)
            except OSError:
                pass
        n += 1
    if n:
        say('[%s] Removed %d old pack(s) from %s that are no longer made (they are made again under their new name)' % (now(), n, jdir))


# ================================================================ run
def jar_stem(path):
    return safe_name(os.path.splitext(os.path.basename(path))[0]).lower()


def run(args):
    top = os.path.abspath(args.staging)
    jars = [os.path.abspath(j) for j in args.jar]
    for k, jp in enumerate(jars):
        if len(jars) > 1:
            say('[%s] ======== %s (%d of %d source jars) ========' % (now(), os.path.basename(jp), k + 1, len(jars)))
        run_one(args, jp, os.path.join(top, jar_stem(jp)), os.path.join(top, 'jars'),
                '' if jar_stem(jp) == 'graphics' else jar_stem(jp) + '_', os.path.join(top, 'progress.json'), (k + 1, len(jars)))


def run_one(args, jar_path, staging, jdir, prefix, ppath, which):
    os.makedirs(staging, exist_ok=True)
    plan = None if args.replan else load_plan(jar_path, staging)
    jar = None
    if plan is None:
        plan, jar = make_plan(jar_path, staging, prefix)
    else:
        say('[%s] Using the plan from %s (%d packs, %d textures)' % (now(), plan['made'], len(plan['packs']), len(plan['textures'])))
    remove_old_packs(staging, jdir, plan)
    if args.plan_only:
        return
    jar = jar or Jar(jar_path)
    # --folders: "creatures,trees" (any source jar) or "graphics:creatures,pmk:models" (one source jar)
    wanted = [f.strip().lower() for f in (args.folders or '').split(',') if f.strip()]
    stem = jar_stem(jar_path)
    folders = {f.split(':', 1)[1] if ':' in f else f for f in wanted if ':' not in f or f.split(':', 1)[0] == stem}
    if wanted and not folders:
        say('[%s] No folders of %s are selected: skipped.' % (now(), os.path.basename(jar_path)))
        return
    packs = [p for p in plan['packs'] if not folders or p['top'].lower() in folders]
    if folders:
        say('[%s] Only these folders: %s (%d packs)' % (now(), ', '.join(sorted(folders)), len(packs)))

    work = os.path.join(staging, 'work'); src_root = os.path.join(staging, 'source')
    n = clean_parts(work) + clean_parts(src_root) + clean_parts(jdir)
    if n:
        say('[%s] Removed %d half-written file(s) from the last run' % (now(), n))

    todo = [p for p in packs if args.redo or not pack_done(staging, jdir, p)]
    say('[%s] %d of %d packs already finished; %d to do' % (now(), len(packs) - len(todo), len(packs), len(todo)))
    all_tex = list(dict.fromkeys(t for p in packs for t in p['textures']))
    progress = {'source': os.path.basename(jar_path), 'source_n': which[0], 'source_total': which[1],
                'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'packs_total': len(packs), 'packs_done': len(packs) - len(todo),
                'tex_total': len(all_tex), 'tex_done': 0, 'phase': 'checking', 'current': '', 'eta': None}

    def outp(t):
        return os.path.join(work, *t.split('/'))

    def srcp(t):
        return os.path.join(src_root, *t.split('/'))

    # what is already finished (checks that every finished texture is whole)
    def keep_as_is(t):
        tp = plan['textures'].get(t, {})
        if tp.get('kind') == 'copy':
            return True
        jar.extract(t, srcp(t))
        return small(srcp(t)) or is_lookup(t, srcp(t))

    done_tex, kept = set(), 0
    for i, t in enumerate(all_tex):
        if args.redo or not output_ok(outp(t)):
            continue
        if keep_as_is(t) and os.path.getsize(outp(t)) != os.path.getsize(srcp(t)):
            kept += 1                       # was upscaled by an earlier version: put the original back
            continue
        done_tex.add(t)
    if kept:
        say('[%s] %d texture(s) are now kept at their original size (icons under %dx%d, dye masks, face parts): putting the originals back' % (
            now(), kept, KEEP_BELOW, KEEP_BELOW))
    if args.redo:
        say('[%s] Redo: every texture is made again' % now())
    progress['tex_done'] = len(done_tex)
    say('[%s] %d of %d textures already upscaled' % (now(), len(done_tex), len(all_tex)))
    write_json(ppath, progress, must=False)
    if not todo:
        progress['phase'] = 'finished'; write_json(ppath, progress, must=False)
        say('[%s] Everything from %s is finished. The packs are in %s' % (now(), os.path.basename(jar_path), jdir))
        return

    import womtex, womfast
    engine = womtex.make_engine(args.engine, None, args.model, args.gpu_id or None)
    say('[%s] Upscaler: %s' % (now(), engine.name))

    t_start, tex_start = time.time(), len(done_tex)
    redo_left = set(all_tex) if args.redo else set()
    i = 0
    while i < len(todo):
        # one pack at a time: upscale what it still needs, build it, then the next pack
        p = todo[i]; i += 1
        group, need = [p], []
        for t in p['textures']:
            if (t not in done_tex or t in redo_left) and t not in need:
                need.append(t)
        progress.update(phase='upscaling', current=p['name'])
        write_json(ppath, progress, must=False)
        if need:
            say('[%s] Pack %d of %d: %s - %d texture(s) to upscale' % (
                now(), progress['packs_done'] + 1, len(packs), p['name'], len(need)))
            jobs = []
            for t in need:
                tp = plan['textures'].get(t, {'kind': 'ai'})
                jar.extract(t, srcp(t))
                j = {'src': srcp(t), 'dst': outp(t), 'name': t}
                if tp['kind'] == 'shift' and tp.get('higher'):
                    jar.extract(tp['higher'], srcp(tp['higher']))
                    j.update(kind='shift', higher=srcp(tp['higher']))
                elif tp['kind'] == 'copy' or is_lookup(t, srcp(t)) or small(srcp(t)):
                    j['kind'] = 'copy'                 # dye masks, colour tables and icons under 64x64: used as they are
                else:
                    j['kind'] = 'ai'
                if os.path.exists(j['dst']):      # damaged (cut off) or --redo: make it again
                    os.remove(j['dst'])
                jobs.append(j)
            opts = dict(scale=SCALE, max_size=MAX_SIZE, ai_normals=False, ai_alpha=False, keep_color=True, strength=1.0,
                        png=False, debug_dir=os.path.join(os.path.dirname(staging), 'gpu_rejected'), cpu_jobs=args.cpu_jobs or None, gpu_jobs=args.gpu_jobs or None, tile=None,
                        redo=False, repair=False, cpu_cores='all')
            womfast.upscale_many(jobs, engine, opts, 'Upscaling %d texture(s)' % len(jobs))
            for t in need:
                if output_ok(outp(t)):
                    done_tex.add(t); redo_left.discard(t)
                else:
                    say('[%s]   ! %s could not be upscaled; the original is used in its pack' % (now(), t))
                    os.makedirs(os.path.dirname(outp(t)), exist_ok=True)
                    womtex.copy_atomic(srcp(t), outp(t))
                    done_tex.add(t); redo_left.discard(t)
        # build the packs of this group
        progress['phase'] = 'packing'
        for p in group:
            try:
                size = build_pack(jar, staging, jdir, p)
                progress['packs_done'] += 1
                say('[%s] Pack %d/%d ready: %s.jar (%d files, %d textures, %.1f MB)' % (
                    now(), progress['packs_done'], len(packs), p['name'], len(p['files']) + 1, len(p['textures']), size / 1048576))
            except Exception as e:
                say('[%s]   ! pack %s not made: %s' % (now(), p['name'], e))
        progress['tex_done'] = len(done_tex)
        el = time.time() - t_start
        made = progress['tex_done'] - tex_start
        left = len(all_tex) - progress['tex_done']
        progress['eta'] = int(el / made * left) if made > 0 and el > 30 else None
        progress['rate'] = round(made / el * 3600) if el > 0 else None
        write_json(ppath, progress, must=False)
        say('[%s] == Overall: %d/%d packs, %d/%d textures (%d%%), %s elapsed%s' % (
            now(), progress['packs_done'], len(packs), progress['tex_done'], len(all_tex),
            100 * progress['tex_done'] // max(1, len(all_tex)), fmt_time(el),
            (', about %s left' % fmt_time(progress['eta'])) if progress['eta'] is not None else ''))
    progress.update(phase='finished', current='', eta=0)
    write_json(ppath, progress, must=False)
    say('[%s] Finished %s. The packs are in %s - copy the ones you want into WurmLauncher\\userpacks.' % (now(), os.path.basename(jar_path), jdir))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--jar', required=True, action='append', help='graphics.jar (WurmLauncher\\packs\\graphics.jar); give --jar again for pmk.jar etc.')
    ap.add_argument('--staging', required=True, help='folder for the work files and the finished packs')
    ap.add_argument('--folders', help='only these top folders of graphics.jar, e.g. creatures,trees')
    ap.add_argument('--plan-only', action='store_true', help='only read graphics.jar and make plan.json')
    ap.add_argument('--replan', action='store_true', help='make a new plan even if graphics.jar did not change')
    ap.add_argument('--redo', action='store_true', help='upscale and pack everything again')
    ap.add_argument('--keep-below', type=int, default=64, help='keep pictures smaller than this many pixels (both sides) as they are')
    ap.add_argument('--engine', default='auto', choices=['auto', 'gpu', 'cpu', 'lanczos'])
    ap.add_argument('--model', default='realesrgan-x4plus')
    ap.add_argument('--gpu-id', default='')
    ap.add_argument('--gpu-jobs', default='')
    ap.add_argument('--cpu-jobs', type=int, default=0)
    args = ap.parse_args()
    global KEEP_BELOW
    KEEP_BELOW = max(1, args.keep_below)
    run(args)


if __name__ == '__main__':
    main()
