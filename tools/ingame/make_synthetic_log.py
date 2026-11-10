"""make_synthetic_log.py <out.csv> [--variant NAME]: a SYNTHETIC validation log for testing analyze_diag.py.

Never use it as evidence: it only exercises the analyzer's code paths. It imitates how the game and the addon produce
a real log:
- the car's physics steps at 60 Hz; frames render at ~170 fps with jitter; a record is written on the first frame at
  least 1/30 s after the previous one, stamped with that frame's time, holding the state of the last simulation step;
- the world velocity is (v sin(heading), 0, v cos(heading)) with Y up; a left turn raises the heading; g_long is the
  speed's rate of change, g_lat the lateral acceleration (positive toward the car's left); steer > 0 is right;
- the progress total moves once per step; speed_dist_kmh / dist_win_s come from a copy of the provider's distance
  reference (game_state_f1_25.cpp distance_reference);
- a 2026 car's battery: E changes by (harvest_k - deploy) every step; deploy is capped per ERS mode (Medium 160 kW,
  Hotlap 240, Boost 350) and tapers at high speed; harvest_k is the energy that enters the store (0 when full or at
  the lap limit); mode 0 (None) in the garage and the pit lane: no harvest, no deploy;
- a 10 s pause on a straight: frames and records go on, the state repeats bit for bit;
- a corner's curvature rises linearly from 40 m before its apex to 1 / radius at the apex and falls back as far after
  it; the halo shows a turn from 220 m before its listed position to 15 m after it, or until the next turn's window.

Variants (each breaks one thing; tools/ingame/test_analyze.py lists the verdicts each must fail):
  legacy           a log from before 2026-11-09: no dist_win_s or turn_shift_m column, speed_dist_kmh is the
                   frame-to-frame difference
  speed_scale      speed (and velocity, HUD km/h) 8 % high
  speed_ref_frame  the provider reference as the old frame-to-frame difference, while claiming a 0.5 s window
  glong_sign       g_long with the wrong sign
  glat_axis        g_lat reading the longitudinal axis
  harvest_half     harvest_k half the energy that enters the store
  deploy_zero      deploy never moves
  boost_hud        the halo's Boost light on for 10 s outside Boost
  arrow_inverted   every turn arrow points the wrong way
  arrow_one_wrong  turn 3's arrow points the wrong way (a wrong direction in the turn table)
  turn_offset      the halo's turn list sits 33 m before the game's corners (Bahrain logs of 2026-11-09)
  turn_learned     as turn_offset on lap 0; from lap 1 the list has moved 33 m to the corners (turn_shift_m)
  two_tracks       first 40 s of another race at another track in a 2025 car (generation 1): a standing start from the
                   grid behind the line, a launch with the clutch slipping, turn 1, then a hard stop at turn 2 and a
                   pause with the clutch in; the drive above follows as generation 2 (a log of 2026-11-09). Must
                   change nothing.
  car_lost         the player car lost for 10 s while the game names it
  slot_reject      the player's slot rejected ('t') for 5 s, the car lost with it
  gm_off           the G-force meter option off (its default): the meter rows have no data
  gm_scale         the meter shows twice the g it reads
  gm_mirror        the meter's arc mirrored left / right
  gm_gap           a wide arc lights the segments either side of its centre but not the centre
  gm_red           the red bar from 2.0 g instead of 2.4 g
  gm_flash         the digits flash for 3 s at 50 s without a 4.3 g peak
  gm_unavail       the meter keeps a value while g is unreadable (accel_ok 0 from 100 to 105 s)
The G-force meter (columns hud_g_*) is on in every variant but gm_off and legacy, as the meter's rules give it from
the logged g (Meter).

The timing tower's companion log (<stem>.tower.csv; tower_<stamp>.csv for a halo_<stamp>.csv) is written for every
variant: a 22-car race over the same 330 s (make_tower_log). The tower_* variants break it instead of the halo log:
  tower_absent       no tower log (a build without the timing tower)
  tower_tyre_visual  car 6's visual byte reads 17 (medium) while its compound enum is 3 (soft)
  tower_tyre_offpit  car 5's letter changes S -> M at 60 s without a pit stop
  tower_gap_swap     gap to the leader and interval swapped (+0x58 and +0x70 the wrong way round)
  tower_sorted       the game's sorted list disagrees with the positions in a tenth of the reads
  tower_sc_flap      the SC byte flips 0 / 1 every 2 s from 100 to 120 s
  tower_pen_dt       car 8's drive-through never shows as pending
  tower_warn_drop    the player's warning count falls at 250 s
  tower_shown_round  the tower rounds gap texts instead of cutting them
  tower_cost         the reader costs 300 us more per frame
  tower_flag_pit     the gap flags stay valid in the pit lane
  tower_restart      the game clears its penalty log at 170 s (a race restarted with the same car set): must pass
  tower_pen_glitch   the penalty log reads empty from 170 to 171 s, then comes back with its old records
  tower_full         the Full field layout (22 rows) instead of Around me: must pass
  tower_nobadges     a tower log from before leaves v4 (no badge columns)
  tower_badge_missing  car 7 never gets a badge (no entrant with its vehicle id)
  tower_badge_change   car 5's badge changes from red_bull_26 to red_bull_25 at 150 s
  tower_badge_three    car 8 reads mclaren_26 too: three cars on one badge
  tower_badge_row      the rows' badges lag one record behind the rows' cars
"""
import math
import os
import random
import statistics
import sys
from collections import defaultdict, deque

VARIANTS = ('good', 'legacy', 'speed_scale', 'speed_ref_frame', 'glong_sign', 'glat_axis', 'harvest_half',
            'deploy_zero', 'boost_hud', 'arrow_inverted', 'arrow_one_wrong', 'turn_offset', 'turn_learned',
            'two_tracks', 'car_lost', 'slot_reject', 'gm_off', 'gm_scale', 'gm_mirror', 'gm_gap', 'gm_red',
            'gm_flash', 'gm_unavail', 'tower_absent', 'tower_tyre_visual', 'tower_tyre_offpit',
            'tower_gap_swap', 'tower_sorted', 'tower_sc_flap', 'tower_pen_dt', 'tower_warn_drop', 'tower_shown_round',
            'tower_cost', 'tower_flag_pit', 'tower_restart', 'tower_pen_glitch', 'tower_full', 'tower_yellow_flicker',
            'tower_red_as_sc', 'tower_noflags', 'tower_oldlog', 'tower_nobadges', 'tower_badge_missing',
            'tower_badge_change', 'tower_badge_three', 'tower_badge_row', 'resume')

HEADER = open(__file__.replace('make_synthetic_log.py', 'header.txt')).read().strip()
L = 4309.0                     # track length, m
STEP = 1 / 60                  # simulation step
FPS = 170                      # rendered frames per second (+-30 %)
RECORD = 1 / 30                # halo_hud.cpp kDiagPeriod
END = 330.0                    # s of log
GARAGE_S = 4.0                 # parked in the garage, then the pit lane (total < 0) at the limiter
PIT_LIMIT = 80 / 3.6
PAUSE = (150.0, 160.0)         # wall-clock seconds the game is paused
CAP_J = 4e6
LIMIT_J = 7.9e6                # harvest per lap
MODE_CAP = {0: 0.0, 1: 160e3, 2: 350e3, 3: 240e3}
RATIOS = [None, 110, 88, 72, 61, 53, 46, 40, 34]  # rpm per km/h; upshift at 11500 rpm
# corners: (fraction of the lap at the apex, right-hander, radius at the apex m)
CORNERS = [(0.10, True, 50.0), (0.16, False, 70.0), (0.27, False, 80.0), (0.40, True, 60.0), (0.62, False, 90.0),
           (0.72, True, 65.0), (0.85, True, 55.0)]
