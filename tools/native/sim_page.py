"""Write the simulator page for the built scene with a few driving states, or (for a scene_dump of dial_complete's
halo_pv with build_native's preview.json) the HUD editor preview: every element of the static copy, its .uipre texts.
usage: python -I sim_page.py <scene.json> <png dir> <halo dir> <out.html> [--gmeter]
"""
import json
import math
import sys


def leaves(st):
    L = {'live': True, 'spd': True, 'pedals': True, 'nm': True, 'kmh': str(round(st['kmh'])), 'mph': str(round(st['kmh'] * 0.621371)), 'drv': st['drv'], 'riv': st['riv'],
         'turn': st['turn'] is not None, 'tnum': str(st['turn'] or ''), 'tl': st['turn'] is not None and st['dir'] == 'L',
         'tr': st['turn'] is not None and st['dir'] == 'R', 'boost': st['boost'], 'ot': st['ot'], 'chg': st['chg'],
         'aero_s': st['straight'], 'aero_t': st['tint'], 'aero_et': st['straight'] and st['tint'], 'aero_ew': st['straight'] and not st['tint']}
    rc, dp = round(st['recharge'] * 16), round(st['deploy'] * 16)
    br, th = round(st['brake'] * 10), round(st['throttle'] * 10)   # leaves.hpp kStripes = 10, kCapLevels = 16
    for i in range(1, 17):
        L[f'rc{i:02d}'] = rc == i
        L[f'dp{i:02d}'] = dp == i
    for i in range(1, 11):
        L[f'br{i:02d}'] = br >= i
        L[f'th{i:02d}'] = th >= i
    for i in range(9):
        L[f'g{i}'] = st['gear'] == i
    # game-side values the template binds directly (the game computes these; the sim stands in for it)
    L['om_active'] = st['ot']
    L['is_xm_active'] = st['straight']
    pos, name = st['drv'].split()
    L['#session.current_car.position'] = pos
    L['#session.current_car.driver.second_name'] = name
    rpos, rname = st['riv'].split()
    rv = 5                                   # the rival's vehicle id, chosen by the DLL from the classification
    L[f'rv{rv:02d}'] = True
    L[f'#session.cars.car{rv}.position'] = rpos
    L[f'#session.cars.car{rv}.driver.second_name'] = rname
    if 'g' in st:
        L.update(gmeter(st['g'], st.get('gdir', 0.0), st.get('gred', False)))
    return L


def gmeter(m, d, red):
    """The G-force meter's leaves (native/src/leaves.hpp publish_gmeter, gmeter.cpp) for force m (g; None = no reading)
    at direction d (degrees, felt force: 0 right, 90 down, 180 left, 270 up). Wide from 2.0 g (no hysteresis here)."""
    L = {'gm': True, 'gok': m is not None, 'gred': m is not None and red}
    tenths = max(0, min(99, math.floor(m * 10 + 0.5))) if m is not None else -1
    for x in range(10):
        L[f'gu{x}'] = m is not None and tenths // 10 == x
        L[f'gt{x}'] = m is not None and tenths % 10 == x
    ind = m is not None and m >= 0.3
    wide = ind and m >= 2.0
    k = math.floor(d / 45 + 0.5) - 1 if wide else math.floor(d / 45)
    segs = {(k + i) % 8 for i in range(3 if wide else 2)}
    axis = math.floor(d / 90 + 0.5) % 4
    for x in range(8):
        L[f'gs{x}'] = ind and x in segs
    for a in range(4):
        L[f'gw{a}'] = ind and axis == a
        L[f'gr{a}'] = ind and m >= 2.3 and axis == a
    return L


