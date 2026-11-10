// tower_reader.hpp - the timing tower's in-process reads (Phase 2).
//
// Reads the game's own systems through the component registry ([[g_Game_Manager]+0x30]) with fault-free copies
// (the injected tower::Mem; in the DLL ReadProcessMemory on the game's own process). Never writes game memory and
// never calls game code. Offsets and evidence: docs/timing-tower/field-traces.md and data-and-ui.md §3; field
// table with levels: docs/internal-state/fields.md "Timing tower". Nothing here is L3 yet.
//
// Cost rules: no per-frame scans, no allocations, no locks. Every system is read by a job with its own rate
// (classification, gaps, pit state and laps at 10 Hz, penalties and flags at 4 Hz, tyres at 2 Hz in two halves); a
// frame runs at most two due jobs. Registry slots are cached and re-checked with two small copies; a missing system
// is searched for again at most once a second. The sector table (image globals) is read once per session, each
// car's team badge once per car set (with the classification, a few cars a run).
#pragma once

#include "tower_state.hpp"

#include <cstdint>

namespace tower {

constexpr int kCars = 24;       // vehicle ids 0..23 (the game's tables hold up to 24 cars; the halo's rival slots)
constexpr int kLogRecords = 96; // penalty records kept per read (a session holds tens)

// Registry keys and the globals the reader starts from (absolute addresses: image base + rva in the game).
struct Keys {
    uintptr_t game_manager = 0;      // address of g_Game_Manager (a pointer variable)
    uintptr_t results = 0;           // R    image + 0x607f1a0
    uintptr_t timing = 0;            // T    image + 0x604ea90
    uintptr_t pit = 0;               // pit-state system, image + 0x60fb708
    uintptr_t safety_car = 0;        // SafetyCarLogicSystem, image + 0x6100bd8
    uintptr_t penalty_log = 0;       // image + 0x60fdfe0
    uintptr_t session_component = 0; // S1 (MisconductManager inside), image + 0x6096ac8
    uintptr_t tyres = 0;             // image + 0x6080d28
    uintptr_t marshal_zones = 0;     // "MarshalZoneMonitor", image + 0x60fdde0
    uintptr_t red_flag = 0;          // "RedFlagSystem", image + 0x60fde00
    uintptr_t sector_table = 0;      // image globals: sector ends, track length, count (image + 0x6ce6660, kSectorBlock)
    uintptr_t game_mode_context = 0; // team badges: the entrants' game, image + 0x604ed28
    uintptr_t team_tables = 0;       // team badges: the team records per kind, image + 0x606ecd8
};
constexpr uintptr_t kRvaPit = 0x60fb708;
Keys keys_from_image(uintptr_t image_base, uintptr_t game_manager);

// What the reader needs from the halo's provider each frame.
struct Frame {
    bool session_ok = false;  // the session type was read
    uint32_t session = 0;     // 1..4 P, 5..9 Q, 10..14 SQ, 15..17 R, 18 TT
    uint32_t generation = 0;  // the provider's car-set generation (new session, restart, car joins/leaves)
    char slots[33]{};         // the vehicle table's slot status from the halo's last scan ('.' = a car with ERS,
                              // 's' = a car without: the safety car, and every F2 car)
    int player = -1;          // the player's vehicle id, -1 none
    float player_lap_m = -1;  // the player's distance into the lap (the halo's progress read), m; < 0 unknown
    char slot(int vid) const { return vid >= 0 && vid < 32 ? slots[vid] : 0; }
};

// ---------------------------------------------------------------- snapshot

// Results (R): one copy of [P, P+0x58) per competitor at 10 Hz. pos 1-based; status P+0x18 0..7
// (2 running, 3 finished, 4 DNF, 5 DSQ, 6 NC, 7 retired); the time-penalty total P+0x38 ^ P+0x40 (double, s).
struct Classification {
    bool ok = false;           // at least one car, no two cars on one position
    uint32_t seq = 0;          // bumps on every successful read
    double t = -1;             // when it was read
    int n = 0;                 // classified competitors
    uint8_t order[kCars]{};    // vehicle ids by position
    uint8_t pos[kCars]{};      // by vehicle id: 1..n, 0 = not classified
    uint8_t status[kCars]{};   // by vehicle id; 0xff unreadable
    bool tpen_ok[kCars]{};
    float tpen_s[kCars]{};
    int holes = 0;             // positions 1..max with no car (a car the table no longer holds)
    int dups = 0;              // cars that shared a position (the read is then not ok)
    int8_t sorted = -1;        // the game's sorted list [R+0x108, R+0x110) agrees with the positions: 1 yes, 0 no, -1 unread
    int entries = 0;           // results entries (vector length)
};

// Timing (T): one copy of every 0x98-byte entry at 10 Hz. ms values with the game's valid flags; +0x88/+0x89 the
// game's own gained / lost bytes (logged only).
struct GapRec {
    bool have = false;         // the car has a T entry
    int64_t leader_ms = 0;
    bool leader_valid = false;
    int64_t ahead_ms = 0;
    bool ahead_valid = false;
    uint8_t gained = 0, lost = 0;
};
struct Timing {
    bool ok = false;
    double t = -1;
    int entries = 0;
    GapRec car[kCars];
};

// Pit state ([[S + vid*0x10 + 0x68] + 4], u32 0..15) and the progress lap counter, 10 Hz.
struct PitLaps {
    bool pit_ok = false;
    bool pit_have[kCars]{};
    uint8_t pit[kCars]{};
    bool laps_ok = false;
    bool lap_have[kCars]{};
    int16_t lap[kCars]{};      // laps completed (0 on lap 1, seen in game)
    double t = -1;
};
// The game's pit-lane rule for the gap flags (0x140814093..0x1408140c1): states 2..7 and 14..15.
inline bool pit_clears_gap(uint8_t s) { return (s >= 2 && s <= 7) || s == 14 || s == 15; }
// The full-grid list's "PIT" rule (0x1417784c4..0x14177851b): states 2..15.
inline bool in_pit(uint8_t s) { return s >= 2 && s <= 15; }

// Tyres, 2 Hz. state: 0 never read, 1 ok, 2 stale cache, 3 unavailable (no entry, no match, bad values).
struct TyreRead {
    uint8_t state = 0;
    uint32_t set_id = 0;
    uint32_t desc_id = 0;
    uint8_t visual = 0xff, actual = 0xff;
    int32_t compound = -1;
    char letter = 0;
    double t = -1;             // last read attempt
    char held = 0;             // the last checked letter (shown for at most 1 s while the cache is stale)
    double held_t = -1;        // when it was read
};

// Tyre letter after the cross-check: the visual byte must be the game's own id for the enum's compound
// (16 S, 17 M, 18 H, 7 I, 8 W). 0 when they disagree, the read is not ok or the compound has no letter.
// Only a checked letter is shown or held.
char checked_letter(const TyreRead &t);

// Penalties, 4 Hz: the log's records, unserved drive-throughs / stop-gos, warning counts per car.
struct Penalties {
    bool log_ok = false;
    int records = 0;                 // records in the log (may exceed kLogRecords)
    PenaltyRecord rec[kLogRecords];
    uint32_t log_seq = 0;            // bumps when the record count or the last record changes
    bool mc_ok = false;              // the MisconductManager vectors were read
    uint8_t dt[kCars]{}, sg[kCars]{};
    WarningCounts warn[kCars];
    double t = -1;
};

struct SafetyCarRead {
    int8_t state = -1;               // -1 unavailable, 0 none, 1 SC, 2 VSC, 3 formation lap (values L1)
    uint8_t extra = 0;               // +0x109, logged only
    double t = -1;
};

// Flags, 4 Hz (field-traces.md §7). The zone list MZ = registry(marshal_zones): entries [MZ+0x88, MZ+0x90) of
// kZoneStride bytes, zone Z = [entry+8]; one copy of [Z, Z+0x18) gives the zone definition pointer (+0) and the flag
// (i32 +0x14, 0..4; 3 = yellow). A yellow zone's start is the lap fraction f32 [[Z]+0x10]; its sector is the game's
// own rule (sector_of) over the session's sector table. The red flag is RedFlagSystem byte +0x40 (0 none,
// 1 deployed, 2 suspended). The zone value 4 is logged only: its writers do not depend on the red flag system.
struct FlagRead {
    uint32_t seq = 0;                // bumps on every flags read (the model's yellow hold counts reads)
    double t = -1;
    bool zones_ok = false;           // the list was read: system found, sane vector, every zone readable, flags 0..4
    int zones = 0;                   // zones in the list (0: a valid empty list)
    int8_t flag[kMaxMarshalZones]{}; // per zone in list order
    int8_t sector[kMaxMarshalZones]{}; // yellow zones: 1..n, 0 unmapped; other zones 0 (their start is not read)
    int yellow = 0;                  // zones at 3
    uint8_t ysec = 0;                // bit i: a yellow zone lies in sector i + 1
    bool unmapped = false;           // a yellow zone has no sector: start unreadable or outside 0..1, past the last
                                     // sector end, or no sector table
    int8_t red = -1;                 // red flag byte: -1 unavailable, 0 none, 1 deployed, 2 suspended
    bool sectors_ok = false;         // the session's sector table was read (kept until the next reset)
    SectorTable sectors;
    int8_t player_sector = 0;        // the player's sector by the same rule from Frame::player_lap_m, 0 unknown
};

// Team badges (field-traces.md §10, the game's Team_Set_TimingPillBadge): read at the classification refresh, at most
// kBadgeCarsPerRun cars a run, once per car per car set (the snapshot clears with a new generation or session); a
// failed read is tried again at most once a second. A car's result never changes otherwise.
enum BadgeState : uint8_t {
    kBadgeUnread = 0, // not read yet
    kBadgeKey,        // the key was read: the pill shows kBadgePrefix + key
    kBadgeOther,      // the game builds another path for this team (My Team, or a render badge): unknown here
    kBadgeFailed,     // a step failed, or the game has no badge for the car (it writes nothing): unknown, retried
};
// The step a failed read stopped at (the log's digit): 1 game mode context not in the registry, 2 [GMC+0x88] or
// [..+0x260] null or unreadable, 3 entrant vector unreadable, not sane or empty (Badges::entrants says which), 4 no
// entrant with the vehicle id, 5 kind
// above 2, 6 team tables missing or the kind's table not sane, 7 index past the table or a null record, 8 the
// record or its key pointer unreadable or null, 9 the key not 1..39 printable ASCII characters (0x21..0x7e).
struct BadgeRead {
    uint8_t state = kBadgeUnread;
    uint8_t step = 0;            // kBadgeFailed: the step (1..9)
    uint8_t kind = 0xff;         // team word low byte (0xff: no entrant read)
    int8_t key = -1;             // kBadgeKey: index into Badges::key
    uint16_t index = 0;          // team word high 16 bits
    double t = -1;               // the last attempt
};
// The game's entrant vector [G+0x2e0, G+0x2e8) at the last badge run (the log's bdgvec): its record count (0 = empty),
// or one of these.
enum : int32_t {
    kEntrantsNotRead = -1,   // no run reached the vector in this car set (steps 1-2 failed, or no car due yet)
    kEntrantsUnreadable = -2, // the 16 bytes at G+0x2e0 unreadable
    kEntrantsNotSane = -3,   // null begin, end before begin, not whole 0x88-byte records, or over kMaxEntrants
    kEntrantsCopyFailed = -4, // a chunk of records unreadable
};
struct Badges {
    BadgeRead car[kCars];
    int keys = 0;                    // distinct keys, in first-read order (an index never changes within a car set)
    char key[kCars][kBadgeKeyMax]{};
    uint32_t seq = 0;                // bumps whenever a car's result changes (the log lists the keys then)
    int32_t entrants = kEntrantsNotRead;
};
constexpr int kBadgeCarsPerRun = 6;  // a 22-car field takes four classification runs (0.4 s)
// The entrant vector has no cap in the game (Sess_ParticipantVec_PushBack grows it; a career keeps every entrant of
// its world there, not only the session's cars). The reader walks it in order, kEntrantChunk records per copy, and
// stops once every due car has its first entrant. kMaxEntrants is a sanity bound, not a game value.
constexpr size_t kEntrantChunk = 32;
constexpr size_t kMaxEntrants = 1024;

// The game mode (Time Trial, leaves.md §2): GMC = registry(game_mode_context); the mode object [GMC+0x88] (the team
// badges' first step); its row label, a C string at [[GMC+0x88]+0x278]: "time_trial" in Time Trial, "grand_prix_23"
// in a Grand Prix, "none" in the menus. In game (loader.log 2026-11-10 03:04-03:08) the game set the mode none ->
// time_trial for an F2 Time Trial, back to none and again time_trial, then none -> grand_prix_23 for a Grand Prix; the
// Swofty core reads the same chain (its "game mode time_trial is time_trial" line, 03:04:57). Read by its own job at
// 4 Hz and kept over the snapshot's resets (the mode is not a car set's).
constexpr uintptr_t kModeLabel = 0x278;  // [[GMC+0x88]+0x278]: the mode's row label (char *)
constexpr size_t kModeLabelMax = 32;     // bytes with the NUL; a longer label is not read
struct ModeRead {
    bool ok = false;          // the label was read: 1..31 letters, digits or '_'
    bool time_trial = false;  // the label is "time_trial"
    uint8_t step = 0;         // the step a failed read stopped at: 1 no game mode context, 2 [GMC+0x88] null or
                              // unreadable, 3 the label pointer null or unreadable, 4 the label unreadable, empty,
                              // too long or not letters, digits and '_'
    uint32_t seq = 0;         // bumps on every read
    double t = -1;            // the last read
    char label[kModeLabelMax] = {};
};

struct Snapshot {
    Classification cls;
    Timing timing;
    PitLaps pitlaps;
    TyreRead tyre[kCars];
    Penalties pen;
    SafetyCarRead sc;
    FlagRead flags;
    Badges badges;
    ModeRead mode;
    // which systems the registry gave this second (debug text and the log)
    bool found_results = false, found_timing = false, found_pit = false, found_sc = false, found_log = false,
         found_s1 = false, found_tyres = false, found_progress = false, found_zones = false, found_red = false;
};

// ---------------------------------------------------------------- reader

class Reader {
public:
    Reader() = default;
    Reader(const Mem &m, const Keys &k) : m_(m), k_(k) {}
    void configure(const Mem &m, const Keys &k)
    {
        m_ = m;
        k_ = k;
    }