HALF = 40.0                    # m: a corner's curvature rises from this far before its apex and falls back as far after
A_LAT = 3.0 * 9.81
AHEAD, BEHIND = 220.0, 15.0    # halo_track.cpp: a turn is shown from 220 m before to 15 m after it
EARLY = 33.0                   # turn_offset / turn_learned: the halo's list puts each turn this far before its apex
# two_tracks: 40 s of a race at another track first, in a 2025 car
PRE_S, PRE_L, PRE_GRID = 40.0, 4371.0, -121.9
PRE_CORNERS = [(0.06, False, 80.0), (0.085, True, 60.0)]
PRE_RATIOS = [None, 128, 96, 78, 66, 57, 50, 44, 38]
# classification by vehicle id: the player (vid 3) P14, the car one place ahead (vid 5) P13
_rest = iter(p for p in range(1, 23) if p not in (13, 14))
_pos = {v: (14 if v == 3 else 13 if v == 5 else next(_rest)) for v in range(22)}
CLS = 'p' + ''.join(f'{_pos[v]:02x}' for v in range(22))
SLOTS = '.' * 22 + 's'         # 22 competitors and the safety car (no ERS)


def wrap(x):
    return x % L


def turn_at(d, early=0.0, corners=CORNERS, length=L):
    """(label, right) of the turn the halo shows at lap distance d, or None, with its list putting each turn `early`
    m before the apex."""
    pos = [(c[0] * length - early) % length for c in corners]
    ahead = min(range(len(corners)), key=lambda i: (pos[i] - d) % length)
    behind = min(range(len(corners)), key=lambda i: (d - pos[i]) % length)
    if (pos[ahead] - d) % length <= AHEAD:
        return str(ahead + 1), corners[ahead][1]
    if (d - pos[behind]) % length <= BEHIND:
        return str(behind + 1), corners[behind][1]
    return None


def corner_at(d, corners=CORNERS, length=L):
    """(the corner around lap distance d, the path's curvature there in 1/m, + left), or (None, 0)."""
    for c in corners:
        x = (d - c[0] * length + length / 2) % length - length / 2   # signed distance from the apex
        if abs(x) <= HALF:
            return c, (-1 if c[1] else 1) * (1 - abs(x) / HALF) / c[2]
    return None, 0.0


def next_corner(d, corners=CORNERS, length=L):
    """(distance to where the next corner starts to bend, that corner's speed)."""
    best = min(corners, key=lambda c: (c[0] * length - HALF - d) % length)
    return (best[0] * length - HALF - d) % length, math.sqrt(A_LAT * best[2])


def steer_at(d, corners=CORNERS, length=L):
    c, k = corner_at(d, corners, length)
    if c:
        return -0.35 * k * c[2]
    return 0.02 * math.sin(d / 50)


def deploy_cap(mode, kmh):
    """The ERS mode's deploy limit with its speed taper (the shape in the logs: full to ~270 km/h, then down)."""
    cap = MODE_CAP[mode]
    if mode == 2:
        return cap if kmh < 270 else max(150e3, cap - (cap - 150e3) * (kmh - 270) / 30)
    return cap if kmh < 270 else max(0.0, cap * (1 - (kmh - 270) / 20))


def mode_at(t, lap, d, total):
    if t < GARAGE_S or total < 0:
        return 0                                   # None: garage and pit lane
    if lap == 2:
        return 2 if 2000 <= d < 2500 else 3        # a Hotlap lap with a Boost press on the straight
    return 2 if lap == 0 and 2000 <= d < 2600 else 1


class DistRef:
    """Copy of the provider's distance reference (game_state_f1_25.cpp distance_reference)."""

    def __init__(self):
        self.marks, self.speed, self.win = deque(), 0.0, 0.0

    def frame(self, total, now):
        if self.marks:
            lt, ltot = self.marks[-1]
            dt = now - lt
            if total == ltot:
                return (self.speed, self.win) if 0 <= dt < 0.25 else (0.0, 0.0)
            if dt >= 0.25 or dt <= 0 or abs(total - ltot) > 150 * dt + 1:
                self.marks.clear()
        if not self.marks:
            self.speed = self.win = 0.0
        self.marks.append((now, total))
        while len(self.marks) > 2 and now - self.marks[1][0] >= 0.5:
            self.marks.popleft()
        ot, otot = self.marks[0]
        if now - ot >= 0.5:
            self.win, self.speed = now - ot, (total - otot) / (now - ot)
        return self.speed, self.win


class FrameDiff:
    """The reference before 2026-11-09: the total's change since the previous frame."""

    def __init__(self):
        self.last, self.when, self.speed = 0.0, -1.0, 0.0

    def frame(self, total, now):
        self.speed = 0.0
        if self.when >= 0 and 0.004 < now - self.when < 1.0:
            self.speed = (total - self.last) / (now - self.when)
        self.last, self.when = total, now
        return self.speed


