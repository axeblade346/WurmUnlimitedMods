#!/usr/bin/env python3
"""WOM Viewer launcher for Wurm Unlimited.

Finds the game's graphics.jar through Steam (any Steam library), or uses the one picked last time,
or asks once with a file picker, then opens wom_viewer.html in your browser with that jar loaded.
Needs only Python 3.8+ (no extra packages). Keep this window open while you use the viewer.

    python wom_viewer.py                      # find graphics.jar and open the viewer
    python wom_viewer.py --jar "<path>"       # use this graphics.jar
    python wom_viewer.py --no-jar             # just open the page
"""
import argparse
import json
import os
import re
import sys


def steam_libraries():
    """Steam library folders: Steam's own folder plus every library in steamapps/libraryfolders.vdf"""
    roots = []
    if sys.platform.startswith('win'):
        try:
            import winreg
            for hive, key, val in [(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                                   (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
                                   (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath')]:
                try:
                    with winreg.OpenKey(hive, key) as k:
                        roots.append(winreg.QueryValueEx(k, val)[0])
                except OSError:
                    pass
        except ImportError:
            pass
        roots += [r'C:\Program Files (x86)\Steam', r'C:\Program Files\Steam']
    else:
        h = os.path.expanduser('~')
        roots += [os.path.join(h, '.steam', 'steam'), os.path.join(h, '.local', 'share', 'Steam'),
                  os.path.join(h, 'Library', 'Application Support', 'Steam'),
                  os.path.join(h, '.var', 'app', 'com.valvesoftware.Steam', '.local', 'share', 'Steam')]
    libs = []
    for r in roots:
        r = os.path.normpath(r.replace('/', os.sep))
        if not os.path.isdir(r):
            continue
        libs.append(r)
        vdf = os.path.join(r, 'steamapps', 'libraryfolders.vdf')
        if os.path.exists(vdf):
            try:
                text = open(vdf, encoding='utf-8', errors='replace').read()
                for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                    libs.append(os.path.normpath(m.group(1).replace('\\\\', '\\')))
            except OSError:
                pass
    seen, out = set(), []
    for l in libs:
        if l.lower() not in seen:
            seen.add(l.lower()); out.append(l)
    return out


def find_graphics_jar():
    for lib in steam_libraries():
        p = os.path.join(lib, 'steamapps', 'common', 'Wurm Unlimited', 'WurmLauncher', 'packs', 'graphics.jar')
        if os.path.exists(p):
            return p
    return None


def run_viewer(args):
    import webbrowser, http.server, socketserver, urllib.parse
    here = os.path.dirname(os.path.abspath(__file__))
    page = os.path.join(here, 'wom_viewer.html')
    if not os.path.exists(page) and os.path.exists(os.path.join(here, 'viewer', 'wom_viewer.html')):
        page = os.path.join(here, 'viewer', 'wom_viewer.html')
    if not os.path.exists(page):
        sys.exit('wom_viewer.html not found next to wom_tool.py')
    settings_file = os.path.join(here, 'wom_viewer_settings.json')
    try:
        settings = json.load(open(settings_file, encoding='utf-8'))
    except (OSError, ValueError):
        settings = {}
    jar = None
    if not args.no_jar:
        # 1) --jar  2) Steam  3) the jar used last time  4) ask once with a file picker
        jar = args.jar or find_graphics_jar()
        if not jar and settings.get('jar') and os.path.exists(settings['jar']):
            jar = settings['jar']
        if not jar:
            print('graphics.jar not found through Steam. Pick it once (<game>\\WurmLauncher\\packs\\graphics.jar); it is remembered.')
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk(); root.withdraw()
                jar = filedialog.askopenfilename(title='Pick graphics.jar (Wurm Unlimited\\WurmLauncher\\packs)',
                                                 filetypes=[('Wurm Unlimited packs', '*.jar'), ('All files', '*.*')]) or None
                root.destroy()
            except Exception:
                jar = None
        if jar and not os.path.exists(jar):
            sys.exit('Not found: %s' % jar)
        if jar and settings.get('jar') != os.path.abspath(jar):
            settings['jar'] = os.path.abspath(jar)
            try:
                json.dump(settings, open(settings_file, 'w', encoding='utf-8'), indent=1)
            except OSError:
                pass
    if not jar:
        webbrowser.open('file:///' + page.replace(os.sep, '/').lstrip('/'))
        print('Opened %s' % page)
        return
    size = os.path.getsize(jar)

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send_jar(self, head):
            rng = self.headers.get('Range')
            start, end = 0, size - 1
            if rng:
                m = re.match(r'bytes=(\d*)-(\d*)', rng)
                if m:
                    if m.group(1):
                        start = int(m.group(1)); end = int(m.group(2)) if m.group(2) else size - 1
                    else:
                        start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                self.send_response(206); self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
            else:
                self.send_response(200)
            self.send_header('Accept-Ranges', 'bytes'); self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Content-Type', 'application/java-archive'); self.end_headers()
            if head:
                return
            with open(jar, 'rb') as f:
                f.seek(start); left = end - start + 1
                while left > 0:
                    b = f.read(min(1 << 20, left))
                    if not b:
                        break
                    try:
                        self.wfile.write(b)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(b)

        def _route(self, head):
            path = urllib.parse.urlparse(self.path).path
            if path in ('/', '/index.html', '/wom_viewer.html'):
                data = open(page, 'rb').read()
                self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(data))); self.end_headers()
                if not head:
                    self.wfile.write(data)
            elif path == '/game/' + os.path.basename(jar):
                self._send_jar(head)
            else:
                self.send_error(404)

        def do_GET(self):
            self._route(False)

        def do_HEAD(self):
            self._route(True)

    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    srv = Server(('127.0.0.1', args.port), H)
    url = 'http://127.0.0.1:%d/?jar=%s' % (srv.server_address[1], urllib.parse.quote('/game/' + os.path.basename(jar)))
    print('Game files: %s (%.0f MB, read in place)' % (jar, size / 1e6))
    print('Viewer:     %s' % url)
    print('Keep this window open while you use the viewer. Ctrl+C to stop.')
    webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('Stopped.')



def main():
    ap = argparse.ArgumentParser(description='Open the WOM Viewer with Wurm Unlimited\'s graphics.jar')
    ap.add_argument('--jar', help='graphics.jar to load (default: found through Steam)')
    ap.add_argument('--port', type=int, default=0, help='local port (default: any free one)')
    ap.add_argument('--no-jar', action='store_true', help='just open the page, no game files')
    run_viewer(ap.parse_args())


if __name__ == '__main__':
    main()
