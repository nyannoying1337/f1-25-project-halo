// What the halo shows, decided from validated game state only (game_state.hpp).
//
// Discrete states (gear, Boost, the rival, the turn) switch immediately; continuous ones (pedals,
// recharge/deploy) are eased over a few tens of milliseconds. Anything the game state does not supply
// is left blank: the halo never fills a gap with an invented value.
#pragma once
#include "game_state.hpp"
#include "gmeter.hpp"
#include "halo_track.hpp"

#include <string>

namespace halo {

struct HudConfig {
    bool show_names = true;
    bool show_turns = true;
    bool g_meter = false;       // the G-force meter in place of the speed centre (gmeter.hpp)
    bool all_cars = true;       // the halo in 2025 and F2 cars too (off: their stock dials); 2026 cars always
};

struct View {
    bool live = false;          // the player's car is being read this frame
    bool speed_ok = false;
    int kmh = 0, mph = 0;
    bool gear_ok = false;
    int gear = 0;               // -1 R, 0 N, 1..8 (9 shows nothing)
    bool pedals_ok = false;
    float throttle = 0, brake = 0;   // 0..1, eased
    bool energy_ok = false;
    float recharge = 0, deploy = 0;  // 0..1 of the MGU-K limit, eased
    float recharge25 = 0, deploy25 = 0;  // the same power on the 2025 cars' fixed 120 kW scale, eased
    bool boost = false;        // the driver's ERS mode is the game's "Overtake" mode (max deployment on demand)
    bool race = false;
    bool names = true;          // the drivers' names are wanted (setting); the template binds the game's own names
    bool all_cars = true;       // the halo is wanted in 2025 and F2 cars (setting all_cars)
    std::string turn;           // "5", "10A" ... empty: no turn to show
    bool turn_right = false;
    int rival_id = -1;          // vehicle id of the car shown in the rival lane, -1 none
    GView gmeter;               // the G-force meter (on: the setting, also while not live)
};

class HudModel {
public:
    void update(const gs::GameState &s, double dt, const HudConfig &cfg);
    const View &view() const { return view_; }
    const char *turn_source() const { return corners_.source(); }
    float turn_shift() const { return corners_.shift(); } // metres the turn list moved to the game's corners
    const std::string &track_key() const { return track_key_; }

private:
    void learn_bends(const gs::GameState &s);

    View view_;
    uint32_t generation_ = ~0u;
    Corners corners_;
    GMeter gmeter_;
    std::string track_key_;
    double clock_ = 0;        // seconds of updates (the turn list's learning clock)
    float learn_lap_m_ = -1;  // lap distance of the previous frame, -1 none
    // battery rate of change, used only when the power channels cannot be read
    double e_time_[32]{};
    float e_val_[32]{};
    int e_n_ = 0;
};

}