    // Once per frame. Runs at most two due jobs. A new generation or session type clears the snapshot.
    void update(double now, const Frame &f);
    const Snapshot &snapshot() const { return s_; }
    // copies made by the last update() (bench and tests)
    int copies() const { return copies_; }
    // jobs run by the last update(): bit i = job i (kJob* below)
    unsigned ran() const { return ran_; }

    enum Job { kJobCls, kJobTiming, kJobPitLaps, kJobPen, kJobTyreA, kJobTyreB, kJobFlags, kJobMode, kJobs };

private:
    struct Component {
        uintptr_t value = 0;
        size_t slot = ~size_t(0);
        double last_search = -1e9;
    };
    bool rd(uintptr_t a, void *dst, size_t n);
    template <class T> bool get(uintptr_t a, T &v) { return rd(a, &v, sizeof v); }
    bool registry(uintptr_t &base, size_t &n, uintptr_t &info);
    uintptr_t find(Component &c, uintptr_t key, double now);

    void job_cls(double now, const Frame &f);
    void job_timing(double now, const Frame &f);
    void job_pitlaps(double now, const Frame &f);
    void job_pen(double now, const Frame &f);
    void job_tyres(double now, const Frame &f, int half);
    void job_flags(double now, const Frame &f);
    void job_mode(double now);
    void read_tyre(uintptr_t v, TyreRead &t);
    void read_badges(double now, const Frame &f);
    bool read_cstr(uintptr_t p, char *out, size_t cap);
    void reset(double now);
    // A car in the race: one with ERS, or one without (F2) whose vehicle id lies inside the session's results
    // entries. The safety car has no ERS and no results entry: its vehicle id comes after the entrants'.
    bool racer(const Frame &f, int vid) const;

