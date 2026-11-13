// In-game validation log: what the provider read and what the halo showed, 30 times a second, written
// as CSV by a background thread through swofty/storage.hpp to diag/ in the addon's own folder (swofty/addons/<id>/). The frame thread only copies a
// fixed-size record into a preallocated buffer (never blocks: a busy buffer drops the record and counts it).
// tools/ingame/analyze_diag.py turns a log into the field verification report.
#pragma once
#include "game_state.hpp"
#include "game_state_f1_25.hpp"
#include "hud_model.hpp"
#include "tower_anim.hpp"
#include "tower_model.hpp"

namespace halo::diag {

struct Shown {
    bool live, speed_ok, gear_ok, pedals_ok, energy_ok, boost, race;
    int kmh, mph, gear, th_lv, br_lv, rc_lv, dp_lv, rival_id;
    char turn[8];
    int turn_right; // the turn arrow lit: 1 right (tr), 0 left (tl), -1 no turn shown
    float turn_shift; // metres the turn list moved to the game's corners (0 until a lap is learned)
    // the halo's own CPU time on the game's flow thread (read + model + leaf writes), over the frames since
    // the previous record
    float cost_mean_us, cost_max_us;
    int cost_frames;
    // the G-force meter as lit (gmeter.hpp): the setting, the shown value in tenths (-1 none), the lit segments
    // (bit k = k * 45 degrees), the bars' axis (0 right .. 3 up, -1 none), the red bar and the red digits
    bool g_on;
    int g_tenths, g_segs, g_axis;
    bool g_red_bar, g_red_digits;
};

// The timing tower's companion log (tower_<same stamp>.csv), 10 times a second: the raw reads behind every
// field-traces.md check (classification, gaps with the game's valid flags, pit state, laps, SC byte) and what the
// tower showed; tyres, penalties and warnings once a second (penalty records whenever the log changes).
struct TowerRec {
    double t;
    uint64_t frame;
    uint32_t generation, session;
    bool session_ok;
    int player;
    tower::Snapshot snap;
    tower::View view;
    bool slow;          // this record carries the 1 Hz columns (tyres, penalties, warnings)
    bool pen_changed;   // the penalty log changed since the last record: list the records
    float read_us, model_us, publish_us; // the tower's own CPU time this frame
    int writes, copies, halo_writes;
    unsigned jobs;
    tower::AnimStats anim; // the motion packets so far (cumulative) and the snaps since the last record
    tower::RowEvents started, rowsnaps; // the codes started and the rows' own snaps since the last record
    tower::HeadEvents hdpub, hdanim;    // the header's writes and its own snaps since the last record
};

// Start the writer (first call only). Returns false when the folder cannot be created.
bool start();
// Queue one record (frame thread). Cheap; drops the record if the writer holds the buffer.
void record(const gs::GameState &s, const gs::F1_25Raw &raw, const Shown &shown);
// Queue one tower record (frame thread, 10 Hz). Same rules as record().
void record_tower(const TowerRec &r);
// The file being written, relative to the addon's folder, for the log ("" before start()).
const char *path_utf8();

}
