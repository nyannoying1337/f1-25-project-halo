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

} // namespace

void race_gap_text(int64_t ms, char *out, size_t cap)
{
    const long long tenths = (long long)(ms / 100); // cut, not rounded
    if (tenths < 600)
        std::snprintf(out, cap, "+%lld.%lld", tenths / 10, tenths % 10);
    else
        std::snprintf(out, cap, "+%lld:%02lld.%lld", tenths / 600, (tenths % 600) / 10, tenths % 10);
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
    v.lead = cfg.gap_mode == GapMode::leader ||
             (cfg.gap_mode == GapMode::autoswitch && (long long)(std::floor((now - auto_t0_) / period)) % 2 == 1);
    if (!v.on) {
        std::snprintf(v.dbg, sizeof v.dbg, v.trial ? "time trial" : "off");
        v_ = v;
        return;
    }
    const Classification &c = *cls;
    v.race = race;
    v.timed = timed;
    put(v.sess, sizeof v.sess, session_label(f.session));
    v.count = c.n;
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

    const Timing &tm = s.timing;
    const Penalties &pen = s.pen;
    for (int k = 0; k < v.rows; ++k) {
        const int idx = v.start + k, vid = c.order[idx];
        RowView &r = v.row[k];
        r.on = true;
        r.vid = vid;
        v.car_row[vid] = k;
        r.pos = c.pos[vid];
        r.p1 = r.pos == 1;
        const uint8_t st = c.status[vid];
        r.out = st == 4 || st == 5 || st == 6 || st == 7;
        r.me = cfg.highlight && vid == f.player;
        const int a = cfg.arrows ? arrow(vid, now) : 0;
        r.up = a > 0;
        r.dn = a < 0;
        if (!r.out) {
            r.pit = pl.pit_have[vid] && in_pit(pl.pit[vid]);
            r.pen = (pen.mc_ok && (pen.dt[vid] > 0 || pen.sg[vid] > 0)) || (c.tpen_ok[vid] && c.tpen_s[vid] > 0.f);
        }
        // team badge: the game's pill shows it for every car in the standings, out or not
        const BadgeRead &b = s.badges.car[vid];
        if (b.state == kBadgeKey && b.key >= 0 && b.key < s.badges.keys && b.key < kCars) {
            r.bdg = true;
            r.bkey = b.key;
            std::memcpy(r.badge, s.badges.key[b.key], kBadgeKeyMax);
            r.badge[kBadgeKeyMax - 1] = 0;
        }
        // tyre letter
        if (cfg.tyres && !r.out) {
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
        if (!cfg.gaps) {
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
        badges += s.badges.car[c.order[i]].state == kBadgeKey;
    std::snprintf(v.dbg, sizeof v.dbg, "cls%d%s%s gap%c pit%c sc%d pen%c%c tyre%c lap%c yel%c red%c bdg%d", c.n,
                  held ? "h" : "", c.holes ? "!" : "", s.found_timing ? (tm.ok ? '+' : '?') : '-',
                  s.found_pit ? (pl.pit_ok ? '+' : '?') : '-', int(s.sc.state),
                  s.found_log ? (pen.log_ok ? '+' : '?') : '-', s.found_s1 ? (pen.mc_ok ? '+' : '?') : '-',
                  s.found_tyres ? '+' : '-', s.found_progress ? (pl.laps_ok ? '+' : '?') : '-', ych, rch, badges);
    v_ = v;
}

} // namespace tower
