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

constexpr int kRows = 30;                 // rows the template draws (leaves v9; 22 before)
constexpr double kArrowSeconds = 3.0;     // display choice: about 3 s in the reference clip (4 s before)
constexpr double kClsHold = 0.3;          // s a valid classification is held over invalid reads
constexpr double kTyreHold = 1.0;         // s a tyre letter is held over a stale cache (field-traces.md §1)
constexpr int64_t kMaxGapMs = 3 * 3600 * 1000; // larger gaps are not a valid race state
// The zone writer sets a flag to 0 and then back to 3 on every zone update (field-traces.md §7.2), so one read
// can catch the 0: the yellow header is kept over one successful non-yellow read (0.25 s at 4 Hz). A failed read
// clears it at once.
constexpr int kYellowHoldReads = 1;
constexpr double kFlagMaxAge = 1.0; // s; an older flags read (the tower was off, or the reader fell behind) is unread
constexpr double kModeMaxAge = 1.0; // s; an older game mode read is unread (no Time Trial board from a stale label)
// the lap time flash in Practice and Qualifying (ui-build.md 20): a car's new best lap shows in its gap cell
// for kFlashSeconds (the reference clip: about 2 s). kFlashFill or more cars improving in one read is the game
// filling the cars' laps (an in-game test: 10 at once when Q1 ended), taken over without a flash.
constexpr double kFlashSeconds = 2.0;
constexpr int kFlashFill = 4;
// the knockout zone's field is held per session type; a tower off for longer than this starts it again (an
// in-game test: 0.9 s off between Q1's and Q2's fields, while the type still read Q1)
constexpr double kKoFieldGap = 5.0;

enum class Mode : int { full = 0, compact = 1, top = 2 };
enum class GapMode : int { interval = 0, leader = 1, autoswitch = 2 };

struct Settings {
    bool enabled = true;
    Mode mode = Mode::compact;
    int rows = 5;                 // compact / top N (the setting's range; at most kRows)
    bool header = true, tyres = true, arrows = true, gaps = true, team_colours = true, highlight = true,
         animation = true;
    GapMode gap_mode = GapMode::interval;
    double auto_period = 10;      // s, 5..60
    int opacity = 100;            // background opacity, % of the design's panel opacity
    bool debug = false;           // the validation log is on
    bool clip = false;            // a highlights clip plays (elements.hpp ClipLatch): no fastest-lap mark; the
                                  // caller also switches gaps, arrows and animation off
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
    // the detail cell's text: spectator Detail Penalties "5s", "DT", "SG"; Position Change the places
    // gained or lost ("3", with dup or ddn) or "-" (none), Stops the count or "-" (none, as the game's board); else ""
    char det[8] = {};
    bool dup = false, ddn = false; // Detail Position Change: det counts places gained (dup) or lost (ddn)
    bool tna = false;
    bool tyre_held = false;       // the letter is held over a stale cache (log only)
    bool pit = false, pen = false, out = false, me = false;
    // the knockout zone: Q1, Q2, SQ1, SQ2 only; the car's position is below the last one that goes through
    // (View::ko_safe) and it is not out
    bool ko = false;
    // the lap time flash (best laps in Practice and Qualifying): the gap cell holds the car's new best lap for
    // kFlashSeconds, green (pb) for a personal best, purple (ob) for the session's best; never both
    bool pb = false, ob = false;
    // the race's fastest lap (the game's own fastest car): this car holds it (View::fl_vid)
    bool fl = false;
    // team badge, whatever the team colour setting (the template hides the logo when it is off): the car's key
    // when the reader has it (the leaf is kBadgePrefix + key), else "" and bdg false
    bool bdg = false;
    int8_t bkey = -1;             // the key's index in the snapshot's table (the log), -1 unknown
    char badge[kBadgeKeyMax] = {};
    bool brender = false;         // badge is a render badge's key (the leaf: kRenderBadgePrefix + key)
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
    bool laps = false;            // the gap column shows each car's lap time (spectator Gap 3, best laps)
    bool flap = false;            // spectating with the menu on Gap Fastest Lap (every row a lap time)
    // best laps: a timed session without the spectator menu (or with its Interval / Leader; Interval
    // gaps to the car directly ahead). P1's best lap (m:ss.fff), the others' gap to it
    // (+s.fff), the dim bar without a time. best_p1: P1's time in ms (-1 none); best_n: classified cars with a
    // time; best_inv: cars whose time is below the time of a car classified ahead of it (0 when the field is the best
    // lap and the order is the game's; such a car shows the dim bar)
    bool best = false;
    int64_t best_p1 = -1;
    int best_n = 0, best_inv = 0;
    // the knockout zone: the last position that goes through in a knockout session (Q1, Q2, SQ1, SQ2), from
    // the game's own drop zone rule (field-traces.md 5.1; the cut is inferred); -1 in every other session
    int ko_safe = -1;
    // the race's fastest lap: the game's own fastest car (VehicleLapTimes +0xb8, field-traces.md §11) when it
    // is classified, -1 none; fl_ms its best valid lap by the game's rule from its lap table, -1 unknown (the mark
    // shows without it). An earlier build's source (the results entry's lap time) is no longer used in races
    int fl_vid = -1;
    int64_t fl_ms = -1;
    // the lap time flash per vehicle id (the log): 0 none, 1 green, 2 purple
    uint8_t fx[kCars] = {};
    int sgap = -1, sdet = -1;     // the spectator menu's Gap / Detail the tower follows, -1 its own settings
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
void lap_time_text(int64_t ms, char *out, size_t cap); // "1:32.4", "58.7": one decimal, cut
int64_t game_lap_ms(float s);                          // the game's own conversion: s * 1000.0f, truncated
void best_lap_text(int64_t ms, char *out, size_t cap); // "1:27.470", "58.123": three decimals
void best_gap_text(int64_t ms, char *out, size_t cap); // "+0.293", "+1:02.345": three decimals
void penalty_text(int dt, int sg, bool tpen_ok, float tpen_s, char *out, size_t cap); // "DT", "SG", "5s" or ""
const char *session_label(uint32_t type);              // "Q2", "R", "" for unknown
int knockout_safe(uint32_t session, int n);            // the last position through in Q1/Q2/SQ1/SQ2 (n cars), -1 none

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
    void track_flash(const Classification &c, bool active, double now);

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
    // the best laps the flash follows, by vehicle id (-1 none); taken without a flash after a reset
    bool fx_base_ = false;
    int64_t fx_ms_[kCars] = {};
    double fx_until_[kCars] = {};
    uint8_t fx_kind_[kCars] = {};
    // the knockout zone's field: the most cars classified since the session type changed
    uint32_t ko_session_ = ~0u;
    int ko_n_ = 0;
    double ko_t_ = -1e9;
    // the race's fastest lap holder (the game's)
    int fl_vid_ = -1;
};

} // namespace tower
