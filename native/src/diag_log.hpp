// In-game validation log: what the provider read and what the halo showed, 30 times a second, written
// as CSV by a background thread to %LOCALAPPDATA%\nick.f1-2026-halo\diag\. The frame thread only copies a
// fixed-size record into a preallocated buffer (never blocks: a busy buffer drops the record and counts it).
// tools/ingame/analyze_diag.py turns a log into the field verification report.
#pragma once
#include "game_state.hpp"
#include "game_state_f1_25.hpp"
#include "hud_model.hpp"

namespace halo::diag {

struct Shown {
    bool live, speed_ok, gear_ok, pedals_ok, energy_ok, boost, race;
    int kmh, mph, gear, th_lv, br_lv, rc_lv, dp_lv, rival_id;
    char turn[8];
    int turn_right; // the turn arrow lit: 1 right (tr), 0 left (tl), -1 no turn shown
    // the halo's own CPU time on the game's flow thread (read + model + leaf writes), over the frames since
    // the previous record
    float cost_mean_us, cost_max_us;
    int cost_frames;
};

// Start the writer (first call only). Returns false when the folder cannot be created.
bool start();
// Queue one record (frame thread). Cheap; drops the record if the writer holds the buffer.
void record(const gs::GameState &s, const gs::F1_25Raw &raw, const Shown &shown);
// The file being written, for the log ("" before start()).
const char *path_utf8();

}