class Car:
    def __init__(self):
        self.v, self.psi, self.total = 0.0, 0.3, -300.0
        self.acc = self.lat = 0.0
        self.thr = self.brk = 0.0
        self.E, self.hk, self.dp = 3.2e6, 0.0, 0.0
        self.h_lap = self.d_lap = 0.0
        self.mode = 0
        self.braking = False
        self.lap_index = math.floor(self.total / L)

    def step(self, sim_t):
        v, d = self.v, wrap(self.total)
        if sim_t < GARAGE_S:
            thr, brk, a, turn = 0.0, 0.0, 0.0, 0.0
        elif self.total < 0:                       # pit lane: the limiter
            thr, brk = (1.0, 0.0) if v < PIT_LIMIT - 0.5 else (0.3, 0.0)
            a = min(6.0, (PIT_LIMIT - v) * 3)
            turn = 0.0
        else:
            c, k = corner_at(d)
            if c:
                vc = math.sqrt(A_LAT * c[2])
                thr, brk = 0.35, 0.0
                a = max(-5.0, min(5.0, (vc - v) * 2))
                turn = v * k
                self.braking = False
            else:
                s, vc = next_corner(d)
                # brake (and keep braking) once the corner's speed needs it, down to that speed
                self.braking = v > vc and (self.braking or s <= (v * v - vc * vc) / (2 * 30) + 5)
                if self.braking:
                    thr, brk = 0.0, 0.9
                    a = -36 * brk - 0.00015 * v * v
                else:
                    thr, brk = 1.0, 0.0
                    a = 12 * (1 - v / 105) - 0.00015 * v * v
                turn = 0.0
        self.v = max(0.0, v + a * STEP)
        self.acc = (self.v - v) / STEP
        self.psi += turn * STEP
        self.lat = self.v * turn
        self.total += self.v * STEP
        self.thr, self.brk = thr, brk
        lap_index = math.floor(self.total / L)
        if lap_index != self.lap_index:
            self.lap_index, self.h_lap, self.d_lap = lap_index, 0.0, 0.0
        lap = int(max(self.total, 0) // L)
        self.mode = mode_at(sim_t, lap, wrap(self.total), self.total)
        # the battery: deploy at full throttle up to the mode's cap, harvest under braking; both stop at the ends
        kmh = self.v * 3.6
        dp = deploy_cap(self.mode, kmh) if thr > 0.99 and kmh >= 120 else 0.0
        dp = min(dp, self.E / STEP)
        hk = (min(350e3, 400e3 * brk) if brk > 0.1 else 250e3 if 0.1 < thr < 0.5 else 0.0) if self.mode else 0.0
        hk = max(0.0, min(hk, (CAP_J - self.E) / STEP + dp, (LIMIT_J - self.h_lap) / STEP))
        self.hk, self.dp = hk, dp
        self.E = min(CAP_J, max(0.0, self.E + (hk - dp) * STEP))
        self.h_lap += hk * STEP
        self.d_lap += dp * STEP

    def snapshot(self):
        return dict(v=self.v, psi=self.psi, total=self.total, acc=self.acc, lat=self.lat, thr=self.thr, brk=self.brk,
                    E=self.E, hk=self.hk, dp=self.dp, h_lap=self.h_lap, d_lap=self.d_lap, mode=self.mode)


class Meter:
    """The G-force meter's six log columns, by the meter's rules (native/src/gmeter.cpp): the value is the 0.1 s
    median of the fresh g reads (as the analyzer takes it); the indicator lights from 0.4 g (off at 0.2 g), 2 segments
    or 3 from 2.0 g (back to 2 below 1.0 g); the axis is round(direction / 90); the red bar from 2.4 g (off below
    2.3 g); the digits flash for 1 s from 4.3 g, again only after the value fell below 4.0 g. Direction 0 right,
    90 down, 180 left, 270 up: the side the force pushes the driver (g_lat > 0, a left turn: right; braking: up)."""
    BLANK = ('1', '-1', '0', '-1', '0', '0')

    def __init__(self, variant):
        self.variant = variant
        self.hist = deque()                 # (t, g_lat, g_long) of the fresh reads
        self.lit = self.wide = self.red = False
        self.flash_until, self.armed = -1.0, True

    def update(self, t, g_lat, g_long, ok, fresh):
        v = self.variant
        if v == 'gm_off':
            return None
        if not ok:
            self.hist.clear()
            self.lit = self.wide = self.red = False
            return self.BLANK
        if fresh:
            self.hist.append((t, g_lat, g_long))
        while self.hist and self.hist[0][0] < self.hist[-1][0] - 0.1 - 1e-9:
            self.hist.popleft()
        if not self.hist:
            return self.BLANK
        lat = statistics.median(h[1] for h in self.hist)
        lon = statistics.median(h[2] for h in self.hist)
        g = math.hypot(lat, lon) * (2.0 if v == 'gm_scale' else 1.0)
        tenths = int(round(g * 10))
        self.lit = tenths >= 4 or (self.lit and tenths > 2)
        self.wide = tenths >= 20 or (self.wide and tenths >= 10)
        d = math.degrees(math.atan2(lon, -lat if v == 'gm_mirror' else lat)) % 360
        segs, axis = 0, -1
        if self.lit:
            if self.wide:
                k = int(round(d / 45)) % 8
                ks = [(k - 1) % 8, (k + 1) % 8] if v == 'gm_gap' else [(k - 1) % 8, k, (k + 1) % 8]
            else:
                k = int(math.floor(d / 45)) % 8
                ks = [k, (k + 1) % 8]
            segs, axis = sum(1 << x for x in ks), int(round(d / 90)) % 4
        self.red = tenths >= (20 if v == 'gm_red' else 24) or (self.red and tenths >= 23)
        if tenths >= 43 and self.armed:
            self.flash_until, self.armed = t + 1.0, False
        if tenths < 40 and t >= self.flash_until:  # re-armed only once the flash is over
            self.armed = True
        flash = t < self.flash_until or (v == 'gm_flash' and 50.0 <= t < 53.0)
        return ('1', str(tenths), str(segs), str(axis), '1' if self.red else '0', '1' if flash else '0')


def row_text(cols, t, frame, st, *, gen, track, length, kmh, vx, vz, lap, gear, rpm, g_long, g_lat, steer, hk, dp, sd,
             win, turn, turn_right, shift, max_deploy=350.0, veh_ok=1, slots=SLOTS, hud_boost=False, old_check=False,
             meter=None, accel_ok=1, total_m=None):
    """One record as the addon writes it (diag_log.cpp)."""
    thr, brk = st['thr'], st['brk']
    row = dict.fromkeys(cols, '0')
    row.update(
        t=f'{t:.4f}', frame=str(frame), compatible='1', active='1', generation=str(gen), cars='23', session_type='15',
        track_len_m=f'{length}', track_name=track, veh_ok=str(veh_ok), veh_id='3', is_ai='0',
        speed_ok=str(veh_ok), speed_kmh=f'{kmh:.3f}', speed_dist_kmh=f'{sd * 3.6:.3f}',
        vel_x=f'{vx:.3f}', vel_y='0.000', vel_z=f'{vz:.3f}',
        gear_ok='1', gear=str(gear), gear_index=str(gear + 1), rpm_ok='1', rpm=f'{rpm:.1f}', limiter_ok='1',
        limiter_rpm='13100', input_ok='1', throttle=f'{thr:.4f}', brake=f'{brk:.4f}', throttle_field=f'{thr:.4f}',
        brake_field=f'{brk:.4f}', accel_ok=str(accel_ok), g_lat=f'{g_lat:.4f}', g_long=f'{g_long:.4f}', steer_ok='1',
        steer=f'{steer:.4f}', store_ok='1', store_mj=f'{st["E"] / 1e6:.5f}', capacity_ok='1',
        capacity_mj='4.0000', power_ok='1', harvest_k_kw=f'{hk / 1e3:.3f}', harvest_h_kw='0.000',
        deploy_kw=f'{dp / 1e3:.3f}', max_deploy_ok='1', max_deploy_kw=f'{max_deploy:.2f}', mode_ok='1',
        ers_mode=str(st['mode']), lap_ok='1', harvest_lap_mj=f'{st["h_lap"] / 1e6:.5f}',
        deploy_lap_mj=f'{st["d_lap"] / 1e6:.5f}', harvest_limit_mj=f'{LIMIT_J / 1e6:.5f}', ers_flags='00000000',
        progress_ok='1', total_m=f'{st["total"] if total_m is None else total_m:.3f}', lap_m=f'{st["total"] % length:.3f}', lap=str(lap), field_n='22',
        player_rank='13', results_found='1', classified='1', own_pos='14', cls=CLS, humans='1', progress_link='1',
        ctrl_hits='1', ctrl_vid='3', isai_vid='3', spect_vid='-1', player_src='2', hud_live=str(veh_ok),
        hud_speed_ok=str(veh_ok), hud_kmh=str(round(kmh)), hud_gear_ok='1', hud_gear=str(gear),
        hud_pedals_ok='1', hud_th_lv=str(round(thr * 10)), hud_br_lv=str(round(brk * 10)),
        hud_boost='1' if hud_boost else '0', hud_turn=turn[0] if turn else '-', hud_rival_id='5',
        scan='1' if frame % 3 == 0 else '0', cost_mean_us='12.5', cost_max_us='40.0' if frame % 3 else '95.0',
        cost_frames='5', dropped='0', vcount='23', slots=slots,
        old_check='1' if old_check else '0',  # the garage tag until the pit exit, then the pit-lane tag
        hud_turn_right=turn_right)
    if 'dist_win_s' in row:
        row['dist_win_s'] = f'{win:.3f}'
    if 'turn_shift_m' in row:
        row['turn_shift_m'] = f'{shift:.1f}'
    if meter and 'hud_g_on' in row:
        for k, val in zip(('hud_g_on', 'hud_g_tenths', 'hud_g_segs', 'hud_g_axis', 'hud_g_red_bar', 'hud_g_red_digits'),
                          meter):
            row[k] = val
    return ','.join(row[c] for c in cols) + '\n'


class PreCar:
    """two_tracks: the 2025 car at the other track. On the grid behind the line until 2 s, then full throttle (the
    clutch slips for the first 4 s), braking for turn 1 like the drive above; from turn 2's apex it stops at 3 g down
    to 73 km/h with the clutch in, and the game is paused there. No energy flows (a 2025 car's store, as a log read)."""

    def __init__(self):
        self.v, self.psi, self.total = 0.0, 1.2, PRE_GRID
        self.acc = self.lat = self.thr = self.brk = 0.0
        self.E, self.hk, self.dp, self.h_lap, self.d_lap, self.mode = 2.5e6, 0.0, 0.0, 0.0, 0.0, 1
        self.braking = self.stopping = self.stopped = False

    def step(self, sim_t):
        v, d = self.v, self.total % PRE_L
        c, k = corner_at(d, PRE_CORNERS, PRE_L) if self.total > 0 else (None, 0.0)
        if sim_t < 2.0:
            thr, brk, a = 0.0, 0.0, 0.0
        elif self.stopping or (self.total > 0 and d >= PRE_CORNERS[1][0] * PRE_L):
            self.stopping = True
            thr, brk, a = 0.0, 1.0, -29.4
            if v + a * STEP <= 73 / 3.6:
                a, self.stopped = (73 / 3.6 - v) / STEP, True
        elif c:
            vc = math.sqrt(A_LAT * c[2])
            thr, brk, a = 0.35, 0.0, max(-5.0, min(5.0, (vc - v) * 2))
            self.braking = False
        else:
            s, vc = next_corner(d, PRE_CORNERS, PRE_L) if self.total > 0 else (PRE_CORNERS[0][0] * PRE_L - HALF -
                                                                                self.total, 0.0)
            vc = vc or math.sqrt(A_LAT * PRE_CORNERS[0][2])
            self.braking = v > vc and (self.braking or s <= (v * v - vc * vc) / (2 * 30) + 5)
            thr, brk = (0.0, 0.9) if self.braking else (1.0, 0.0)
            a = -36 * brk - 0.00015 * v * v if self.braking else 12 * (1 - v / 100) - 0.00015 * v * v
        self.v = max(0.0, v + a * STEP)
        self.acc = (self.v - v) / STEP
        turn = self.v * k
        self.psi += turn * STEP
        self.lat = self.v * turn
        self.total += self.v * STEP
        self.thr, self.brk = thr, brk

    def snapshot(self):
        return dict(v=self.v, psi=self.psi, total=self.total, acc=self.acc, lat=self.lat, thr=self.thr, brk=self.brk,
                    E=self.E, hk=self.hk, dp=self.dp, h_lap=self.h_lap, d_lap=self.d_lap, mode=self.mode,
                    stopping=self.stopping)


def pre_stint(out, cols, rng):
    """two_tracks: PRE_S seconds of records before the main drive. Returns the last frame number."""
    car, ref = PreCar(), DistRef()
    wall, next_step, frame, last_rec, launched = 0.0, 0.0, 0, -1.0, None
    st, gear = car.snapshot(), 0
    while wall < PRE_S:
        wall += (1 / FPS) * (1 + 0.3 * (2 * rng.random() - 1))
        frame += 1
        while next_step <= wall and not car.stopped:  # paused once the car has stopped
            car.step(next_step)
            next_step += STEP
            st = car.snapshot()
        sd, win = ref.frame(st['total'], wall)
        if wall - last_rec < RECORD:
            continue
        last_rec = wall
        v, kmh = st['v'], st['v'] * 3.6
        if kmh > 2 and launched is None:
            launched = wall
        if st['stopping'] and kmh < 120:
            rpm = 4000.0                                           # the clutch in
        elif kmh > 2:
            gear = max(gear, next((g for g in range(1, 9) if PRE_RATIOS[g] * kmh <= 11500), 8))
            rpm = PRE_RATIOS[gear] * kmh
            if wall - launched < 4 and kmh < 100:
                rpm = max(rpm, 10500.0)                            # the clutch slips off the line
        else:
            rpm = 4000.0
        turn = turn_at(st['total'] % PRE_L, 0.0, PRE_CORNERS, PRE_L) if st['total'] > 0 else None
        out.write(row_text(
            cols, wall, frame, st, gen=1, track='montreal', length=PRE_L, kmh=kmh, vx=v * math.sin(st['psi']),
            vz=v * math.cos(st['psi']), lap=0, gear=gear, rpm=rpm, g_long=st['acc'] / 9.81, g_lat=st['lat'] / 9.81,
            steer=steer_at(st['total'] % PRE_L, PRE_CORNERS, PRE_L) if st['total'] > 0 else 0.0, hk=0.0, dp=0.0,
            sd=sd, win=win, turn=turn, turn_right=('1' if turn[1] else '0') if turn else '-1', shift=0.0,
            max_deploy=120.0))
    return frame

# ---------------------------------------------------------------- the timing tower's companion log

TOWER_VARIANTS = {
    'tower_absent': 'no tower log (a build without the timing tower)',
    'tower_tyre_visual': 'car 6\'s visual byte reads 17 (medium) while its compound enum is 3 (soft)',
    'tower_tyre_offpit': 'car 5\'s letter changes S -> M at 60 s without a pit stop',
    'tower_gap_swap': 'gap to the leader and interval swapped (+0x58 and +0x70 read the wrong way round)',
    'tower_sorted': 'the game\'s sorted list disagrees with the positions in a tenth of the reads',
    'tower_sc_flap': 'the SC byte flips 0 / 1 every 2 s from 100 to 120 s',
    'tower_pen_dt': 'car 8\'s drive-through never shows as pending',
    'tower_warn_drop': 'the player\'s warning count falls from 3 to 2 at 250 s',
    'tower_shown_round': 'the tower rounds gap texts instead of cutting them',
    'tower_cost': 'the reader costs 300 us more per frame',
    'tower_flag_pit': 'the gap flags stay valid in the pit lane',
    'tower_restart': 'the game clears its penalty log at 170 s (a race restarted with the same car set)',
    'tower_pen_glitch': 'the penalty log reads empty from 170 to 171 s, then comes back with its old records',
    'tower_full': 'the Full field layout (22 rows) instead of Around me',
    'tower_yellow_flicker': 'the yellow header drops out for one record every 2 s during the first yellow',
    'tower_red_as_sc': 'the header shows the safety car during the red flag (the SC byte reads 1 then, as in game)',
    'tower_noflags': 'no yellow zone and no red flag in the drive',
    'tower_oldlog': 'a tower log written before leaves v3 (no flag columns, no badge columns)',
    'tower_nobadges': 'a tower log written before leaves v4 (no badge columns)',
    'tower_badge_missing': 'car 7 never gets a badge (no entrant with its vehicle id: step 4)',
    'tower_badge_change': 'car 5\'s badge changes from red_bull_26 to red_bull_25 at 150 s',
    'tower_badge_three': 'car 8 reads mclaren_26 too: three cars on one badge',
    'tower_badge_row': 'the rows\' badges lag one record behind the rows\' cars',
    'resume': 'a save resumed at 225 s: new generation, the distance counter parked, jumping and running backwards, '
              'g frozen for 10.5 s, four tyre letters stale for 2.5 s',
}
RESUME = 225.0                 # resume: generation 2 from here
RESUME_STALE = (0, 1, 2, 4)    # cars whose letter reads soft (the loaded cache) for 2.5 s after the resume
TOWER_HEADER = ('t,frame,generation,session,on,mode,rows,start,count,player,pidx,held,lead,hs,lap,lapna,cls_ok,cls_n,'
                'holes,dups,sorted,entries,pos,status,tpen,t_ok,t_entries,gl,gi,gain,pit_ok,pit,laps_ok,laps,sc,sc_extra,'
                'zones,red,psec,fseq,fshown,ysec,sectors,'
                'tyre,pen_ok,pen_n,pen_seq,pen_recs,mc_ok,dt,sg,warn,shown,found,read_us,model_us,publish_us,writes,'
                'halo_writes,copies,jobs,dropped,set,bdg,rbdg,bdgkeys,bdgvec')
FLAG_COLS = ('zones', 'red', 'psec', 'fseq', 'fshown', 'ysec', 'sectors')
BADGE_COLS = ('bdg', 'rbdg', 'bdgkeys', 'bdgvec')
T_ENTRANTS = 74                # the game's entrant vector (bdgvec): more records than cars, like a career's
# team badges (leaves v4): car v drives for team v // 2; the reader reads six cars per 10 Hz classification run from
# the start of each car set, so the letters follow the teams' order ('a' = the first key read)
T_TEAMS = ('mclaren_26', 'mercedes_26', 'red_bull_26', 'ferrari_26', 'williams_26', 'alphatauri_26', 'aston_martin_26',
           'haas_26', 'alfa_romeo_26', 'alpine_26', 'gm_cadillac_26')
T_BADGE_CHANGE = 150.0
# flags (leaves v3): 20 marshal zones, zone i from lap fraction i / 20; sectors end at 35 %, 70 %, 100 % of the lap
T_ZONES = 20
T_SECTOR_FRAC = (0.35, 0.70, 1.0)
T_YELLOW = [(30.0, 45.0, 8), (250.0, 262.0, 16)]   # (from, to, zone): sector 2, then sector 3 under the SC
T_RED = (300.0, 312.0, 320.0)                      # deployed, suspended, over; the SC byte reads 1 throughout
T_FLAG_READ0, T_FLAG_PERIOD = 0.175, 0.25          # the reader's flags job (4 Hz)
T_CARS = 22
T_PLAYER = 3                   # the halo log's player (veh_id 3)
T_LAP_S = 80.0
T_START = 12.0                 # lights out; the first timing point at 15 s
T_FIRST_POINT = 15.0
T_RETIRED = (19, 200.0)        # car 19 retires (status 7)
T_SLOW_CAR = 21                # lapped by the leader near the end
T_PIT_LEN = 22.0
T_PIT_PHASES = [(3, 2), (5, 3), (4, 4), (3, 5), (4, 6), (3, 7)]   # (seconds, pit state): all clear the gap flags
T_VSC, T_SC = (60.0, 90.0), (240.0, 290.0)
# (time, vid, type, infringement, seconds): warnings (5), a time penalty (4), a drive-through (0), a stop-go (1)
T_PENALTIES = [(40.0, 3, 5, 7, 0), (70.0, 10, 5, 25, 0), (95.0, 3, 5, 8, 0), (100.0, 8, 0, 2, 0), (130.0, 12, 1, 2, 0),
               (150.0, 3, 5, 9, 0), (151.0, 3, 4, 7, 5), (200.0, 15, 5, 12, 0)]
T_TL_MASK = 0x3e000380
T_RESTART = 170.0              # tower_restart / tower_pen_glitch
T_VIS = {3: 16, 4: 17}
T_ACT = {3: 18, 4: 17}


def tower_path_for(halo_path):
    d, b = os.path.split(halo_path)
    if b.startswith('halo_'):
        return os.path.join(d, 'tower_' + b[len('halo_'):])
    return os.path.splitext(halo_path)[0] + '.tower.csv'


def gap_text(ms, rounded=False):
    tenths = int(round(ms / 100)) if rounded else int(ms) // 100
    if tenths < 600:
        return f'+{tenths // 10}.{tenths % 10}'
    return f'+{tenths // 600}:{(tenths % 600) // 10:02d}.{tenths % 10}'


def pit_state(v, t):
    t0 = 110.0 + 4 * v
    if not t0 <= t < t0 + T_PIT_LEN:
        return 0
    x = t - t0
    for secs, st in T_PIT_PHASES:
        if x < secs:
            return st
        x -= secs
    return 0


def sector_of_frac(x):
    return next((k + 1 for k, e in enumerate(T_SECTOR_FRAC) if e >= x), 0)


def flag_read(tr, variant):
    """The flags read at time tr: (zones token, red byte)."""
    z = ['0'] * T_ZONES
    red = 0
    if variant != 'tower_noflags':
        for a, b, zone in T_YELLOW:
            if a <= tr < b:
                z[zone] = chr(ord('A') + sector_of_frac(zone / T_ZONES) - 1)
            elif b <= tr < b + 5:
                z[zone] = '1'                      # green after the hazard
        if T_RED[0] <= tr < T_RED[2]:
            red = 1 if tr < T_RED[1] else 2
            z = ['4' if ch == '0' else ch for ch in z]   # zone value 4 has other writers: logged only
    return ''.join(z), red


def make_tower_log(path, variant):
    """10 Hz, like native/src/diag_log.cpp write_tower: a 22-car race of the same 330 s with one pit stop per car, a
    VSC and an SC, a retirement, a lapped car, warnings and penalties, and the rows a compact 5-row tower shows."""
    rng = random.Random(23)
    grid = {v: _pos[v] for v in range(T_CARS)}
    speed = {v: L / T_LAP_S * (1 - 0.0015 * (grid[v] - 1)) for v in range(T_CARS)}
    speed[T_PLAYER] = L / T_LAP_S * 1.004            # the player gains places: arrows
    speed[T_SLOW_CAR] = L / T_LAP_S * 0.68
    d = {v: -10.0 * (grid[v] - 1) for v in range(T_CARS)}
    gl_last = {v: 0.0 for v in range(T_CARS)}
    gi_last = {v: 0.0 for v in range(T_CARS)}
    prev_pos, arrow = {}, {}
    pen_recs, pen_seq, last_logged_seq = [], 0, -1
    dt_pending, sg_pending, tpen = defaultdict(int), defaultdict(int), defaultdict(float)
    warn = defaultdict(lambda: [0, 0])
    held_letter = {}
    fired = set()
    restarted = in_glitch = False
    header = TOWER_HEADER.split(',')
    if variant == 'tower_oldlog':
        header = [k for k in header if k not in FLAG_COLS + BADGE_COLS]
    if variant == 'tower_nobadges':
        header = [k for k in header if k not in BADGE_COLS]
    last_bdg = (None, None)                        # (generation, letters) of the previous record: the key listing
    prev_rbdg = {}                                 # tower_badge_row: the previous record's letters by row
    yel_hist = []                                  # (fseq, yellow read, sector text) for the model's hold
    out = open(path, 'w', newline='\n')
    out.write(','.join(header) + '\n')
    frame, t = 0, 0.0
    while t < END:
        t += 0.1 + 0.004 * rng.random()
        frame += 17
        # --- the race
        for v in range(T_CARS):
            if t < T_START or (v == T_RETIRED[0] and t >= T_RETIRED[1]):
                continue
            d[v] += (PIT_LIMIT if pit_state(v, t) else speed[v]) * 0.1
        status = {v: (7 if v == T_RETIRED[0] and t >= T_RETIRED[1] else 2) for v in range(T_CARS)}
        running = sorted((v for v in range(T_CARS) if status[v] == 2), key=lambda v: -d[v])
        order = running + [v for v in range(T_CARS) if status[v] != 2]
        pos = {v: k + 1 for k, v in enumerate(order)}
        laps = {v: int(max(d[v], 0.0) // L) for v in range(T_CARS)}
        pit = {v: (pit_state(v, t) if status[v] == 2 else 0) for v in range(T_CARS)}
        leader = order[0]
        gl, gi, glv, giv = {}, {}, {}, {}
        for k, v in enumerate(order):
            a = order[k - 1] if k else None
            if t >= T_FIRST_POINT and status[v] == 2:
                gl_last[v] = (d[leader] - d[v]) / (L / T_LAP_S) * 1000
                gi_last[v] = (d[a] - d[v]) / (L / T_LAP_S) * 1000 if a is not None else 0.0
            gl[v], gi[v] = gl_last[v], gi_last[v]
            valid = t >= T_FIRST_POINT and status[v] == 2 and v != leader
            if pit[v] and variant != 'tower_flag_pit':
                valid = False
            glv[v] = valid and d[leader] - d[v] < L
            giv[v] = valid and a is not None and d[a] - d[v] < L
        if variant == 'tower_gap_swap':
            gl, gi, glv, giv = gi, gl, giv, glv
        sc = 3 if t < 10 else 2 if T_VSC[0] <= t < T_VSC[1] else 1 if T_SC[0] <= t < T_SC[1] else 0
        if variant == 'tower_sc_flap' and 100 <= t < 120:
            sc = int(t // 2) % 2
        in_red = T_RED[0] <= t < T_RED[2] and variant != 'tower_noflags'
        if in_red:
            sc = 1                                 # the game's SC byte during a red flag (in-game log 2026-11-09)
        # --- flags: the last 4 Hz read (the reader restarts with each generation) and the model's hold
        gen = 2 if variant == 'resume' and t >= RESUME else 1
        g0 = RESUME if gen == 2 else 0.0
        fseq = int((t - g0 - T_FLAG_READ0) // T_FLAG_PERIOD) + 1 if t - g0 >= T_FLAG_READ0 else 0
        zones, red = flag_read(g0 + T_FLAG_READ0 + (fseq - 1) * T_FLAG_PERIOD, variant) if fseq else ('-', -1)
        ytxt = '_'.join(str(k) for k in sorted({ord(ch) - 64 for ch in zones if ch.isalpha()}))
        if fseq and (not yel_hist or yel_hist[-1][0] != (gen, fseq)):
            yel_hist.append(((gen, fseq), bool(ytxt), ytxt))
        cur = [h for h in yel_hist[-2:] if h[0][0] == gen and h[0][1] >= fseq - 1]
        yel = any(h[1] for h in cur)               # held over one non-yellow read
        ysec = next((h[2] for h in reversed(cur) if h[1]), '') if yel else ''
        red_on = red in (1, 2)
        hs = 3 if red_on else 1 if sc == 1 else 2 if sc == 2 else 5 if yel else 0
        fshown = ('r' if red_on else '') + ('y' if yel else '') or '-'
        if variant == 'tower_yellow_flicker' and hs == 5 and t < 100 and int(t * 10) % 20 == 0:
            hs, fshown, ysec = 0, '-', ''
        if variant == 'tower_red_as_sc' and red_on:
            hs, fshown = 1, fshown.replace('r', '') or '-'
        if variant == 'tower_oldlog':
            hs = 1 if sc == 1 else 2 if sc == 2 else 0
        # --- penalties (the game's log, the misconduct vectors, the results' time total)
        if variant == 'tower_restart' and t >= T_RESTART and not restarted:
            restarted = True                       # a new log: the warnings, totals and pending penalties go with it
            pen_recs, pen_seq = [], pen_seq + 1
            for d_ in (warn, tpen, dt_pending, sg_pending):
                d_.clear()
        glitch = variant == 'tower_pen_glitch' and T_RESTART <= t < T_RESTART + 1.0
        if glitch != in_glitch:                    # the reader sees the count change twice: n -> 0 -> n
            in_glitch = glitch
            pen_seq += 1
        for n_, (pt, v, typ, why, secs) in enumerate(T_PENALTIES):
            if pt <= t and (n_, 0) not in fired:
                fired.add((n_, 0))
                pen_recs.append((v, typ, why, secs, laps[v] + 1, 255))
                pen_seq += 1
                if typ == 5:
                    warn[v][0] += 1
                    warn[v][1] += why <= 0x1d and (T_TL_MASK >> why) & 1
            if pt + 0.5 <= t and (n_, 1) not in fired:
                fired.add((n_, 1))
                if typ == 0 and variant != 'tower_pen_dt':
                    dt_pending[v] += 1
                elif typ == 1:
                    sg_pending[v] += 1
                elif typ == 4:
                    tpen[v] += secs
        for v in list(dt_pending):
            if pit[v] == 4:
                dt_pending[v] = 0                  # served at the stop
        for v in list(sg_pending):
            if pit[v] == 4:
                sg_pending[v] = 0
        # --- tyres: soft until the car's box phase, then medium
        tyre = {}
        for v in range(T_CARS):
            changed = t >= 110.0 + 4 * v + 8
            if variant == 'tower_tyre_offpit' and v == 5 and t >= 60:
                changed = True
            if variant == 'resume' and v in RESUME_STALE and RESUME <= t < RESUME + 2.5:
                changed = False                    # the loaded cache's letter until the game rebuilds it
            c = 4 if changed else 3
            vis = T_VIS[c]
            if variant == 'tower_tyre_visual' and v == 6 and c == 3:
                vis = 17
            tyre[v] = (2 if changed else 1, 14 if changed else 13, vis, T_ACT[c], c)
        slow = int(t * 10) % 10 == 0
        # --- what a compact 5-row tower shows (native/src/tower_model.cpp)
        lead = int(t // 10) % 2 == 1                       # Auto, every 10 s
        for v in range(T_CARS):
            if v in prev_pos and prev_pos[v] != pos[v]:
                arrow[v] = (t + 4.0, 'u' if pos[v] < prev_pos[v] else 'd')
            prev_pos[v] = pos[v]
        pidx = order.index(T_PLAYER)
        full = variant == 'tower_full'
        rows = T_CARS if full else 5
        start = 0 if full else min(max(pidx - rows // 2, 0), T_CARS - rows)
        stale = {v: slow and rng.random() < 0.02 for v in range(T_CARS)}
        shown = []
        for k in range(start, start + rows):
            v = order[k]
            st = status[v]
            is_out = st in (4, 5, 6, 7)
            flags = ''
            a_ = arrow.get(v)
            if a_ and t < a_[0]:
                flags += a_[1]
            if not is_out and pit[v] >= 2:
                flags += 'p'
            if not is_out and (dt_pending[v] or sg_pending[v] or tpen[v] > 0):
                flags += 'n'
            if is_out:
                flags += 'o'
            if v == T_PLAYER:
                flags += 'm'
            ok_l = tyre[v][2] == T_VIS[tyre[v][4]]
            letter = '-'
            if not is_out:
                if stale[v] and held_letter.get(v):
                    letter = held_letter[v]
                    flags += 'h'
                elif ok_l and not stale[v]:
                    letter = 'S' if tyre[v][4] == 3 else 'M'
                    held_letter[v] = letter
                else:
                    flags += 't'
            if is_out:
                kind, text_ = 5, 'Out'
            elif pos[v] == 1:
                kind, text_ = 1, 'Leader' if lead else 'Interval'
            else:
                valid = glv[v] if lead else giv[v]
                ms = gl[v] if lead else gi[v]
                if valid and 0 <= ms:
                    kind, text_ = 2, gap_text(ms, rounded=variant == 'tower_shown_round')
                elif valid:
                    kind, text_ = 6, ''
                elif pit[v] in (2, 3, 4, 5, 6, 7, 14, 15):
                    kind, text_ = 4, 'PIT'
                else:
                    ref = leader if lead else (order[k - 1] if k else -1)
                    n = laps[ref] - laps[v] if ref >= 0 else 0
                    kind, text_ = (3, '+1 LAP' if n == 1 else f'+{n} LAPS') if st == 2 and 1 <= n <= 99 else (6, '')
            if kind == 6:
                flags += 'g'
            if pos[v] == 1:
                flags += '1'
            shown.append(f'{v}:{pos[v]}:{kind}:{text_.replace(" ", "_") or "-"}:{letter}:{flags}')
        # --- team badges (native/src/diag_log.cpp): per car the key's letter, per row its car's letter, the keys on
        #     the 1 Hz records and whenever a car's result changed
        runs = int((t - g0) // 0.1) + 1                # classification runs of this car set (offset 0, 10 Hz)
        keys = list(T_TEAMS)
        team = {v: v // 2 for v in range(T_CARS)}
        if variant == 'tower_badge_three':
            team[8] = 0
        if variant == 'tower_badge_change' and t >= T_BADGE_CHANGE:
            keys.append('red_bull_25')
            team[5] = len(keys) - 1
        letters = ''.join(
            '.' if v >= 6 * runs else '4' if variant == 'tower_badge_missing' and v == 7 else chr(97 + team[v])
            for v in range(T_CARS))
        used = sorted({ch for ch in letters if 'a' <= ch <= 'z'})
        if slow or last_bdg != (gen, letters):
            bdgkeys = ' '.join(f'{ch}={keys[ord(ch) - 97]}' for ch in used) or '.'
        else:
            bdgkeys = '-'
        last_bdg = (gen, letters)
        rbdg = ''.join(letters[order[k]] if 'a' <= letters[order[k]] <= 'z' else '-' for k in range(start, start + rows))
        if variant == 'tower_badge_row':           # each row shows the letter it had in the previous record
            rbdg, prev_rbdg = ''.join(prev_rbdg.get(k, ch) for k, ch in enumerate(rbdg)), dict(enumerate(rbdg))
        # --- the record
        cols = {
            't': f'{t:.4f}', 'frame': str(frame), 'generation': str(gen), 'session': '15', 'on': '1',
            'mode': '0' if full else '1',
            'rows': str(rows), 'start': str(start), 'count': str(T_CARS), 'player': str(T_PLAYER), 'pidx': str(pidx),
            'held': '0', 'lead': '1' if lead else '0',
            'hs': str(hs), 'lap': str(laps[leader] + 1), 'lapna': '0',
            'cls_ok': '1', 'cls_n': str(T_CARS), 'holes': '0', 'dups': '0',
            'sorted': '0' if variant == 'tower_sorted' and rng.random() < 0.1 else '1', 'entries': str(T_CARS),
            'pos': ' '.join(str(pos[v]) for v in range(T_CARS)),
            'status': ''.join(str(status[v]) for v in range(T_CARS)),
            'tpen': ' '.join(f'{tpen[v]:g}' for v in range(T_CARS)),
            't_ok': '1', 't_entries': str(T_CARS),
            'gl': ' '.join(f'{int(gl[v])}{"v" if glv[v] else "x"}' for v in range(T_CARS)),
            'gi': ' '.join(f'{int(gi[v])}{"v" if giv[v] else "x"}' for v in range(T_CARS)),
            'gain': ' '.join('00' for _ in range(T_CARS)),
            'pit_ok': '1', 'pit': ''.join('0123456789abcdef'[pit[v]] for v in range(T_CARS)),
            'laps_ok': '1', 'laps': ' '.join(str(laps[v]) for v in range(T_CARS)),
            'sc': str(sc), 'sc_extra': '2' if in_red else '0',
            'zones': zones, 'red': str(red), 'psec': str(sector_of_frac((max(d[T_PLAYER], 0.0) % L) / L)),
            'fseq': str(fseq), 'fshown': fshown, 'ysec': ysec or '-',
            'sectors': '/'.join(f'{f * L:.1f}' for f in T_SECTOR_FRAC) + f'@{L:.1f}' if slow and fseq else '-',
            'tyre': ' '.join('2' if stale[v] else '1.%d.%d.%d.%d.%d.%s' % (tyre[v] + ('S' if tyre[v][4] == 3 else 'M',))
                             for v in range(T_CARS)) if slow else '-',
            'pen_ok': '1', 'pen_n': str(0 if glitch else len(pen_recs)), 'pen_seq': str(pen_seq + 1),
            'pen_recs': (';'.join(':'.join(map(str, r)) for r in ([] if glitch else pen_recs)) or '0')
                        if pen_seq != last_logged_seq else '-',
            'mc_ok': '1',
            'dt': ''.join(str(min(dt_pending[v], 9)) for v in range(T_CARS)) if slow else '-',
            'sg': ''.join(str(min(sg_pending[v], 9)) for v in range(T_CARS)) if slow else '-',
            'warn': ' '.join('0/0' if glitch else
                             f'{warn[v][0] - (1 if variant == "tower_warn_drop" and v == T_PLAYER and t >= 250 else 0)}'
                             f'/{warn[v][1]}' for v in range(T_CARS)) if slow else '-',
            'shown': ' '.join(shown), 'found': 'RTPSZ1YG' if variant == 'tower_oldlog' else 'RTPSZ1YGMF',
            'read_us': f'{2 + 3 * rng.random() + (300 if variant == "tower_cost" else 0):.1f}',
            'model_us': f'{0.5 + 0.4 * rng.random():.1f}', 'publish_us': f'{2 + 2 * rng.random():.1f}',
            'writes': str(rng.randint(8, 20)), 'halo_writes': str(rng.randint(5, 36)), 'copies': str(rng.randint(8, 20)),
            'jobs': str(rng.randint(0, 63)), 'dropped': '0', 'set': 'htagcm',
            'bdg': letters, 'rbdg': rbdg or '-', 'bdgkeys': bdgkeys, 'bdgvec': str(T_ENTRANTS),
        }
        last_logged_seq = pen_seq
        out.write(','.join(cols[k] for k in header) + '\n')
    out.close()


def main():
    out_path = sys.argv[1]
    variant = sys.argv[sys.argv.index('--variant') + 1] if '--variant' in sys.argv else 'good'
    if variant not in VARIANTS:
        sys.exit(f'unknown variant {variant}; known: {", ".join(VARIANTS)}')
    cols = HEADER.split(',')
    if variant == 'legacy':
        cols = [c for c in cols if c not in ('dist_win_s', 'turn_shift_m') and not c.startswith('hud_g_')]
    meter, last_key = Meter(variant), None
    rng = random.Random(7)
    car, ref, old = Car(), DistRef(), FrameDiff()
    out = open(out_path, 'w', newline='\n')
    out.write(','.join(cols) + '\n')
    t0, gen, frame = 0.0, 1, 0
    if variant == 'two_tracks':
        frame = pre_stint(out, cols, random.Random(11))
        t0, gen = PRE_S, 2
    wall, next_step, last_rec = 0.0, 0.0, -1.0
    st = car.snapshot()
    while wall < END:
        wall += (1 / FPS) * (1 + 0.3 * (2 * rng.random() - 1))
        frame += 1
        if PAUSE[0] <= wall < PAUSE[1]:
            sim = next_step - 1e-9                 # the simulation clock stands still
        else:
            sim = wall - (PAUSE[1] - PAUSE[0] if wall >= PAUSE[1] else 0.0)
        while next_step <= sim:
            car.step(next_step)
            next_step += STEP
            st = car.snapshot()
        sd, win = ref.frame(st['total'], wall)
        sd_old = old.frame(st['total'], wall)
        if wall - last_rec < RECORD:
            continue
        last_rec = wall
        t = wall
        v, kmh = st['v'], st['v'] * 3.6
        vx, vz = v * math.sin(st['psi']), v * math.cos(st['psi'])
        lap_m = wrap(st['total'])
        lap = int(max(st['total'], 0) // L)
        gear = next((g for g in range(1, 9) if RATIOS[g] * kmh <= 11500), 8) if kmh > 2 else 0
        rpm = 4000 if gear == 0 else (RATIOS[gear] * kmh if kmh >= 30 else max(4000, RATIOS[gear] * kmh))
        g_long, g_lat = st['acc'] / 9.81, st['lat'] / 9.81
        mode = st['mode']
        hk, dp = st['hk'], st['dp']
        shift, early = 0.0, 0.0
        if variant == 'turn_offset' or (variant == 'turn_learned' and st['total'] < L + 200):
            early = EARLY
        elif variant == 'turn_learned':
            shift = EARLY                          # the halo learned lap 0 and moved its list to the corners
        turn = turn_at(lap_m, early) if st['total'] > 0 else None
        turn_right = ('1' if turn[1] else '0') if turn else '-1'
        boost = mode == 2
        hud_boost = boost
        veh_ok, slots = 1, SLOTS
        speed_scale = 1.0
        if variant == 'legacy':
            sd = sd_old
        elif variant == 'speed_scale':
            speed_scale = 1.08
        elif variant == 'speed_ref_frame':
            sd, win = sd_old, 0.5
        elif variant == 'glong_sign':
            g_long = -g_long
        elif variant == 'glat_axis':
            g_lat = g_long
        elif variant == 'harvest_half':
            hk = hk / 2
        elif variant == 'deploy_zero':
            dp = 0.0
        elif variant == 'boost_hud' and 60 <= t < 70:
            hud_boost = True
        elif turn and (variant == 'arrow_inverted' or (variant == 'arrow_one_wrong' and turn[0] == '3')):
            turn_right = '0' if turn[1] else '1'
        elif variant == 'car_lost' and 100 <= t < 110:
            veh_ok = 0
        elif variant == 'slot_reject' and 100 <= t < 105:
            veh_ok, slots = 0, SLOTS[:3] + 't' + SLOTS[4:]
        accel_ok = 0 if variant == 'gm_unavail' and 100 <= t < 105 else 1
        total_m = None
        if variant == 'resume' and t >= RESUME:
            gen = 2
            x = t - RESUME
            if x < 1.3:                            # the counter parked at the grid while the car replays
                total_m = 84.0 + 0.004 * rng.random()
            elif 1.9 <= x < 2.5:                   # then it runs backwards for 0.6 s
                total_m = resume_mark - v * (x - 1.9)
            elif x < 1.9:
                resume_mark = st['total']
            if x < 10.5:                           # physics resumes later: g stands still
                g_long, g_lat = -0.6297, -0.0304
        # the meter: fresh when the logged velocity or distance moved (the analyzer's own test); gm_unavail keeps
        # showing a value while g is unreadable
        key = (f'{vx * speed_scale:.3f}', f'{vz * speed_scale:.3f}', f'{st["total"]:.3f}')
        m = meter.update(t0 + t, g_lat, g_long, veh_ok == 1 and (accel_ok == 1 or variant == 'gm_unavail'),
                         key != last_key)
        last_key = key
        out.write(row_text(
            cols, t0 + t, frame, st, gen=gen, track='brazil', length=L, kmh=kmh * speed_scale, vx=vx * speed_scale,
            vz=vz * speed_scale, lap=lap, gear=gear, rpm=rpm, g_long=g_long, g_lat=g_lat, steer=steer_at(lap_m), hk=hk,
            dp=dp, sd=sd, win=win, turn=turn, turn_right=turn_right, shift=shift, veh_ok=veh_ok, slots=slots,
            hud_boost=hud_boost, old_check=t < GARAGE_S + 1, meter=m, accel_ok=accel_ok, total_m=total_m))
    out.close()
    if variant != 'tower_absent':
        make_tower_log(tower_path_for(out_path), variant)
    elif os.path.exists(tower_path_for(out_path)):
        os.remove(tower_path_for(out_path))


if __name__ == '__main__':
    main()
