"""Timing tower textures: BC7 sRGB surface + SRV + ui_texture material + material binding (.emb) per sprite, plus a
material + binding for each game texture the tower shows (F1 logo, FIA badge). Same mechanism as the halo
(tools/native/resources.py), but the binding maps the bottom cap's own quad mesh slot "pill_base", the mesh every
tower quad reuses. Game textures are never copied: their materials name the game's own texture paths.
"""
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
NATIVE = os.path.join(os.path.dirname(HERE), 'native')
sys.path.insert(0, NATIVE)
import emb  # noqa: E402

SLOT = 'pill_base'
TEX = 'eaid://ui_package/art/osd/textures/tower/tt_{}.tif'
MAT = 'eaid://ui_package/art/osd/materials/tower/tt_{}.material'
EMB = 'eaid://ui_package/art/osd/components/tower/tt_{}.emb?context=default'
# the game's own textures (present in flow_race, flow_options and persistent; build_tower.py checks)
GAME_TEX = {'g_f1': 'eaid://ui_package/art/osd/textures/lap_counter/osd_customisation/lc_f1_logo.tif',
            'g_fia': 'eaid://ui_package/art/osd/textures/message_system/ms_fia_logo.tif',
            'g_fia_k': 'eaid://ui_package/art/osd/textures/message_system/ms_fia_logo.tif'}
# A tinted copy: the material's me_colour multiplies the texture (the game tints its own textured materials the same
# way, e.g. dial_drs_glow, harv_radial_fill). g_fia_k is the FIA badge on the yellow SC / VSC boxes, black like their
# text (tower.js drawStatus, F1 TV frame "sc"): the game's white badge was hard to read on yellow (in game 2026-11-09).
GAME_TINT = {'g_fia_k': (0.0, 0.0, 0.0, 1.0)}


def tint(material_bytes, rgba):
    """a material with its me_colour set to rgba (every other parameter unchanged)"""
    import struct
    import resources as R
    m = R.GM.parse25(material_bytes)
    hits = [p for p in m.params if p.name == 'me_colour']
    assert len(hits) == 1, 'me_colour'
    hits[0].value = struct.pack('<4f', *rgba)
    out = R.GM.write25(m)
    assert R.GM.parse25(out).get('me_colour').value == struct.pack('<4f', *rgba)
    return out


def css_rgba(c):
    """'#RRGGBB', 'rgba(r,g,b,a)' or [r, g, b] -> (r, g, b, a) bytes"""
    if isinstance(c, (list, tuple)):
        return (int(c[0]), int(c[1]), int(c[2]), 255 if len(c) < 4 else int(round(c[3] * 255)))
    c = c.strip()
    if c.startswith('#'):
        return (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16), 255)
    m = re.match(r'rgba?\(([^)]*)\)', c)
    v = [float(x) for x in m.group(1).split(',')]
    return (int(round(v[0])), int(round(v[1])), int(round(v[2])), int(round((v[3] if len(v) > 3 else 1.0) * 255)))


def solid_colours(P):
    """The flat fills of tower.js (palette P from the export): name -> (r, g, b, a)."""
    panel = tuple(P['panel'])
    strip = css_rgba(P['strip'])
    return {
        'strip': strip,                                           # position strip, opaque
        'panel': panel + (int(round(P['panelAlpha'] * 255)),),    # row panel, 81 %
        'sep': css_rgba(P['stripSep']),                           # strip separator line
        'p1': css_rgba(P['red']),                                 # P1 position box
        'me': css_rgba(P['me']),                                  # player highlight, +10 % white
        'na': css_rgba(P['na']),                                  # "unavailable" bar (design state g)
        # retired rows: tower.js draws their texts at 50 %. The game cannot fade a text per row, so a half-opaque
        # layer in the row's own colours goes over the row (strip and panel parts): texts read at about 50 %.
        'dims': strip[:3] + (128,),
        'dimp': panel + (128,),
        # team-colour bar (round 4): white, so the template's colourOverride (the game's nub_colour) is the colour, as
        # the halo's solid_white
        'bar': (255, 255, 255, 255),
    }


# The knockout hatch: "/" stripes over the position strip, measured on the reference (measurements.md,
# knockout hatch): 49.5 degrees from horizontal, period 0.072 p across the stripes, light #4A242C / dark #1F0001, about
# half each. Drawn here (no art copied): the cell's aspect (strip x p), 4 x 4 samples per pixel, opaque.
HATCH = {'angle': 49.5, 'period_p': 0.072, 'light': (0x4A, 0x24, 0x2C), 'dark': (0x1F, 0x00, 0x01), 'h': 128}


