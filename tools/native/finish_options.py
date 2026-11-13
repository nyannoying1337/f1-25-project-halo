"""The last build step: one archive set per element, switched by the element's own option.

Input: the addon built twice from the same sources (build_native, build_tower, build_cards): <tv dir> with today's
halo sprites, <cam dir> with the symmetric set (export_sprites.py --layout cam). This step rewrites <tv dir>/erp:

  always             tower_scene.erp (without the toast scenes), tower_replay.erp, tower_replay_scene.erp,
                     tower_spectator.erp
  halo_on            halo_scene.erp;  with halo_layout = camera also halo_scene_cam.erp, tower_spectator_cam.erp
  rc_banner          banner_scene.erp (the toast's scenes and clip, split out of tower_scene.erp)
                     and the HUD template WITH the banner's static hide nodes (hud_templates_bn.erp);
  rc_banner off      the HUD template without them (hud_templates.erp)
  pit_card           cards_pit.erp
  lap_card           cards_lap.erp, cards_lap2.erp (the lap time scenes)
  rc_banner and pit_banner   cards_banner.erp (the pit speed unit, over banner_scene.erp's)

The HUD template holds every element's nodes; an element that is off has its stock scene, and its nodes then name
elements that are not there. That is only allowed for nodes on parts the element itself adds: this step checks that
no template node of a switchable element drives a stock part (the banner's hide nodes do, hence the two variants).
halo_template.erp, tower_template.erp, halo_spectator*.erp and the unsplit cards archives are removed: every file
they overlaid is overlaid again by an archive above.

usage: python -I finish_options.py <stock folder> <tv addon dir> <cam addon dir>
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tower_native'))
import erpbuild as E  # noqa: E402
import halo_native as H  # noqa: E402
import banner_native as BN  # noqa: E402
from pkg import Pkg  # noqa: E402

N = H.N
RACE = '2025_asset_groups/ui_package/flow_race.erp'
TEMPLATE = 'eaid://ui_package/templates/hud_dynamic_templates.ui'
BANNER_PARTS = ('eaid://ui_package/art/osd/components/message_system/', 'eaid://ui_package/art/osd/units/message_system/',
                'eaid://ui_package/art/osd/components/illegal_overtake/')
PIT_UNIT = 'eaid://ui_package/art/osd/units/message_system/pit_lane_icon'
# the pit speed colour also holds the message scene with the two state fills, their bindings and the two
# fills' texture and material
PIT_PARTS = (PIT_UNIT, 'eaid://ui_package/art/osd/units/message_system/central_message.idf', '/cd_central_message_',
             '/cd_pit_lane_icon_', '/cd_pgreen.', '/cd_pred.')
ELEMENT_OPTIONS = ('halo_on', 'rc_banner', 'pit_card', 'lap_card', 'pit_banner')


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def write(ref, path, res):
    a = E.Archive(ref)
    for name, (typ, frags) in res.items():
        a.add(name, typ, frags)
    a.write(path)
    back = E.read_all(path)
    assert list(back) == list(res) and all(back[n] == (res[n][0], res[n][1]) for n in res), path
    return os.path.getsize(path)


def strip_banner(ui_bytes):
    """the HUD template without the banner's static hide nodes (banner_native.toast_hides) -> (bytes, removed)"""
    p = Pkg(ui_bytes)
    removed = 0
    for scene in BN.RESTYLE:
        for toast in BN.TOASTS:
            g = H._node_at(p.root, f'{toast}.osd_visibility_option.{toast}.{BN.GROUP[scene]}')
            kids = g.items[N.CHILDREN].items
            keep = [k for k in kids if not (N.is_node(k) and N.name(k).startswith(BN.HIDE_NODE))]
            removed += len(kids) - len(keep)
            kids[:] = keep
    out = p.to_bytes()
    assert not any(N.name(n).startswith(BN.HIDE_NODE) for _p, n in H._walk_paths(Pkg(out).root))
    return out, removed


def stock_driving_nodes(ui_bytes, stock_ui_bytes, scenes_added):
    """template nodes of ours (not in the stock template) whose layout's last element is a stock element name, i.e.
    not one of the names the builds added -> [(path, element)]"""
    stock_paths = {p for p, _n in H._walk_paths(Pkg(stock_ui_bytes).root)}
    out = []
    for path, n in H._walk_paths(Pkg(ui_bytes).root):
        if path in stock_paths:
            continue
        for lp in n.items[N.LAYOUT].items:
            if lp.items:
                el = lp.items[-1]['debugName'].value
                if el not in scenes_added:
                    out.append((path, el))
    return out