STATES = [
    dict(title='Flat out on a straight: 8th, Boost + Overtake, Active Aero straight mode', team='#E8002D',
         kmh=312, gear=8, revs=0.93, ers=0.55, throttle=1.0, brake=0.0, recharge=0.0, deploy=0.8, boost=True, ot=True, chg=False,
         straight=True, tint=True, drv='4  HAMILTON', riv='3  LECLERC', turn=None, dir=None),
    dict(title='Braking for turn 4 (left): 3rd, recharging', team='#FF8000',
         kmh=96, gear=3, revs=0.55, ers=0.72, throttle=0.0, brake=0.85, recharge=0.9, deploy=0.0, boost=False, ot=False, chg=True,
         straight=False, tint=True, drv='1  NORRIS', riv='2  PIASTRI', turn=4, dir='L'),
    dict(title='Other game build (memory reader off): the game\'s own speed, revs and battery only', team='#27F4D2', native_only=True,
         kmh=187, gear=5, revs=0.5, ers=0.4),
]
# the same frames with the G-force meter on (setting g_meter): force g at gdir degrees (felt force), gred = the flash
_BRAKE = dict(STATES[1], kmh=288, gear=7, revs=0.86, brake=1.0, turn=1, dir='R')
GSTATES = [
    dict(_BRAKE, title='G-force meter: braking at 4.6 g (pushed forward), the first reading over 4.3 g flashes red',
         g=4.6, gdir=270.0, gred=True),
    dict(STATES[0], title='G-force meter: 2.96 g in a fast right-hander on the throttle (pushed left and back)',
         kmh=244, gear=7, revs=0.8, straight=False, g=2.96, gdir=168.3),
    dict(STATES[0], title='G-force meter: 0.8 g accelerating out of a left-hander', kmh=141, gear=4, revs=0.7,
         straight=False, g=0.8, gdir=40.0),
    dict(STATES[0], title='G-force meter: 0.1 g, under the 0.3 g indicator threshold', g=0.1, gdir=90.0),
    dict(STATES[0], title='G-force meter: no reading from the car (label dimmed, no value)', g=None),
]


def editor(scene):
    """The editor shows dial_complete with no template: all of halo_pv, the .uipre's texts, the pre-tinted sprites
    (drawn here as the sim's team tint of the white sprite they were made from)."""
    pv = scene['info']
    base = {v: k for k, v in pv['sprites'].items()}
    for n in walk(scene['halo']):
        if n.get('sprite') in base:
            n['sprite'] = base[n['sprite']]
    scene['info'] = {'vis': [], 'texts': [['pv', el, 'pv:' + el, None, True, False] for el, _ in pv['texts']],
                     'rpm_keys': [], 'batt_keys': []}
    native = {'revs': pv['state']['revs'], 'ers_stored': pv['state']['ers_stored'], 'speed_str': ''}
    native.update({'pv:' + el: txt for el, txt in pv['texts']})
    title = ('HUD editor (Select Element on the dial): dial_complete with the stock dial hidden and the static halo copy; '
             'dashed = its customisation box')
    return [{'title': title, 'team': pv['team'], 'native': native, 'leaves': {}}]


def main():
    scene = json.load(open(sys.argv[1]))
    png, halo, out = sys.argv[2], sys.argv[3], sys.argv[4]
    states = []
    if 'state' in scene['info']:
        states = editor(scene)
    for st in ([] if states else STATES + (GSTATES if '--gmeter' in sys.argv else [])):
        native = {'revs': st['revs'], 'ers_stored': st['ers'], 'speed_str': str(st['kmh'])}
        states.append({'title': st['title'], 'team': st['team'], 'native': native, 'leaves': {} if st.get('native_only') else leaves(st)})
    sprites = sorted({n['sprite'] for n in walk(scene['halo']) if n.get('sprite')} | {'rails', 'solid_white'})
    sim = {'scene': scene, 'states': states, 'sprites': sprites, 'png': 'file:///' + png.replace(chr(92), '/').rstrip('/') + '/',
           'px': 140, 'bottomPad': 60}
    rows = ''.join(f'<h2>{s["title"]}</h2><canvas data-state="{i}" width="1240" height="{int(140 * 3.0) + 60}"></canvas>' for i, s in enumerate(states))
    html = f'''<!doctype html><html><head><meta charset="utf-8"><title>sim</title><style>
@font-face {{ font-family: SimSaira; src: url('file:///{halo.replace(chr(92), '/')}/saira.ttf'); font-weight: 100 900; }}
body {{ margin: 0; padding: 16px; background: #11161b; color: #cfd8de; font: 14px system-ui; }}
h2 {{ font-size: 14px; font-weight: 600; margin: 14px 0 6px; }} canvas {{ display: block; border-radius: 6px; }}
</style></head><body><div id="status">…</div>{rows}
<script>window.SIM = {json.dumps(sim)};</script><script src="file:///{halo.replace(chr(92), '/')}/sim.js"></script></body></html>'''
    open(out, 'w', encoding='utf-8').write(html)


def walk(n):
    yield n
    for k in n['kids']:
        yield from walk(k)


if __name__ == '__main__':
    main()
