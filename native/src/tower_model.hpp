// tower_model.hpp - what the timing tower shows, decided from the reader's snapshot only (no memory access).
//
// Rules (docs/timing-tower/leaves.md, the contract with the template):
//  - order and positions are the game's classification (results R), never road order;
//  - a value the game does not give is "unavailable" (text "" + a flag), never guessed;
//  - discrete states are never interpolated; the only timers are display rules (arrow duration, Auto gap mode,
//    the 0.3 s hold over a torn classification read, the 1 s hold of a tyre letter over a stale cache, the yellow
//    flag held over one non-yellow zone read).
#pragma once

#include "tower_reader.hpp"

#include <cstdint>

namespace tower {

constexpr int kRows = 22;                 // rows the template draws
constexpr double kArrowSeconds = 4.0;     // display choice (F1 TV: "for a while", research.md §6, §9)
constexpr double kClsHold = 0.3;          // s a valid classification is held over invalid reads
constexpr double kTyreHold = 1.0;         // s a tyre letter is held over a stale cache (field-traces.md §1)
constexpr int64_t kMaxGapMs = 3 * 3600 * 1000; // larger gaps are not a valid race state
// The zone writer sets a flag to 0 and then back to 3 on every zone update (field-traces.md §7.2), so one read
// can catch the 0: the yellow header is kept over one successful non-yellow read (0.25 s at 4 Hz). A failed read
// clears it at once.
constexpr int kYellowHoldReads = 1;
constexpr double kFlagMaxAge = 1.0; // s; an older flags read (the tower was off, or the reader fell behind) is unread
constexpr double kModeMaxAge = 1.0; // s; an older game mode read is unread (no Time Trial board from a stale label)

enum class Mode : int { full = 0, compact = 1, top = 2 };
enum class GapMode : int { interval = 0, leader = 1, autoswitch = 2 };

struct Settings {
    bool enabled = true;
    Mode mode = Mode::compact;
    int rows = 5;                 // compact / top N, 3..22
    bool header = true, tyres = true, arrows = true, gaps = true, team_colours = true, highlight = true,
         animation = true;
    GapMode gap_mode = GapMode::interval;
    double auto_period = 10;      // s, 5..60
    int opacity = 100;            // background opacity, % of the design's panel opacity
    bool debug = false;           // the validation log is on
};

// Why a row's gap cell holds what it holds (the validation log checks these against the raw reads).
enum GapShown : uint8_t {
    kShownOff = 0,      // gap column off (setting) or row hidden
    kShownWord,         // P1: Interval / Leader
    kShownTime,         // a valid game time
    kShownLapped,       // +N LAP(S), inferred format
    kShownPit,          // PIT
    kShownOut,          // Out / DSQ / NC
    kShownUnavailable,  // dim bar
};

struct RowView {
    bool on = false;
    int vid = -1;
    int pos = 0;
    bool p1 = false, up = false, dn = false;
    char gap[16] = {};
    bool gna = false;
    uint8_t shown = kShownOff;
    char tyre = 0;                // 'S' 'M' 'H' 'I' 'W' or 0
    bool tna = false;
    bool tyre_held = false;       // the letter is held over a stale cache (log only)
    bool pit = false, pen = false, out = false, me = false;
    // team badge, whatever the team colour setting (the template hides the logo when it is off): the car's key
    // when the reader has it (the leaf is kBadgePrefix + key), else "" and bdg false
    bool bdg = false;
    int8_t bkey = -1;             // the key's index in the snapshot's table (the log), -1 unknown
    char badge[kBadgeKeyMax] = {};
};

struct View {
    bool on = false;
    // Time Trial (leaves.md §2): the game mode label read within kModeMaxAge is "time_trial" (setting on). The
    // standings tower is off then (on false, whatever the session type reads: it stays at the last race's after one)
    // and the template shows its Time Trial board, whose rows are the game's own board's.
    bool trial = false;
    bool show = false;            // on || trial: the tower's host shows (the stock board and lap counter hide)
    Settings set;
    bool lead = false;            // the gap column shows gaps to the leader
    int count = 0;                // classified cars
    int start = 0;                // window start (index into the classification)
    int rows = 0;
    bool trunc = false;
    int player_index = -1;        // the player's index in the classification, -1 none
    bool held = false;            // the classification shown is held over an invalid read
    bool race = false, timed = false;
    char sess[8] = {};
    char lap[8] = {};
    bool lapna = false;
    // Header state, one at a time: 4 chequered > 3 red flag > 1 SC > 2 VSC > 5 yellow > 0 none. SC, VSC and the
    // chequered flag are race-only; the red and yellow flags show in every tower session.
    int hs = 0;
    bool sc = false, vsc = false, chq = false; // sc / vsc stay 0 under a red flag (the SC byte also reads 1 then)
    bool red = false;             // the red flag system is 1 or 2, or every marshal zone reads 4 (held over one
                                  // other read); the zones are what moved in game (2026-11-09 17:44 log)
    bool yel = false;             // a marshal zone is yellow (held over one non-yellow read: kYellowHoldReads)
    char ysec[16] = {};           // the yellow zones' sectors in track order ("2", "1 3"); "" when not yellow or a
                                  // yellow zone has no sector
    bool ysna = false;            // yellow, but a yellow zone has no sector (ysec is "")
    RowView row[kRows];
    int car_row[kCars];
    char dbg[64] = {};
    View()
    {
        for (int &r : car_row)
            r = -1;
    }
};

// Text helpers (also used by the tests).
void race_gap_text(int64_t ms, char *out, size_t cap); // "+5.1", "+1:05.3": one decimal, cut
const char *session_label(uint32_t type);              // "Q2", "R", "" for unknown

// The window over the classification: compact = N rows around the player, start = clamp(i - floor(N/2), 0,
// count - N) (the game's own 5-pill rule for N = 5); top = the first N; full = every car up to kRows.
void window(int count, int n, int player_index, Mode mode, int &start, int &rows);

class Model {
public:
    void update(const Snapshot &s, const Frame &f, const Settings &cfg, double now);
    const View &view() const { return v_; }
    // arrow state per vehicle id (tests and the log): +1 up, -1 down, 0 none
    int arrow(int vid, double now) const;

private:
    void track_arrows(const Classification &c, double now);

    View v_;
    uint32_t generation_ = ~0u, session_ = ~0u;
    uint32_t cls_seq_ = 0;
    bool have_prev_ = false;
    uint8_t prev_pos_[kCars] = {};
    double arrow_until_[kCars] = {};
    int8_t arrow_dir_[kCars] = {};
    Classification held_;
    double held_t_ = -1e9;
    bool have_held_ = false;
    double auto_t0_ = 0;
    GapMode last_gap_mode_ = GapMode::interval;
    bool was_on_ = false;
    // yellow: the last flags read used, the state it gave and the non-yellow reads since the last yellow one
    uint32_t flag_seq_ = 0;
    bool yel_ = false;
    int yel_misses_ = 0;
    bool zred_ = false;   // every marshal zone at 4 (held over one other read, like the yellow)
    int zred_misses_ = 0;
    uint8_t ysec_ = 0;
    bool yun_ = false;
};

} // namespace tower
