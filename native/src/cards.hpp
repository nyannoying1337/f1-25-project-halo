// Broadcast cards (0.2.2): the few values the pit lane timer and lap time cards need beside the game's own bindings.
// No memory read of its own: everything comes from the timing tower's snapshot (tower_reader.cpp) and the halo's
// lap distance, for the car the halo follows. Fixed arrays, no allocation. A value that is not read this moment is
// never guessed: its leaf goes false / empty.
//
// Leaves (view_model_data.hud_cd_*), written on change and rewritten every kCardRefresh seconds (the game can rebuild
// its view model):
//   badge (text)  the followed car's team logo, the string the tower writes per row (tower_state.hpp badge_text)
//   bdg           badge holds a logo
//   tS tM tH tI tW  the followed car's tyre letter, one bool per compound (the tower's rule: checked_letter, 1 s hold)
//   pfin          the followed car left the pit lane less than kPitFinal seconds ago: the pit card shows its
//                 3-decimal time text instead of the counting one
//   pit3 (text)   the node the template's own formatter writes the 3-decimal pit lane time into. The DLL creates it
//                 once ("", never while pfin) and keeps it alive while the car is on track and pfin is false; after
//                 that first write it never writes it in the pit lane or while pfin
//   lcol lpb lob  the lap time's result colour for kLapColour seconds: lpb the followed car's best lap just
//                 improved (green), lob it is also the session's best (purple), lcol either. Sources: in timed
//                 sessions the tower model's own flash for that car; in races the car's best valid lap falling
//                 in the game's lap table, purple when the game's fastest-lap car is this car. A first lap is no
//                 improvement (nothing to compare with): white
//   sKpJJ         sector K (1..3), step JJ (00..15): the car has covered (JJ + 1) / 16 of the sector it is in.
//                 Sectors by the game's own table (sector ends in metres, tower_state.hpp sector_of); all false
//                 without the table, the distance, or with a table that has not 3 sectors
#pragma once

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "tower_model.hpp"
#include "tower_reader.hpp"
#include "tower_state.hpp"

namespace cards {

constexpr int kSteps = 16;
constexpr int kSectors = 3;
constexpr double kCardRefresh = 2.0; // s between rewrites of every leaf
constexpr double kPitFinal = 6.0;    // s the final pit time may show after the exit (the game closes the element)
constexpr double kPitAge = 1.0;      // s: an older pit state read is no pit state
constexpr double kTyreAge = 3.0;     // s: an older tyre read is no tyre (read at 2 Hz)
constexpr double kLapColour = 3.0;   // s the lap time keeps its result colour
constexpr double kLineHold = 4.0;    // s after the line without sector 1 steps: the game still shows the last
                                     // lap's sector colours there (seen in game; its own hold is not known)
constexpr int kCardWrites = 6;       // leaf writes per frame at most
constexpr size_t kBadgeText = 96;

enum LeafId : int {
    kBadge = 0, kPit3, // texts
    kBdg, kPfin, kTyS, kTyM, kTyH, kTyI, kTyW, kLcol, kLpb, kLob,
    kStep0, // kSectors * kSteps bools
    kLeaves = kStep0 + kSectors * kSteps,
};
constexpr int kTexts = 2;

struct In {
    bool live = false;   // the classification reader runs for the cards (provider compatible, a card switched on)
    int vid = -1;        // the followed car, -1 none
    int flash = 0;       // the tower model's lap time flash for that car (0 none, 1 personal best, 2 session best)
    float lap_m = -1.f;  // its distance into the lap, m; < 0 unknown
    const tower::Snapshot *snap = nullptr;
};

struct Want {
    char badge[kBadgeText] = {};
    bool bdg = false;
    char tyre = 0;
    bool pit_known = false, in_pit = false;
    int8_t sector = 0;   // 1..3, 0 none
    int8_t steps = 0;    // lit steps in that sector, 0..kSteps
};

// What the cards should show for this input (pure; the tests call it directly).
inline Want decide(const In &in, double now)
{
    Want w;
    if (!in.live || !in.snap || in.vid < 0 || in.vid >= tower::kCars)
        return w;
    const tower::Snapshot &s = *in.snap;
    const tower::BadgeRead &b = s.badges.car[in.vid];
    if ((b.state == tower::kBadgeKey || b.state == tower::kBadgeRender) && b.key >= 0 && b.key < s.badges.keys &&
        b.key < tower::kCars && s.badges.render[b.key] == (b.state == tower::kBadgeRender)) {
        char key[tower::kBadgeKeyMax];
        std::memcpy(key, s.badges.key[b.key], sizeof key);
        key[sizeof key - 1] = 0;
        w.bdg = tower::badge_text(key, w.badge, sizeof w.badge, b.state == tower::kBadgeRender);
        if (!w.bdg)
            w.badge[0] = 0;
    }
    const tower::TyreRead &t = s.tyre[in.vid];
    if (t.t >= 0 && now >= t.t && now - t.t <= kTyreAge) {
        w.tyre = tower::checked_letter(t);
        if (!w.tyre && t.state == 2 && t.held && now >= t.held_t && now - t.held_t <= tower::kTyreHold)
            w.tyre = t.held;
    }
    const tower::PitLaps &pl = s.pitlaps;
    if (pl.pit_ok && pl.pit_have[in.vid] && pl.t >= 0 && now >= pl.t && now - pl.t <= kPitAge) {
        w.pit_known = true;
        w.in_pit = tower::in_pit(pl.pit[in.vid]);
    }
    const tower::FlagRead &f = s.flags;
    if (f.sectors_ok && f.sectors.count == kSectors && in.lap_m >= 0.f && std::isfinite(in.lap_m)) {
        const int k = tower::sector_of(f.sectors, in.lap_m);
        if (k >= 1 && k <= kSectors) {
            const float a = k > 1 ? f.sectors.end_m[k - 2] : 0.f, e = f.sectors.end_m[k - 1];
            if (e > a && in.lap_m >= a) {
                int n = int(std::floor(double(in.lap_m - a) / double(e - a) * kSteps));
                w.sector = int8_t(k);
                w.steps = int8_t(n < 0 ? 0 : n > kSteps ? kSteps : n);
            }
        }
    }
    return w;
}

class Cards {
public:
    using Sink = bool (*)(void *ctx, const char *path, bool is_text, bool value, const char *text);

