#include "hud_model.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace halo {
namespace {

float ease(float x, float target, float dt, float tau) { return target + (x - target) * std::exp(-dt / tau); }

constexpr float kMguKLimit = 350e3f;  // W, the 2026 MGU-K limit: the scale when the car's own limit is unreadable
constexpr float kPowerFloor = 2e3f;   // W below which the capsules stay dark (sensor noise, coasting)
constexpr float kPedalTau = 0.035f;   // s
constexpr uint32_t kTimeTrial = 18; // session type 0x12: the game never updates positions there
constexpr float kPowerTau = 0.02f;    // s: the broadcast fills change within one 25 fps frame (docs/research 3.5)

} // namespace

void HudModel::update(const gs::GameState &s, double dt, const HudConfig &cfg)
{
    View &v = view_;
    const float fdt = float(std::clamp(dt, 0.0, 0.1));
    if (s.session.generation != generation_) { // new session, restart, other car: nothing carries over
        generation_ = s.session.generation;
        v = View{};
        e_n_ = 0;
    }
    v.live = s.compatible && s.session.active && s.vehicle.ok;
    v.race = s.session.race();
    v.names = cfg.show_names;
    if (!v.live) {
        v = View{};
        v.race = s.session.race();
        v.names = cfg.show_names;
        return;
    }

    // speed: one source for both units
    v.speed_ok = s.vehicle.speed_ok;
    if (v.speed_ok) {
        v.kmh = int(std::lround(s.vehicle.speed_mps * 3.6f));
        v.mph = int(std::lround(s.vehicle.speed_mps * 2.2369363f));
    }

    // gear: discrete, never eased
    v.gear_ok = s.vehicle.gear_ok && s.vehicle.gear >= -1 && s.vehicle.gear <= 9;
    v.gear = v.gear_ok ? s.vehicle.gear : 0;

    // pedals
    v.pedals_ok = s.input.ok;
    v.throttle = v.pedals_ok ? ease(v.throttle, s.input.throttle, fdt, kPedalTau) : 0.f;
    v.brake = v.pedals_ok ? ease(v.brake, s.input.brake, fdt, kPedalTau) : 0.f;

    // recharge / deploy: the MGU-K's power, one capsule at a time like the broadcast (harvest left, deploy
    // right, 0..max deployment); the battery's rate of change only when the power channels are unreadable.
    // MGU-H harvest is not shown (the 2026 power unit has no MGU-H; the game's channel is logged only).
    float net = 0; // W: + deploying, - harvesting
    bool have = false;
    if (s.energy.power_ok) {
        net = std::max(0.f, s.energy.deploy_w) - std::max(0.f, s.energy.harvest_k_w);
        have = true;
        e_n_ = 0;
    } else if (s.energy.store_ok) {
        if (e_n_ == 32) {
            std::copy(e_time_ + 1, e_time_ + 32, e_time_);
            std::copy(e_val_ + 1, e_val_ + 32, e_val_);
            --e_n_;
        }
        e_time_[e_n_] = s.time;
        e_val_[e_n_++] = s.energy.store_j;
        int j = 0;
        while (j < e_n_ - 2 && e_time_[j + 1] <= s.time - 0.3)
            ++j;
        const double span = s.time - e_time_[j];
        if (span > 0.05) {
            net = -float((s.energy.store_j - e_val_[j]) / span); // W out of the battery
            have = true;
        }
    } else
        e_n_ = 0;
    v.energy_ok = have;
    const float limit = s.energy.max_deploy_ok ? s.energy.max_deploy_w : kMguKLimit;
    const float rc = have ? std::clamp((-net - kPowerFloor) / limit, 0.f, 1.f) : 0.f;
    const float dp = have ? std::clamp((net - kPowerFloor) / limit, 0.f, 1.f) : 0.f;
    v.recharge = ease(v.recharge, rc, fdt, kPowerTau);
    v.deploy = ease(v.deploy, dp, fdt, kPowerTau);

    // Boost: the driver has the game's on-demand maximum-deployment mode selected
    v.boost = s.energy.mode_ok && s.energy.mode == 2;

    // the next turn, from the game's lap distance
    v.turn.clear();
    if (cfg.show_turns && s.progress.ok && s.session.track_ok) {
        char key[80];
        std::snprintf(key, sizeof key, "%s|%.0f", s.session.track_name_ok ? s.session.track_name : "", s.session.track_length_m);
        if (track_key_ != key) {
            track_key_ = key;
            corners_.reset(s.session.track_name_ok ? s.session.track_name : "", s.session.track_length_m);
        }
        char label[8] = {};
        bool right = false;
        if (corners_.current(s.progress.lap_m, label, sizeof label, &right)) {
            v.turn = label;
            v.turn_right = right;
        }
    }

    // the rival lane: the car one place ahead in the game's own classification (P1 sees P2), every session
    // type but time trial; without the classification, in races only, the car ahead on the road by the
    // game's distance counter (the leader sees the car behind)
    v.rival_id = -1;
    if (cfg.show_names && s.field.classified && s.session.type_ok && s.session.type != kTimeTrial) {
        const int me = s.field.pos[s.vehicle.id % gs::kMaxCars];
        const int want = me == 1 ? 2 : me - 1;
        for (int id = 0; id < gs::kMaxCars; ++id)
            if (s.field.pos[id] == want && id != s.vehicle.id) {
                v.rival_id = id;
                break;
            }
        return;
    }
    if (cfg.show_names && v.race && s.field.ok && s.field.n > 1 && s.field.player_rank >= 0) {
        const int r = s.field.player_rank, t = r > 0 ? r - 1 : r + 1;
        if (t < s.field.n)
            v.rival_id = s.field.id[t];
    }
}

}
