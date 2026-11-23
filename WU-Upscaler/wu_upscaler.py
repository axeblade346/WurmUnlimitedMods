"""WU Upscaler - web page to upscale Wurm Unlimited's textures into userpacks.

Start with Start_Upscaler.bat (or: python wu_upscaler.py). A page opens in your browser at http://127.0.0.1:5110
Everything runs on your own PC; the page only talks to this program.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

# ---------------------------------------------------------------- the Python packages it needs, installed by itself
NEEDED = [('numpy', 'numpy', None), ('PIL', 'pillow', (11, 2)), ('psutil', 'psutil', None)]


def _missing():
    import importlib
    out = []
    for mod, pkg, minv in NEEDED:
        try:
            m = importlib.import_module(mod)
            if minv:
                v = tuple(int(x) for x in m.__version__.split('.')[:2] if x.isdigit())
                if v < minv:
                    out.append('%s>=%s' % (pkg, '.'.join(map(str, minv))))
        except Exception:
            out.append(pkg if not minv else '%s>=%s' % (pkg, '.'.join(map(str, minv))))
    return out


def self_install():
    need = _missing()
    if not need:
        return
    print('Installing the Python packages this tool needs: %s' % ', '.join(need))
    base = [sys.executable, '-m', 'pip', 'install', '--upgrade']
    r = subprocess.run(base + need)
    if r.returncode != 0:
        subprocess.run([sys.executable, '-m', 'ensurepip', '--upgrade'])
        r = subprocess.run(base + ['--user'] + need)
    import importlib
    importlib.invalidate_caches()
    if _missing():
        print('\nCould not install: %s\nInstall them by hand:  "%s" -m pip install %s' % (
            ', '.join(_missing()), sys.executable, ' '.join(_missing())))
        input('Press Enter to close.'); sys.exit(1)
    if any(n.startswith('pillow') for n in need) and 'PIL' in sys.modules:
        print('Pillow was updated: starting again ...')
        os.execv(sys.executable, [sys.executable] + sys.argv)
    print('Done.\n')


self_install()

import datetime   # noqa: E402
import html       # noqa: E402
import http.server   # noqa: E402
import json       # noqa: E402
import re         # noqa: E402
import signal     # noqa: E402
import threading  # noqa: E402
import time       # noqa: E402
import urllib.parse   # noqa: E402
import webbrowser  # noqa: E402

import psutil     # noqa: E402

SETTINGS_FILE = os.path.join(HERE, 'upscaler_settings.json')
PORT = 5110
WU_APPID = '366220'          # Wurm Unlimited (the game client) on Steam


# ================================================================ settings
def load_settings():
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    s.setdefault('graphics_jar', '')
    s.setdefault('staging', '')
    s.setdefault('pmk', True)
    s.setdefault('engine', 'auto')
    s.setdefault('gpu_id', '')
    s.setdefault('gpu_jobs', '')
    s.setdefault('cpu_jobs', 0)
    s.setdefault('keep_below', 64)
    s.setdefault('folders', [])          # ["graphics:creatures", "pmk:models"]; empty = all
    return s


def save_settings(s):
    tmp = SETTINGS_FILE + '.part'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, SETTINGS_FILE)


def source_jars(s):
    """[(stem, path)] of the jars to upscale: graphics.jar, and pmk.jar from the same packs folder"""
    out = []
    g = s.get('graphics_jar') or ''
    if g and os.path.isfile(g):
        out.append(('graphics', g))
        pmk = os.path.join(os.path.dirname(g), 'pmk.jar')
        if s.get('pmk') and os.path.isfile(pmk):
            out.append(('pmk', pmk))
    return out


# ================================================================ finding the game through Steam
def steam_roots():
    roots = []
    if sys.platform.startswith('win'):
        try:
            import winreg
            for hive, key, val in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                                   (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
                                   (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath')):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        roots.append(os.path.normpath(winreg.QueryValueEx(k, val)[0]))
                except OSError:
                    pass
        except ImportError:
            pass
        roots += [r'C:\Program Files (x86)\Steam', r'C:\Program Files\Steam']
    else:
        home = os.path.expanduser('~')
        roots += [os.path.join(home, '.steam', 'steam'), os.path.join(home, '.local', 'share', 'Steam'),
                  os.path.join(home, 'Library', 'Application Support', 'Steam')]
    return [r for r in dict.fromkeys(roots) if os.path.isdir(r)]


def steam_libraries():
    libs = []
    for r in steam_roots():
        libs.append(r)
        vdf = os.path.join(r, 'steamapps', 'libraryfolders.vdf')
        try:
            txt = open(vdf, encoding='utf-8', errors='replace').read()
            for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
                libs.append(os.path.normpath(m.group(1).replace('\\\\', '\\')))
        except OSError:
            pass
    return [l for l in dict.fromkeys(libs) if os.path.isdir(l)]


def find_graphics_jar():
    """WurmLauncher\\packs\\graphics.jar of the Steam copy of Wurm Unlimited, or ''"""
    for lib in steam_libraries():
        names = ['Wurm Unlimited']
        acf = os.path.join(lib, 'steamapps', 'appmanifest_%s.acf' % WU_APPID)
        try:
            m = re.search(r'"installdir"\s+"([^"]+)"', open(acf, encoding='utf-8', errors='replace').read())
            if m:
                names.insert(0, m.group(1))
        except OSError:
            pass
        for n in dict.fromkeys(names):
            p = os.path.join(lib, 'steamapps', 'common', n, 'WurmLauncher', 'packs', 'graphics.jar')
            if os.path.isfile(p):
                return p
    return ''


def beta_status(s):
    """Userpacks only work with the beta branch of the client. -> {'ok': True/False/None, 'branch': str, 'text': str}"""
    g = s.get('graphics_jar') or ''
    if not g:
        return {'ok': None, 'branch': '', 'text': ''}
    launcher = os.path.dirname(os.path.dirname(g))            # ...\WurmLauncher
    client = os.path.join(launcher, 'client.jar')
    branch = ''
    common = os.path.dirname(launcher.rstrip('\\/'))       # ...\steamapps\common\Wurm Unlimited
    acf = os.path.join(os.path.dirname(os.path.dirname(common)), 'appmanifest_%s.acf' % WU_APPID)
    try:
        m = re.search(r'"BetaKey"\s+"([^"]*)"', open(acf, encoding='utf-8', errors='replace').read())
        branch = m.group(1) if m else 'default'
    except OSError:
        pass
    try:
        import zipfile
        with zipfile.ZipFile(client) as z:
            ok = b'./userpacks' in z.read('com/wurmonline/client/settings/GlobalData.class')
    except Exception:
        return {'ok': None, 'branch': branch, 'text': 'Could not read %s to check for userpacks support.' % client}
    if ok:
        return {'ok': True, 'branch': branch, 'text': 'This game client supports userpacks%s.' % (' (Steam branch: %s)' % branch if branch else '')}
    return {'ok': False, 'branch': branch,
            'text': 'This game client does not support userpacks: they are part of the beta branch of Wurm Unlimited%s. '
                    'In Steam: right-click Wurm Unlimited > Properties > Betas, choose the beta branch, let Steam update, '
                    'then press "Check again".' % (' (installed now: %s)' % branch if branch else '')}


BROWSE_SCRIPT = r'''
import sys, tkinter as tk
from tkinter import filedialog as fd
r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)
kind, start = sys.argv[1], sys.argv[2]
if kind == 'file':
    p = fd.askopenfilename(title='Choose graphics.jar (WurmLauncher\\packs\\graphics.jar)', initialdir=start or None,
                           filetypes=[('graphics.jar', 'graphics.jar'), ('Java packs', '*.jar'), ('All files', '*.*')])
else:
    p = fd.askdirectory(title='Choose the staging folder (the work files and finished packs go here)', initialdir=start or None, mustexist=False)
print(p or '')
'''


def browse(kind, start):
    try:
        r = subprocess.run([sys.executable, '-c', BROWSE_SCRIPT, kind, start or ''], capture_output=True, text=True, timeout=600)
        return os.path.normpath(r.stdout.strip()) if r.stdout.strip() else ''
    except Exception:
        return ''


# ================================================================ CPU / RAM / GPU / VRAM
class Monitor:
    """samples the PC every ~2 s in the background"""
    def __init__(self):
        self.data = {'cpu': None, 'ram_used': None, 'ram_total': None, 'gpu': None, 'vram_used': None, 'vram_total': None,
                     'gpu_name': '', 'gpu_source': ''}
        self.lock = threading.Lock()
        self.method = None
        psutil.cpu_percent(None)
        threading.Thread(target=self.loop, daemon=True).start()

    def get(self):
        with self.lock:
            return dict(self.data)

    def loop(self):
        while True:
            try:
                vm = psutil.virtual_memory()
                d = {'cpu': psutil.cpu_percent(None), 'ram_used': vm.used, 'ram_total': vm.total}
                d.update(self.gpu())
                with self.lock:
                    self.data.update(d)
            except Exception:
                pass
            time.sleep(2)

    def gpu(self):
        if self.method in (None, 'nvidia'):
            try:
                r = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total,name',
                                    '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=8,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                rows = [l.split(',') for l in r.stdout.strip().splitlines() if l.count(',') >= 3]
                if rows:
                    self.method = 'nvidia'
                    row = max(rows, key=lambda x: float(x[2]))
                    return {'gpu': float(row[0]), 'vram_used': float(row[1]) * 1048576, 'vram_total': float(row[2]) * 1048576,
                            'gpu_name': row[3].strip(), 'gpu_source': 'nvidia-smi'}
            except Exception:
                pass
            if self.method == 'nvidia':
                return {}
            self.method = 'win' if sys.platform.startswith('win') else 'linux'
        if self.method == 'win':
            return self.gpu_windows()
        if self.method == 'linux':
            return self.gpu_linux()
        return {}

    def gpu_windows(self):
        """Windows' own GPU counters (any make of graphics card, as in Task Manager)"""
        try:
            r = subprocess.run(['typeperf', r'\GPU Engine(*)\Utilization Percentage', r'\GPU Adapter Memory(*)\Dedicated Usage',
                                '-sc', '1', '-si', '1'], capture_output=True, text=True, timeout=20,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            lines = [l for l in r.stdout.splitlines() if l.startswith('"')]
            if len(lines) < 2:
                self.method = 'none'; return {}
            import csv
            head = next(csv.reader([lines[0]])); vals = next(csv.reader([lines[-1]]))
            eng, mem = {}, {}
            for h, v in zip(head[1:], vals[1:]):
                try:
                    v = float(v)
                except ValueError:
                    continue
                m = re.search(r'luid_(\w+?)_phys_\d+(?:_eng_\d+_engtype_([^)]*))?\)', h)
                if not m:
                    continue
                if 'Utilization' in h:
                    k = (m.group(1), m.group(2) or '')
                    eng[k] = eng.get(k, 0.0) + v
                elif 'Dedicated' in h:
                    mem[m.group(1)] = max(mem.get(m.group(1), 0.0), v)
            out = {'gpu_source': 'Windows GPU counters'}
            if eng:
                out['gpu'] = min(100.0, max(eng.values()))
            if mem:
                luid = max(mem, key=mem.get)
                out['vram_used'] = mem[luid]
            tot = vram_total()
            if tot:
                out['vram_total'] = tot
            return out
        except Exception:
            self.method = 'none'
            return {}

    def gpu_linux(self):
        import glob
        best = None
        for d in glob.glob('/sys/class/drm/card*/device'):
            try:
                busy = float(open(os.path.join(d, 'gpu_busy_percent')).read())
                used = int(open(os.path.join(d, 'mem_info_vram_used')).read())
                tot = int(open(os.path.join(d, 'mem_info_vram_total')).read())
                if best is None or tot > best['vram_total']:
                    best = {'gpu': busy, 'vram_used': used, 'vram_total': tot, 'gpu_source': 'amdgpu'}
            except (OSError, ValueError):
                pass
        if best is None:
            self.method = 'none'
        return best or {}


_VRAM_TOTAL = [None]


def vram_total():
    if _VRAM_TOTAL[0] is None:
        try:
            import womfast
            v = womfast.free_vram_mb()
            _VRAM_TOTAL[0] = v[1] * 1048576 if v else 0
        except Exception:
            _VRAM_TOTAL[0] = 0
    return _VRAM_TOTAL[0]


MON = None


def gb(b):
    return '%.1f' % (b / 1073741824) if b is not None else '?'


def stats_line():
    d = MON.get() if MON else {}
    parts = ['CPU %s%%' % ('%.0f' % d['cpu'] if d.get('cpu') is not None else '?'),
             'RAM %s/%s GB' % (gb(d.get('ram_used')), gb(d.get('ram_total')))]
    if d.get('gpu') is not None or d.get('vram_used') is not None:
        parts.append('GPU %s%%' % ('%.0f' % d['gpu'] if d.get('gpu') is not None else '?'))
        parts.append('VRAM %s/%s GB' % (gb(d.get('vram_used')), gb(d.get('vram_total')) if d.get('vram_total') else '?'))
    else:
        parts.append('GPU n/a')
    return ' | '.join(parts)


# ================================================================ jobs (one at a time), output streamed to the page
class Job:
    def __init__(self, name):
        self.name = name; self.chunks = []; self.lock = threading.Lock(); self.done = False; self.code = None
        self.proc = None; self.stopped = False; self.started = time.time(); self.log = None

    def add(self, text):
        with self.lock:
            self.chunks.append(text)
        if self.log:
            try:
                self.log.write(text); self.log.flush()
            except Exception:
                pass

    def read_from(self, pos):
        with self.lock:
            return ''.join(self.chunks[pos:]), len(self.chunks)


JOBS, LAST = {}, [None]
JOBS_LOCK = threading.Lock()


def running_job():
    j = LAST[0]
    return JOBS[j] if j and not JOBS[j].done else None


def read_json(path):
    """read a .json and close it at once (an open file would stop the upscaler from replacing it on Windows)"""
    with open(path, 'rb') as f:
        data = f.read()
    return json.loads(data.decode('utf-8'))


def progress_text(staging):
    try:
        p = read_json(os.path.join(staging, 'progress.json'))
    except (OSError, ValueError):
        return ''
    eta = p.get('eta')
    t = '%s: packs %d/%d, textures %d/%d (%d%%)' % (p.get('source', ''), p.get('packs_done', 0), p.get('packs_total', 0),
                                                    p.get('tex_done', 0), p.get('tex_total', 0),
                                                    100 * p.get('tex_done', 0) // max(1, p.get('tex_total', 1)))
    if eta:
        t += ', about %s left' % str(datetime.timedelta(seconds=int(eta)))
    return t


def start_job(name, cmd, staging=None):
    with JOBS_LOCK:
        if running_job():
            return None, '%s is still running - wait for it or press Stop.' % JOBS[LAST[0]].name
        jid = str(int(time.time() * 1000))
        job = Job(name); JOBS[jid] = job; LAST[0] = jid
    if staging:
        os.makedirs(os.path.join(staging, 'logs'), exist_ok=True)
        job.log = open(os.path.join(staging, 'logs', 'run_%s.log' % time.strftime('%Y%m%d_%H%M%S')), 'a', encoding='utf-8')
    threading.Thread(target=worker, args=(job, cmd, staging), daemon=True).start()
    return jid, None


def worker(job, cmd, staging):
    env = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    if staging:
        tmp = os.path.join(staging, 'tmp')
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)      # GPU work pictures left by a run that was stopped
        os.makedirs(tmp, exist_ok=True)
        env.update(TMP=tmp, TEMP=tmp, TMPDIR=tmp)
    stamp = lambda: time.strftime('%H:%M:%S')
    job.add('[%s] === %s ===\n[%s] %s\n' % (stamp(), job.name, stamp(), stats_line()))
    kw = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    try:
        p = subprocess.Popen(cmd, cwd=HERE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
        job.proc = p
        last_status = [time.time()]

        def status_loop():          # a status line every minute: progress + CPU, RAM, GPU, VRAM
            while p.poll() is None:
                time.sleep(5)
                if time.time() - last_status[0] >= 60 and p.poll() is None:
                    last_status[0] = time.time()
                    pt = progress_text(staging) if staging else ''
                    job.add('[%s] -- status: %s%s\n' % (stamp(), (pt + ' | ') if pt else '', stats_line()))
        threading.Thread(target=status_loop, daemon=True).start()
        for raw in iter(p.stdout.readline, b''):
            line = raw.decode('utf-8', 'replace').rstrip('\r\n')
            if not line.strip():
                continue
            if not re.match(r'^\[\d\d:\d\d:\d\d\]', line):
                line = '[%s] %s' % (stamp(), line)
            job.add(line + '\n')
        job.code = p.wait()
        job.add('[%s] === %s (exit code %s) === %s\n' % (stamp(), 'Stopped' if job.stopped else 'Finished', job.code, stats_line()))
    except Exception as e:
        job.add('[%s] Error: %s\n' % (stamp(), e))
    finally:
        job.done = True
        if job.log:
            try:
                job.log.close()
            except Exception:
                pass


def stop_job():
    job = running_job()
    if not job or not job.proc:
        return
    job.stopped = True
    job.add('[%s] Stopping ... (finished textures and packs are kept; Start again carries on from here)\n' % time.strftime('%H:%M:%S'))
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(job.proc.pid)], capture_output=True)
        else:
            os.killpg(os.getpgid(job.proc.pid), signal.SIGTERM)
    except Exception as e:
        job.add('could not stop it: %s\n' % e)


