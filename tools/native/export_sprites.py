"""Render the halo's sprites from tools/halo.js with a headless Chromium browser, one sprite per browser run, and write
the sprite set the builder reads: <out>/sprites.npz, sprites.json and png/*.png (the same files textures.py writes).

usage: python -I export_sprites.py <out dir> [--keep OLD_DIR] [--only a,b] [--chrome PATH] [--r PX_PER_HUD]
                                   [--profile DIR] [--layout cam]

--layout cam: the symmetric "Default camera" layout of halo.js; without it today's set.

--keep OLD_DIR: take every sprite that OLD_DIR's set already has from there, unchanged, and render only the others.
That keeps a released look byte-identical when sprites are added (browser updates can move pixels).
The geometry header (G, P, ...) always comes from the current halo.js.

Browser: Microsoft Edge when it is installed, else Chrome (--chrome or CHROME picks another). Since 2026-11-09 the
build PC's headless Chrome 157 hangs its renderer on any canvas drawn after the page has loaded a web font (Saira), so
it cannot render these pages; headless Edge 158 renders them, and its base, rails, boost_on, gear_5, cap_l_on,
rpm_team, str_l_3 and batt_fill came out byte-identical to the shipped set (native_out_v9). One sprite per run keeps a
hang to one sprite. Each run gets its own new profile folder. Nothing here reads or writes game files.
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

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pngio  # noqa: E402
import textures  # noqa: E402

PAGE = os.path.join(os.path.dirname(HERE), 'export_native.html')
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'


def default_browser():
    if os.environ.get('CHROME'):
        return os.environ['CHROME']
    return EDGE if os.path.exists(EDGE) else CHROME


def chrome_dump(chrome, profile_root, query, timeout=90):
    run = os.path.join(profile_root, 'run_%d_%d' % (os.getpid(), time.time_ns()))
    url = 'file:///' + PAGE.replace('\\', '/') + query
    # --disable-features=SkiaGraphite: with Chrome 157's Graphite backend on, a software canvas hangs its renderer on
    # the first stroke() (2026-11-09); without it the canvases raster as they did when the shipped sprites were made
    cmd = [chrome, '--headless=new', '--disable-gpu', '--disable-features=SkiaGraphite', '--allow-file-access-from-files',
           '--virtual-time-budget=60000', '--user-data-dir=' + run, '--dump-dom', url]
    res = subprocess.run(cmd, capture_output=True, timeout=timeout)
    m = re.search(r'<pre id="out">(.*?)</pre>', res.stdout.decode('utf-8', 'replace'), re.S)
    if not m:
        raise SystemExit(f'export_native.html{query} produced no output (exit {res.returncode}): {res.stderr[-400:]!r}')
    txt = html.unescape(m.group(1))
    if not txt.startswith('{'):
        raise SystemExit(f'export_native.html{query} failed: {txt[:800]}')
    return json.loads(txt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--keep')
    ap.add_argument('--only')
    ap.add_argument('--chrome', default=default_browser(), help='Chromium-based browser (default: Edge, else Chrome)')
    ap.add_argument('--r', type=int, default=3)
    ap.add_argument('--profile', default=os.path.join(tempfile.gettempdir(), 'halo-export-chrome'))
    ap.add_argument('--layout', choices=('tv', 'cam'), default='tv')
    a = ap.parse_args()
    lay = '&layout=cam' if a.layout == 'cam' else ''
    if not os.path.exists(os.path.join(os.path.dirname(PAGE), 'saira.ttf')):
        raise SystemExit('tools/saira.ttf is missing: export_native.html needs the Saira font there (see README)')
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.profile, exist_ok=True)

    head = chrome_dump(a.chrome, a.profile, f'?r={a.r}&only=' + lay)
    names = head['names']
    kept, meta_old = {}, None
    if a.keep:
        meta_old = json.load(open(os.path.join(a.keep, 'sprites.json'), encoding='utf-8'))
        if meta_old['R'] != a.r:
            raise SystemExit(f'--keep set was rendered at R={meta_old["R"]}, not {a.r}')
        z = np.load(os.path.join(a.keep, 'sprites.npz'))
        kept = {n: (z[n], meta_old['sprites'][n]) for n in z.files if n in names}
    want = a.only.split(',') if a.only else [n for n in names if n not in kept]
    print(f'{len(names)} sprites in export_native.js; {len(kept)} kept from {a.keep}; rendering {len(want)} '
          f'with {os.path.basename(a.chrome)}')

    images, bounds = {}, {}
    for n, (img, b) in kept.items():
        images[n], bounds[n] = img, {k: b[k] for k in ('x0', 'y0', 'x1', 'y1', 'w', 'h')}
    digits = None
    for i, n in enumerate(want, 1):
        t0 = time.time()
        d = chrome_dump(a.chrome, a.profile, f'?r={a.r}&only={n}' + lay)
        (s,) = d['sprites']
        raw = np.frombuffer(__import__('base64').b64decode(s['rgba']), np.uint8).reshape(s['h'], s['w'], 4)
        images[n] = textures.bleed(raw.copy())
        bounds[n] = {k: s[k] for k in ('x0', 'y0', 'x1', 'y1', 'w', 'h')}
        digits = d.get('digits') or digits
        print(f'  [{i}/{len(want)}] {n:12s} {s["w"]:5d}x{s["h"]:<4d} {time.time() - t0:4.1f} s')

    order = [n for n in names if n in images]
    meta = {k: v for k, v in head.items() if k not in ('sprites', 'names', 'digits')}
    # the value digits' layout comes with the G-meter digit sprites: when those are kept, so is their layout
    meta['digits'] = digits if digits is not None else (meta_old or {}).get('digits')
    meta['kept'] = {'from': a.keep, 'names': sorted(kept)} if a.keep else None
    meta['sprites'] = {n: bounds[n] for n in order}
    json.dump(meta, open(os.path.join(a.out, 'sprites.json'), 'w'), indent=1)
    np.savez_compressed(os.path.join(a.out, 'sprites.npz'), **{n: images[n] for n in order})
    os.makedirs(os.path.join(a.out, 'png'), exist_ok=True)
    for n in order:
        pngio.write_png(os.path.join(a.out, 'png', n + '.png'), images[n])
    # the two solid sprites build_native.py makes itself (same values), as PNGs for the simulator (sim.js)
    pngio.write_png(os.path.join(a.out, 'png', 'solid_white.png'), np.full((16, 16, 4), 255, np.uint8))
    pngio.write_png(os.path.join(a.out, 'png', 'solid_core.png'), np.tile(np.array([225, 255, 250, 140], np.uint8), (16, 16, 1)))
    total = sum(b['w'] * b['h'] for b in meta['sprites'].values())
    print(f'{len(order)} sprites, {total} px, BC7 {total} bytes -> {a.out}')
    if digits:
        print(f"value digits: widest advance {digits['A']:.3f}, tabular {digits['tabular']}")


if __name__ == '__main__':
    main()