def main():
    stock, tv, cam = sys.argv[1:4]
    ref = os.path.join(stock, RACE)
    erp = os.path.join(tv, 'erp')
    ops = {o['source']: o for o in json.load(open(os.path.join(erp, 'halo.json'), encoding='utf-8'))['ops']}
    assert not any(k in o.get('when', {}) for o in ops.values() for k in ELEMENT_OPTIONS), 'already finished'
    tg = {k: list(ops[f'erp/{k}.erp']['erps']) for k in ('halo_scene', 'tower_scene', 'tower_replay', 'tower_replay_scene',
                                                        'tower_spectator', 'cards_pit', 'cards_timing', 'cards_timing2',
                                                        'cards_template')}
    # the two builds share everything but the halo's scenes and the spectator templates
    for n in ('halo_template', 'tower_template', 'tower_scene', 'tower_replay', 'tower_replay_scene', 'cards_template',
              'cards_pit', 'cards_timing', 'cards_timing2'):
        assert sha(os.path.join(erp, n + '.erp')) == sha(os.path.join(cam, 'erp', n + '.erp')), f'{n}.erp differs between the layouts'
    out = []     # (file, when, targets)

    # 1. the halo's scenes
    out.append(('halo_scene.erp', {'halo_on': True}, tg['halo_scene']))
    for n in ('halo_scene', 'tower_spectator'):
        src = os.path.join(cam, 'erp', n + '.erp')
        assert sha(src) != sha(os.path.join(erp, n + '.erp')), n
        open(os.path.join(erp, n + '_cam.erp'), 'wb').write(open(src, 'rb').read())
    out.append(('halo_scene_cam.erp', {'halo_on': True, 'halo_layout': 'camera'}, tg['halo_scene']))

    # 2. the tower's scenes without the toast; the toast's scenes on their own
    ts = E.read_all(os.path.join(erp, 'tower_scene.erp'))
    banner = {n: v for n, v in ts.items() if n.startswith(BANNER_PARTS)}
    rest = {n: v for n, v in ts.items() if n not in banner}
    assert set(BN.SCENES) <= set(banner) and BN.RC_TEXT_CLIP in banner, 'the toast scenes'
    assert not any('message_system' in n or 'illegal_overtake' in n for n in rest)
    sizes = {'tower_scene.erp': write(ref, os.path.join(erp, 'tower_scene.erp'), rest),
             'banner_scene.erp': write(ref, os.path.join(erp, 'banner_scene.erp'), banner)}
    out.append(('tower_scene.erp', None, tg['tower_scene']))
    out.append(('banner_scene.erp', {'rc_banner': True}, tg['tower_scene']))

    # 3. the HUD template: with the banner's hide nodes, and without
    full = E.read_all(os.path.join(erp, 'cards_template.erp'))
    assert list(full) == [TEMPLATE]
    stock_ui = E.read_all(ref)[TEMPLATE][1][0]
    plain, removed = strip_banner(full[TEMPLATE][1][0])
    bn_nodes = sum(len(h) for _f, h in BN.RESTYLE.values()) * len(BN.TOASTS)
    assert removed == bn_nodes, (removed, bn_nodes)
    os.replace(os.path.join(erp, 'cards_template.erp'), os.path.join(erp, 'hud_templates_bn.erp'))
    sizes['hud_templates.erp'] = write(ref, os.path.join(erp, 'hud_templates.erp'), {TEMPLATE: (full[TEMPLATE][0], [plain])})
    out.append(('hud_templates.erp', {'rc_banner': False}, tg['cards_template']))
    out.append(('hud_templates_bn.erp', {'rc_banner': True}, tg['cards_template']))
    # no node of a switchable element drives a stock part in the plain template: every node of ours either sits on an
    # element the builds added, or belongs to the tower (live switch, its scenes always applied) or to the 2025 / F2
    # dials' stock parts (shown whenever the halo's leaf is off)
    added = set()
    for f in ('halo_scene.erp', 'tower_scene.erp', 'banner_scene.erp', 'cards_pit.erp', 'cards_timing.erp', 'cards_timing2.erp'):
        for name, (typ, frags) in E.read_all(os.path.join(erp, f)).items():
            if typ == 'UILayout':
                import idf as I
                added |= {I._val(e.obj.get('name')) for e, _ in I.Idf(frags[0]).scenes[0].root.walk()}
    stock_names = set()
    stock_all = E.read_all(ref)
    for name, (typ, frags) in stock_all.items():
        if typ == 'UILayout' and (name in ts or any(name in E.read_all(os.path.join(erp, f))
                                                     for f in ('halo_scene.erp', 'cards_pit.erp', 'cards_timing.erp', 'cards_timing2.erp'))):
            import idf as I
            stock_names |= {I._val(e.obj.get('name')) for e, _ in I.Idf(frags[0]).scenes[0].root.walk()}
    ours_only = added - stock_names
    drives = [(p, el) for p, el in stock_driving_nodes(plain, stock_ui, ours_only)]
    allowed = ('.halo_ctl', '.halo_pv_ctl', '.tt_', 'tt_ctl', '.v_tp_', '.tp_')
    left = [(p, el) for p, el in drives if not any(a in p for a in allowed)]
    json.dump({'nodes_on_stock_elements': len(drives), 'not_tower_or_dial': left[:200]},
              open(os.path.normpath(tv) + '_options.json', 'w'), indent=1)

    # 4. the cards: the pit card as built; the lap card's scenes; the pit speed unit on its own
    ct = E.read_all(os.path.join(erp, 'cards_timing.erp'))
    unit = {n: v for n, v in ct.items() if n.startswith(PIT_PARTS[:2]) or any(k in n for k in PIT_PARTS[2:])}
    lap = {n: v for n, v in ct.items() if n not in unit}
    assert unit and lap and PIT_PARTS[1] in unit and any('/cd_pgreen.' in n for n in unit) and any('/cd_pred.' in n for n in unit)
    assert not any('central_message' in n or 'pit_lane_icon' in n or 'cd_pgreen' in n or 'cd_pred' in n for n in lap)
    assert PIT_UNIT + '.idf' in banner and PIT_UNIT + '.idf' in unit, 'the pit speed unit: the scene the banner build also holds'
    sizes['cards_lap.erp'] = write(ref, os.path.join(erp, 'cards_lap.erp'), lap)
    sizes['cards_banner.erp'] = write(ref, os.path.join(erp, 'cards_banner.erp'), unit)
    os.replace(os.path.join(erp, 'cards_timing2.erp'), os.path.join(erp, 'cards_lap2.erp'))
    out.append(('cards_pit.erp', {'pit_card': True}, tg['cards_pit']))
    out.append(('cards_lap.erp', {'lap_card': True}, tg['cards_timing']))
    out.append(('cards_lap2.erp', {'lap_card': True}, tg['cards_timing2']))
    out.append(('cards_banner.erp', {'rc_banner': True, 'pit_banner': True}, tg['cards_timing']))

    # 5. replay and spectator
    out.append(('tower_replay.erp', None, tg['tower_replay']))
    out.append(('tower_replay_scene.erp', None, tg['tower_replay_scene']))
    out.append(('tower_spectator.erp', None, tg['tower_spectator']))
    out.append(('tower_spectator_cam.erp', {'halo_on': True, 'halo_layout': 'camera'}, tg['tower_spectator']))

    for f in ('halo_template.erp', 'tower_template.erp', 'halo_spectator.erp', 'halo_spectator_cam.erp', 'cards_timing.erp'):
        fp = os.path.join(erp, f)
        if os.path.exists(fp):
            os.remove(fp)
    final = []
    for f, when, targets in out:
        o = {'op': 'overlay'}
        if when:
            o['when'] = when
        o.update(erps=targets, source='erp/' + f)
        final.append(o)
    json.dump({'schema_version': 1, 'ops': final}, open(os.path.join(erp, 'halo.json'), 'w', encoding='utf-8'), indent=2)
    have = sorted(f for f in os.listdir(erp) if f.endswith('.erp'))
    assert have == sorted(f for f, _w, _t in out), (have, [f for f, _w, _t in out])
    # the manifest declares every option the ops name
    man = json.load(open(os.path.join(tv, 'swofty.json'), encoding='utf-8'))
    opts = {o['id']: o for o in man['options']}
    for o in final:
        for k, v in o.get('when', {}).items():
            assert k in opts and opts[k]['binds'] == 'db', ('option', k)
            assert (opts[k]['type'] == 'toggle' and isinstance(v, bool)) or v in [x['value'] for x in opts[k]['values']], (k, v)
    print(f'{len(final)} ops, {len(have)} archives; template: {removed} banner hide nodes only in hud_templates_bn.erp; '
          f'{len(drives)} of our nodes sit on stock elements, {len(left)} outside the tower and the dials')
    for f, when, targets in out:
        print(f'  {f:26s} {os.path.getsize(os.path.join(erp, f)):>8}  {sha(os.path.join(erp, f))[:8]}  '
              f'{json.dumps(when) if when else "always":52s} {len(targets)} game archives')


if __name__ == '__main__':
    main()
