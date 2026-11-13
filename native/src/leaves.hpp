// The halo's view_model_data.hud_halo_* leaves: the template nodes in hud_dynamic_templates.ui read them.
// Desired values are set every frame; flush() writes only the ones that changed, at most kWriteBudget per
// frame (the core's queue holds 64), and rewrites everything every kRefresh seconds because the game can
// rebuild its view model (session load, HUD reset).
#pragma once
#include "hud_model.hpp"

#include <swofty/hud.hpp>
#include <swofty/mixin.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <string>
#include <unordered_map>
#include <vector>

namespace halo {

constexpr int kStripes = 10;    // brake / throttle slats (2026 broadcast, late-season version)
constexpr int kCapLevels = 16;  // recharge / deploy capsule steps
constexpr int kRivalSlots = 24; // rival lane slots, one per vehicle id
constexpr int kWriteBudget = 40;
constexpr double kRefresh = 2.0;

class Leaves {
public:
    void want(const std::string &key, bool v) { slot(key, 0).want_b = v; }
    void want(const std::string &key, const std::string &v) { slot(key, 1).want_t = v; }

    // Returns the writes queued this frame (the tower takes what is left of the frame's budget).
    int flush(double now)
    {
        namespace hud = swofty::hud;
        if (now - last_refresh_ >= kRefresh) {
            last_refresh_ = now;
            for (Leaf &l : leaves_)
                l.sent = false;
        }
        int budget = kWriteBudget;
        // 0.2.3: two passes over the same leaves. First the ones whose value differs from the last one sent (a real
        // change), then the ones that are only due again (the refresh, or never sent). The writes are the same as
        // before; a change no longer waits behind a refresh, which takes several frames at the budget (the gear's
        // digit and the suggested-gear leaves must turn in the same frame).
        for (int pass = 0; pass < 2; ++pass)
            for (Leaf &l : leaves_) {
                if (budget <= 0)
                    break;
                const bool differs = l.kind == 0 ? l.sent_b != l.want_b : l.sent_t != l.want_t;
                if (pass == 0 ? !differs : (differs || l.sent))
                    continue;
                const hud::Result r = l.kind == 0 ? hud::set(l.path, l.want_b) : hud::set(l.path, l.want_t);
                --budget;
                if (r == hud::Result::ok) {
                    l.sent = true;
                    l.sent_b = l.want_b;
                    l.sent_t = l.want_t;
                } else if (r != last_error_) {
                    last_error_ = r;
                    swofty::log("[halo] hud set %s: %s", l.path.c_str(), hud::name(r));
                }
            }
        return kWriteBudget - budget;
    }

    // the bool a leaf is set to this frame (tests); false for an unknown leaf
    bool wanted(const std::string &key) const
    {
        const auto it = index_.find(key);
        return it != index_.end() && leaves_[it->second].kind == 0 && leaves_[it->second].want_b;
    }