def hatch_image(G):
    """the knockout hatch sprite for the position strip (G: the export's geometry) -> HxWx4 uint8"""
    import math
    p, w_u = G['p'], G['strip']
    h = HATCH['h']
    w = int(round(h * w_u / p / 4.0)) * 4                       # the cell's aspect, a multiple of 4 pixels
    a = math.radians(HATCH['angle'])
    period = HATCH['period_p'] * p                              # HUD units across the stripes
    k = 4
    xs = (np.arange(w * k) + 0.5) / (w * k) * w_u               # sample centres in HUD units, x right
    ys = (np.arange(h * k) + 0.5) / (h * k) * p                 # y down (image rows: row 0 is the top in game)
    s = xs[None, :] * math.sin(a) + ys[:, None] * math.cos(a)  # constant along a "/" line
    light = (np.mod(s / period, 1.0) < 0.5).astype(np.float64)
    cov = light.reshape(h, k, w, k).mean(axis=(1, 3))
    lo, hi = np.array(HATCH['dark'], np.float64), np.array(HATCH['light'], np.float64)
    rgb = lo[None, None, :] + cov[:, :, None] * (hi - lo)[None, None, :]
    img = np.empty((h, w, 4), np.uint8)
    img[..., :3] = np.clip(np.round(rgb), 0, 255).astype(np.uint8)
    img[..., 3] = 255
    return img


def fastest_lap_image(purple, box):
    """the race's fastest lap side box: a purple box with a white stopwatch, drawn (no art copied), the size
    of the other side boxes (box: the export's pen sprite, its pixel w, h) -> HxWx4 uint8"""
    import math
    w, h, k = int(box['w']), int(box['h']), 4
    u = h / 36.0                                                 # drawn on the 28 x 36 box
    X, Y = np.meshgrid((np.arange(w * k) + 0.5) / k / u, (np.arange(h * k) + 0.5) / k / u)
    cx, cy, ro, ri = w / u / 2.0, 20.5, 8.4, 6.5
    d = np.hypot(X - cx, Y - cy)
    m = (d <= ro) & (d >= ri)                                    # the ring
    m |= (np.abs(X - cx) <= 2.1) & (Y >= 7.4) & (Y <= 9.5)       # the crown
    m |= (np.abs(X - cx) <= 0.85) & (Y >= 9.5) & (Y <= cy - ro + 0.6)
    a = math.radians(45.0)                                       # the side button
    bx, by = cx + (ro + 1.1) * math.sin(a), cy - (ro + 1.1) * math.cos(a)
    m |= np.hypot(X - bx, Y - by) <= 1.25
    a = math.radians(35.0)                                       # the hand, towards one o'clock
    ux, uy = math.sin(a), -math.cos(a)
    t = (X - cx) * ux + (Y - cy) * uy
    m |= (t >= -0.5) & (t <= 4.9) & (np.abs((X - cx) * uy - (Y - cy) * ux) <= 0.9)
    m |= d <= 1.4                                                # the hub
    cov = m.astype(np.float64).reshape(h, k, w, k).mean(axis=(1, 3))
    lo, hi = np.array(purple, np.float64), np.array((255.0, 255.0, 255.0))
    img = np.empty((h, w, 4), np.uint8)
    img[..., :3] = np.clip(np.round(lo[None, None, :] + cov[:, :, None] * (hi - lo)[None, None, :]), 0, 255)
    img[..., 3] = 255
    return img


def solid_images(P):
    return {name: {'img': np.tile(np.array(c, np.uint8), (16, 16, 1))} for name, c in solid_colours(P).items()}


BANNER_EMB = EMB.format('banner')


def banner_resources(slots, sprite='bn_m'):
    """The Race Control banner's one material binding: every toast fill mesh slot -> the bn_m sprite's material
    (made by tower_resources, so bn_m must be among the sprites)."""
    return [(BANNER_EMB, 'GfxMatBindRes', [emb.write([(s, MAT.format(sprite)) for s in slots])])]


def tower_resources(sprites, stock_material, cache_dir):
    """sprites: {name: {'img': HxWx4}} -> ([(resource name, type, [fragments])], {name: emb path}).
    Every GAME_TEX key also gets a material + binding (no surface: the game has the texture)."""
    import resources as R  # needs SWOFTY_TOOLS; imported here so tower_sim.py runs without it
    os.makedirs(cache_dir, exist_ok=True)
    res, embs = [], {}
    for name, s in sprites.items():
        tex, mat, eb = TEX.format(name), MAT.format(name), EMB.format(name)
        res.append((tex + '.image', 'GfxSurfaceRes', list(R.surface(s['img'], cache_dir))))
        res.append((tex, 'GfxSRVResource', [R.srv(tex)]))
        res.append((mat, 'GfxMaterialRes', [R.material(stock_material, tex)]))
        res.append((eb, 'GfxMatBindRes', [emb.write([(SLOT, mat)])]))
        embs[name] = eb
    for key, tex in GAME_TEX.items():
        mat, eb = MAT.format(key), EMB.format(key)
        m = R.material(stock_material, tex)
        res.append((mat, 'GfxMaterialRes', [tint(m, GAME_TINT[key]) if key in GAME_TINT else m]))
        res.append((eb, 'GfxMatBindRes', [emb.write([(SLOT, mat)])]))
        embs[key] = eb
    return res, embs
