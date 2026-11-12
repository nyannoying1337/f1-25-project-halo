// tower_model.cpp - the timing tower's display logic. Contract: docs/timing-tower/leaves.md.
#include "tower_model.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace tower {
namespace {

bool is_race(uint32_t t) { return t >= 15 && t <= 17; }
bool is_timed(uint32_t t) { return t >= 1 && t <= 14; }

void put(char *dst, size_t cap, const char *s)
{
    std::snprintf(dst, cap, "%s", s);
}

// " sG1D3": the spectator menu's Gap and Detail the tower follows ('-' its own setting); for the debug line
const char *spect_tag(int g, int d)
{
    static char b[8];
    std::snprintf(b, sizeof b, " sG%cD%c", g >= 0 ? char('0' + g) : '-', d >= 0 ? char('0' + d) : '-');
    return b;
}

} // namespace

// The knockout zone (field-traces.md 5.1). The game marks a car in its drop zone when its 0-based position
// index is above the session's cut (in_drop_zone), and its results code treats the knockout segments 5, 6, 10, 11
// (Q1, Q2, SQ1, SQ2) apart (Sess_PQRuleset_FinaliseResults, mask 0xc60). The cut is not readable through plain
// pointers; its shape from the code with the qualifying rules' inputs: Q1 / SQ1 keep 10 + (n - 10) / 2 cars (16 of
// 22, 15 of 20), Q2 / SQ2 keep 10. Seen in game: Q2 held 16 cars after a 22-car Q1 (2026-11-10).
// Inferred: the Q2 / SQ2 cut and other field sizes.
int knockout_safe(uint32_t session, int n)
{
    int safe = -1;
    if (session == 5 || session == 10)
        safe = n > 10 ? 10 + (n - 10) / 2 : -1;
    else if (session == 6 || session == 11)
        safe = 10;
    return safe > 0 && n > safe ? safe : -1;
}

void race_gap_text(int64_t ms, char *out, size_t cap)
{
    const long long tenths = (long long)(ms / 100); // cut, not rounded
    if (tenths < 600)
        std::snprintf(out, cap, "+%lld.%lld", tenths / 10, tenths % 10);
    else
        std::snprintf(out, cap, "+%lld:%02lld.%lld", tenths / 600, (tenths % 600) / 10, tenths % 10);
}

void lap_time_text(int64_t ms, char *out, size_t cap)
{
    const long long tenths = (long long)(ms / 100); // cut, not rounded, like the gaps
    if (tenths < 600)
        std::snprintf(out, cap, "%lld.%lld", tenths / 10, tenths % 10);
    else
        std::snprintf(out, cap, "%lld:%02lld.%lld", tenths / 600, (tenths % 600) / 10, tenths % 10);
}

int64_t game_lap_ms(float s)
{
    // the game's board (Fastest Lap, 0x14177a59d): vmulss by 1000.0f, then vcvttss2si (single precision, cut)
    const float p = s * 1000.0f;
    return int64_t(p);
}

void best_lap_text(int64_t ms, char *out, size_t cap)
{
    const long long m = (long long)(ms / 60000), r = (long long)(ms % 60000);
    if (m > 0)
        std::snprintf(out, cap, "%lld:%02lld.%03lld", m, r / 1000, r % 1000);
    else
        std::snprintf(out, cap, "%lld.%03lld", r / 1000, r % 1000);
}

void best_gap_text(int64_t ms, char *out, size_t cap)
{
    const long long m = (long long)(ms / 60000), r = (long long)(ms % 60000);
    if (m > 0)
        std::snprintf(out, cap, "+%lld:%02lld.%03lld", m, r / 1000, r % 1000);
    else
        std::snprintf(out, cap, "+%lld.%03lld", r / 1000, r % 1000);
}