    Cards()
    {
        name(kBadge, "badge");
        name(kPit3, "pit3");
        name(kBdg, "bdg");
        name(kPfin, "pfin");
        name(kLcol, "lcol");
        name(kLpb, "lpb");
        name(kLob, "lob");
        const char *ty[5] = {"tS", "tM", "tH", "tI", "tW"};
        for (int i = 0; i < 5; ++i)
            name(kTyS + i, ty[i]);
        for (int k = 0; k < kSectors; ++k)
            for (int j = 0; j < kSteps; ++j) {
                char b[12];
                std::snprintf(b, sizeof b, "s%dp%02d", k + 1, j);
                name(kStep0 + k * kSteps + j, b);
            }
    }

    const char *path(int id) const { return path_[id]; }
    bool is_text(int id) const { return id < kTexts; }
    bool pfin() const { return want_b_[kPfin]; }
    // the sector the white bar is in (1..3, 0 none), its lit steps, and writes the sink refused (the log)
    int sector() const { return sector_; }
    int steps() const { return steps_; }
    unsigned failed() const { return failed_; }
    unsigned written() const { return written_; }
    // for the log: in the sector the bar just left, the most steps it asked for and the step leaves written
    // true there (refreshes included)
    int left_peak() const { return left_peak_; }
    unsigned left_on() const { return left_on_; }

    void update(const In &in, double now)
    {
        const Want w = decide(in, now);
        std::memcpy(want_t_[kBadge], w.badge, kBadgeText);
        want_b_[kBdg] = w.bdg;
        const char letters[5] = {'S', 'M', 'H', 'I', 'W'};
        for (int i = 0; i < 5; ++i)
            want_b_[kTyS + i] = w.tyre == letters[i];
        // the final pit time: from the frame the car is read out of the pit lane after being read in it, for
        // kPitFinal seconds; a car change, an unread state or a clock going back ends it
        if (in.vid != vid_ || now < last_t_) {
            was_in_ = false;
            fin_until_ = -1e9;
            have_best_ = false;
            col_until_ = line_until_ = -1e9;
            prev_m_ = -1.f;
            flash_was_ = 0;
        }
        // the lap time's result colour
        int kind = 0;
        const bool car = in.live && in.snap && in.vid >= 0 && in.vid < tower::kCars;
        if (car && in.flash && in.flash != flash_was_)
            kind = in.flash == 2 ? 2 : 1;
        flash_was_ = car ? in.flash : 0;
        if (car && in.snap->laps.ok && in.snap->laps.best_ok[in.vid]) {
            const tower::LapTimes &lt = in.snap->laps;
            if (have_best_ && lt.best_ms[in.vid] < best_ms_)
                kind = lt.fastest_ok && lt.fastest == in.vid ? 2 : 1;
            best_ms_ = lt.best_ms[in.vid];
            have_best_ = true;
        } else if (!car || !in.snap->laps.ok || !in.snap->laps.read[in.vid])
            have_best_ = false;
        if (kind) {
            col_kind_ = kind;
            col_until_ = now + kLapColour;
        }
        const bool col = car && now < col_until_;
        want_b_[kLcol] = col;
        want_b_[kLpb] = col && col_kind_ == 1;
        want_b_[kLob] = col && col_kind_ == 2;
        vid_ = in.vid;
        last_t_ = now;
        if (!w.pit_known) {
            was_in_ = false;
            fin_until_ = -1e9;
        } else if (w.in_pit) {
            was_in_ = true;
            fin_until_ = -1e9;
        } else if (was_in_) {
            was_in_ = false;
            fin_until_ = now + kPitFinal;
        }
        want_b_[kPfin] = now < fin_until_;
        // pit3: kept alive ("") only while the car is known to be on track and no final time shows
        keep_pit3_ = w.pit_known && !w.in_pit && !want_b_[kPfin];
        // the line. The distance falling by more than half the last sector end is a new lap: sector 1's
        // steps wait kLineHold (the game still shows the finished lap's sector colours there)
        int steps = w.sector ? w.steps : 0;
        if (car && w.sector && in.snap->flags.sectors_ok) {
            const float len = in.snap->flags.sectors.end_m[kSectors - 1];
            if (prev_m_ >= 0.f && prev_m_ - in.lap_m > 0.5f * len)
                line_until_ = now + kLineHold;
            prev_m_ = in.lap_m;
        } else
            prev_m_ = -1.f;
        if (w.sector == 1 && now < line_until_)
            steps = 0;
        for (int k = 0; k < kSectors; ++k)
            for (int j = 0; j < kSteps; ++j)
                want_b_[kStep0 + k * kSteps + j] = w.sector == k + 1 && j < steps;
        if (w.sector != sector_) {
            left_peak_ = peak_;
            left_on_ = step_on_;
            peak_ = 0;
            step_on_ = 0;
        }
        if (steps > peak_)
            peak_ = steps;
        sector_ = w.sector;
        steps_ = steps;
    }

