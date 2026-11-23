"""Fast texture upscaling for whole folders.

- The GPU engine (realesrgan-ncnn-vulkan) runs once per batch of images instead of once per image,
  and processes several images on the GPU at the same time (as many as free video memory allows).
- Reading the textures, and finishing them (resizing, colour, alpha, DDS + mipmap compression),
  runs on all CPU cores in parallel while the GPU works on the next batch.
- Textures that are already done (output newer than the source) are skipped, so a stopped run
  carries on where it left off.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, FIRST_COMPLETED, wait

from PIL import Image

import womtex
from womprogress import Progress
import womprogress


# ------------------------------------------------------------------ settings
def cpu_layout():
    """Which logical processors are Performance-cores and which Efficient-cores.
    Returns {'p': [cpu numbers], 'e': [cpu numbers], 'total': n} ('e' is empty on CPUs without E-cores).
    Windows: GetLogicalProcessorInformationEx (EfficiencyClass per core). Linux: /sys/devices/cpu_core
    and cpu_atom (Intel hybrid). Mac: sysctl hw.perflevel0/1 (Apple Silicon)."""
    total = os.cpu_count() or 2
    allc = list(range(total))
    try:
        if sys.platform.startswith('win'):
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL('kernel32', use_last_error=True)
            size = wintypes.DWORD(0)
            k32.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))   # RelationProcessorCore
            buf = ctypes.create_string_buffer(size.value)
            if not k32.GetLogicalProcessorInformationEx(0, buf, ctypes.byref(size)):
                raise OSError('GetLogicalProcessorInformationEx failed')
            raw, off, cores = buf.raw, 0, []
            while off < size.value:
                rel, sz = int.from_bytes(raw[off:off + 4], 'little'), int.from_bytes(raw[off + 4:off + 8], 'little')
                if rel == 0:
                    eff = raw[off + 9]
                    groups = int.from_bytes(raw[off + 30:off + 32], 'little')
                    cpus = []
                    for gi in range(groups):
                        base = off + 32 + gi * 16
                        mask = int.from_bytes(raw[base:base + 8], 'little'); grp = int.from_bytes(raw[base + 8:base + 10], 'little')
                        cpus += [grp * 64 + b for b in range(64) if mask >> b & 1]
                    cores.append((eff, cpus))
                off += sz
            classes = sorted({c[0] for c in cores})
            if len(classes) > 1:
                top = classes[-1]
                return {'p': sorted(c for e, cs in cores if e == top for c in cs),
                        'e': sorted(c for e, cs in cores if e != top for c in cs), 'total': total}
        elif sys.platform.startswith('linux'):
            def rng(path):
                txt = open(path).read().strip(); out = []
                for part in txt.split(','):
                    if '-' in part:
                        a, b = part.split('-'); out += list(range(int(a), int(b) + 1))
                    elif part:
                        out.append(int(part))
                return out
            if os.path.exists('/sys/devices/cpu_core/cpus') and os.path.exists('/sys/devices/cpu_atom/cpus'):
                return {'p': rng('/sys/devices/cpu_core/cpus'), 'e': rng('/sys/devices/cpu_atom/cpus'), 'total': total}
        elif sys.platform == 'darwin':
            def sysctl(name):
                r = subprocess.run(['sysctl', '-n', name], capture_output=True, text=True, timeout=5)
                return int(r.stdout.strip())
            p, e = sysctl('hw.perflevel0.logicalcpu'), sysctl('hw.perflevel1.logicalcpu')
            if e:
                return {'p': list(range(p)), 'e': list(range(p, p + e)), 'total': total}   # macOS can't pin; counts only
    except Exception:
        pass
    return {'p': allc, 'e': [], 'total': total}


def describe_cpu(lay=None):
    lay = lay or cpu_layout()
    if lay['e']:
        return '%d P-core threads + %d E-cores' % (len(lay['p']), len(lay['e']))
    return '%d threads' % lay['total']


def default_cpu_jobs(cores='all'):
    """CPU workers: all threads but one (the GPU feeder and Windows need one), up to 16.
    With cores='p', only the P-core threads (but one)."""
    lay = cpu_layout()
    n = len(lay['p']) if cores == 'p' and lay['e'] else lay['total']
    return max(1, min(n - 1, 16))


def _pin_worker(cpus):
    """runs in each worker: keep it on these logical processors (Windows / Linux)"""
    if not cpus:
        return
    try:
        if hasattr(os, 'sched_setaffinity'):
            os.sched_setaffinity(0, set(cpus))
        elif sys.platform.startswith('win') and max(cpus) < 64:
            import ctypes
            mask = 0
            for c in cpus:
                mask |= 1 << c
            k32 = ctypes.WinDLL('kernel32')
            k32.SetProcessAffinityMask(k32.GetCurrentProcess(), ctypes.c_size_t(mask))
    except Exception:
        pass


def make_pool(n, cores='all'):
    """process pool for the CPU work; cores='p' keeps the workers on the P-cores (CPUs with E-cores)"""
    lay = cpu_layout()
    if cores == 'p' and lay['e']:
        return ProcessPoolExecutor(max_workers=n, initializer=_pin_worker, initargs=(lay['p'],))
    return ProcessPoolExecutor(max_workers=n)


def free_vram_mb(gpu_id=None):
    """(free, total) video memory in MB, or None if unknown.
    NVIDIA: nvidia-smi (real free memory). AMD on Linux: the amdgpu driver's counters. Any card on
    Windows (AMD Radeon, Intel Arc, NVIDIA): the size Windows records for it, minus ~1.5 GB that the
    desktop and other programs usually hold (Windows doesn't say how much is free)."""
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=memory.free,memory.total', '--format=csv,noheader,nounits'],
                           capture_output=True, text=True, timeout=10)
        rows = [l.split(',') for l in r.stdout.strip().splitlines() if l.strip()]
        if rows:
            row = rows[gpu_id if gpu_id is not None and gpu_id < len(rows) else 0]
            return int(float(row[0])), int(float(row[1]))
    except Exception:
        pass
    cards = []   # (total MB, free MB or None, name)
    if sys.platform.startswith('linux'):
        import glob
        for d in sorted(glob.glob('/sys/class/drm/card*/device')):
            try:
                tot = int(open(os.path.join(d, 'mem_info_vram_total')).read()) // (1 << 20)
                used = int(open(os.path.join(d, 'mem_info_vram_used')).read()) // (1 << 20)
                cards.append((tot, tot - used, os.path.basename(os.path.dirname(d))))
            except (OSError, ValueError):
                pass
    elif sys.platform.startswith('win'):
        try:
            import winreg
            base = r'SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
                for i in range(64):
                    try:
                        sub = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(k, sub) as g:
                            size = winreg.QueryValueEx(g, 'HardwareInformation.qwMemorySize')[0]
                            try:
                                name = winreg.QueryValueEx(g, 'DriverDesc')[0]
                            except OSError:
                                name = 'GPU'
                            if isinstance(size, bytes):
                                size = int.from_bytes(size, 'little')
                            if size:
                                cards.append((int(size) // (1 << 20), None, name))
                    except OSError:
                        pass
        except Exception:
            pass
    if not cards:
        return None
    # the biggest card is the one worth using (a built-in Intel/AMD chip has little or shared memory)
    tot, free, _ = max(cards, key=lambda c: c[0])
    return (free if free is not None else max(0, tot - 1500)), tot


def is_integrated(name):
    """a GPU built into the processor (shares memory, power and cooling with the CPU)"""
    import re
    n = name.lower()
    if re.search(r'radeon(\(tm\))?\s+\d{3,4}m\b', n):          # Ryzen laptop graphics: Radeon 680M / 780M / 890M
        return True
    if re.search(r'\barc\b', n):                         # Arc A770 / B580 = card; plain "Arc Graphics" = Core Ultra built-in
        return not re.search(r'\barc\S*\s+[ab]\d{3}', n)
    if re.search(r'\brx\s?\d|radeon pro|geforce|quadro|rtx|gtx|tesla', n):
        return False
    return bool(re.search(r'uhd|iris|hd graphics|intel\(r\) graphics|radeon\(tm\) graphics|radeon graphics|vega \d+ graphics|llvmpipe|swiftshader', n))


def auto_gpu_jobs(gpu_id=None):
    """how many images to put on the GPU at once: ~1.4 GB each, keep ~0.8 GB spare for Windows/games"""
    v = free_vram_mb(gpu_id)
    if not v:
        return 2, 'video memory unknown, using 2'
    free, total = v
    n = max(1, min(6, int((free - 800) / 1400)))
    return n, '%d MB of %d MB video memory free' % (free, total)


def looks_broken(src_img, out_img):
    """True if an upscaled picture is damaged: black or missing areas from a GPU fault, or garbage.
    The result, shrunk back to the original size, is compared with the original. Dark textures are fine:
    the AI deepens near-black a little, so only areas that were clearly lit and came back black count."""
    import numpy as np
    a = np.asarray(src_img.convert('RGB'), dtype=np.int16)
    b = np.asarray(out_img.convert('RGB').resize(src_img.size, Image.BOX), dtype=np.int16)
    diff = np.abs(a - b).mean()
    lost = ((b.max(axis=2) < 6) & (a.max(axis=2) >= 40)).mean()
    dimmed = a.mean() > 20 and b.mean() < a.mean() * 0.4
    if diff > 40 or lost > 0.03 or dimmed:
        return 'difference %.1f, lit area turned black %.1f%%, brightness %.0f -> %.0f' % (diff, lost * 100, a.mean(), b.mean())
    return ''


def _work_check(src, dst):
    """for --repair: is a finished texture OK?"""
    try:
        s = Image.open(src); s.load()
        d = Image.open(dst); d.load()
        return not looks_broken(s, d)
    except Exception:
        return False


def job_weight(j):
    """rough cost of a job, for the time-left estimate: AI work by picture size, copies nearly free"""
    if j['kind'] == 'copy':
        return 0.02
    try:
        if j['src'].lower().endswith('.dds'):
            with open(j['src'], 'rb') as fh:
                hd = fh.read(20)
            h, w = int.from_bytes(hd[12:16], 'little'), int.from_bytes(hd[16:20], 'little')
        else:
            w, h = Image.open(j['src']).size
    except Exception:
        w = h = 512
    px = max(1.0, w * h / (512 * 512))
    return 0.3 * px if j['kind'] == 'shift' else 4.0 * px


def is_done(src, dst):
    try:
        return os.path.getsize(dst) > 0 and os.path.getmtime(dst) >= os.path.getmtime(src)
    except OSError:
        return False


# ------------------------------------------------------------------ worker functions (run in other processes)
def _work_copy(src, dst, png):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if png and not src.lower().endswith('.png') and src.lower().endswith(womtex.TEX_EXT):
        im = Image.open(src); im.load(); im.save(dst)
    else:
        womtex.copy_atomic(src, dst)
    return 'copied'


def _work_shift(src, higher, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    return womtex.tier_shift_file(src, higher, dst)


_CPU_ENGINE = {}


def _work_local(src, dst, kind, opts):
    """whole job in this process: lanczos, CPU AI, or normal maps"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if kind == 'cpu':
        eng = _CPU_ENGINE.get(opts.get('cpu_weights'))
        if eng is None:
            eng = _CPU_ENGINE[opts.get('cpu_weights')] = womtex.CpuEngine(opts.get('cpu_weights'))
    else:
        eng = womtex.LanczosEngine()
    return womtex.upscale_file(src, dst, eng, opts['scale'], opts['max_size'], opts['ai_normals'], opts['ai_alpha'],
                               opts['keep_color'], opts['strength'])


def _work_prepare(src, tmp_png, opts):
    """read a texture and write the RGB picture the GPU engine will upscale; returns the plan for it"""
    img = Image.open(src); img.load()
    w, h = img.size
    s = opts['scale']
    while s > 1 and max(w, h) * s > opts['max_size']:
        s //= 2
    if s <= 1:
        return {'skip': True, 'w': w, 'h': h}
    img.convert('RGBA').convert('RGB').save(tmp_png, compress_level=1)
    return {'skip': False, 'w': w, 'h': h, 's': s}


def _work_finish(src, dst, ai_png, plan, opts):
    """turn the GPU result into the final texture: exact size, colour from the original, alpha, DDS + mipmaps"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    info = womtex.dds_info(src)
    orig = Image.open(src); orig.load()
    rgba = orig.convert('RGBA')
    alpha = rgba.getchannel('A')
    alpha_used = alpha.getextrema()[0] < 255
    rgb = rgba.convert('RGB')
    size = (plan['w'] * plan['s'], plan['h'] * plan['s'])
    up = Image.open(ai_png).convert('RGB'); up.load()
    why = looks_broken(rgb, up)
    if why:
        dbg = opts.get('debug_dir')
        if dbg:          # keep the rejected GPU picture to look at
            try:
                os.makedirs(dbg, exist_ok=True)
                base = os.path.join(dbg, os.path.basename(dst).rsplit('.', 1)[0])
                shutil.copyfile(ai_png, base + '.gpu.png')
                rgb.save(base + '.original.png')
                with open(base + '.txt', 'w') as fh:
                    fh.write('%s\n%s\n' % (src, why))
            except OSError:
                pass
        return 'BROKEN ' + why
    if up.size != size:
        up = up.resize(size, Image.LANCZOS)
    if opts['keep_color'] or opts['strength'] < 1:
        lz = rgb.resize(size, Image.LANCZOS)
        if opts['keep_color']:
            y = up.convert('YCbCr').getchannel(0)
            _, cb, cr = lz.convert('YCbCr').split()
            up = Image.merge('YCbCr', (y, cb, cr)).convert('RGB')
        if opts['strength'] < 1:
            up = Image.blend(lz, up, max(0.0, opts['strength']))
    if alpha_used:
        up = up.convert('RGBA'); up.putalpha(alpha.resize(size, Image.LANCZOS))
    womtex.save_like(up, dst, info, alpha_used)
    try:
        os.remove(ai_png)
    except OSError:
        pass
    return '%dx%d -> %dx%d (GPU %s)%s' % (plan['w'], plan['h'], size[0], size[1], opts['model'], ' +alpha' if alpha_used else '')


# ------------------------------------------------------------------ GPU batch run
def _run_gpu_batch(exe, in_dir, out_dir, model, native, gpu_jobs, gpu_id, tile, on_tick):
    """gpu_jobs: images at once per GPU (list, one number per GPU in gpu_id); gpu_id: None or [numbers].
    With several GPUs the engine shares the pictures between them (-g 0,1 -j load:n0,n1:save)."""
    jobs = gpu_jobs if isinstance(gpu_jobs, (list, tuple)) else [gpu_jobs] * max(1, len(gpu_id or [0]))
    io = 2 * max(1, len(jobs))
    cmd = [exe, '-i', in_dir, '-o', out_dir, '-n', model, '-s', str(native), '-f', 'png',
           '-j', '%d:%s:%d' % (io, ','.join(str(max(1, j)) for j in jobs), io)]
    mdir = os.path.join(os.path.dirname(exe), 'models')
    if os.path.isdir(mdir):
        cmd += ['-m', mdir]
    if gpu_id:
        cmd += ['-g', ','.join(str(g) for g in gpu_id)]
    if tile:
        cmd += ['-t', str(tile)]
    pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    tail = []
    import threading

    def reader():
        for ln in pr.stdout:
            tail.append(ln.strip())
            del tail[:-8]
    t = threading.Thread(target=reader, daemon=True); t.start()
    while pr.poll() is None:
        on_tick()
        time.sleep(0.3)
    t.join(timeout=2)
    on_tick()
    return pr.returncode, ' | '.join(tail)


# ------------------------------------------------------------------ main entry
def upscale_many(jobs, engine, opts, title='Upscaling textures'):
    """jobs: list of dicts {src, dst, kind: 'ai'|'shift'|'copy', higher?}
    engine: the engine object from womtex.make_engine (GPU / CPU / lanczos)
    opts: scale, max_size, ai_normals, ai_alpha, keep_color, strength, cpu_jobs, gpu_jobs, tile, redo, png"""
    cores = opts.get('cpu_cores') or 'all'
    cpu_jobs = opts.get('cpu_jobs') or default_cpu_jobs(cores)
    todo, skipped = [], 0
    if opts.get('repair'):
        # check finished AI textures against their originals; redo only damaged or missing ones
        check = [j for j in jobs if j['kind'] == 'ai' and os.path.exists(j['dst'])]
        cp = Progress(len(check), 'Checking finished textures for damage')
        bad = set()
        with make_pool(cpu_jobs, cores) as pool:
            futs = {pool.submit(_work_check, j['src'], j['dst']): j for j in check}
            for fu in futs:
                j = futs[fu]
                cp.step(j.get('name') or os.path.basename(j['src']))
                if not fu.result():
                    bad.add(id(j)); cp.log('  damaged: %s' % (j.get('name') or j['dst']))
        cp.done('%d damaged' % len(bad))
        for j in jobs:
            if id(j) in bad or not os.path.exists(j['dst']):
                todo.append(j)
            else:
                skipped += 1
    else:
        for j in jobs:
            if not opts.get('redo') and is_done(j['src'], j['dst']):
                skipped += 1
            else:
                todo.append(j)
    gpu = engine.cur if isinstance(engine, womtex.FallbackEngine) else engine
    use_gpu = isinstance(gpu, womtex.GpuEngine)
    kind_local = 'cpu' if isinstance(gpu, womtex.CpuEngine) else 'lanczos'
    local_opts = dict(opts, cpu_weights=getattr(gpu, 'weights', None))
    ai_jobs = [j for j in todo if j['kind'] == 'ai' and use_gpu and not j.get('plain')
               and (opts['ai_normals'] or not womtex.is_normal_map(j['src']))]
    ai_set = set(id(j) for j in ai_jobs)
    other = [j for j in todo if id(j) not in ai_set]

    if skipped:
        print('%d texture(s) already done, skipped' % skipped)
    if use_gpu:
        ids = gpu.gpu_id or [None]
        user = opts.get('gpu_jobs')
        if isinstance(user, str):   # --gpu-jobs 4,1 : one count per GPU in --gpu-id order
            user = [int(x) for x in user.split(',') if x.strip()]
        if not user:
            names = dict((int(i), n) for i, n in womtex.list_gpus(gpu.exe)) if len(ids) > 1 else {}
            nv_order = [i for i in sorted(names) if 'nvidia' in names[i].lower()]
            per = []
            for g in ids:
                name = names.get(g, '')
                if name and is_integrated(name):
                    per.append((1, 'built-in GPU: 1 at a time so it never holds up the run'))
                else:
                    # nvidia-smi lists only NVIDIA cards: use this card's place among them
                    per.append(auto_gpu_jobs(nv_order.index(g) if g in nv_order else g))
            opts['gpu_jobs'] = [n for n, _ in per]
            for g, (n, why) in zip(ids, per):
                label = '' if g is None else ' %d%s' % (g, (' (%s)' % names[g]) if g in names else '')
                print('GPU%s: %d image(s) at a time (%s).' % (label, n, why))
        else:
            if isinstance(user, int):
                user = [user]
            opts['gpu_jobs'] = (user + [user[-1]] * len(ids))[:len(ids)]
            print('GPU%s: %s image(s) at a time.' % ('' if ids == [None] else 's ' + ','.join(map(str, ids)), ','.join(map(str, opts['gpu_jobs']))))
        if len(ids) > 1:
            print('Sharing the work between %d GPUs (%s).' % (len(ids), ','.join(map(str, ids))))
    print('CPU: %d worker(s) for reading/finishing textures (%s%s).' % (
        cpu_jobs, describe_cpu(), ', workers kept on the P-cores' if cores == 'p' and cpu_layout()['e'] else ''))

    weights = {id(j): job_weight(j) for j in todo}
    prog = Progress(len(todo), title, sum(weights.values()))
    done = failed = 0
    results = []
    by_name = {}
    broken = []

    def finished(name, msg):
        nonlocal done
        if msg and msg.startswith('BROKEN'):
            j = by_name.get(name)
            if j is not None:
                broken.append(j)
                prog.log('  black/damaged GPU result for %s (%s); will redo it' % (name, msg[7:]))
            return
        done += 1
        j = by_name.get(name)
        prog.step(name, weights.get(id(j), 1.0) if j is not None else 1.0)
        if msg and not msg.startswith('copied'):
            results.append('  %s  %s' % (name, msg))

    with make_pool(cpu_jobs, cores) as pool:
        running = {}

        def submit(fn, name, *args):
            running[pool.submit(fn, *args)] = name

        for j in todo:
            by_name[j.get('name') or os.path.basename(j['src'])] = j

        def drain(block=False, limit=None):
            nonlocal failed
            while running and (block or limit is not None and len(running) > limit):
                ds, _ = wait(list(running), return_when=FIRST_COMPLETED)
                for f in ds:
                    name = running.pop(f)
                    try:
                        finished(name, f.result())
                    except Exception as e:
                        failed += 1; prog.step(name); prog.log('  FAILED %s: %s' % (name, e))
                if not block:
                    break
            # collect anything already finished
            for f in [f for f in running if f.done()]:
                name = running.pop(f)
                try:
                    finished(name, f.result())
                except Exception as e:
                    failed += 1; prog.step(name); prog.log('  FAILED %s: %s' % (name, e))

        # 1) everything that doesn't need the GPU: copies, tier shifts, normal maps, CPU/lanczos AI
        for j in other:
            name = j.get('name') or os.path.basename(j['src'])
            if j['kind'] == 'copy':
                submit(_work_copy, name, j['src'], j['dst'], opts.get('png'))
            elif j['kind'] == 'shift':
                submit(_work_shift, name, j['src'], j['higher'], j['dst'])
            else:
                kind = 'lanczos' if (j.get('plain') or (not opts['ai_normals'] and womtex.is_normal_map(j['src']))) else kind_local
                submit(_work_local, name, j['src'], j['dst'], kind, local_opts)
            drain(limit=cpu_jobs * 3)

        # 2) GPU work in batches: prepare (CPU) -> GPU -> finish (CPU, overlapping the next GPU batch)
        passes = 0
        gpu_broken = False
        while ai_jobs and passes < 2:
            passes += 1
            tmp = tempfile.mkdtemp(prefix='wom_upscale_')
            batch_size = max(4, sum(opts['gpu_jobs']) * 4)
            native = 2 if womtex.model_is_x2(gpu.model) else 4
            try:
                for bi in range(0, len(ai_jobs), batch_size):
                    chunk = ai_jobs[bi:bi + batch_size]
                    if gpu_broken:
                        for j in chunk:
                            submit(_work_local, j.get('name') or os.path.basename(j['src']), j['src'], j['dst'], 'cpu', local_opts)
                        drain(limit=cpu_jobs * 2)
                        continue
                    in_dir = os.path.join(tmp, 'in%d' % bi); out_dir = os.path.join(tmp, 'out%d' % bi)
                    os.makedirs(in_dir); os.makedirs(out_dir)
                    prep = {}
                    futs = {pool.submit(_work_prepare, j['src'], os.path.join(in_dir, '%05d.png' % k), opts): (k, j)
                            for k, j in enumerate(chunk)}
                    for f in futs:
                        k, j = futs[f]
                        try:
                            prep[k] = f.result()
                        except Exception as e:
                            failed += 1; prog.step(os.path.basename(j['src'])); prog.log('  FAILED %s: %s' % (j['src'], e))
                    for k, plan in list(prep.items()):
                        if plan['skip']:
                            j = chunk[k]
                            submit(_work_copy, os.path.basename(j['src']), j['src'], j['dst'], False)
                            del prep[k]
                    if not prep:
                        continue
                    n_in = len(prep)
                    label = 'GPU batch %d/%d (%d images, %d at a time%s)' % (bi // batch_size + 1,
                                                                           (len(ai_jobs) + batch_size - 1) // batch_size,
                                                                           n_in, sum(opts['gpu_jobs']),
                                                                           ' on %d GPUs' % len(opts['gpu_jobs']) if len(opts['gpu_jobs']) > 1 else '')
                    womprogress.label(label)

                    def tick():
                        try:
                            n_out = len(os.listdir(out_dir))
                        except OSError:
                            n_out = 0
                        prog.sub_progress(min(1.0, n_out / n_in), '%d/%d upscaled' % (n_out, n_in))
                        drain(limit=None)
                    code, tail = _run_gpu_batch(gpu.exe, in_dir, out_dir, gpu.model, native, opts['gpu_jobs'],
                                                gpu.gpu_id, opts.get('tile'), tick)
                    missing = [k for k in prep if not os.path.exists(os.path.join(out_dir, '%05d.png' % k))]
                    if missing and max(opts['gpu_jobs']) > 1 and ('memory' in tail.lower() or 'vk' in tail.lower() or code != 0):
                        prog.log('  GPU ran out of video memory with %d at a time; retrying this batch with 1 per GPU.' % max(opts['gpu_jobs']))
                        opts['gpu_jobs'] = [1] * len(opts['gpu_jobs'])
                        code, tail = _run_gpu_batch(gpu.exe, in_dir, out_dir, gpu.model, native, opts['gpu_jobs'], gpu.gpu_id, opts.get('tile'), tick)
                        missing = [k for k in prep if not os.path.exists(os.path.join(out_dir, '%05d.png' % k))]
                    if missing:
                        prog.log('  GPU engine did not produce %d image(s) (%s); doing those on the CPU.' % (len(missing), tail[-200:]))
                        if len(missing) == len(prep):
                            gpu_broken = True
                            prog.log('  The GPU engine is not working on this PC; the rest goes to the CPU engine (slower).')
                    for k, plan in prep.items():
                        j = chunk[k]
                        name = j.get('name') or os.path.basename(j['src'])
                        outp = os.path.join(out_dir, '%05d.png' % k)
                        if k in missing:
                            submit(_work_local, name, j['src'], j['dst'], 'cpu', local_opts)
                        else:
                            submit(_work_finish, name, j['src'], j['dst'], outp, plan, dict(opts, model=gpu.model))
                    womprogress.label('finishing textures on the CPU')
                    drain(limit=cpu_jobs * 2)
            finally:
                drain(block=True)
                shutil.rmtree(tmp, ignore_errors=True)
            # damaged results (GPU reset mid-image): one more GPU pass with 1 image at a time, then CPU
            ai_jobs, broken[:] = list(broken), []
            if ai_jobs and passes == 1:
                # black/damaged pictures: some GPUs/drivers give black results with big tiles; try small tiles, one at a time
                prog.log('  redoing %d damaged texture(s) on the GPU, one at a time with small tiles' % len(ai_jobs))
                opts['gpu_jobs'] = [1] * len(opts['gpu_jobs'])
                opts['tile'] = 128
            elif ai_jobs:
                prog.log('  %d texture(s) still damaged; doing them on the CPU' % len(ai_jobs))
                for j in ai_jobs:
                    submit(_work_local, j.get('name') or os.path.basename(j['src']), j['src'], j['dst'], 'cpu', local_opts)
                ai_jobs = []
        drain(block=True)
    prog.done('%d done, %d skipped%s' % (done, skipped, (', %d failed' % failed) if failed else ''))
    if results and len(results) <= 40:
        print('\n'.join(results))
    return done, skipped, failed
