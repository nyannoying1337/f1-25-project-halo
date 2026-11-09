"""make_synthetic_log.py <out.csv>: a SYNTHETIC validation log (simple car model) for testing analyze_diag.py.
Never use it as evidence: it only exercises the analyzer's code paths."""
import math, sys
HEADER = open(__file__.replace('make_synthetic_log.py', 'header.txt')).read().strip()
cols = HEADER.split(',')
out = open(sys.argv[1], 'w', newline='\n')
out.write(HEADER + '\n')
t, v, total, gear, E = 0.0, 0.0, -100.0, 0, 4.0e6
ratios = [None, 145, 120, 102, 89, 79, 71, 64, 58]  # rpm per km/h
L = 4309.0
# classification by vehicle id: the player (vid 3) P14, the car one place ahead (vid 5) P13
rest = iter(p for p in range(1, 23) if p not in (13, 14))
pos = {v: (14 if v == 3 else 13 if v == 5 else next(rest)) for v in range(22)}
CLS = 'p' + ''.join(f'{pos[v]:02x}' for v in range(22))
# the vehicle table: 22 competitors and the safety car (no ERS)
SLOTS = '.' * 22 + 's'
# turns (fraction of the lap, right-hander), shown as halo_track.cpp Corners::current does
CORNERS = [(0.10, True), (0.16, False), (0.40, True), (0.62, False), (0.85, True)]
AHEAD, BEHIND = 220.0, 15.0


def wrap(x):
    return x % L


def turn_at(d):
    """(label, right) of the turn the halo shows at lap distance d, or None."""
    ahead = min(range(len(CORNERS)), key=lambda i: wrap(CORNERS[i][0] * L - d))
    behind = min(range(len(CORNERS)), key=lambda i: wrap(d - CORNERS[i][0] * L))
    if wrap(CORNERS[ahead][0] * L - d) <= AHEAD:
        return str(ahead + 1), CORNERS[ahead][1]
    if wrap(d - CORNERS[behind][0] * L) <= BEHIND:
        return str(behind + 1), CORNERS[behind][1]
    return None


def steer_at(d):
    """Steering (-1 left .. 1 right): into each corner from 60 m before it to 10 m after it."""
    for frac, right in CORNERS:
        if wrap(d - frac * L + 60) <= 70:
            return 0.35 if right else -0.35
    return 0.02 * math.sin(d / 50)


for i in range(30 * 240):
    t = i / 30
    ph = (t % 40)
    thr = 1.0 if ph < 22 else 0.0
    brk = 0.9 if 22 <= ph < 27 else 0.0
    a = 9.0 * thr * max(0.2, 1 - v / 90) - 35 * brk - 0.002 * v * v
    v = max(0.0, v + a / 30)
    kmh = v * 3.6
    gear = max(1, min(8, 1 + int(kmh / 40))) if kmh > 2 else 0
    rpm = 4000 if gear == 0 else min(11800, max(4500, ratios[gear] * kmh))
    total += v / 30
    harvest = 300.0 if brk else 0.0
    deploy = 250.0 if thr and kmh > 80 else 0.0
    E = min(4e6, max(0, E + (harvest - deploy) * 1e3 / 30))
    lap = int(max(total, 0) // L)
    lap_m = total % L
    boost = 100 < t < 110 or 150 < t < 160
    turn = turn_at(lap_m) if total > 0 else None
    row = dict.fromkeys(cols, '0')
    row.update(t=f'{t:.4f}', frame=str(i), compatible='1', active='1', generation='1', cars='23', session_type='15',
               track_len_m=f'{L}', track_name='brazil', veh_ok='1', veh_id='3', speed_ok='1', speed_kmh=f'{kmh:.3f}',
               speed_dist_kmh=f'{kmh:.3f}', gear_ok='1', gear=str(gear), gear_index=str(gear + 1), rpm_ok='1',
               rpm=f'{rpm:.1f}', limiter_ok='1', limiter_rpm='13100', input_ok='1', throttle=f'{thr}', brake=f'{brk}',
               accel_ok='1', g_long=f'{a / 9.81:.4f}', steer_ok='1', steer=f'{steer_at(lap_m):.4f}', store_ok='1',
               store_mj=f'{E / 1e6:.5f}', capacity_ok='1', capacity_mj='4', power_ok='1', harvest_k_kw=f'{harvest}',
               deploy_kw=f'{deploy}', max_deploy_ok='1', max_deploy_kw='350', mode_ok='1', ers_mode='2' if boost else '1',
               ers_flags='00000000', progress_ok='1', total_m=f'{total:.3f}', lap_m=f'{lap_m:.3f}', lap=str(lap),
               field_n='22', player_rank='13', results_found='1', classified='1', own_pos='14', cls=CLS, humans='1',
               progress_link='1', ctrl_hits='1', ctrl_vid='3', isai_vid='3', spect_vid='-1', player_src='2',
               hud_live='1', hud_speed_ok='1', hud_kmh=str(round(kmh)), hud_gear_ok='1', hud_gear=str(gear),
               hud_pedals_ok='1', hud_th_lv=str(round(thr * 10)), hud_br_lv=str(round(brk * 10)),
               hud_boost='1' if boost else '0', hud_turn=turn[0] if turn else '-', hud_rival_id='5',
               scan='1' if i % 3 == 0 else '0', cost_mean_us='12.5', cost_max_us='40.0' if i % 3 else '95.0',
               cost_frames='4', dropped='0', vcount='23', slots=SLOTS,
               old_check='1' if t < 5 else '0',  # the garage tag until the pit exit, then the pit-lane tag
               hud_turn_right=('1' if turn[1] else '0') if turn else '-1')
    out.write(','.join(row[c] for c in cols) + '\n')