def worker_cmd(s, plan_only=False, replan=False, redo=False):
    cmd = [sys.executable, os.path.join(HERE, 'upscale_run.py'), '--staging', s['staging']]
    for _, p in source_jars(s):
        cmd += ['--jar', p]
    if plan_only:
        cmd.append('--plan-only')
    if replan:
        cmd.append('--replan')
    if redo:
        cmd.append('--redo')
    if s.get('folders'):
        cmd += ['--folders', ','.join(s['folders'])]
    cmd += ['--engine', s.get('engine') or 'auto']
    if s.get('gpu_id') not in ('', None):
        cmd += ['--gpu-id', str(s['gpu_id'])]
    if s.get('gpu_jobs') not in ('', None):
        cmd += ['--gpu-jobs', str(s['gpu_jobs'])]
    if s.get('cpu_jobs'):
        cmd += ['--cpu-jobs', str(int(s['cpu_jobs']))]
    try:
        cmd += ['--keep-below', str(int(s.get('keep_below') or 64))]
    except (TypeError, ValueError):
        pass
    return cmd


# ================================================================ what the plans say
def plan_summary(s):
    import upscale_run as ur
    out = []
    for stem, path in source_jars(s):
        st = os.path.join(s['staging'], stem)
        try:
            plan = json.load(open(os.path.join(st, 'plan.json'), encoding='utf-8'))
        except (OSError, ValueError):
            out.append({'stem': stem, 'jar': path, 'planned': False}); continue
        jdir = os.path.join(s['staging'], 'jars')
        packs = []
        for p in plan['packs']:
            done = ur.pack_done(st, jdir, p)
            size = os.path.getsize(os.path.join(jdir, p['name'] + '.jar')) if done else 0
            packs.append({'name': p['name'], 'top': p['top'], 'section': p['section'], 'lines': len(p['lines']),
                          'textures': len(p['textures']), 'files': len(p['files']), 'done': done, 'size': size})
        out.append({'stem': stem, 'jar': path, 'planned': True, 'made': plan.get('made'), 'packs': packs,
                    'textures': len(plan.get('textures', {})), 'notes': plan.get('note_count', 0)})
    return out


