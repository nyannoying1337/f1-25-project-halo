// The halo's animations: when each motion starts, decided from state the DLL already
// holds (the model's view and the provider's validated state). Nothing here reads memory, allocates or searches:
// fixed arrays, a handful of comparisons per frame.
//
// Leaves (view_model_data.hud_halo_*, all bool), written only while the Animations option is on (or to take back a
// value written before it went off), so with the option off the DLL writes exactly what it wrote before it had animations. With
// the option on every leaf is written once as false first (the tower does the same), so the game's node exists
// before the first pulse and a decision node registered on it has something to follow:
//   held:   xan    the animated parts may show (the option is on, the car is read, no settle runs)
//           xrl    the white RPM line (revs at the limiter)
//           gvNN   the copy of rival slot NN, shown while its line rolls out
//   pulses: xbo    Boost turned on, and again every kAnimRepeat seconds while it stays on: the streak along the
//                  wings (no rest pulse: the streak's start, end and rest
//                  poses are all invisible, and on the 2026 dial the game's own Overtake value starts the same
//                  streak from the template, which a rest timed here could cut)
//           xgN    the gear changed to N (0 = neutral .. 8): the pop    xgr  the nine digit nulls back to rest
//           xrv    the rival changed: the roll                          xrr  the two rival nulls back to rest
// A pulse is the tower's: false -> true starts the motion (a registered decision node fires
// on the write), back to false at least kAnimPulse seconds and kAnimPulseFrames frames later, true again only
// kAnimPulseFrames frames after that false, and never refreshed (a rewrite would start the motion again).
#pragma once
#include <cstdint>
#include <cstdio>

namespace halo {

constexpr double kAnimPlay = 0.75;      // s: a play's length (the curve's period; tools/native/halo_native.py ANIM_PLAY)
constexpr double kAnimRepeat = 1.0;     // s between two streaks while Boost stays on (halo_native.py GLOW_REPEAT)
constexpr double kAnimBusy = 0.85;      // s: no new play on a null before this (the play and 0.1 s to spare)
constexpr double kAnimSettle = 2.0;     // s without motion after the followed car or the car set changes, or a jump
constexpr double kAnimPulse = 0.1;      // s a pulse stays true
constexpr int kAnimPulseFrames = 2;     // frames between a pulse leaf's writes
constexpr double kAnimGhost = 0.6;      // s the leaving rival's copy shows (its roll takes 0.5 s)
constexpr double kAnimRefresh = 2.0;    // s between rewrites of the held leaves (the game can rebuild its view model)
constexpr float kAnimRevOn = 0.95f;     // the white RPM line: on at this share of the limiter in force ...
constexpr float kAnimRevOff = 0.93f;    // ... off below this one
constexpr float kAnimJumpM = 100.f;     // m of lap distance in one frame: a replay jump, a rewind or a reset
constexpr int kAnimSlots = 24;          // rival slots (leaves.hpp kRivalSlots)
constexpr int kAnimGears = 9;           // lit digits N, 1..8
constexpr int kAnimWrites = 8;          // leaf writes per frame at most

enum AnimLeaf : int {
    kAnXan, kAnXrl, kAnGhost,                       // held: kAnGhost + slot
    kAnHeld = kAnGhost + kAnimSlots,
    kAnXbo = kAnHeld, kAnXg, kAnXgr = kAnXg + kAnimGears, kAnXrv, kAnXrr, // pulses: kAnXg + gear
    kAnLeaves
};

// What the animations read each frame: the model's view and already-validated provider state.
struct AnimIn {
    bool enabled = false;       // the Animations option
    bool live = false;          // the followed car is read this frame
    uint32_t subject = 0;       // bumps when the followed car or the car set changes
    bool gear_ok = false;
    int gear = 0;               // -1 R, 0 N, 1..8
    bool boost = false;
    int rival_id = -1;          // the rival slot shown, -1 none
    bool rev_ok = false;        // rpm and limiter are both read
    float rpm = 0, limiter_rpm = 0;
    bool lap_ok = false;
    float lap_m = 0;
    float track_m = 0;          // the lap's length, 0 unknown
};

struct AnimStats {
    uint32_t pops = 0, pops_busy = 0, boosts = 0, boosts_busy = 0, boost_repeats = 0, rolls = 0, rolls_at_once = 0,
             settles = 0, rests = 0;
};

class HaloAnim {
public:
    using Sink = bool (*)(void *ctx, const char *path, bool value);

    HaloAnim()
    {
        name(kAnXan, "xan");
        name(kAnXrl, "xrl");
        for (int i = 0; i < kAnimSlots; ++i)
            std::snprintf(path_[kAnGhost + i], sizeof path_[0], "view_model_data.hud_halo_gv%02d", i);
        name(kAnXbo, "xbo");
        for (int i = 0; i < kAnimGears; ++i)
            std::snprintf(path_[kAnXg + i], sizeof path_[0], "view_model_data.hud_halo_xg%d", i);
        name(kAnXgr, "xgr");
        name(kAnXrv, "xrv");
        name(kAnXrr, "xrr");
        for (int i = 0; i < kAnimGears; ++i)
            gear_t_[i] = -100;
    }

