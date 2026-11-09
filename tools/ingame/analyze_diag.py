"""analyze_diag.py <halo_*.csv> [report.md]

Turns an in-game validation log (written by the addon's "Validation log" option) into a per-field verification
report: every check below compares a value the provider read against another, independent in-game observation
(the game's own distance counter, the battery's rate of change, the car's motion, the steering in a corner, the
game's own record of who drives which car), so a wrong offset shows up as a failed check instead of a
plausible-looking number. Verdicts: PASS, FAIL, or NO DATA (the drive did not exercise that state; the report says
what to do). Logs written by older builds lack some columns: those checks are skipped.
"""
import csv
import math
import re
import sys
from collections import Counter, defaultdict

import numpy as np

KMH = 3.6
RECORD_S = 1 / 30      # the log's record period (halo_hud.cpp kDiagPeriod)
STRIPES = 10           # throttle / brake slats (leaves.hpp kStripes)
LOST_MAX_S = 2.0       # longest tolerated loss: table churn while cars are created or destroyed lasts a few frames
SLOT_REJECT = 'uti?'   # vehicle-table slot statuses that are not a car (game_state_f1_25.hpp SlotStatus)


def text(v):
    """A text column as strings (the loader turns a column whose every value is numeric into floats)."""
    return np.array([str(int(x)) if isinstance(x, float) and math.isfinite(x) and x == int(x) else str(x) for x in v],
                    dtype=object)


def runs(mask):
    """Inclusive (first, last) index pairs of the True runs of a boolean array."""
    d = np.diff(np.concatenate(([0], np.asarray(mask, dtype=np.int8), [0])))
    return list(zip(np.nonzero(d == 1)[0].tolist(), (np.nonzero(d == -1)[0] - 1).tolist()))


def longest(mask, t):
    """(seconds, first index) of the longest True run; (0.0, None) without one."""
    return max(((float(t[b] - t[a]) + RECORD_S, a) for a, b in runs(mask)), default=(0.0, None))


def turn_key(label):
    """'9' -> (9, ''), '14a' -> (14, 'a'): the order of official turn labels."""
    m = re.fullmatch(r'(\d+)([a-z]?)', label)
    return (int(m.group(1)), m.group(2)) if m else None


def pct(x):
    return 'n/a' if x is None or math.isnan(x) else f'{100 * x:.0f}%'


def load(path):
    rows = []
    with open(path, newline='', encoding='utf-8', errors='replace') as f:
        r = csv.DictReader(line for line in f if not line.startswith('#'))
        for row in r:
            rows.append(row)
    if not rows:
        sys.exit('empty log')
    cols = {}
    for k in rows[0]:
        vals = [row[k] for row in rows]
        try:
            cols[k] = np.array([float(v) for v in vals])
        except ValueError:
            cols[k] = np.array(vals, dtype=object)
    return cols, len(rows)


class Report:
    def __init__(self):
        self.lines, self.table = [], []

    def verdict(self, field, verdict, evidence, todo=''):
        self.table.append((field, verdict, evidence, todo))

    def text(self, s=''):
        self.lines.append(s)

    def render(self, path, n, dur):
        out = ['# In-game validation report', '',
               f'Log: `{path}` — {n} records, {dur:.0f} s of driving.', '',
               '| Field | Verdict | Evidence | To complete |', '|---|---|---|---|']
        for f, v, e, t in self.table:
            out.append(f'| {f} | **{v}** | {e} | {t} |')
        out += [''] + self.lines
        return '\n'.join(out) + '\n'


def corr(a, b):
    if len(a) < 10 or np.std(a) == 0 or np.std(b) == 0:
        return float('nan')
    return float(np.corrcoef(a, b)[0, 1])


def finish(rep, path, n, dur):
    out = sys.argv[2] if len(sys.argv) > 2 else 'report.md'
    text_ = rep.render(path, n, dur)
    open(out, 'w', encoding='utf-8').write(text_)
    sys.stdout.buffer.write(text_.encode('utf-8'))


