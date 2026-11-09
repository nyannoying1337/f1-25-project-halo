"""Build the game-native halo HUD archives for the addon.

usage: python -I build_native.py <F1 25 folder> <native_out dir> <addon dir> <work dir>

Writes <addon>/erp/halo_scene.erp (for the 4 archives that carry the dial scenes: dial_om_xm with the halo, its clips,
string table, textures, materials, bindings; dial_complete with the HUD editor's static halo copy and its .uipre),
<addon>/erp/halo_template.erp (hud_dynamic_templates.ui: flow_race and flow_options), <addon>/erp/halo_spectator.erp
(hud_spectator_2.ui: flow_race and screens/hud_spectator_2) and <addon>/erp/halo.json (the overlay ops). Stock inputs
are read straight from the given folder's archives: pass a folder of stock copies, not a game folder Swofty has built.
"""
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from compression import zstd  # noqa: E402
from erpmeta import index  # noqa: E402
import erpbuild as E  # noqa: E402
import halo_native as H  # noqa: E402
import resources as R  # noqa: E402

UI = '2025_asset_groups/ui_package/'
SCENE_ERPS = [UI + 'flow_race.erp', UI + 'flow_options.erp', UI + 'persistent.erp', UI + 'screens/hud_spectator_2.erp']
TEMPLATE_ERPS = [UI + 'flow_race.erp', UI + 'flow_options.erp']
SPECTATOR_ERPS = [UI + 'flow_race.erp', UI + 'screens/hud_spectator_2.erp']
TEMPLATE = 'eaid://ui_package/templates/hud_dynamic_templates.ui'
SPECTATOR = 'eaid://ui_package/screens/hud_spectator_2.ui'
MODS = 'eaid://ui_package/art/osd/components/dial/dial_mods.idf'
BAR = 'eaid://ui_package/art/osd/components/dial/dial_om_bar_complete.idf'
MAT = 'eaid://ui_package/art/osd/materials/dial/dial_frame/dial_central_bg_fill.material'
CLIP_TMPL = MODS + '/mod_1_icon_fill_mask_anim?context=animation'


def read(archive, names):
    hdr, res = index(archive)
    doff = struct.unpack_from('<QQQ', hdr, 0x10)[2]
    want = {r[0]: r for r in res if r[0] in names}
    out = {}
    with open(archive, 'rb') as f:
        for n in names:
            if n not in want:
                raise KeyError(f'{archive}: no {n}')
            frs = []
            for fn, off, size, flags, comp, packed in want[n][3]:
                f.seek(doff + off)
                raw = f.read(packed)
                frs.append(zstd.decompress(raw) if comp == E.ZSTD else raw)
            out[n] = frs
    return out