    void update(const AnimIn &in, double now)
    {
        const bool was_gate = gate_;
        if (in.enabled && in.live) {
            bool settle = !have_ || in.subject != subject_;
            if (have_ && !settle && in.lap_ok && lap_ok_) {
                // against the last lap distance that was read (a frame without one does not hide a jump). Across the
                // line: from the lap's last 150 m to its first 150 m; with the length unknown, from beyond 1500 m
                const float d = in.lap_m - lap_m_;
                const bool wrap = in.lap_m < 150.f && (in.track_m > 300.f ? lap_m_ > in.track_m - 150.f : lap_m_ > 1500.f);
                if ((d > kAnimJumpM || d < -kAnimJumpM) && !wrap)
                    settle = true;
            }
            if (settle) {
                settle_until_ = now + kAnimSettle;
                ++stats_.settles;
            }
        }
        gate_ = in.enabled && in.live && now >= settle_until_;
        if (was_gate && !gate_)
            cut(now);
        if (!in.enabled && (gear_rest_ > 0 || riv_rest_ > 0))
            cut(now);

        if (gate_ && prev_ok_) {
            // gear tick: the digit the gear changed to
            if (in.gear_ok && pgear_ok_ && in.gear != pgear_ && in.gear >= 0 && in.gear < kAnimGears) {
                if (now - gear_t_[in.gear] >= kAnimBusy) {
                    pend_[kAnXg + in.gear - kAnHeld] = true;
                    pend_[kAnXgr - kAnHeld] = false; // a rest still waiting must not follow this start
                    gear_t_[in.gear] = now;
                    gear_rest_ = now + kAnimBusy;
                    ++stats_.pops;
                } else
                    ++stats_.pops_busy;
            }
            // Boost streak
            if (in.boost && !pboost_) {
                if (now - glow_t_ >= kAnimBusy) {
                    pend_[kAnXbo - kAnHeld] = true;
                    glow_t_ = now;
                    ++stats_.boosts;
                } else
                    ++stats_.boosts_busy;
            } else if (in.boost && pboost_ && now - glow_t_ >= kAnimRepeat) {
                // Boost is still on: the streak again, once a second, for as long as it stays on
                pend_[kAnXbo - kAnHeld] = true;
                glow_t_ = now;
                ++stats_.boost_repeats;
            }
            // rival roll: from one car to another
            if (in.rival_id != privial_) {
                if (privial_ >= 0 && in.rival_id >= 0 && privial_ < kAnimSlots && now - riv_t_ >= kAnimBusy) {
                    pend_[kAnXrv - kAnHeld] = true;
                    pend_[kAnXrr - kAnHeld] = false;
                    ghost_until_[privial_] = now + kAnimGhost;
                    riv_t_ = now;
                    riv_rest_ = now + kAnimBusy;
                    ++stats_.rolls;
                } else
                    ++stats_.rolls_at_once;
            }
        }
        // rests: once the last play on those nulls is over, and never with a start of the same nulls
        if (gate_) {
            rest(kAnXgr, gear_rest_, now);
            rest(kAnXrr, riv_rest_, now);
        }

        // held leaves
        want_[kAnXan] = gate_;
        if (in.enabled && in.live && in.rev_ok && in.limiter_rpm > 0) {
            const float r = in.rpm / in.limiter_rpm;
            rev_ = r >= (rev_ ? kAnimRevOff : kAnimRevOn);
        } else
            rev_ = false;
        want_[kAnXrl] = rev_;
        for (int i = 0; i < kAnimSlots; ++i)
            want_[kAnGhost + i] = gate_ && ghost_until_[i] > now;

        // what the next frame compares with
        have_ = in.live && in.enabled;
        prev_ok_ = have_;
        subject_ = in.subject;
        pgear_ok_ = in.gear_ok;
        pgear_ = in.gear;
        pboost_ = in.boost;
        privial_ = in.rival_id;
        if (in.lap_ok) {
            lap_ok_ = true;
            lap_m_ = in.lap_m;
        } else if (!have_)
            lap_ok_ = false; // the car is not read: the next reading is a new start (a settle follows anyway)
        enabled_ = in.enabled;
    }