void penalty_text(int dt, int sg, bool tpen_ok, float tpen_s, char *out, size_t cap)
{
    // unserved first (they still have to be served), then the time added to the race time (whole seconds; no '+',
    // so "5s" does not read as part of the gap "+5.1" beside it)
    const long s = tpen_ok && tpen_s > 0.f ? std::lround(tpen_s) : 0;
    if (dt > 0)
        put(out, cap, "DT");
    else if (sg > 0)
        put(out, cap, "SG");
    else if (s > 0)
        std::snprintf(out, cap, "%lds", std::min(s, 999L));
    else
        put(out, cap, "");
}

const char *session_label(uint32_t t)
{
    static const char *const kLabel[] = {"",    "P1",  "P2", "P3",  "P",   "Q1", "Q2", "Q3", "Q",  "OSQ",
                                         "SQ1", "SQ2", "SQ3", "SQ", "OSQ", "R",  "R2", "R3", "TT"};
    return t < sizeof kLabel / sizeof kLabel[0] ? kLabel[t] : "";
}

void window(int count, int n, int pi, Mode mode, int &start, int &rows)
{
    start = 0;
    rows = 0;
    if (count <= 0)
        return;
    n = std::clamp(n, 1, kRows);
    if (mode == Mode::full) {
        rows = std::min(count, kRows);
        return;
    }
    rows = std::min(n, count);
    if (mode == Mode::compact && pi >= 0)
        start = std::clamp(pi - n / 2, 0, count - rows);
}

int Model::arrow(int vid, double now) const
{
    if (vid < 0 || vid >= kCars || arrow_until_[vid] <= now)
        return 0;
    return arrow_dir_[vid];
}

// A car whose classification position improved gets ▲, one that lost places ▼, for kArrowSeconds; a newer change
// restarts it. Only between two valid reads of one car set (the caller resets on a new generation or session).
void Model::track_arrows(const Classification &c, double now)
{
    if (have_prev_)
        for (int vid = 0; vid < kCars; ++vid) {
            const int a = prev_pos_[vid], b = c.pos[vid];
            if (!a || !b || a == b)
                continue;
            arrow_dir_[vid] = int8_t(b < a ? 1 : -1);
            arrow_until_[vid] = now + kArrowSeconds;
        }
    std::memcpy(prev_pos_, c.pos, sizeof prev_pos_);
    have_prev_ = true;
}

// The lap time flash (ui-build.md 20). It follows each classified car's best lap (the results entry's time,
// confirmed as the best lap in timed sessions). Taken without a flash: the first read, a new car set or session
// type (the reset in update), the tracking off (no best laps: a race, the spectator menu's Gap, the tower off). Per
// car: a time that rises or goes (a flashback, a replay rewind, a deleted lap) is taken over quietly and ends that
// car's flash; a time that falls, or a first time, flashes for kFlashSeconds: purple when it is below every other
// car's time, else green (a tie is green). kFlashFill or more cars improving in one read is the game filling the
// laps, taken over quietly. No flash for a car that is not classified.
void Model::track_flash(const Classification &c, bool active, double now)
{
    if (!active) {
        fx_base_ = false;
        std::memset(fx_kind_, 0, sizeof fx_kind_);
        return;
    }
    int64_t t[kCars];
    for (int id = 0; id < kCars; ++id)
        t[id] = -1;
    for (int i = 0; i < c.n && i < kCars; ++i) {
        const int id = c.order[i];
        if (id < kCars && c.lap_ok[id])
            t[id] = game_lap_ms(c.lap_s[id]);
    }
    if (!fx_base_) {
        std::memcpy(fx_ms_, t, sizeof fx_ms_);
        std::memset(fx_kind_, 0, sizeof fx_kind_);
        fx_base_ = true;
        return;
    }
    int better = 0;
    for (int id = 0; id < kCars; ++id)
        better += t[id] >= 0 && (fx_ms_[id] < 0 || t[id] < fx_ms_[id]);
    const bool fill = better >= kFlashFill;
    for (int id = 0; id < kCars; ++id) {
        const int64_t was = fx_ms_[id];
        fx_ms_[id] = t[id];
        if (t[id] == was)
            continue;
        if (t[id] < 0 || (was >= 0 && t[id] > was) || fill) {
            fx_kind_[id] = 0;
            continue;
        }
        bool overall = true;
        for (int o = 0; o < kCars; ++o)
            overall = overall && (o == id || t[o] < 0 || t[id] < t[o]);
        fx_kind_[id] = overall ? 2 : 1;
        fx_until_[id] = now + kFlashSeconds;
    }
    for (int id = 0; id < kCars; ++id)
        if (fx_kind_[id] && (now >= fx_until_[id] || now < fx_until_[id] - kFlashSeconds))
            fx_kind_[id] = 0;
}

