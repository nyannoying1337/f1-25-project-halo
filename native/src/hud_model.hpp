// What the halo shows, decided from validated game state only (game_state.hpp).
//
// Discrete states (gear, Boost, the rival, the turn) switch immediately; continuous ones (pedals,
// recharge/deploy) are eased over a few tens of milliseconds. Anything the game state does not supply
// is left blank: the halo never fills a gap with an invented value.
#pragma once
#include "game_state.hpp"
#include "halo_track.hpp"

#include <string>

namespace halo {

struct HudConfig {
    bool show_names = true;
    bool show_turns = true;
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
    bool boost = false;         // the driver's ERS mode is the game's "Overtake" mode (max deployment on demand)
    bool race = false;
    bool names = true;          // the drivers' names are wanted (setting); the template binds the game's own names
    std::string turn;           // "5", "10A" ... empty: no turn to show
    bool turn_right = false;
    int rival_id = -1;          // vehicle id of the car shown in the rival lane, -1 none
};

class HudModel {
public:
    void update(const gs::GameState &s, double dt, const HudConfig &cfg);
    const View &view() const { return view_; }
    const char *turn_source() const { return corners_.source(); }
    const std::string &track_key() const { return track_key_; }

private:
    View view_;
    uint32_t generation_ = ~0u;
    Corners corners_;
    std::string track_key_;
    // battery rate of change, used only when the power channels cannot be read
    double e_time_[32]{};
    float e_val_[32]{};
    int e_n_ = 0;
};

}
