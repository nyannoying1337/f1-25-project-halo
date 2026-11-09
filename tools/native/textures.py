"""Load export_native.html's output: sprites as straight-alpha RGBA arrays with edge colours bled into the
transparent pixels (so bilinear sampling has no dark fringes), plus the halo.js geometry.

usage: python -I textures.py <dom.html> <out dir>     (writes sprites.npz, sprites.json and PNG previews)
"""
import base64
import html
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pngio  # noqa: E402


def bleed(img, rounds=12):
    rgb, known = img[..., :3].astype(np.float32), img[..., 3] > 0
    for _ in range(rounds):
        if known.all():
            break
        acc, cnt = np.zeros_like(rgb), np.zeros(known.shape, np.float32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx or dy:
                    k = np.roll(np.roll(known, dy, 0), dx, 1)
                    acc += np.roll(np.roll(rgb, dy, 0), dx, 1) * k[..., None]
                    cnt += k
        new = ~known & (cnt > 0)
        rgb[new] = acc[new] / cnt[new][:, None]
        known |= new
    out = img.copy()
    out[..., :3] = np.clip(np.round(rgb), 0, 255).astype(np.uint8)
    return out


def load(dom):
    text = open(dom, encoding='utf-8').read()
    m = re.search(r'<pre id="out">(.*?)</pre>', text, re.S)
    payload = html.unescape(m.group(1))
    if payload.startswith('ERROR'):
        raise SystemExit(payload)
    data = json.loads(payload)
    sprites = {}
    for s in data['sprites']:
        raw = np.frombuffer(base64.b64decode(s['rgba']), np.uint8).reshape(s['h'], s['w'], 4)
        sprites[s['name']] = dict(img=bleed(raw.copy()), x0=s['x0'], y0=s['y0'], x1=s['x1'], y1=s['y1'], w=s['w'], h=s['h'])
    return data, sprites


def main():
    dom, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    data, sprites = load(dom)
    meta = {k: v for k, v in data.items() if k != 'sprites'}
    meta['sprites'] = {n: {k: v for k, v in s.items() if k != 'img'} for n, s in sprites.items()}
    json.dump(meta, open(os.path.join(out, 'sprites.json'), 'w'), indent=1)
    np.savez_compressed(os.path.join(out, 'sprites.npz'), **{n: s['img'] for n, s in sprites.items()})
    os.makedirs(os.path.join(out, 'png'), exist_ok=True)
    for n, s in sprites.items():
        pngio.write_png(os.path.join(out, 'png', n + '.png'), s['img'])
    total = sum(s['w'] * s['h'] for s in sprites.values())
    for n, s in sprites.items():
        print(f"{n:12s} {s['w']:5d}x{s['h']:<4d}  ({s['x0']:8.2f},{s['y0']:7.2f})-({s['x1']:8.2f},{s['y1']:7.2f})")
    print(f'{len(sprites)} sprites, {total} px, BC7 {total} bytes')


if __name__ == '__main__':
    main()