    // Writes what changed, at most `budget` leaves. Returns the writes made.
    int flush(double now, int budget, Sink sink, void *ctx)
    {
        ++frame_;
        int n = 0;
        if (enabled_ && now - refresh_t_ >= kAnimRefresh) {
            refresh_t_ = now;
            for (int i = 0; i < kAnHeld; ++i)
                if (written_[i])
                    fresh_[i] = false;
        }
        // pulses first: a start is never held up by the held leaves' refresh
        for (int k = 0; k < kAnLeaves - kAnHeld && n < budget; ++k) {
            const int i = kAnHeld + k;
            if (sent_[i]) {
                if (now - on_t_[k] >= kAnimPulse && frame_ - on_f_[k] >= uint32_t(kAnimPulseFrames)) {
                    ++n;
                    if (sink(ctx, path_[i], false)) {
                        sent_[i] = false;
                        off_f_[k] = frame_;
                    }
                }
            } else if (!written_[i]) {
                // the leaf's first write, false: only with the option on, or when a start or a rest has to go out
                if (!enabled_ && !pend_[k])
                    continue;
                ++n;
                if (sink(ctx, path_[i], false)) {
                    written_[i] = true;
                    off_f_[k] = frame_;
                }
            } else if (pend_[k] && frame_ - off_f_[k] >= uint32_t(kAnimPulseFrames)) {
                ++n;
                if (sink(ctx, path_[i], true)) {
                    sent_[i] = written_[i] = true;
                    pend_[k] = false;
                    on_t_[k] = now;
                    on_f_[k] = frame_;
                    ++started_[k];
                }
            }
        }
        // held leaves: first the ones whose value changes, then the refresh's rewrites
        for (int pass = 0; pass < 2; ++pass)
            for (int i = 0; i < kAnHeld && n < budget; ++i) {
                // with the option off a leaf never written stays unwritten; a false is then written only to take a true back
                if (!written_[i] && !want_[i] && !enabled_)
                    continue;
                const bool same = written_[i] && sent_[i] == want_[i];
                if (pass == 0 ? same : fresh_[i])
                    continue;
                ++n;
                if (sink(ctx, path_[i], want_[i])) {
                    written_[i] = fresh_[i] = true;
                    sent_[i] = want_[i];
                }
            }
        return n;
    }

    static constexpr int count() { return kAnLeaves; }
    const char *path(int i) const { return path_[i]; }
    bool gate() const { return gate_; }
    bool want(int i) const { return i < kAnHeld ? want_[i] : pend_[i - kAnHeld]; }
    bool sent(int i) const { return sent_[i]; }
    bool written(int i) const { return written_[i]; }
    uint32_t started(int i) const { return started_[i - kAnHeld]; } // times pulse leaf i went true
    const AnimStats &stats() const { return stats_; }

private:
    void name(int i, const char *key) { std::snprintf(path_[i], sizeof path_[0], "view_model_data.hud_halo_%s", key); }
    // a rest pulse, when its time has come and no start of the same nulls waits or is still true
    void rest(int leaf, double &due, double now)
    {
        if (due <= 0 || now < due)
            return;
        pend_[leaf - kAnHeld] = true;
        due = 0;
        ++stats_.rests;
    }
    // motion stops here (a settle, the car lost, the option off): starts not yet written are dropped, the copies
    // hide, and every null a play may still move gets its rest pulse now
    void cut(double now)
    {
        (void)now;
        for (int k = 0; k < kAnLeaves - kAnHeld; ++k)
            pend_[k] = false;
        for (int i = 0; i < kAnimSlots; ++i)
            ghost_until_[i] = 0;
        if (gear_rest_ > 0) {
            pend_[kAnXgr - kAnHeld] = true;
            ++stats_.rests;
        }
        if (riv_rest_ > 0) {
            pend_[kAnXrr - kAnHeld] = true;
            ++stats_.rests;
        }
        gear_rest_ = riv_rest_ = 0;
    }

    char path_[kAnLeaves][40] = {};
    bool want_[kAnHeld] = {};                 // held leaves: the value wanted
    bool pend_[kAnLeaves - kAnHeld] = {};     // pulses: a start waits to be written
    bool sent_[kAnLeaves] = {};               // the value last written (false before any write)
    bool written_[kAnLeaves] = {};            // the leaf was written at least once
    bool fresh_[kAnHeld] = {};                // held: written since the last refresh
    double on_t_[kAnLeaves - kAnHeld] = {};
    uint32_t on_f_[kAnLeaves - kAnHeld] = {}, off_f_[kAnLeaves - kAnHeld] = {}, started_[kAnLeaves - kAnHeld] = {};
    uint32_t frame_ = 0;
    double refresh_t_ = -100;
    // state
    bool enabled_ = false, gate_ = false, have_ = false, prev_ok_ = false, rev_ = false;
    uint32_t subject_ = 0;
    double settle_until_ = 0;
    bool pgear_ok_ = false, pboost_ = false, lap_ok_ = false;
    int pgear_ = 0, privial_ = -1;
    float lap_m_ = 0;
    double gear_t_[kAnimGears] = {}, glow_t_ = -100, riv_t_ = -100;
    double gear_rest_ = 0, riv_rest_ = 0; // when the rest pulse is due, 0 none
    double ghost_until_[kAnimSlots] = {};
    AnimStats stats_;
};

}