def car_table(rep, c, n, t, live, named):
    """The vehicle table's identity checks: the per-slot status of every scan (log column "slots")."""
    sl = text(c['slots'])
    tab = (c['compatible'] == 1) & (sl != '-') & (sl != '')
    if not tab.any():
        rep.verdict('Car table (identity)', 'NO DATA', 'the vehicle table was never read', 'drive on track with the addon enabled')
        return
    width = max(len(s) for s in sl[tab])
    grid = np.array([list(s.ljust(width, '-')) if ok else ['-'] * width for s, ok in zip(sl, tab)])
    cnt = Counter(''.join(sl[tab]))
    mix = ', '.join(f"'{k}' {cnt[k]}" for k in '.snuti?' if cnt[k])
    counts = sorted(set(c['vcount'][tab].astype(int).tolist()))
    length_off = int(sum(len(s) != int(v) for s, v, ok in zip(sl, c['vcount'], tab) if ok))
    # the player car's slot, named by the game's ControllerSystem (independent of the table's identity check)
    pk = np.nonzero(named & tab)[0]
    pst = np.array([grid[k, int(c['ctrl_vid'][k])] if int(c['ctrl_vid'][k]) < width else '-' for k in pk], dtype='<U1')
    p_car = np.isin(pst, ['.', 's'])
    p_in = float(p_car.mean()) if len(pst) else float('nan')
    p_mask = np.zeros(n, dtype=bool)
    p_mask[pk[~p_car]] = True
    p_s, p_at = longest(p_mask, t)
    # any slot rejected for longer than the churn while cars are created or destroyed
    worst = (0.0, None, None)
    for j in range(width):
        m = tab & np.isin(grid[:, j], list(SLOT_REJECT))
        if m.any():
            s, at = longest(m, t)
            if s > worst[0]:
                worst = (s, j, at)
    sc = float(np.mean([s.count('s') == 1 for s in sl[tab]]))
    ev = (f'vehicle count {counts}; slot statuses over {int(tab.sum())} records: {mix}' +
          (f'; {length_off} records whose slot list differs from the count in length' if length_off else '') +
          f"; the player car's slot (vehicle named by the ControllerSystem) held a car in {pct(p_in)} of {len(pst)} records" +
          (f" (otherwise {dict(Counter(pst[~p_car].tolist()))}, longest {p_s:.1f} s from t = {t[p_at]:.1f} s)"
           if p_at is not None else '') +
          f'; longest rejection of any slot {worst[0]:.1f} s' +
          (f" (slot {worst[1]}, '{grid[worst[2], worst[1]]}', from t = {t[worst[2]]:.1f} s)" if worst[1] is not None else '') +
          f"; exactly one car without ERS ('s', the safety car) in {pct(sc)} of records")
    if 'old_check' in c:
        oc = c['old_check']
        lv = live & (oc >= 0)
        mv = lv & (c['speed_kmh'] > 5)
        drop = float((oc[lv] == 0).mean()) if lv.any() else float('nan')
        drop_mv = float((oc[mv] == 0).mean()) if mv.any() else float('nan')
        ev += (f'; the check used before 2026-11-09 (CarLive+0x0 read as a vtable) would have dropped the player car in '
               f'{pct(drop)} of {int(lv.sum())} live records ({pct(drop_mv)} of {int(mv.sum())} moving)')
    ok = p_s <= LOST_MAX_S and worst[0] <= LOST_MAX_S
    if not ok:
        verdict, todo = 'FAIL', ("send the log: 't' means the container vptr (+0x380) or the lock pointer (+0x98) differ, "
                                 "'i' the vehicle id (+0xe8) is not the slot, 'u' the car could not be copied")
    elif not len(pst):
        verdict, todo = 'NO DATA', 'the ControllerSystem never named a player car: drive on track'
    else:
        verdict, todo = 'PASS', ''
    rep.verdict('Car table (identity)', verdict, ev, todo)
    rep.text("- Slot statuses: '.' a car with ERS, 's' a car without ERS (the safety car), 'n' null slot, 'u' unreadable, "
             "'t' not a CarLive, 'i' vehicle id not the slot index.")