def gpu_status():
    import womtex
    exe = womtex.find_gpu_exe()
    return {'installed': bool(exe), 'exe': exe or ''}


# ================================================================ web server
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        return

    def send_json(self, obj, code=200):
        data = json.dumps(obj).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def body_json(self):
        n = int(self.headers.get('Content-Length') or 0)
        try:
            return json.loads(self.rfile.read(n).decode('utf-8') or '{}')
        except ValueError:
            return {}

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        path = u.path
        s = load_settings()
        if path == '/':
            data = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
        elif path == '/settings':
            jars = source_jars(s)
            self.send_json({'settings': s, 'jars': [{'stem': a, 'path': b} for a, b in jars],
                            'pmk_found': bool(s['graphics_jar']) and os.path.isfile(os.path.join(os.path.dirname(s['graphics_jar']), 'pmk.jar')),
                            'gpu': gpu_status(), 'python': sys.executable, 'version': read_version(), 'beta': beta_status(s)})
        elif path == '/detect':
            self.send_json({'graphics_jar': find_graphics_jar(), 'libraries': steam_libraries()})
        elif path == '/browse':
            self.send_json({'path': browse(q.get('kind', ['dir'])[0], q.get('start', [''])[0])})
        elif path == '/stats':
            d = MON.get()
            prog = None
            if s.get('staging'):
                try:
                    prog = read_json(os.path.join(s['staging'], 'progress.json'))
                except (OSError, ValueError):
                    prog = None
            j = running_job()
            self.send_json({'stats': d, 'time': time.strftime('%H:%M:%S'), 'progress': prog,
                            'running': j.name if j else '', 'elapsed': int(time.time() - j.started) if j else 0})
        elif path == '/plan':
            self.send_json({'sources': plan_summary(s) if s.get('staging') else []})
        elif path == '/poll':
            job = JOBS.get(q.get('job', [''])[0])
            if not job:
                self.send_json({'text': '', 'pos': 0, 'done': True, 'code': None}); return
            text, pos = job.read_from(int(q.get('pos', ['0'])[0] or 0))
            self.send_json({'text': text, 'pos': pos, 'done': job.done and job.read_from(pos)[0] == '', 'code': job.code})
        elif path == '/current':
            j = LAST[0]
            self.send_json({'job': j, 'name': JOBS[j].name, 'done': JOBS[j].done} if j else {})
        elif path == '/stop':
            stop_job(); self.send_json({'ok': True})
        elif path == '/open':
            what = q.get('what', ['jars'])[0]
            target = {'jars': os.path.join(s.get('staging', ''), 'jars'), 'staging': s.get('staging', ''),
                      'userpacks': os.path.join(os.path.dirname(os.path.dirname(s.get('graphics_jar', ''))), 'userpacks')}.get(what, '')
            if target:
                os.makedirs(target, exist_ok=True)
                try:
                    if sys.platform.startswith('win'):
                        os.startfile(target)
                    else:
                        subprocess.Popen(['xdg-open' if sys.platform.startswith('linux') else 'open', target])
                except Exception:
                    pass
            self.send_json({'ok': True, 'path': target})
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        path = u.path
        s = load_settings()
        b = self.body_json()
        if path == '/settings':
            for k in ('graphics_jar', 'staging', 'pmk', 'engine', 'gpu_id', 'gpu_jobs', 'cpu_jobs', 'folders', 'keep_below'):
                if k in b:
                    s[k] = b[k]
            for k in ('graphics_jar', 'staging'):
                s[k] = os.path.normpath(s[k].strip().strip('"')) if s.get(k) else ''
            save_settings(s)
            self.send_json({'ok': True, 'settings': s})
        elif path in ('/scan', '/start'):
            err = check_ready(s)
            if err:
                self.send_json({'error': err}); return
            if path == '/start':
                b_ = beta_status(s)
                if b_['ok'] is False and not b.get('anyway'):
                    self.send_json({'error': b_['text'], 'beta': False}); return
            if path == '/scan':
                jid, err = start_job('Reading the mappings.txt of %s' % ', '.join(os.path.basename(p) for _, p in source_jars(s)),
                                     worker_cmd(s, plan_only=True, replan=bool(b.get('replan'))), s['staging'])
            else:
                jid, err = start_job('Upscaling (%s)' % (', '.join(s['folders']) if s.get('folders') else 'all folders'),
                                     worker_cmd(s, redo=bool(b.get('redo'))), s['staging'])
            self.send_json({'job': jid, 'error': err})
        elif path == '/gpu-setup':
            jid, err = start_job('Installing the GPU engine (Real-ESRGAN ncnn Vulkan)',
                                 [sys.executable, '-c', 'import womtex; womtex.setup_gpu()'], s.get('staging') or None)
            self.send_json({'job': jid, 'error': err})
        elif path == '/gpu-check':
            jid, err = start_job('Testing the GPU engine', [sys.executable, '-c', 'import womtex; womtex.gpu_check()'], None)
            self.send_json({'job': jid, 'error': err})
        else:
            self.send_response(404); self.end_headers()