    Mem m_;
    Keys k_;
    Snapshot s_;
    Component c_results_, c_timing_, c_pit_, c_sc_, c_log_, c_s1_, c_tyres_, c_zones_, c_red_, c_mode_, c_teams_;
    double due_[kJobs] = {};
    uint32_t generation_ = ~0u;
    uint32_t session_ = ~0u;
    double last_now_ = -1e9;
    int copies_ = 0;
    unsigned ran_ = 0;
    uint32_t pen_count_ = ~0u;
    uint64_t pen_last_ = 0;
    double sector_try_ = -1e9;  // the last attempt at the session's sector table (again at most once a second)
    int entrants_ = 0;          // results entries at the last classification read of this session (0: none yet)
    uint8_t tbuf_[64 * 0x98];   // T entries (one copy per read)
    uint8_t zbuf_[kMaxMarshalZones * kZoneStride]; // zone entries (one copy per read)
    uint8_t ebuf_[kEntrantChunk * badge::entrant_stride]; // entrants (one chunk per copy, badge runs only)
};

// Job periods (s). Tyres: each half every 0.5 s (2 Hz per car), the halves 0.25 s apart. Flags: 4 Hz
// (field-traces.md §7.6). Game mode: 4 Hz.
constexpr double kPeriod[Reader::kJobs] = {0.1, 0.1, 0.1, 0.25, 0.5, 0.5, 0.25, 0.25};

} // namespace tower