void Model::update(const Snapshot &s, const Frame &f, const Settings &cfg, double now)
{
    const uint32_t session = f.session_ok ? f.session : ~0u;
    // Nothing carries over into another car set, and nothing is kept while the tower is off (the reader is not
    // updated then, so its snapshot can belong to a car set that is gone).
    if (f.generation != generation_ || session != session_ || !cfg.enabled) {
        generation_ = f.generation;
        session_ = session;
        have_prev_ = false;
        have_held_ = false;
        std::memset(arrow_until_, 0, sizeof arrow_until_);
        std::memset(arrow_dir_, 0, sizeof arrow_dir_);
        flag_seq_ = 0; // the reader's flags read count restarts with its snapshot
        yel_ = false;
        yel_misses_ = 0;
        zred_ = false;
        zred_misses_ = 0;
        fx_base_ = false; // the flash starts again from the next read
        std::memset(fx_kind_, 0, sizeof fx_kind_);
        fl_vid_ = -1;
    }
    // the yellow flag and the zones' red, once per flags read (the reader bumps seq on every read)
    const FlagRead &fl = s.flags;
    const bool flags_fresh = cfg.enabled && fl.seq && now - fl.t <= kFlagMaxAge && now >= fl.t;
    if (!flags_fresh) {
        yel_ = false;
        yel_misses_ = 0;
        zred_ = false;
        zred_misses_ = 0;
    } else if (fl.seq != flag_seq_) {
        flag_seq_ = fl.seq;
        // red from the zones: every zone at 4. In game (2026-11-09 17:44 log, L3) a red flag turned all 17 zones to 4
        // in one read while the red flag byte stayed 0; the SC deployment before it turned them all yellow, and two
        // retirements in between changed no zone. Held over one other read, like the yellow (the writer clears each
        // zone to 0 before it writes the new value); an unreadable list drops it at once.
        int zones_at_4 = 0;
        for (int i = 0; fl.zones_ok && i < fl.zones && i < int(kMaxMarshalZones); ++i)
            zones_at_4 += fl.flag[i] == zone_red;
        if (fl.zones_ok && fl.zones > 0 && zones_at_4 == fl.zones) {
            zred_ = true;
            zred_misses_ = 0;
        } else if (fl.zones_ok && zred_ && zred_misses_ < kYellowHoldReads) {
            ++zred_misses_;
        } else {
            zred_ = false;
            zred_misses_ = 0;
        }
        if (!fl.zones_ok) {
            yel_ = false;
            yel_misses_ = 0;
        } else if (fl.yellow > 0) {
            yel_ = true;
            yel_misses_ = 0;
            ysec_ = fl.ysec;
            yun_ = fl.unmapped || !fl.ysec;
        } else if (yel_ && yel_misses_ < kYellowHoldReads) {
            ++yel_misses_;
        } else {
            yel_ = false;
            yel_misses_ = 0;
        }
    }
    // the classification: a fresh valid read, else the last valid one for kClsHold. The first valid read after a
    // reset is only the arrows' reference.
    const Classification *cls = nullptr;
    bool held = false;
    if (cfg.enabled && s.cls.ok) {
        if (s.cls.seq != cls_seq_ || !have_prev_) {
            cls_seq_ = s.cls.seq;
            track_arrows(s.cls, now);
        }
        held_ = s.cls;
        held_t_ = s.cls.t;
        have_held_ = true;
        cls = &s.cls;
    } else if (have_held_ && now - held_t_ <= kClsHold && now >= held_t_) {
        cls = &held_;
        held = true;
    }

    View v;
    v.set = cfg;
    v.held = held;
    // the game's spectator menu (docs/spectator-ui.md 10.4), while its spectator HUD is up and the tower follows the
    // watched car. Gap (+0xe4): 0 no gap column (as the Intervals setting off), 1 interval, 2 leader, 3 each car's
    // lap time. Detail (+0xe8): the detail cell (the tyre cell) is off at 0; 1 position change, 2 stops, 3 the tyre
    // letter, 4 the tyre of the best lap, 5 the penalty (1, 2 and 4 from the game's own values).
    // Another value: the settings.
    if (f.spect && f.spect_gap <= 3) {
        v.sgap = int(f.spect_gap);
        v.set.gaps = f.spect_gap != 0;
    }
    if (f.spect && f.spect_detail <= 5) {
        v.sdet = int(f.spect_detail);
        v.set.tyres = f.spect_detail != 0;
    }
    const bool race = f.session_ok && is_race(f.session), timed = f.session_ok && is_timed(f.session);
    // Time Trial: the game's mode label, fresh. A failed or stale read is no Time Trial (the rule below as before).
    const ModeRead &md = s.mode;
    v.trial = cfg.enabled && md.ok && md.time_trial && now - md.t <= kModeMaxAge && now >= md.t;
    v.on = cfg.enabled && cls && (race || timed) && !v.trial;
    v.show = v.on || v.trial;
    // gap mode: Auto starts with Interval whenever it is chosen or the tower comes on
    if (cfg.gap_mode != last_gap_mode_ || (v.on && !was_on_))
        auto_t0_ = now;
    last_gap_mode_ = cfg.gap_mode;
    was_on_ = v.on;
    const double period = std::clamp(cfg.auto_period, 5.0, 60.0);
    v.lead = v.sgap >= 0 ? v.sgap == 2
                         : cfg.gap_mode == GapMode::leader ||
                               (cfg.gap_mode == GapMode::autoswitch &&
                                (long long)(std::floor((now - auto_t0_) / period)) % 2 == 1);
    // best laps: timed sessions, and the spectator menu's Interval and Leader too (Leader as the HUD tower:
    // the gap to P1's best lap; Interval: to the best lap of the car directly ahead); its Fastest Lap keeps the
    // game's lap time, None no column. Races: the spectator modes as before.
    v.best = timed && (v.sgap < 0 || v.sgap == 1 || v.sgap == 2);
    v.laps = v.sgap == 3 || v.best;
    v.flap = v.sgap == 3; // the template sets every row's lap time at its lap time size (leaf flap)
    if (!v.on) {
        track_flash(held_, false, now);
        std::snprintf(v.dbg, sizeof v.dbg, v.trial ? "time trial" : "off");
        v_ = v;
        return;
    }
    const Classification &c = *cls;
    v.race = race;
    v.timed = timed;
    put(v.sess, sizeof v.sess, session_label(f.session));
    v.count = c.n;
    // the knockout zone's field: the most cars classified since the session type changed (or since the
    // tower came back after more than kKoFieldGap off), so the next segment's smaller field read while the type
    // still says the last one does not move the cut (an in-game test: 3.3 s of session 5 with Q2's 16 cars)
    if (session != ko_session_ || now - ko_t_ > kKoFieldGap || now < ko_t_) {
        ko_session_ = session;
        ko_n_ = 0;
    }
    ko_t_ = now;
    ko_n_ = std::max(ko_n_, c.n);
    // and only on the game's own order for the session. A session switch can show the next session's grid while
    // the type still says the last one: an in-game log, t 787.8-788.5, has the race's 22 cars in vehicle-id order
    // with no lap times while the type still read Q2, after the tower had been off 68 s (earlier builds hatched P11-P22
    // for 0.8 s). At the four segment starts in the logs the cars had no times either but stood in the game's order,
    // never the vehicle ids'. So no zone while no classified car has a lap time and the order is the vehicle ids' own.
    // The classification's own copy, no new read
    bool any_time = false, id_order = true;
    for (int i = 0; i < c.n; ++i) {
        const int vid = c.order[i];
        any_time = any_time || (c.lap_ok[vid] && game_lap_ms(c.lap_s[vid]) > 0);
        id_order = id_order && vid == i;
    }
    v.ko_safe = any_time || !id_order ? knockout_safe(f.session, ko_n_) : -1;
    for (int i = 0; i < c.n; ++i)
        if (c.order[i] == f.player)
            v.player_index = i;
    window(c.n, cfg.rows, v.player_index, cfg.mode, v.start, v.rows);
    v.trunc = cfg.mode == Mode::full && c.n > kRows;

    // header: the leader's lap (broadcast convention), the flags, the safety car, the chequered flag
    const int leader = c.n > 0 && c.pos[c.order[0]] == 1 ? c.order[0] : -1;
    const PitLaps &pl = s.pitlaps;
    // red: the red flag system (1 or 2), or every marshal zone at 4 (field-traces.md §7.2, in-game log 17:44)
    v.red = flags_fresh && (fl.red == 1 || fl.red == 2 || zred_);
    v.yel = yel_;
    if (yel_ && !yun_) {
        size_t k = 0;
        for (int i = 0; i < kMaxSectors; ++i)
            if ((ysec_ >> i) & 1u) {
                if (k)
                    v.ysec[k++] = ' ';
                v.ysec[k++] = char('1' + i);
            }
        v.ysec[k] = 0;
    }
    v.ysna = yel_ && yun_;
    if (race) {
        v.lapna = true;
        if (leader >= 0 && pl.lap_have[leader]) {
            const int lap = pl.lap[leader] + (c.status[leader] == 3 ? 0 : 1); // the counter is 0 on lap 1
            if (lap >= 1) {
                std::snprintf(v.lap, sizeof v.lap, "%d", lap);
                v.lapna = false;
            }
        }
        v.chq = leader >= 0 && c.status[leader] == 3;
        // the SC byte also reads 1 under a red flag (in-game log 2026-11-09 16:39): the red flag wins
        v.sc = s.sc.state == 1 && !v.red;
        v.vsc = s.sc.state == 2 && !v.red;
    }
    v.hs = v.chq ? 4 : v.red ? 3 : v.sc ? 1 : v.vsc ? 2 : v.yel ? 5 : 0;

    // best laps: P1's time is the reference; a car whose time is below a time classified ahead of it is not shown
    // (the order and the field disagree: no gap is made up)
    int64_t best_ms[kCars];
    bool best_ok[kCars] = {};
    if (v.best) {
        int64_t prev = -1;
        for (int i = 0; i < c.n; ++i) {
            const int id = c.order[i];
            if (!c.lap_ok[id])
                continue;
            best_ms[id] = game_lap_ms(c.lap_s[id]);
            ++v.best_n;
            if (best_ms[id] < prev) {
                ++v.best_inv;
                continue;
            }
            prev = best_ms[id];
            best_ok[id] = true;
        }
        if (leader >= 0 && best_ok[leader])
            v.best_p1 = best_ms[leader];
    }
    // the flash (also in every spectator Gap mode with a gap column): timed sessions, not the menu's None
    track_flash(c, timed && v.sgap != 0, now);
    std::memcpy(v.fx, fx_kind_, sizeof v.fx);
    // the race's fastest lap: the game's own fastest car, VehicleLapTimes +0xb8 (set by the game's rule at a
    // lap's end, field-traces.md §11), when it is a classified car; its time from its lap table (the log). An earlier build's
    // lowest results-entry lap time is not used: a race log could not show it as the best lap
    const LapTimes &lt = s.laps;
    if (race) {
        const int fc = lt.fastest_ok && lt.fastest < kCars ? int(lt.fastest) : -1;
        fl_vid_ = fc >= 0 && c.pos[fc] > 0 ? fc : -1;
        v.fl_vid = fl_vid_;
        v.fl_ms = fl_vid_ >= 0 && lt.best_ok[fl_vid_] ? lt.best_ms[fl_vid_] : -1;
    } else {
        fl_vid_ = -1;
    }
    const Timing &tm = s.timing;
    const Penalties &pen = s.pen;
    // Detail Position Change: a grid is one slot per car; two classified cars on one slot (an unwritten or
    // foreign field) is no grid, so no car's change is shown (the dim bar)
    bool grid_dup = false;
    uint64_t grid_seen = 0;
    for (int i = 0; i < c.n; ++i) {
        const int g = c.grid[c.order[i]];
        if (g <= 0 || g > 64)
            continue;
        grid_dup = grid_dup || ((grid_seen >> (g - 1)) & 1u);
        grid_seen |= 1ull << (g - 1);
    }
    for (int k = 0; k < v.rows; ++k) {
        const int idx = v.start + k, vid = c.order[idx];
        RowView &r = v.row[k];
        r.on = true;
        r.vid = vid;
        v.car_row[vid] = k;
        r.pos = c.pos[vid];
        r.p1 = r.pos == 1;
        const uint8_t st = c.status[vid];
        // out: retired, DSQ, NC (4..7). Timed sessions: a car with a best lap keeps its row and time (an in-game
        // test: every car still out on track went to 7 when Q1 ended, the player through to Q2 included)
        r.out = (st == 4 || st == 5 || st == 6 || st == 7) && !(timed && c.lap_ok[vid]);
        r.fl = v.fl_vid == vid;
        r.me = cfg.highlight && vid == f.player;
        r.ko = v.ko_safe > 0 && !r.out && r.pos > v.ko_safe;
        const int a = cfg.arrows ? arrow(vid, now) : 0;
        r.up = a > 0;
        r.dn = a < 0;
        if (!r.out) {
            r.pit = pl.pit_have[vid] && in_pit(pl.pit[vid]);
            r.pen = (pen.mc_ok && (pen.dt[vid] > 0 || pen.sg[vid] > 0)) || (c.tpen_ok[vid] && c.tpen_s[vid] > 0.f);
        }
        // team badge: the game's pill shows it for every car in the standings, out or not
        const BadgeRead &b = s.badges.car[vid];
        if ((b.state == kBadgeKey || b.state == kBadgeRender) && b.key >= 0 && b.key < s.badges.keys &&
            b.key < kCars && s.badges.render[b.key] == (b.state == kBadgeRender)) {
            r.bdg = true;
            r.bkey = b.key;
            r.brender = b.state == kBadgeRender;
            std::memcpy(r.badge, s.badges.key[b.key], kBadgeKeyMax);
            r.badge[kBadgeKeyMax - 1] = 0;
        }
        // the detail cell: the spectator menu's Detail (the penalty text, "" for a car without one; unreadable
        // penalty state: the dim bar). Position change, stops and the best lap's tyre from the
        // game's own values, the dim bar when they are not read
        if (v.set.tyres && !r.out && v.sdet == 1) {
            // Position Change: places gained or lost since the grid, the game's own rule (grid slot minus position,
            // 0x141778b8f). Races only: the menu offers it there, and the grid slot means nothing in other sessions
            const int g = c.grid[vid];
            if (race && !grid_dup && g > 0 && r.pos > 0) {
                const int d = g - r.pos;
                r.dup = d > 0;
                r.ddn = d < 0;
                if (d != 0)
                    std::snprintf(r.det, sizeof r.det, "%d", d > 0 ? d : -d);
                else
                    put(r.det, sizeof r.det, "-");
            } else {
                r.tna = true;
            }
        } else if (v.set.tyres && !r.out && v.sdet == 2) {
            // Stops: the game's own count (pit entry +0x14); "-" for none, as the game's board (lng_dash)
            if (pl.stops_have[vid]) {
                if (pl.stops[vid])
                    std::snprintf(r.det, sizeof r.det, "%d", int(pl.stops[vid]));
                else
                    put(r.det, sizeof r.det, "-");
            } else {
                r.tna = true;
            }
        } else if (v.set.tyres && !r.out && v.sdet == 4) {
            // Best: the tyre of the set the car's best lap was on. The game takes the first stint whose end lap is
            // at least the best lap's number, else the last one (0x1417792a0). The DLL knows the current set's
            // compound only: its letter shows when the best lap was on the current set, the dim bar otherwise (and
            // without a best lap)
            const TyreRead &t = s.tyre[vid];
            const int bl = c.best_lap[vid];
            char letter = checked_letter(t);
            if (!letter && t.state == 2 && t.held && now - t.held_t <= kTyreHold && now >= t.held_t)
                letter = t.held;
            if (letter && bl >= 0 && bl != 0xff && c.lap_ok[vid] && t.stint_ok && t.prev_end < bl)
                r.tyre = letter;
            else
                r.tna = true;
        } else if (v.set.tyres && !r.out && v.sdet == 5) {
            if (pen.mc_ok || c.tpen_ok[vid])
                penalty_text(pen.mc_ok ? pen.dt[vid] : 0, pen.mc_ok ? pen.sg[vid] : 0, c.tpen_ok[vid], c.tpen_s[vid],
                             r.det, sizeof r.det);
            else
                r.tna = true;
        } else if (v.set.tyres && !r.out) { // tyre letter
            const TyreRead &t = s.tyre[vid];
            const char letter = checked_letter(t);
            if (letter)
                r.tyre = letter;
            else if (t.state == 2 && t.held && now - t.held_t <= kTyreHold && now >= t.held_t) {
                r.tyre = t.held;
                r.tyre_held = true;
            } else
                r.tna = true;
        }
        // gap / interval column
        if (!v.set.gaps) {
            r.shown = kShownOff;
            continue;
        }
        if (r.out) {
            put(r.gap, sizeof r.gap, st == 5 ? "DSQ" : st == 6 ? "NC" : "Out");
            r.shown = kShownOut;
            continue;
        }
        r.shown = kShownUnavailable;
        r.gna = true;
        if (v.best) { // best laps: P1's time, the others' gap to it; the dim bar without both
            if (fx_kind_[vid]) { // the flash: the car's new best lap, green or purple
                best_lap_text(fx_ms_[vid], r.gap, sizeof r.gap);
                r.pb = fx_kind_[vid] == 1;
                r.ob = fx_kind_[vid] == 2;
                r.shown = kShownTime;
                r.gna = false;
                continue;
            }
            if (best_ok[vid] && v.best_p1 >= 0) {
                if (vid == leader) {
                    best_lap_text(v.best_p1, r.gap, sizeof r.gap);
                } else if (v.sgap == 1) {
                    // the spectator's Interval: the gap to the best lap of the car directly ahead; the dim
                    // bar when that car's time is missing or out of order (no gap is made up)
                    const int ahead = idx > 0 ? c.order[idx - 1] : -1;
                    if (ahead < 0 || !best_ok[ahead])
                        continue;
                    best_gap_text(best_ms[vid] - best_ms[ahead], r.gap, sizeof r.gap);
                } else {
                    best_gap_text(best_ms[vid] - v.best_p1, r.gap, sizeof r.gap);
                }
                r.shown = kShownTime;
                r.gna = false;
            }
            continue;
        }
        if (v.laps) { // the spectator menu's lap time: the game's own value for this mode, every row and session
            // in races each car's best valid lap from its lap table (field-traces.md §11), not the results
            // entry's time (a race log: not shown to be the best lap); timed sessions as before
            if (race) {
                if (lt.best_ok[vid]) {
                    lap_time_text(lt.best_ms[vid], r.gap, sizeof r.gap);
                    r.shown = kShownTime;
                    r.gna = false;
                }
                continue;
            }
            if (c.lap_ok[vid]) {
                // the game's own conversion (f32 product, cut), as the best laps and the flash; a double product
                // dropped a tenth for times just under one in f32 (88.6f read 1:28.5). Three decimals, as
                // the best laps: one decimal tied real times (an in-game Q1: P1-P3 all 1:06.5); the template sets them
                // at its lap time size (leaf flap), where they fit the timed gap column unsqueezed
                best_lap_text(game_lap_ms(c.lap_s[vid]), r.gap, sizeof r.gap);
                r.shown = kShownTime;
                r.gna = false;
                // the flash (timed sessions only: none is tracked in races): the cell's own time, coloured
                r.pb = fx_kind_[vid] == 1;
                r.ob = fx_kind_[vid] == 2;
            }
            continue;
        }
        if (!race) // timed sessions: no verified best-lap source yet (contract §5)
            continue;
        if (r.pos == 1) {
            put(r.gap, sizeof r.gap, v.lead ? "Leader" : "Interval");
            r.shown = kShownWord;
            r.gna = false;
            continue;
        }
        if (!tm.ok || !tm.car[vid].have)
            continue;
        const GapRec &g = tm.car[vid];
        const bool valid = v.lead ? g.leader_valid : g.ahead_valid;
        const int64_t ms = v.lead ? g.leader_ms : g.ahead_ms;
        if (valid && (st == 2 || st == 3) && ms >= 0 && ms <= kMaxGapMs) {
            race_gap_text(ms, r.gap, sizeof r.gap);
            r.shown = kShownTime;
            r.gna = false;
            continue;
        }
        if (valid)
            continue; // a valid flag with a status that leaves it stale, or an absurd value
        if (pl.pit_have[vid] && pit_clears_gap(pl.pit[vid])) {
            put(r.gap, sizeof r.gap, "PIT");
            r.shown = kShownPit;
            r.gna = false;
            continue;
        }
        // lapped: the game cleared the flag for a running car outside the pits; N from the game's lap counters
        const int ref = v.lead ? leader : (idx > 0 ? c.order[idx - 1] : -1);
        if (st == 2 && ref >= 0 && pl.lap_have[ref] && pl.lap_have[vid]) {
            const int n = pl.lap[ref] - pl.lap[vid];
            if (n >= 1 && n <= 99) {
                std::snprintf(r.gap, sizeof r.gap, n == 1 ? "+1 LAP" : "+%d LAPS", n);
                r.shown = kShownLapped;
                r.gna = false;
            }
        }
    }
    // yel: yellow zones in the last read ('-' no zone system, '?' unreadable list, 9 = 9 or more); red: the byte,
    // or 'z' when only the zones raise the red flag
    const char ych = !s.found_zones ? '-' : !fl.zones_ok ? '?' : char('0' + std::min(fl.yellow, 9));
    const char rch = v.red && fl.red != 1 && fl.red != 2 ? 'z'
                     : !s.found_red                      ? '-'
                     : fl.red < 0                        ? '?'
                                                         : char('0' + fl.red);
    // bdg: classified cars whose team badge key is known
    int badges = 0;
    for (int i = 0; i < c.n; ++i)
        badges += s.badges.car[c.order[i]].state == kBadgeKey || s.badges.car[c.order[i]].state == kBadgeRender;
    std::snprintf(v.dbg, sizeof v.dbg, "cls%d%s%s gap%c pit%c sc%d pen%c%c tyre%c lap%c yel%c red%c bdg%d%s", c.n,
                  held ? "h" : "", c.holes ? "!" : "", s.found_timing ? (tm.ok ? '+' : '?') : '-',
                  s.found_pit ? (pl.pit_ok ? '+' : '?') : '-', int(s.sc.state),
                  s.found_log ? (pen.log_ok ? '+' : '?') : '-', s.found_s1 ? (pen.mc_ok ? '+' : '?') : '-',
                  s.found_tyres ? '+' : '-', s.found_progress ? (pl.laps_ok ? '+' : '?') : '-', ych, rch, badges,
                  v.sgap >= 0 || v.sdet >= 0 ? spect_tag(v.sgap, v.sdet) : "");
    v_ = v;
}

} // namespace tower