def tinted(img, hexcol):
    """A white sprite in one colour, alpha kept: what the template's colourOverride makes of it in game."""
    col = np.array([int(hexcol[i:i + 2], 16) for i in (1, 3, 5)], np.uint32)
    out = img.copy()
    out[..., :3] = (img[..., :3].astype(np.uint32) * col // 255).astype(np.uint8)
    return out


def main():
    game, native_out, addon, work = sys.argv[1:5]
    os.makedirs(work, exist_ok=True)
    meta = json.load(open(os.path.join(native_out, 'sprites.json')))
    sprites = R.load_sprites(native_out)
    sprites['solid_white'] = {'img': np.full((16, 16, 4), 255, np.uint8)}
    sprites['solid_core'] = {'img': np.tile(np.array([225, 255, 250, 140], np.uint8), (16, 16, 1))}
    for base, pv in H.PREVIEW_SPRITES.items():   # the editor preview's team colour (no template tints it there)
        sprites[pv] = {'img': tinted(sprites[base]['img'], H.PREVIEW_TEAM)}
    geo = H.Geo(meta)

    race = os.path.join(game, SCENE_ERPS[0])
    scenes = [H.SCENE, H.STRTAB, H.PREVIEW_SCENE, H.PREVIEW_UIPRE]
    stock = read(race, scenes + [TEMPLATE, SPECTATOR, MODS, BAR, MAT, CLIP_TMPL])
    for a in SCENE_ERPS[1:]:
        other = read(os.path.join(game, a), scenes)
        for n in scenes:
            assert other[n] == stock[n], f'{a} carries a different {n}'
    assert read(os.path.join(game, TEMPLATE_ERPS[1]), [TEMPLATE])[TEMPLATE] == stock[TEMPLATE]
    assert read(os.path.join(game, SPECTATOR_ERPS[1]), [SPECTATOR])[SPECTATOR] == stock[SPECTATOR]
    assert len(stock[H.PREVIEW_SCENE]) == len(stock[H.PREVIEW_UIPRE]) == len(stock[SPECTATOR]) == 1

    res, embs = R.sprite_resources(sprites, stock[MAT][0], os.path.join(work, 'bc7_cache'))
    tex = {n: R.TEX.format(n) for n in sprites}
    scene, info = H.build_scene(stock[H.SCENE][0], stock[MODS][0], stock[BAR][0], geo, embs, tex)
    strtab, clips = H.build_clips(stock[CLIP_TMPL][0], stock[H.STRTAB][0], info)
    template, nnodes = H.build_template(stock[TEMPLATE][0], info)
    preview, pinfo = H.build_preview(stock[H.PREVIEW_SCENE][0], stock[MODS][0], stock[BAR][0], geo, embs, tex)
    uipre, nset = H.build_preview_uipre(stock[H.PREVIEW_UIPRE][0], pinfo['texts'])
    template, npv1 = H.add_preview_control(template, H.PREVIEW_PARENTS['hud_f1_dial'])
    spectator, npv2 = H.add_preview_control(stock[SPECTATOR][0], H.PREVIEW_PARENTS['hud_spectator_2'])

    os.makedirs(os.path.join(addon, 'erp'), exist_ok=True)
    a = E.Archive(race)
    a.add(H.SCENE, 'UILayout', [scene])
    a.add(H.STRTAB, 'ACStringTable', [strtab])
    for nm, (temp, syst) in clips.items():
        a.add(f'{H.SCENE}/{nm}?context=animation', 'AnimClip', [temp, syst])
    a.add(H.PREVIEW_SCENE, 'UILayout', [preview])
    a.add(H.PREVIEW_UIPRE, 'UIPR', [uipre])
    for n, t, fr in res:
        a.add(n, t, fr)
    scene_erp = os.path.join(addon, 'erp', 'halo_scene.erp')
    size1 = a.write(scene_erp)
    b = E.Archive(race)
    b.add(TEMPLATE, 'UIDF', [template])
    tmpl_erp = os.path.join(addon, 'erp', 'halo_template.erp')
    size2 = b.write(tmpl_erp)
    c = E.Archive(race)
    c.add(SPECTATOR, 'UIDF', [spectator])
    spec_erp = os.path.join(addon, 'erp', 'halo_spectator.erp')
    size3 = c.write(spec_erp)
    ops = {'schema_version': 1, 'ops': [
        {'op': 'overlay', 'erps': SCENE_ERPS, 'source': 'erp/halo_scene.erp'},
        {'op': 'overlay', 'erps': TEMPLATE_ERPS, 'source': 'erp/halo_template.erp'},
        {'op': 'overlay', 'erps': SPECTATOR_ERPS, 'source': 'erp/halo_spectator.erp'},
    ]}
    json.dump(ops, open(os.path.join(addon, 'erp', 'halo.json'), 'w'), indent=2)

    # read everything back
    back = E.read_all(scene_erp)
    assert back[H.SCENE][1][0] == scene and back[H.PREVIEW_SCENE][1][0] == preview and back[H.PREVIEW_UIPRE][1][0] == uipre
    assert len(back) == len(a.res)
    assert E.read_all(tmpl_erp)[TEMPLATE][1][0] == template
    assert E.read_all(spec_erp)[SPECTATOR][1][0] == spectator
    for name, data in (('dial_om_xm.idf', scene), ('hud_dynamic_templates.ui', template), ('dial_complete.idf', preview),
                       ('dial_complete.uipre', uipre), ('hud_spectator_2.ui', spectator)):
        open(os.path.join(work, name), 'wb').write(data)
    json.dump({k: v for k, v in info.items() if k != 'rpm_static'}, open(os.path.join(work, 'info.json'), 'w'), indent=1)
    json.dump({'texts': pinfo['texts'], 'state': {k: v for k, v in H.PREVIEW.items()}, 'team': H.PREVIEW_TEAM,
               'sprites': H.PREVIEW_SPRITES}, open(os.path.join(work, 'preview.json'), 'w'), indent=1)
    print(f'scene {len(stock[H.SCENE][0])} -> {len(scene)} bytes, {info["n_new"]} new elements')
    print(f'template {len(stock[TEMPLATE][0])} -> {len(template)} bytes, {nnodes} halo nodes + {npv1} preview control nodes')
    print(f'clips {len(clips)}, string table {len(stock[H.STRTAB][0])} -> {len(strtab)}')
    print(f'editor preview: dial_complete {len(stock[H.PREVIEW_SCENE][0])} -> {len(preview)} bytes, {pinfo["n_new"]} new '
          f'elements; uipre {len(stock[H.PREVIEW_UIPRE][0])} -> {len(uipre)} bytes, {nset} new setters')
    print(f'spectator {len(stock[SPECTATOR][0])} -> {len(spectator)} bytes, {npv2} preview control nodes')
    print(f'{scene_erp}: {len(a.res)} resources, {size1} bytes')
    print(f'{tmpl_erp}: {size2} bytes')
    print(f'{spec_erp}: {size3} bytes')


if __name__ == '__main__':
    main()