    // every leaf path this publisher writes (tests and the template check use it)
    std::vector<std::string> paths() const
    {
        std::vector<std::string> out;
        for (const Leaf &l : leaves_)
            out.push_back(l.path);
        return out;
    }

private:
    struct Leaf {
        std::string path;
        int kind = 0; // 0 bool, 1 text
        bool want_b = false, sent_b = false, sent = false;
        std::string want_t, sent_t;
    };
    Leaf &slot(const std::string &key, int kind)
    {
        auto [it, added] = index_.try_emplace(key, leaves_.size());
        if (added) {
            Leaf &l = leaves_.emplace_back();
            l.path = "view_model_data.hud_halo_" + key;
            l.kind = kind;
        }
        return leaves_[it->second];
    }
    std::vector<Leaf> leaves_;
    std::unordered_map<std::string, size_t> index_;
    double last_refresh_ = -100;
    swofty::hud::Result last_error_ = swofty::hud::Result::ok;
};

inline std::string two(int i)
{
    char b[8];
    std::snprintf(b, sizeof b, "%02d", i);
    return b;
}

// Stripe and capsule levels as the halo lights them.
inline int stripe_level(float x) { return int(std::lround(std::clamp(x, 0.f, 1.f) * kStripes)); }
inline int cap_level(float x) { return int(std::lround(std::clamp(x, 0.f, 1.f) * kCapLevels)); }

// The G-force meter (gmeter.hpp; all bool): gm shows the meter in place of the speed centre; gok its value, else the
// dimmed label; gred the red digits; gu<d> / gt<d> the units / tenths digit d; gs<k> segment k (k * 45 degrees);
// gw<a> / gr<a> the white / red bar on axis a (0 right, 1 down, 2 left, 3 up).
constexpr int kGSegments = 8;
constexpr int kGAxes = 4;

inline void publish_gmeter(Leaves &L, const View &v)
{
    const GView &m = v.gmeter;
    const bool ok = m.on && v.live && m.ok;
    L.want("gm", m.on);
    L.want("gok", ok);
    L.want("gred", ok && m.red_digits);
    for (int d = 0; d <= 9; ++d) {
        L.want("gu" + std::to_string(d), ok && m.tenths / 10 == d);
        L.want("gt" + std::to_string(d), ok && m.tenths % 10 == d);
    }
    const bool ind = ok && m.indicator;
    for (int k = 0; k < kGSegments; ++k)
        L.want("gs" + std::to_string(k), ind && ((m.segs >> k) & 1u));
    for (int a = 0; a < kGAxes; ++a) {
        L.want("gw" + std::to_string(a), ind && m.axis == a);
        L.want("gr" + std::to_string(a), ind && m.red_bar && m.axis == a);
    }
}

// The halo in 2025 and F2 cars (docs/halo-car-classes.md; written after the 2026 leaves, so their order is unchanged):
// cls = the setting all_cars (the hud_f1_dial / hud_f2_dial halos show while it is true, their stock dials while it
// is false); rkNN / dkNN = the 2025 cars' recharge / deploy capsule level NN on the fixed 120 kW scale (one at a
// time, like rcNN / dpNN).
inline void publish_classes(Leaves &L, const View &v)
{
    L.want("cls", v.all_cars);
    const int rk = v.live && v.energy_ok ? cap_level(v.recharge25) : 0;
    const int dk = v.live && v.energy_ok ? cap_level(v.deploy25) : 0;
    for (int i = 1; i <= kCapLevels; ++i) {
        L.want("rk" + two(i), rk == i);
        L.want("dk" + two(i), dk == i);
    }
}

// The suggested gear (docs/suggested-gear.md; written after the class leaves, so their order is unchanged). The game
// itself names the suggested digit (its own desired_gear_display, read by the template); these leaves only say on
// which side of the current gear each strip place k (0 = N, 1..8) lies: su<k> = above it (the green mark), sd<k> =
// below it (the amber mark). The current gear's own place has neither, so a suggestion equal to the current gear
// shows nothing. All false while the setting is off, the gear is not read or the car is not the player's own. A place
// the gear left a moment ago has neither for kSgearHold seconds (View.sgear_hold, hud_model.cpp).
inline void publish_sgear(Leaves &L, const View &v)
{
    const bool on = v.live && v.sgear && v.gear_ok;
    for (int k = 0; k < kGearPlaces; ++k) {
        const bool lit = on && !((v.sgear_hold >> k) & 1u);
        L.want("su" + std::to_string(k), lit && k > v.gear);
        L.want("sd" + std::to_string(k), lit && k < v.gear);
    }
}

inline int publish(Leaves &L, const View &v, double now)
{
    const bool live = v.live;
    L.want("live", live);
    L.want("spd", live && v.speed_ok);
    L.want("kmh", live && v.speed_ok ? std::to_string(v.kmh) : std::string());
    L.want("mph", live && v.speed_ok ? std::to_string(v.mph) : std::string());
    for (int i = 0; i <= 8; ++i)
        L.want("g" + std::to_string(i), live && v.gear_ok && v.gear == i);
    const int br = live && v.pedals_ok ? stripe_level(v.brake) : 0;
    const int th = live && v.pedals_ok ? stripe_level(v.throttle) : 0;
    for (int i = 1; i <= kStripes; ++i) {
        L.want("br" + two(i), br >= i);
        L.want("th" + two(i), th >= i);
    }
    const int rc = live && v.energy_ok ? cap_level(v.recharge) : 0;
    const int dp = live && v.energy_ok ? cap_level(v.deploy) : 0;
    for (int i = 1; i <= kCapLevels; ++i) {
        L.want("rc" + two(i), rc == i);
        L.want("dp" + two(i), dp == i);
    }
    L.want("boost", live && v.boost);
    L.want("race", v.race);
    L.want("nm", v.names);
    const bool turn = live && !v.turn.empty();
    L.want("turn", turn);
    L.want("tnum", turn ? v.turn : std::string());
    L.want("tl", turn && !v.turn_right);
    L.want("tr", turn && v.turn_right);
    for (int i = 0; i < kRivalSlots; ++i)
        L.want("rv" + two(i), live && v.rival_id == i);
    publish_gmeter(L, v);
    publish_classes(L, v);
    publish_sgear(L, v);
    return L.flush(now);
}

}
