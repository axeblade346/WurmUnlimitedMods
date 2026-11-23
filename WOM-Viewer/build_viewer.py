#!/usr/bin/env python3
"""Bundle the viewer into one self-contained HTML file (opens from disk with a double-click).

Build:  npm install three   (in this folder)   then   python build_viewer.py

All JavaScript modules (three.js, OrbitControls, formats.js, app.js) are put into an import map
as data: URLs, because browsers refuse to load module files next to a page opened from file://.
"""
import base64
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
THREE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'node_modules', 'three')
THREE_ADDONS = sys.argv[2] if len(sys.argv) > 2 else THREE
OUT = sys.argv[3] if len(sys.argv) > 3 else os.path.join(HERE, 'wom_viewer.html')


def data_url(js):
    return 'data:text/javascript;base64,' + base64.b64encode(js.encode('utf-8')).decode('ascii')


def main():
    core = open(os.path.join(THREE, 'build/three.core.js'), encoding='utf-8').read()
    module = open(os.path.join(THREE, 'build/three.module.js'), encoding='utf-8').read()
    module = re.sub(r"""from\s+['"]\./three\.core\.js['"]""", "from 'three-core'", module)
    orbit = open(os.path.join(THREE_ADDONS, 'examples/jsm/controls/OrbitControls.js'), encoding='utf-8').read()
    formats = open(os.path.join(HERE, 'src/formats.js'), encoding='utf-8').read()
    exporters = open(os.path.join(HERE, 'src/export.js'), encoding='utf-8').read()
    app = open(os.path.join(HERE, 'src/app.js'), encoding='utf-8').read()
    imports = {
        'three-core': data_url(core),
        'three': data_url(module),
        'three/addons/OrbitControls.js': data_url(orbit),
        'wom-formats': data_url(formats),
        'wom-export': data_url(exporters),
        'wom-app': data_url(app),
    }
    html = open(os.path.join(HERE, 'src/index.html'), encoding='utf-8').read()
    tag = '<script type="importmap">' + json.dumps({'imports': imports}) + '</script>'
    html = html.replace('<!--IMPORTMAP-->', tag)
    open(OUT, 'w', encoding='utf-8').write(html)
    print('Wrote %s (%.1f MB)' % (OUT, os.path.getsize(OUT) / 1e6))


if __name__ == '__main__':
    main()