def turns(rep, L, tl):
    """Turn number: labels in track order; the arrow against the steering in the corner."""
    lab = text(L['hud_turn'])
    shown = (lab != '-') & (L['hud_live'] == 1)
    passes, k = [], 0
    while k < len(lab):
        if not shown[k]:
            k += 1
            continue
        j = k
        while j + 1 < len(lab) and shown[j + 1] and lab[j + 1] == lab[k] and tl[j + 1] - tl[j] < 0.5:
            j += 1
        passes.append((lab[k], k, j))
        k = j + 1
    tlen = float(np.median(L['track_len_m'][shown])) if shown.any() else 0.0
    seen = sorted({p[0] for p in passes}, key=lambda s: turn_key(s) or (999, s))
    # Driving forward, each label is followed by the next one (a turn's window starts where the previous turn's ends,
    # so none is skipped), and the line is crossed only between the last turn and turn 1 (or during turn 1 when it
    # is shown before the line).
    succ = {la: seen[(i + 1) % len(seen)] for i, la in enumerate(seen)}
    fwd, bad, wrong = 0, 0, Counter()
    for (la, a0, a1), (lb, b0, b1) in zip(passes, passes[1:]):
        if tl[b0] - tl[a1] > 40:  # a long gap: the pits, a restart, the menus
            continue
        wrapped = L['lap_m'][b0] + 0.5 * tlen < L['lap_m'][a1]  # crossed the line in between
        if lb == la and not wrapped:
            continue
        if lb == succ[la] and (not wrapped or (la == seen[-1] and lb == seen[0])):
            fwd += 1
        else:
            bad += 1
            wrong[f'{la}>{lb}' + (' across the line' if wrapped else '')] += 1
    if fwd + bad < 5:
        rep.verdict('Turn number (order)', 'NO DATA', f'{len(passes)} turn passes, labels seen {seen}',
                    'drive a full lap (turn numbers need the lap distance)')
    else:
        share = fwd / (fwd + bad)
        rep.verdict('Turn number (order)', 'PASS' if share >= 0.9 else 'FAIL',
                    f'{len(passes)} turn passes; labels seen {seen}; {fwd} of {fwd + bad} label changes in track order '
                    f'(wrapping at the line)' + (f'; out of order: {dict(wrong.most_common(6))}' if wrong else ''),
                    'check that the number matches the corner on screen; a few out-of-order changes come from spins or '
                    'the pit lane')
    if 'hud_turn_right' not in L:
        return
    per, flips, arrow = defaultdict(list), 0, defaultdict(set)
    for la, a0, a1 in passes:
        tr = L['hud_turn_right'][a0:a1 + 1]
        arrow[la].add(int(tr[0]))
        if (tr != tr[0]).any() or tr[0] < 0:
            flips += 1
            continue
        seg = slice(a0 + (a1 - a0) // 2, a1 + 1)  # the half of the window closest to the corner
        m = (L['steer_ok'][seg] == 1) & (L['speed_kmh'][seg] > 30)
        if m.sum() < 3:
            continue
        s = L['steer'][seg][m]
        peak = float(s[np.argmax(np.abs(s))])
        if abs(peak) >= 0.08:
            per[la].append((peak > 0) == (tr[0] == 1))  # steer > 0 is right (UDP m_steer convention, static F)
    dec = {la: (sum(v), len(v)) for la, v in per.items()}
    agree = [la for la, (a, m) in dec.items() if 2 * a > m]
    changed = sorted(la for la, s in arrow.items() if len(s) > 1)
    by_label = ', '.join(f"T{la} {'R' if 1 in arrow[la] else 'L'} {dec[la][0]}/{dec[la][1]}"
                         for la in seen if la in dec)
    ev = (f'the arrow matches the steering direction near the corner for {len(agree)} of {len(dec)} turns '
          f'({by_label}); the arrow changed within a pass {flips} times' +
          (f'; between passes for turns {changed}' if changed else ''))
    if len(dec) < 4:
        rep.verdict('Turn arrow (steering)', 'NO DATA', ev, 'drive a full lap at speed: the check needs steering in each corner')
    else:
        share = len(agree) / len(dec)
        hint = ('nearly every turn is opposite: the arrow or the steering sign is inverted' if share < 0.2 else
                f'watch the arrow at turns {sorted(set(dec) - set(agree), key=lambda s: turn_key(s) or (999, s))}: '
                'a nearly straight corner can fool the steering check')
        rep.verdict('Turn arrow (steering)', 'PASS' if share >= 0.8 and not flips else 'FAIL', ev,
                    '' if share == 1 and not flips else hint)


def main():
    path = sys.argv[1]
    c, n = load(path)
    t = c['t']
    rep = Report()
    live = (c['veh_ok'] == 1) & (c['compatible'] == 1)
    dur = float(t[live][-1] - t[live][0]) if live.any() else 0.0

    # --- lifecycle
    gens = np.unique(c['generation'])
    rej = c['rejects']
    rep.verdict('Lifecycle', 'PASS' if live.any() else 'NO DATA',
                f'{len(gens)} car/session generations, player car found in {100 * live.mean():.0f}% of records, '
                f'max {int(rej.max())} rejected table slots in a frame, {int(c["dropped"].max())} records dropped',
                '' if live.any() else 'drive on track with the addon enabled')
    if 'humans' in c:
        act = (c['active'] == 1) & (c['compatible'] == 1)
        one = float((c['humans'][act] == 1).mean()) if act.any() else float('nan')
        rep.text(f'- is_ai rule: exactly one human-driven car in {100 * one:.0f}% of in-session records; '
                 f'{int(((c["humans"] != 1) & act & (c["veh_ok"] == 1)).sum())} records kept the held car '
                 f'(AI handover / loading), {int((act & (c["veh_ok"] == 0)).sum())} records had no player (halo hidden).')
    named = np.zeros(n, dtype=bool)
    if 'ctrl_hits' in c:
        act = (c['active'] == 1) & (c['compatible'] == 1)
        # the game names the player car (one local HumanController) but the provider has none: the halo is blank
        # while the player drives (an earlier table check rejected the car after the pit exit)
        named = (c['compatible'] == 1) & (c['ctrl_hits'] == 1) & (c['ctrl_vid'] >= 0)
        lost = named & (c['veh_ok'] == 0)
        lost_s, lost_at = longest(lost, t)
        lost_txt = (f'no player car while the ControllerSystem named one in {int(lost.sum())} of {int(named.sum())} '
                    f'records' + (f' (longest {lost_s:.1f} s from t = {t[lost_at]:.1f} s, vehicle '
                                  f'{int(c["ctrl_vid"][lost_at])})' if lost_at is not None else ''))
        lost_todo = 'the provider rejected the car the game names; Car table (identity) shows why (logs from 2026-11-09 on)'
        worst3 = sorted(((float(t[b] - t[a]) + RECORD_S, a, b) for a, b in runs(lost)), reverse=True)[:3]
        if worst3:
            sl = text(c['slots']) if 'slots' in c else None

            def at(k):
                vid = int(c['ctrl_vid'][k])
                st = sl[k][vid] if sl is not None and vid < len(sl[k]) and sl[k] != '-' else None
                return f'vehicle {vid}' + (f", slot '{st}'" if st else '')
            rep.text('- Player car lost while the ControllerSystem named it (longest first): ' +
                     ', '.join(f't = {t[a]:.1f}–{t[b]:.1f} s ({s:.1f} s, {at(a)})' for s, a, b in worst3) + '.')
        if act.any():
            hits = c['ctrl_hits'][act]
            readable = float((hits >= 0).mean())
            single = float((hits == 1).mean())
            both = act & (c['ctrl_vid'] >= 0) & (c['isai_vid'] >= 0)
            agree = float((c['ctrl_vid'][both] == c['isai_vid'][both]).mean()) if both.any() else float('nan')
            src = c['player_src'][act]
            spect = int((c['spect_vid'][act] >= 0).sum())
            ok = readable > 0.95 and single > 0.9 and (math.isnan(agree) or agree > 0.99)
            verdict = 'PASS' if ok and lost_s <= LOST_MAX_S else ('NO DATA' if readable == 0 else 'FAIL')
            rep.verdict('Player car (ControllerSystem)', verdict,
                        f'system readable in {100 * readable:.0f}% of in-session records, exactly one local human car in '
                        f'{100 * single:.0f}%; agrees with the is_ai rule in '
                        f'{"n/a" if math.isnan(agree) else f"{100 * agree:.1f}%"} of {int(both.sum())} records where both '
                        f'name a car; player source: ControllerSystem {100 * float((src == 2).mean()):.0f}%, is_ai fallback '
                        f'{100 * float((src == 3).mean()):.0f}%, none {100 * float((src == 0).mean()):.0f}%; '
                        f'spectate flag set in {spect} records (expect 0 while driving); {lost_txt}',
                        lost_todo if lost_s > LOST_MAX_S else 'include a formation lap and a pit stop (AI handovers)')
        elif named.any():
            rep.verdict('Player car (ControllerSystem)', 'FAIL', f'no car passed validation; {lost_txt}', lost_todo)
    if 'slots' in c:
        car_table(rep, c, n, t, live, named)
    L = {k: v[live] for k, v in c.items()}
    if not live.any():
        finish(rep, path, n, dur)
        return
    tl = L['t']

    # --- speed vs the game's own distance counter (independent object: VehicleProgressSystem)
    sp, sd = L['speed_kmh'], L['speed_dist_kmh']
    m = (L['speed_ok'] == 1) & (L['progress_ok'] == 1) & (sd != 0) & (sp > 20)
    if m.sum() > 50:
        err = np.abs(sp[m] - sd[m])
        ok = np.median(err) < 3 and corr(sp[m], sd[m]) > 0.95
        rep.verdict('Speed', 'PASS' if ok else 'FAIL',
                    f'median |speed − d(distance)/dt| = {np.median(err):.1f} km/h, r = {corr(sp[m], sd[m]):.3f}, '
                    f'{m.sum()} samples above 20 km/h; max {sp.max():.0f} km/h')
    else:
        rep.verdict('Speed', 'NO DATA', 'too few moving samples', 'drive a lap')
    still = (L['speed_ok'] == 1) & (sp < 1)
    rep.text(f'- Stationary samples: {still.sum()} (speed < 1 km/h); speed while stationary max {sp[still].max() if still.any() else float("nan"):.2f} km/h.')

    # --- gear: discrete, sequential, constant rpm/speed ratio per gear
    g = L['gear'][L['gear_ok'] == 1].astype(int)
    seen = sorted(set(g.tolist()))
    steps = np.diff(g)
    jumps = int((np.abs(steps[steps != 0]) > 1).sum())
    ratio_cv = []
    for gear in range(1, 9):
        mm = (L['gear'] == gear) & (L['speed_kmh'] > 30) & (L['rpm_ok'] == 1)
        if mm.sum() > 20:
            r = L['rpm'][mm] / L['speed_kmh'][mm]
            ratio_cv.append((gear, float(np.median(r)), float(np.std(r) / np.mean(r))))
    mono = all(ratio_cv[i][1] > ratio_cv[i + 1][1] for i in range(len(ratio_cv) - 1))
    tight = all(cv < 0.08 for _, _, cv in ratio_cv)
    if len(ratio_cv) >= 3:
        rep.verdict('Gear', 'PASS' if mono and tight else 'FAIL',
                    f'gears seen {seen}; rpm per km/h by gear ' + ', '.join(f'{gg}: {r:.1f} (cv {cv:.2f})' for gg, r, cv in ratio_cv) +
                    f'; {jumps} multi-step jumps between samples',
                    '' if -1 in seen else 'select reverse once to cover R')
    else:
        rep.verdict('Gear', 'NO DATA', f'gears seen {seen}', 'drive through at least 3 gears')

    # --- rpm: idle, limiter, drops on upshift
    rpm = L['rpm'][L['rpm_ok'] == 1]
    lim = L['limiter_rpm'][L['limiter_ok'] == 1]
    idle = L['rpm'][(L['rpm_ok'] == 1) & (L['speed_kmh'] < 1) & (L['throttle'] < 0.05)]
    up = np.nonzero(np.diff(L['gear']) == 1)[0]
    drops = [L['rpm'][i] - L['rpm'][min(i + 3, len(L['rpm']) - 1)] for i in up if L['speed_kmh'][i] > 40]
    ok = len(rpm) > 50 and rpm.max() <= (lim.max() * 1.02 if len(lim) else 20000) and (not drops or np.median(drops) > 500)
    rep.verdict('RPM', 'PASS' if ok else ('NO DATA' if len(rpm) <= 50 else 'FAIL'),
                f'range {rpm.min():.0f}–{rpm.max():.0f} rpm, limiter {np.median(lim) if len(lim) else float("nan"):.0f}, '
                f'idle median {np.median(idle) if len(idle) else float("nan"):.0f}, median drop on upshift '
                f'{np.median(drops) if drops else float("nan"):.0f} rpm over {len(drops)} upshifts')

    # --- pedals vs the car's longitudinal acceleration (from the speed signal, not from the g field)
    dv = np.gradient(L['speed_kmh'] / KMH, tl)
    thr, brk = L['throttle'], L['brake']
    mv = (L['input_ok'] == 1) & (L['speed_kmh'] > 30)
    full_thr = mv & (thr > 0.95) & (brk < 0.05)
    hard_brk = mv & (brk > 0.6)
    if full_thr.sum() > 20 and hard_brk.sum() > 10:
        a_thr, a_brk = float(np.median(dv[full_thr])), float(np.median(dv[hard_brk]))
        rep.verdict('Throttle', 'PASS' if a_thr > 0.3 else 'FAIL', f'median accel at full throttle {a_thr:.1f} m/s², {full_thr.sum()} samples')
        rep.verdict('Brake', 'PASS' if a_brk < -5 else 'FAIL', f'median accel under brake > 60% {a_brk:.1f} m/s², {hard_brk.sum()} samples')
    else:
        rep.verdict('Throttle', 'NO DATA', f'{full_thr.sum()} full-throttle samples', 'accelerate flat out down a straight')
        rep.verdict('Brake', 'NO DATA', f'{hard_brk.sum()} heavy-braking samples', 'brake hard into a corner')
    both = mv & (thr > 0.5) & (brk > 0.5)
    rep.text(f'- Throttle and brake both above 50%: {both.sum()} samples (should be near 0).')
    rev = (L['gear'] == -1) & (L['input_ok'] == 1)
    rep.text(f'- Reverse samples: {rev.sum()}; input flags seen: {sorted(set(L["input_flags"].astype(int).tolist()))}.')

    # --- g fields vs the speed derivative
    acc = (L['accel_ok'] == 1) & mv
    if acc.sum() > 50:
        r_long = corr(L['g_long'][acc], dv[acc] / 9.81)
        rep.verdict('Longitudinal g (extra)', 'PASS' if abs(r_long) > 0.8 else 'FAIL',
                    f'r(g_long, dv/dt) = {r_long:.2f} (sign tells the axis direction)')

    # --- energy: the battery's rate of change vs the power channels
    es = (L['store_ok'] == 1) & (L['power_ok'] == 1)
    if es.sum() > 100:
        e = L['store_mj'][es] * 1e6
        te = tl[es]
        dEdt = np.gradient(e, te)
        net = (L['harvest_k_kw'][es] + L['harvest_h_kw'][es] - L['deploy_kw'][es]) * 1e3
        sm = lambda x: np.convolve(x, np.ones(9) / 9, mode='same')
        cap = np.median(L['capacity_mj'][es]) * 1e6 if (L['capacity_ok'][es] == 1).any() else 4e6
        free = (e > 0.05e6) & (e < cap - 0.05e6)  # the store saturates at empty and full: rate != power there
        r_e = corr(sm(dEdt)[free], sm(net)[free])
        harvest = L['harvest_k_kw'][es]
        deploy = L['deploy_kw'][es]
        brk_h = np.median(harvest[L['brake'][es] > 0.5]) if (L['brake'][es] > 0.5).any() else float('nan')
        thr_d = np.median(deploy[L['throttle'][es] > 0.95]) if (L['throttle'][es] > 0.95).any() else float('nan')
        ok = r_e > 0.8
        rep.verdict('Battery energy', 'PASS' if (e.min() >= 0 and e.max() <= 4.2e6) else 'FAIL',
                    f'{e.min() / 1e6:.2f}–{e.max() / 1e6:.2f} MJ (capacity {np.median(L["capacity_mj"]):.2f} MJ)')
        # a parked car gives no braking / full-throttle samples and a flat store (r = nan): that is missing data, not a fail
        no_h, no_d = bool(np.isnan(brk_h) or np.isnan(r_e)), bool(np.isnan(thr_d) or np.isnan(r_e))
        rep.verdict('Recharge (harvest power)', 'NO DATA' if no_h else ('PASS' if ok and brk_h > 20 else 'FAIL'),
                    f'r(dE/dt, harvest − deploy) = {r_e:.2f}; median MGU-K harvest under braking {brk_h:.0f} kW',
                    'brake hard into a few corners' if no_h else '')
        rep.verdict('Deploy (deploy power)', 'NO DATA' if no_d else ('PASS' if ok and thr_d > 20 else 'FAIL'),
                    f'median deploy at full throttle {thr_d:.0f} kW (max {deploy.max():.0f} kW, limit {np.median(L["max_deploy_kw"]):.0f} kW)',
                    'accelerate flat out down a straight' if no_d else '')
        low = e.min() < 0.5e6
        rep.text(f'- Low-battery state reached: {"yes" if low else "no"} (minimum {e.min() / 1e6:.2f} MJ).')
    else:
        rep.verdict('Battery / Recharge / Deploy', 'NO DATA', 'energy channels not read', 'drive a lap')

    # --- ERS mode: Boost is mode 2 (the Boost control's handler writes it; the stock HUD shows eActive for it)
    modes = sorted(set(L['ers_mode'][L['mode_ok'] == 1].astype(int).tolist()))
    ch = np.nonzero(np.diff(L['ers_mode']) != 0)[0]
    boost = (L['mode_ok'] == 1) & (L['ers_mode'] == 2)
    presses = runs(boost)
    held = [float(tl[b] - tl[a]) + RECORD_S for a, b in presses]
    hud_b = int(((L['hud_boost'] == 1) != boost).sum())
    ft = (L['throttle'] > 0.95) & (L['speed_kmh'] > 100) & (L['power_ok'] == 1) & (L['store_mj'] > 0.2)
    on, off = ft & boost, ft & ~boost & (L['mode_ok'] == 1)
    d_on = float(np.median(L['deploy_kw'][on])) if on.sum() > 10 else float('nan')
    d_off = float(np.median(L['deploy_kw'][off])) if off.sum() > 10 else float('nan')
    if hud_b:
        b_verdict, b_todo = 'FAIL', "the halo's Boost light does not follow the mode: send the log"
    elif len(presses) >= 2:
        b_verdict, b_todo = 'PASS', ("check that the halo's Boost light came on with the game's own Boost indicator "
                                     '(the log cannot see the button)')
    else:
        b_verdict, b_todo = 'NO DATA', ("press Boost twice (hold it once, tap it once) and watch the halo's Boost light "
                                        "against the game's own Boost indicator")
    rep.verdict('Boost (ERS mode 2)', b_verdict,
                f'modes seen {modes}, {len(ch)} mode changes; {len(presses)} Boost activations' +
                (f' (median {np.median(held):.1f} s, longest {max(held):.1f} s)' if held else '') +
                f'; HUD Boost lit in {100 * L["hud_boost"].mean():.0f}% of records, disagreeing with mode 2 in {hud_b}; '
                f'median deploy at full throttle above 100 km/h {d_on:.0f} kW in Boost, {d_off:.0f} kW otherwise', b_todo)
    flags = L['ers_flags']
    hexs = [v if isinstance(v, str) else f'{int(v):08d}' for v in flags.tolist()]  # all-digit values parse as numbers
    om = np.array([int(h[4:6], 16) != 0 if len(h) == 8 else False for h in hexs])  # +0x1a62: Overtake Mode active
    lt = (L['session_type'] >= 1) & (L['session_type'] <= 14) & (L['speed_kmh'] > 30)
    rc = (L['session_type'] >= 15) & (L['session_type'] <= 17) & (L['speed_kmh'] > 30)
    if lt.sum() > 50:
        share = float(om[lt].mean())
        rep.verdict('Overtake (Overtake Mode active, +0x1a62)', 'PASS' if share > 0.9 else 'FAIL',
                    f'set in {100 * share:.0f}% of moving practice/qualifying records (2026 rule: active at all times in '
                    f'lap-time sessions), {100 * float(om[rc].mean()) if rc.any() else float("nan"):.0f}% in races; '
                    "the halo binds the game's own om_active",
                    'a FAIL with a 2026 car means the game does not apply that rule: check OVERTAKE against the MFD')
    else:
        rep.verdict('Overtake (Overtake Mode active, +0x1a62)', 'NO DATA', 'no moving practice/qualifying records',
                    'drive a practice lap in a 2026 car')
    uniq = sorted(set(flags.tolist()))
    rep.text(f'- Overtake Mode bytes +0x1a60..63 (eligible, armed at detection, active, earned while suspended) seen: '
             f'{uniq[:12]}{" …" if len(uniq) > 12 else ""}.')

    # --- progress
    pg = L['progress_ok'] == 1
    laps = sorted(set(L['lap'][pg].astype(int).tolist()))
    tlen = np.median(L['track_len_m'][pg]) if pg.any() else 0
    wraps = int((np.diff(np.floor(L['total_m'][pg] / tlen)) == 1).sum()) if tlen > 0 else 0
    lap_inc = int((np.diff(L['lap'][pg]) == 1).sum())
    rep.verdict('Lap distance / lap', 'PASS' if wraps > 0 and abs(wraps - lap_inc) <= 1 else ('NO DATA' if wraps == 0 else 'FAIL'),
                f'laps {laps[:3]}…{laps[-3:]}, {wraps} distance wraps vs {lap_inc} lap increments; '
                f'track {np.median(L["track_len_m"]):.0f} m, name "{L["track_name"][0]}"' +
                (f'; entry → car link matched in {100 * L["progress_link"][pg].mean():.0f}% of records'
                 if 'progress_link' in L and pg.any() else ''),
                '' if wraps else 'cross the line at least once')

    # --- turn number and arrow
    turns(rep, L, tl)

    # --- position: the session classification the game's own UI shows (the results system's entries)
    if 'classified' in L:
        def positions(s):
            s = str(s)
            return [int(s[1 + 2 * i:3 + 2 * i], 16) for i in range((len(s) - 1) // 2)] if s.startswith('p') else []
        found = L['results_found'] == 1
        cl = (L['classified'] == 1) & (L['session_type'] != 18)
        perm, rival_ok, rival_n = 0, 0, 0
        for k in np.nonzero(cl)[0]:
            p = positions(L['cls'][k])
            got = sorted(x for x in p if x)
            perm += len(got) >= 2 and got == list(range(1, len(got) + 1))
            own = int(L['own_pos'][k])
            want = 2 if own == 1 else own - 1
            rid = int(L['hud_rival_id'][k])
            if want in p:
                rival_n += 1
                rival_ok += 0 <= rid < len(p) and p[rid] == want
        race = cl & (L['session_type'] >= 15) & (L['session_type'] <= 17) & (L['player_rank'] >= 0) & (L['progress_ok'] == 1)
        agree = float((L['own_pos'][race] == L['player_rank'][race] + 1).mean()) if race.sum() > 50 else float('nan')
        if not found.any():
            rep.verdict('Position (classification)', 'FAIL', 'the results system was never found in the component registry',
                        'send the log: the registry key may differ in this build')
        elif not cl.any():
            rep.verdict('Position (classification)', 'NO DATA', f'results system found in {100 * found.mean():.0f}% of records, '
                        'classification never complete', 'drive a practice session for a lap')
        else:
            perm_ok = perm >= 0.95 * cl.sum()
            race_ok = math.isnan(agree) or agree >= 0.8
            rv_ok = rival_n == 0 or rival_ok == rival_n
            rep.verdict('Position (classification)', 'PASS' if perm_ok and race_ok and rv_ok else 'FAIL',
                        f'results system found in {100 * found.mean():.0f}% of records; a full permutation 1..N in '
                        f'{100 * perm / cl.sum():.0f}% of {cl.sum()} classified records; race: own position = road order in '
                        f'{"n/a" if math.isnan(agree) else f"{100 * agree:.0f}%"} of {race.sum()} records; '
                        f'rival lane = one place ahead in {rival_ok}/{rival_n} records',
                        'in practice or qualifying, check that the rival name is the car one place above you on the '
                        "game's timing tower (that order is L2)")
    else:
        rep.verdict('Position (classification)', 'NO DATA', 'log written by an older build (no classification columns)',
                    'update the addon')

    # --- HUD shows what was read (pedal slats are eased with a 35 ms time constant: within one slat)
    hk = (L['hud_speed_ok'] == 1)
    mis = int((np.abs(L['hud_kmh'][hk] - np.round(L['speed_kmh'][hk])) > 1).sum())
    gmis = int(((L['hud_gear'] != L['gear']) & (L['hud_gear_ok'] == 1)).sum())
    pmis = int((L['hud_pedals_ok'] != L['input_ok']).sum())
    pd = (L['hud_pedals_ok'] == 1) & (L['input_ok'] == 1)
    th_ok = br_ok = float('nan')
    if pd.sum() > 50:
        th_ok = float((np.abs(L['hud_th_lv'][pd] - np.round(np.clip(L['throttle'][pd], 0, 1) * STRIPES)) <= 1).mean())
        br_ok = float((np.abs(L['hud_br_lv'][pd] - np.round(np.clip(L['brake'][pd], 0, 1) * STRIPES)) <= 1).mean())
    slats_ok = math.isnan(th_ok) or (th_ok >= 0.9 and br_ok >= 0.9)
    rep.verdict('HUD = state', 'PASS' if mis == 0 and gmis == 0 and pmis == 0 and hud_b == 0 and slats_ok else 'FAIL',
                f'{mis} km/h mismatches, {gmis} gear mismatches, {hud_b} Boost mismatches, {pmis} pedal-availability '
                f'mismatches between the read state and the published leaves; throttle slats within one of the read '
                f'throttle in {pct(th_ok)}, brake slats in {pct(br_ok)} of {int(pd.sum())} records')

    # --- the halo's own cost on the game's flow thread (whole log, not only live frames)
    if 'cost_frames' in c:
        fr = c['cost_frames']
        ok = fr > 0
        if ok.any():
            mean = float((c['cost_mean_us'][ok] * fr[ok]).sum() / fr[ok].sum())
            p99 = float(np.percentile(c['cost_max_us'][ok], 99))
            worst = float(c['cost_max_us'][ok].max())
            fps = float(fr[ok].sum() / max(1e-9, t[-1] - t[0]))
            budget = 1e6 / fps if fps > 0 else 0
            rep.verdict('Performance', 'PASS' if mean < 0.01 * budget and p99 < 1000 else 'FAIL',
                        f'{mean:.1f} us/frame mean, {p99:.0f} us p99 of the per-record worst, {worst:.0f} us worst; '
                        f'{fps:.0f} fps, so the mean is {100 * mean / budget:.2f} % of a frame' if budget else 'no frame rate',
                        '' if mean < 0.01 * budget else 'report the CPU and frame rate')
    else:
        rep.verdict('Performance', 'NO DATA', 'log written by an older build (no cost columns)', 'update the addon')

    finish(rep, path, n, dur)


if __name__ == '__main__':
    main()