    // Writes what changed, at most `budget` leaves; every leaf again each kCardRefresh. Returns the writes made.
    int flush(double now, int budget, Sink sink, void *ctx)
    {
        if (now - refresh_t_ >= kCardRefresh || now < refresh_t_) {
            refresh_t_ = now;
            std::memset(fresh_, 0, sizeof fresh_);
        }
        int n = 0;
        // changed values first, then the refresh: a change never waits behind rewrites of unchanged leaves
        for (int pass = 0; pass < 2; ++pass)
        for (int k = 0; k < kLeaves && n < budget; ++k) {
            const int i = (next_ + k) % kLeaves;
            if (i == kPit3) {
                // the node's first write (it must exist before the formatter's text is shown), then only on track
                const bool create = !sent_[i] && !want_b_[kPfin];
                if (pass == 0 ? !create : (!keep_pit3_ || fresh_[i]))
                    continue;
                ++n;
                if (sink(ctx, path_[i], true, false, ""))
                    sent_[i] = fresh_[i] = true;
                continue;
            }
            if (i < kTexts) {
                const bool same = sent_[i] && std::strcmp(sent_t_[i], want_t_[i]) == 0;
                if (pass == 0 ? same : (!same || fresh_[i]))
                    continue;
                ++n;
                if (sink(ctx, path_[i], true, false, want_t_[i])) {
                    std::memcpy(sent_t_[i], want_t_[i], kBadgeText);
                    sent_[i] = fresh_[i] = true;
                }
                continue;
            }
            const bool same = sent_[i] && sent_b_[i] == want_b_[i];
            if (pass == 0 ? same : (!same || fresh_[i]))
                continue;
            ++n;
            if (sink(ctx, path_[i], false, want_b_[i], nullptr)) {
                sent_b_[i] = want_b_[i];
                sent_[i] = fresh_[i] = true;
                ++written_;
                if (i >= kStep0 && want_b_[i])
                    ++step_on_;
            } else
                ++failed_;
        }
        next_ = (next_ + 7) % kLeaves; // the scan's start moves, so a full budget starves no leaf
        return n;
    }

private:
    void name(int id, const char *key) { std::snprintf(path_[id], sizeof path_[id], "view_model_data.hud_cd_%s", key); }

    char path_[kLeaves][40] = {};
    bool want_b_[kLeaves] = {}, sent_b_[kLeaves] = {}, sent_[kLeaves] = {}, fresh_[kLeaves] = {};
    char want_t_[kTexts][kBadgeText] = {}, sent_t_[kTexts][kBadgeText] = {};
    bool keep_pit3_ = false;
    bool was_in_ = false;
    double fin_until_ = -1e9, last_t_ = -1e9, refresh_t_ = -1e9;
    int vid_ = -1;
    int next_ = 0;
    int sector_ = 0, steps_ = 0;
    bool have_best_ = false;
    int64_t best_ms_ = 0;
    int col_kind_ = 0, flash_was_ = 0;
    double col_until_ = -1e9, line_until_ = -1e9;
    float prev_m_ = -1.f;
    unsigned failed_ = 0, written_ = 0, step_on_ = 0, left_on_ = 0;
    int peak_ = 0, left_peak_ = 0;
};

} // namespace cards
