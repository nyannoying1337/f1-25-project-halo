"""Halo sprite resources: BC7 sRGB surface + SRV view + ui_texture material + material binding (.emb) per sprite.

The binding maps the reused quad mesh's slot "central_bg_fill" to the sprite's own material, so every quad element
in the scene can show its own texture through its geom's materialid.
"""
import hashlib
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.environ.get('SWOFTY_TOOLS', ''))
import bc7  # noqa: E402
import emb  # noqa: E402
import gfx_material as GM  # noqa: E402

FMT_BC7_SRGB = 70
SLOT = 'central_bg_fill'
TEX = 'eaid://ui_package/art/osd/textures/halo/halo_{}.tif'
MAT = 'eaid://ui_package/art/osd/materials/halo/halo_{}.material'
EMB = 'eaid://ui_package/art/osd/components/halo/halo_{}.emb?context=default'


def surface(img, cache_dir):
    h, w = img.shape[:2]
    assert h % 4 == 0 and w % 4 == 0, (w, h)
    key = hashlib.sha1(img.tobytes() + struct.pack('<2I', w, h)).hexdigest()[:20]
    cached = os.path.join(cache_dir, key + '.bc7')
    if os.path.exists(cached):
        pix = open(cached, 'rb').read()
    else:
        pix = bc7.encode(img)
        open(cached, 'wb').write(pix)
    assert len(pix) == w * h
    return struct.pack('<10I', 2, 0x108, FMT_BC7_SRGB, w, h, 1, 1, 1, 0, 0), pix


def srv(tex):
    return struct.pack('<6I', 5, FMT_BC7_SRGB, 0, 1, 0, 0) + (tex + '.image').encode() + b'\0'


def material(stock_bytes, tex):
    m = GM.parse25(stock_bytes)
    for p in m.params:
        if p.name in ('me_colour', 'me_finalColourTint'):
            p.value = struct.pack('<4f', 1, 1, 1, 1)
        elif p.name == 'me_diffuseTexHeapIndex':
            p.link = tex
        elif p.name == 'me_diffuseTex':
            p.value = tex
    out = GM.write25(m)
    back = GM.parse25(out)
    assert back.get('me_diffuseTex').value == tex and back.get('me_diffuseTexHeapIndex').link == tex
    return out


def sprite_resources(sprites, stock_material, cache_dir):
    """sprites: {name: {'img': HxWx4 uint8}}  ->  ([(resource name, type, [fragments])], {name: emb path})"""
    os.makedirs(cache_dir, exist_ok=True)
    res, embs = [], {}
    for name, s in sprites.items():
        tex, mat, eb = TEX.format(name), MAT.format(name), EMB.format(name)
        res.append((tex + '.image', 'GfxSurfaceRes', list(surface(s['img'], cache_dir))))
        res.append((tex, 'GfxSRVResource', [srv(tex)]))
        res.append((mat, 'GfxMaterialRes', [material(stock_material, tex)]))
        res.append((eb, 'GfxMatBindRes', [emb.write([(SLOT, mat)])]))
        embs[name] = eb
    return res, embs


def load_sprites(native_out):
    z = np.load(os.path.join(native_out, 'sprites.npz'))
    return {n: {'img': z[n]} for n in z.files}
