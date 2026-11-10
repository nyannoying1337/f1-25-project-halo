"""Render the timing tower's baked textures from tools/tower/tower.js with headless Chrome, then convert them with the
halo's loader (tools/native/textures.py): <out>/sprites.npz, sprites.json, png/*.png.

usage: python -I export_sprites.py <out dir> [--chrome PATH] [--r PX_PER_HUD] [--profile DIR]

One sprite per Chrome run, each run with its own new profile folder: since 2026-11-09 about 08:00, headless Chrome on
this PC hangs on pages that draw more than a couple of canvases, and a hung run can leave child processes holding its
profile folder. Nothing here reads or writes game files.
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
NATIVE = os.path.join(os.path.dirname(HERE), 'native')


def chrome_dump(chrome, profile_root, query, timeout=90):
    run = os.path.join(profile_root, 'run_%d_%d' % (os.getpid(), time.time_ns()))
    url = 'file:///' + os.path.join(HERE, 'export_tower.html').replace('\\', '/') + query
    cmd = [chrome, '--headless=new', '--disable-gpu', '--allow-file-access-from-files', '--virtual-time-budget=60000',
           '--user-data-dir=' + run, '--dump-dom', url]
    res = subprocess.run(cmd, capture_output=True, timeout=timeout)
    m = re.search(r'<pre id="out">(.*?)</pre>', res.stdout.decode('utf-8', 'replace'), re.S)
    if not m:
        raise SystemExit(f'export_tower.html{query} produced no output (exit {res.returncode}): {res.stderr[-400:]!r}')
    txt = html.unescape(m.group(1))
    if not txt.startswith('{'):
        raise SystemExit(f'export_tower.html{query} failed: {txt[:800]}')
    return json.loads(txt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--chrome', default=os.environ.get('CHROME', r'C:\Program Files\Google\Chrome\Application\chrome.exe'))
    ap.add_argument('--r', type=int, default=4)
    ap.add_argument('--profile', default=os.path.join(tempfile.gettempdir(), 'tower-export-chrome'))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    head = chrome_dump(a.chrome, a.profile, f'?r={a.r}&list=1')
    sprites = []
    for name in head['names']:
        got = chrome_dump(a.chrome, a.profile, f'?r={a.r}&only={name}')['sprites']
        assert [s['name'] for s in got] == [name], (name, [s['name'] for s in got])
        sprites += got
        print(f'  {name}', flush=True)
    data = dict(head, sprites=sprites)
    dom = os.path.join(a.out, 'dom.html')
    with open(dom, 'w', encoding='utf-8') as f:
        f.write('<pre id="out">' + html.escape(json.dumps(data)) + '</pre>\n')
    subprocess.run([sys.executable, '-I', os.path.join(NATIVE, 'textures.py'), dom, a.out], check=True)
    # textures.py keeps sprites.json's keys; record which sprites are exact (edge to edge) for the builder
    meta_path = os.path.join(a.out, 'sprites.json')
    meta = json.load(open(meta_path))
    for s in sprites:
        meta['sprites'][s['name']]['exact'] = bool(s.get('exact'))
    json.dump(meta, open(meta_path, 'w'), indent=1)


if __name__ == '__main__':
    main()
