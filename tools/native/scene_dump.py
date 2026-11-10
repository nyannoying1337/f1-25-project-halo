"""Dump the built scene's halo subtree (and the tl/br box) as JSON for the browser simulator.

usage: python -I scene_dump.py <built dial_om_xm.idf> <info.json> <out.json>
       python -I scene_dump.py <built dial_complete.idf> <preview.json> <out.json> halo_pv   (the HUD editor preview)
       python -I scene_dump.py <built dial_complete.idf> <info_2025.json> <out.json> h25     (2025 cars; F2: hf2)
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.environ.get('SWOFTY_TOOLS', ''))
from idf import Idf, get_param  # noqa: E402


def zangle(q):
    x, y, z, w = q
    return math.degrees(2 * math.atan2(z, w))


def node(e):
    o = e.obj
    t = e.type
    d = {'name': e.name, 'type': t, 'pos': list(o['position'].value[:3]), 'scale': list(o['scale'].value[:3]),
         'rot': list(o['rotation'].value), 'kids': [node(c) for c in e.children]}
    if get_param(o, 'isHidden') is True:   # hidden in the scene: only a template's bound visible shows it
        d['hidden'] = True
    if t == 'eNull' and e.geoms:
        mat = e.geoms[0]['materialid']
        d['type'] = 'quad'
        d['sprite'] = mat.rsplit('/halo_', 1)[1].split('.emb')[0] if '/halo_' in mat else None
        # the cloned quad's mesh size (its extents, x and z: the quad is turned): 4.48 x 1.92 in dial_om_xm and
        # dial_complete, 3.4 x 1.68 for the F2 dial's edge quad
        lo, hi = get_param(o, 'minExtents'), get_param(o, 'maxExtents')
        d['mw'], d['mh'] = (hi[0] - lo[0], hi[2] - lo[2]) if lo and hi else (4.48, 1.92)
        d['w'], d['h'] = d['mw'] * d['scale'][0], d['mh'] * d['scale'][2]
        d['layer'] = get_param(o, 'eLayer.layer')
    elif t == 'eNull':
        d['zrot'] = zangle(d['rot'])
    elif t == 'eWindow':
        d['w'], d['h'] = get_param(o, 'width'), get_param(o, 'length')
    elif t == 'eMaskTexture':
        d['w'], d['h'] = get_param(o, 'width'), get_param(o, 'height')
        d['sprite'] = get_param(o, 'eMaskTexture.maskTextureResource').rsplit('/halo_', 1)[1].split('.tif')[0]
    elif t == 'eText':
        d.update(style=get_param(o, 'style'), halign=get_param(o, 'halign'), box=get_param(o, 'boxWidth'),
                 layer=get_param(o, 'eLayer.layer'), wrapping=get_param(o, 'wrapping'))
    return d


def main():
    idf = Idf.load(sys.argv[1])
    info = json.load(open(sys.argv[2]))
    root = idf.scenes[0].root
    top = sys.argv[4] if len(sys.argv) > 4 else 'halo'
    halo = None
    for e, _ in root.walk():
        if e.name == top:
            halo = e
            break
    box = {}
    for e, _ in root.walk():
        if e.name in ('tl_customisation', 'br_customisation'):
            box[e.name] = list(e.obj['position'].value[:2])
    out = {'halo': node(halo), 'box': box, 'info': info}
    json.dump(out, open(sys.argv[3], 'w'))
    n = sum(1 for _ in halo.walk())
    print('halo subtree', n, 'elements; box', box)


if __name__ == '__main__':
    main()
