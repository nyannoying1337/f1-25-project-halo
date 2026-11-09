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

    void flush(double now)
    {
        namespace hud = swofty::hud;
        if (now - last_refresh_ >= kRefresh) {
            last_refresh_ = now;
            for (Leaf &l : leaves_)
                l.sent = false;
        }
        int budget = kWriteBudget;
        for (Leaf &l : leaves_) {
            if (budget <= 0)
                break;
            const bool same = l.sent && (l.kind == 0 ? l.sent_b == l.want_b : l.sent_t == l.want_t);
            if (same)
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

inline void publish(Leaves &L, const View &v, double now)
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
    L.flush(now);
}

}