def check_ready(s):
    if not s.get('graphics_jar') or not os.path.isfile(s['graphics_jar']):
        return 'Set where graphics.jar is first (WurmLauncher\\packs\\graphics.jar).'
    if not s.get('staging'):
        return 'Set the staging folder first.'
    try:
        os.makedirs(s['staging'], exist_ok=True)
    except OSError as e:
        return 'Cannot use the staging folder: %s' % e
    return None


def read_version():
    try:
        return open(os.path.join(HERE, 'VERSION.txt'), encoding='utf-8').read().strip()
    except OSError:
        return ''


PAGE = open(os.path.join(HERE, 'page.html'), encoding='utf-8').read() if os.path.exists(os.path.join(HERE, 'page.html')) else ''


# ================================================================ start
def port_in_use(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sk:
        sk.settimeout(1.0)
        return sk.connect_ex(('127.0.0.1', port)) == 0


def main():
    global MON
    port = PORT
    if port_in_use(port):
        print('WU Upscaler (or another program) is already using port %d.' % port)
        print('If an older WU Upscaler window is still open, close it first. Using the next free port instead.\n')
        while port_in_use(port):
            port += 1
    MON = Monitor()
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
    srv.daemon_threads = True
    url = 'http://127.0.0.1:%d' % port
    print('WU Upscaler %s' % read_version())
    print('Web page: %s  (opens in your browser)' % url)
    print('Keep this window open while it works. Close it (or press Ctrl+C) to stop the page;')
    print('a running upscale is stopped with the Stop button on the page.\n')
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        stop_job()
        print('Closing ...')


if __name__ == '__main__':
    main()
