#include "hud_model.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace halo {
namespace {

float ease(float x, float target, float dt, float tau) { return target + (x - target) * std::exp(-dt / tau); }

constexpr float kMguKLimit = 350e3f;  // W, the 2026 MGU-K limit: the scale when the car's own limit is unreadable
constexpr float kMguK2025 = 120e3f;   // W, the 2025 cars' capsule scale (docs/halo-car-classes.md 7; their logged peak 119.985 kW)
constexpr float kPowerFloor = 2e3f;   // W below which the capsules stay dark (sensor noise, coasting)
constexpr float kPedalTau = 0.035f;   // s
constexpr uint32_t kTimeTrial = 18; // session type 0x12: the game never updates positions there
constexpr float kPowerTau = 0.02f;    // s: the broadcast fills change within one 25 fps frame (docs/research 3.5)
constexpr float kGravity = 9.80665f;  // m/s^2 per g
constexpr float kLearnSpeed = 10.f;   // m/s: slower, g noise over speed^2 swamps the curvature
constexpr float kLearnStep = 20.f;    // m: a larger move between two frames is a restart or a teleport

} // namespace

// The player's own path teaches the turn list where the game's corners are (halo_track.hpp): one curvature
// sample each time the lap distance moves on (a simulation step; none while paused), driving forward at speed,
// with the player at the wheel (the AI's pit-lane drive is not the racing line). Only the player's own car: a car
// the spectator HUD watches never teaches it (its g is validated for the player's car only).
void HudModel::learn_bends(const gs::GameState &s)
{
    const float d = s.progress.lap_m, len = s.session.track_length_m;
    if (d == learn_lap_m_)
        return;
    const float moved = d - learn_lap_m_;
    const bool forward = learn_lap_m_ >= 0 && (moved > 0 ? moved < kLearnStep : moved + len < kLearnStep);
    learn_lap_m_ = d;
    const float v = s.vehicle.speed_mps;
    if (forward && s.vehicle.player && s.vehicle.speed_ok && s.vehicle.accel_ok && !s.vehicle.ai_driving &&
        v >= kLearnSpeed)
        corners_.feed_curvature(d, s.vehicle.g_lat * kGravity / (v * v));
}

void HudModel::update(const gs::GameState &s, double dt, const HudConfig &cfg)
{
    View &v = view_;
    clock_ += std::max(0.0, dt);
    const float fdt = float(std::clamp(dt, 0.0, 0.1));
    // new session, restart, other car (also the spectator's next watched car): nothing carries over
    if (s.session.subject != generation_) {
        generation_ = s.session.subject;
        v = View{};
        e_n_ = 0;
        gmeter_.reset();
        sg_gear_known_ = false;
        for (double &t : sg_hold_until_)
            t = 0;
    }
    v.live = s.compatible && s.session.active && s.vehicle.ok;
    v.race = s.session.race();
    v.names = cfg.show_names;
    v.all_cars = cfg.all_cars;
    // G-force meter: the car's own acceleration, filtered (gmeter.hpp); no value without a validated reading. Off
    // while spectating (docs/spectator-ui.md §3.3): the speed centre shows instead, since the game's g is validated
    // for the player's car only (in-game logs)
    gmeter_.update(cfg.g_meter && !s.spectate.on, v.live && s.vehicle.accel_ok, s.vehicle.g_lat, s.vehicle.g_long, fdt);
    v.gmeter = gmeter_.view();
    if (!v.live) {
        v = View{};
        v.race = s.session.race();
        v.names = cfg.show_names;
        v.all_cars = cfg.all_cars;
        v.gmeter = gmeter_.view();
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
    v.sgear = cfg.suggested_gear && v.gear_ok && !s.spectate.on;
    // The game names the suggested digit itself and gives the current gear when it has no suggestion. Its value and
    // this read of the gear do not turn in the same frame, so right after a shift the game can still name the gear
    // just left, which now lies beside the current one and would light as a suggestion for a frame or a few. Each
    // place the gear leaves (and each it passes in a shift of several gears) is therefore held dark for kSgearHold.
    // Per place: a mark on any other place is not touched. A frame without a gear keeps the last one read.
    if (v.gear_ok) {
        if (sg_gear_known_ && v.gear != sg_gear_) {
            const int lo = std::max(std::min(sg_gear_, v.gear), 0);
            const int hi = std::min(std::max(sg_gear_, v.gear), kGearPlaces - 1);
            for (int k = lo; k <= hi; ++k)
                if (k != v.gear)
                    sg_hold_until_[k] = clock_ + kSgearHold;
        }
        sg_gear_known_ = true;
        sg_gear_ = v.gear;
    }
    v.sgear_hold = 0;
    for (int k = 0; k < kGearPlaces; ++k)
        if (clock_ < sg_hold_until_[k])
            v.sgear_hold = uint16_t(v.sgear_hold | (1u << k));

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
    // the 2025 cars' capsules (the hud_f1_dial halo binds them): the same power on a fixed scale, so the DLL needs
    // no car class; the 2026 halo keeps the car's own limit above
    const float rc25 = have ? std::clamp((-net - kPowerFloor) / kMguK2025, 0.f, 1.f) : 0.f;
    const float dp25 = have ? std::clamp((net - kPowerFloor) / kMguK2025, 0.f, 1.f) : 0.f;
    v.recharge25 = ease(v.recharge25, rc25, fdt, kPowerTau);
    v.deploy25 = ease(v.deploy25, dp25, fdt, kPowerTau);

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
            learn_lap_m_ = -1;
        }
        learn_bends(s);
        corners_.update(clock_);
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
