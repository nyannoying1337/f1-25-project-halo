// tower_state.hpp - prototype readers for the timing tower's traced fields (Phase 2).
//
// The field-by-field readers are not used by the DLL: tools/tower_re/run_tower_tests.sh tests them against a synthetic
// memory image. The DLL compiles this file for its keys, layouts, types and shared rules (tyre_letter, sector_of,
// sector_table_from) and makes its own bulk reads in tower_reader.cpp.
// Evidence for every offset: docs/timing-tower/field-traces.md (static analysis, build 25251167). Levels there:
// L1 inferred, L2 writer and reader found in code, L3 seen in game. Nothing here is L3 yet.
//
// Rules the readers follow:
//  - every read goes through the injected Mem (in the DLL: the provider's fault-free copy());
//  - any failed read, out-of-range count or value outside the range the game's own code produces returns
//    "unavailable" (false / -1 / SafetyCar::unavailable / kCutUnavailable). No reader invents a value.
#pragma once

#include <cstddef>
#include <cstdint>

namespace tower {

// ---------------------------------------------------------------- memory access (injected)

using ReadFn = bool (*)(void *ctx, uintptr_t addr, void *dst, size_t n);

struct Mem {
    ReadFn fn = nullptr;
    void *ctx = nullptr;
    bool read(uintptr_t a, void *dst, size_t n) const { return fn && a && a + n > a && fn(ctx, a, dst, n); }
    template <class T> bool get(uintptr_t a, T &v) const { return read(a, &v, sizeof v); }
};

// ---------------------------------------------------------------- component registry

// Image-relative registry keys (add the image base). A key is the address of a type descriptor; AddSystem
// 0x144500dc0 files a system under the address its vtable slot 0 returns (`lea rax,[KEY]; ret`).
namespace keys {
constexpr uintptr_t results = 0x607f1a0;            // R (the provider already reads it)
constexpr uintptr_t timing = 0x604ea90;             // T: plain getter 0x142882980
constexpr uintptr_t penalty_log = 0x60fdfe0;        // slot0 0x1435cb830, vtable 0x145848e80, built in 0x1407e5420
constexpr uintptr_t session_component = 0x6096ac8;  // slot0 0x142fe6060, vtable 0x1457f6250, ctor 0x142f24900
constexpr uintptr_t tyre_system = 0x6080d28;        // slot0 0x142ed1b10, vtable 0x1457ef110
constexpr uintptr_t safety_car_logic = 0x6100bd8;   // slot0 0x143671550, vtable 0x145850710
constexpr uintptr_t marshal_zones = 0x60fdde0;      // "MarshalZoneMonitor": slot0 0x1435cc0d0, vtable 0x14584aa90
constexpr uintptr_t red_flag = 0x60fde00;           // "RedFlagSystem": slot0 0x1435cc3d0, vtable 0x14584b0d0
// team badges (field-traces.md §10): the two systems the standings pill's view model takes from the registry in
// its constructor 0x141759a40 (stores 0x141759ab1 / 0x141759ae4) and its badge setter 0x141760020 reads
constexpr uintptr_t game_mode_context = 0x604ed28;  // pill [vm+0x20]; also [g_Game_Manager]+0xc0 (0x1407eb3da)
constexpr uintptr_t team_tables = 0x606ecd8;        // pill [vm+0x28]: the team tables per kind at +0x2c8
} // namespace keys

// The registry ([[g_Game_Manager]+0x30]) is a robin-hood map: 16-byte {key, value} slots from pointer [reg+0x18]
// up to pointer [reg+0x20]; one "used" byte per slot starts at pointer [reg+0x20] (the layout the provider's
// find_component scans). Returns 0 when the key is absent or the map is unreadable.
uintptr_t find_in_registry(const Mem &m, uintptr_t registry, uintptr_t key);

// ---------------------------------------------------------------- penalty log

// One record of the penalty log: vector [Z+0x48, Z+0x50) of 0x30-byte records, Z = registry(penalty_log).
// Field names from the game's own log line in Sess_PenaltyLog_SendAllRecords 0x143566630.
struct PenaltyRecord {
    uint8_t vehicle = 0xff;       // +0x08
    uint8_t penalty = 0xff;       // +0x09  0 drive-through, 1 stop-go, 2 grid, 3 reminder, 4 time, 5 warning, 6 DSQ ...
    uint8_t infringement = 0xff;  // +0x0a
    uint8_t other_vehicle = 0xff; // +0x0b
    uint32_t time_s = 0;          // +0x0c
    uint32_t lap = 0;             // +0x10
    uint32_t places = 0;          // +0x18
    uint32_t points = 0;          // +0x20
    uint32_t safety_points = 0;   // +0x2c
};

constexpr size_t kPenaltyStride = 0x30;
constexpr size_t kMaxPenaltyRecords = 1024; // sanity bound, not a game value

// Copies the records of one vehicle (vehicle 0xff = every record) into out[0..max). Returns how many matched
// (may exceed max; only max are copied), 0 for an empty log, or -1 when the log is unavailable.
int read_penalties(const Mem &m, uintptr_t penalty_log, uint8_t vehicle, PenaltyRecord *out, int max);

// ---------------------------------------------------------------- warnings (track limits)

// The game's own count (UDP lap-data builder 0x142cfd90d..0x142cfd987, cited for the rule only): warnings =
// records of the car with penalty 5; track-limits warnings = those whose infringement is <= 0x1d and set in
// this mask (7, 8, 9, 25..29).
constexpr uint32_t kTrackLimitsMask = 0x3e000380;
constexpr uint8_t kPenaltyWarning = 5;

struct WarningCounts {
    int total = 0;
    int track_limits = 0;
};

bool count_warnings(const Mem &m, uintptr_t penalty_log, uint8_t vehicle, WarningCounts &out);
// Same rule over records already read (one bulk read per frame, then per-car counts in memory).
WarningCounts count_warnings(const PenaltyRecord *recs, int n, uint8_t vehicle);

// ---------------------------------------------------------------- penalty state per car

// Session component S1 = registry(session_component); its MisconductManager is embedded at S1+0x410
// (ctor 0x143589fb0 stores the three penalty objects at MM+0x158/+0x168/+0x178).
namespace misconduct {
constexpr uintptr_t drive_through = 0x568;     // [S1+0x568], vtable 0x14584c840
constexpr uintptr_t stop_go = 0x578;           // [S1+0x578], vtable 0x14584dfe0
constexpr uintptr_t multiple_warnings = 0x588; // [S1+0x588], vtable 0x14584d1f0
} // namespace misconduct
constexpr size_t kMaxPenaltyCars = 256; // sanity bound on the per-car vectors, not a game value

// Unserved drive-throughs: per-car 0x28-byte record in [DT+0x68, DT+0x70); slots +8/+0x10/+0x18/+0x20,
// 0xff = empty (0x142cfd851..0x142cfd8c6). Range 0..4. A car past the end of the vector has 0 (the game's rule).
bool unserved_drive_throughs(const Mem &m, uintptr_t session_component, uint8_t vehicle, int &out);
// Unserved stop-gos: per-car 4-byte record in [SG+0x68, SG+0x70), byte +3 (0x142cfd8cd..0x142cfd906). Range u8.
bool unserved_stop_gos(const Mem &m, uintptr_t session_component, uint8_t vehicle, int &out);
// Time penalty total, seconds: double bits [P+0x38] ^ [P+0x40] (Sess_Issue_TimePenalty adds to it at
// 0x143573bdc..0x143573c35). P = [[R+0x148] + vehicle*8]; P+0 must read back the vehicle id.
bool time_penalty_seconds(const Mem &m, uintptr_t results, uint8_t vehicle, double &out);
// Result status P+0x18: 0..7 (3 finished, 4 DNF, 5 DSQ, 6 NC, 7 retired; data-and-ui.md §3.1).
bool result_status(const Mem &m, uintptr_t results, uint8_t vehicle, uint8_t &out);

// ---------------------------------------------------------------- safety car

// byte [SC+0x108], SC = registry(safety_car_logic). Sess_Set_SafetyCarDeploymentType 0x143608160 stores the
// deployment type while it is 0, allows only 2 -> 1 while deployed, and clears it on eResumeRace.
// Location L2. Meaning of 1 / 2 / 3 is L1 (KB, the 2 -> 1 upgrade rule, the UDP enum); needs an in-game log.
enum class SafetyCar : int { unavailable = -1, none = 0, full = 1, virtual_sc = 2, formation_lap = 3 };
SafetyCar safety_car_state(const Mem &m, uintptr_t safety_car_logic);

// ---------------------------------------------------------------- flags (yellow per marshal zone, red)

// MZ = registry(marshal_zones). Zone entries [MZ+0x88, MZ+0x90), stride 0x10; zone Z = [entry+8]; the zone's flag
// is the int32 Z+0x14; its start is the lap fraction f32 [[Z]+0x10] (end [[Z]+0x14]). The game's UDP session
// builder reads exactly these as zone start / zone flag (0x142cfb711..0x142cfb799; cited to name the fields only).
// Sess_MarshalZone_CheckFlags 0x14357ce30 rewrites the flag on each zone update: 0 first, then 4 red (the red
// flag system's state is 1, 0x14357dc11; or any entry of a car list at [ctx+0x30]+0x48 has state 0xe,
// 0x14357dc79..0x14357dc9f, a loop with no zone check, meaning not traced), 3 yellow (hazard level 3, or held by
// its timer), 1 green (after a hazard), else 0 or 2 x a neighbour byte (rule bit 2, 0x14357e60e; meaning not
// traced, and 4 if that byte is ever 2).
enum ZoneFlag : int32_t { zone_none = 0, zone_green = 1, zone_two = 2, zone_yellow = 3, zone_red = 4 };
constexpr size_t kZoneStride = 0x10;
constexpr size_t kMaxMarshalZones = 64; // sanity bound, not a game value (the UDP packet has room for 21)

// Image-relative globals (add the image base). The game's per-sector mapping and its lap-data builder both read
// them: sector i ends at sector_end[i] metres (the first i with sector_end[i] >= distance is the sector).
namespace track_globals {
constexpr uintptr_t sector_end = 0x6ce6660;   // f32[sector_count]
constexpr uintptr_t track_length = 0x6ce66b8; // f32 metres, g_Game_TrackLength
constexpr uintptr_t sector_count = 0x6ce66bc; // u32
} // namespace track_globals
constexpr int kMaxSectors = 8; // sanity bound for the bit mask; the game's own array holds 3

struct SectorTable {
    float end_m[kMaxSectors] = {};
    int count = 0;
    float track_length = 0.f;
};
// False when unreadable, count outside 1..kMaxSectors, or a value that is not finite, not positive or decreasing.
bool read_sector_table(const Mem &m, uintptr_t image_base, SectorTable &out);
// The DLL reads the three globals as one block (one copy): sector ends from sector_end (room for 22 floats), the
// track length at +0x58, the count at +0x5c.
constexpr size_t kSectorBlock = track_globals::sector_count + sizeof(uint32_t) - track_globals::sector_end; // 0x60
// read_sector_table's checks on the block's bytes.
bool sector_table_from(const uint8_t *block, SectorTable &out);
// The game's own rule (Sess_Flags_UpdateYellowReasons 0x14356fef8..0x14356ff5a): the first sector i whose end is
// >= metres, as 1-based i + 1. 0 when metres is not finite or lies past the last sector end (the game's loop marks
// nothing then), or the table is empty.
int sector_of(const SectorTable &t, float metres);

struct ZoneFlags {
    int zones = 0;              // zone count (0 = the system has no zones: valid, no flags)
    int yellow_zones = 0;       // zones with flag 3
    int red_zones = 0;          // zones with flag 4
    uint8_t yellow_sectors = 0; // bit i: a yellow zone starts in sector i + 1 (the game's own mapping,
                                // 0x14356fef8..0x14356ff65); 0 when no sector table was given
};
// False (unavailable) when the system is missing, the vector is broken, a zone pointer is null or a flag is
// outside 0..4. `sectors` may be null; with it, each yellow zone sets the bit of the first sector whose end is
// >= track length x zone start, and no bit when the start lies past the last sector end (the game's own loop).
// An unreadable zone start leaves the zone counted as yellow with no sector bit.
bool read_zone_flags(const Mem &m, uintptr_t marshal_zones, const SectorTable *sectors, ZoneFlags &out);

// RFS = registry(red_flag); state byte [RFS+0x40]: Sess_RedFlagSystem_Deploy 0x143583b60 sets 1 (only from 0),
// its update 0x143583fb0 sets 2 when the countdown +0x48 ends (and posts RedFlagStatusChangedMessage {2}). The
// reset to 0 (slot 11, a protected thunk) is KB-only. Location and 1 / 2 are L2; on track the tower sees 1.
enum class RedFlag : int { unavailable = -1, none = 0, deployed = 1, suspended = 2 };
RedFlag red_flag_state(const Mem &m, uintptr_t red_flag);

// Header status proposal (leaves.md `hs`): 3 red, 1 SC, 2 VSC, 5 yellow, 0 none, in that priority. Red needs
// the red flag system (deployed or suspended); a red zone alone does not raise it here. The live model
// (tower_model.cpp) also raises red when every zone reads 4: in game the red flag byte stayed 0 through a red
// flag while every zone read 4 (log 2026-11-09 17:44, field-traces.md §7). Yellow needs a readable zone list
// with a yellow zone. An unavailable input never raises a state (it can only leave a lower one).
int flag_header_state(RedFlag red, SafetyCar sc, const ZoneFlags *zones);

// ---------------------------------------------------------------- tyre compound

struct Tyre {
    uint8_t visual_id = 0xff; // visual record +0: the byte the game's car-status builder sends as "visual compound"
    uint8_t actual_id = 0xff; // [desc+8] +0: the byte it sends as "actual compound"
    int32_t compound = -1;    // visual record +0x50, set by Sess_Load_VisualTyreCompounds 0x142e985e0 (store
                              // 0x142e98710): 0 HyperSoft, 1 UltraSoft, 2 SuperSoft, 3 Soft, 4 Medium, 5 Hard,
                              // 6 SuperHard, 7 Intermediate, 8 Wet, -1 unknown name
    char letter = 0;          // 'S' 'M' 'H' 'I' 'W'; 0 for every other compound
};

// V = [[TS+0x110] + vehicle*8]; current set id = dword at [V+0x9c98] - 0x6c (the last 0x78-byte record of
// [V+0x9c90, V+0x9c98)); descriptor = the 0x18-byte entry of the inline list V+0x9bd0 (count qword V+0x9c48,
// room for 5) whose dword +0 equals the id, else the one equal to (id >= 3 ? 4 : 1); visual record = [desc+0x10].
// The list is a cache that the game rebuilds (0x142e9e6c0) before reading when [V+0x9c58] == 0 or
// [V+0x9c50] != [V+0x9bc0]; this reader never calls game code, so a stale cache reads as unavailable.
bool tyre_compound(const Mem &m, uintptr_t tyre_system, uint8_t vehicle, Tyre &out);
char tyre_letter(int32_t compound);

// ---------------------------------------------------------------- gaps (validity)

// T entries [T+0x30, T+0x38), stride 0x98; the entry of a car is the one whose u8 +0x90 equals its vehicle id
// (the game's readers scan for it: 0x142cfdbd3..0x142cfdc19). Each gap record: +0 i64 ms, +8 label handle,
// +0x10 u8 valid (nonzero = valid). Written by T's update 0x140812e30 through 0x140813ee0.
enum class GapKind : uintptr_t { leader = 0x58, ahead = 0x70 };
struct Gap {
    bool valid = false;
    int64_t ms = 0;
};
constexpr size_t kMaxTimingEntries = 64; // sanity bound, not a game value
bool read_gap(const Mem &m, uintptr_t timing, uint8_t vehicle, GapKind kind, Gap &out);

// ---------------------------------------------------------------- team badges (field-traces.md §10)

// Team_Set_TimingPillBadge 0x141760020 (every pill update, 0x14175ef85 and 0x141761523) for vehicle id V:
//   GMC = registry(game_mode_context); G = [[GMC+0x88]+0x260]; the first entrant of [G+0x2e0, G+0x2e8) (0x88-byte
//   entries) whose u8 +0x82 is V; its team word u32 +0x58: kind = low byte (above 2: nothing written), index = the
//   high 16 bits; table = [TT + 0x2c8 + kind * 16], TT = registry(team_tables); record = [[table+8] + index*16 + 8]
//   (index below the 16-byte element count of [table+8, table+0x10)). Kind 1 (My Team) or a record whose byte
//   +0x58d is set: a render-badge path built in protected code (Team_Format_RenderBadgePath, not followed). Else
//   the string "#overrides.osd.timing_tower.team_badges_hud" + "." + the C string at [record+0x4d8] (the team's
//   timing_tower_texture_path), set on the pill's team_badge_texture leaf. Any failed step writes nothing: the leaf
//   keeps its last value, "" from the pill's initialiser (0x14175a782).
namespace badge {
constexpr uintptr_t mode = 0x88;            // [GMC+0x88]
constexpr uintptr_t game = 0x260;           // [[GMC+0x88]+0x260] = G
constexpr uintptr_t entrants = 0x2e0;       // vector [G+0x2e0, G+0x2e8)
constexpr size_t entrant_stride = 0x88;
constexpr uintptr_t entrant_team = 0x58;    // u32 team word
constexpr uintptr_t entrant_vid = 0x82;     // u8 vehicle id
constexpr uintptr_t tables = 0x2c8;         // [TT + 0x2c8 + kind * 16]
constexpr uintptr_t table_vec = 0x8;        // vector [table+8, table+0x10) of 16-byte elements, record at +8
constexpr uintptr_t record_key = 0x4d8;     // char * (timing_tower_texture_path)
constexpr uintptr_t record_render = 0x58d;  // u8: nonzero = the record shows a render badge
constexpr unsigned max_kind = 2;
constexpr unsigned my_team_kind = 1;
} // namespace badge
// The leaf text: kBadgePrefix (0x145706ede and the "." of 0x14570c9c6) + the key.
constexpr const char kBadgePrefix[] = "#overrides.osd.timing_tower.team_badges_hud.";
constexpr size_t kBadgePrefixLen = sizeof kBadgePrefix - 1; // 44
constexpr size_t kBadgeKeyMax = 40;  // key bytes with the NUL: a sanity bound (the longest stock key has 24 characters)
constexpr size_t kBadgeTextMax = kBadgePrefixLen + kBadgeKeyMax; // the leaf text with the NUL (84)
// A key the tower names: 1..kBadgeKeyMax - 1 characters, each printable ASCII without the space (0x21..0x7e),
// NUL-terminated within s[0..cap). Anything else is unknown, never cut or repaired.
bool badge_key_ok(const char *s, size_t cap);
// out = kBadgePrefix + key: the pill's own string. False and out = "" when the key is not ok or cap < kBadgeTextMax.
bool badge_text(const char *key, char *out, size_t cap);

// ---------------------------------------------------------------- knockout (formula only; inputs not wired)

// The game's own cut-position rule, 0x140afa130 (recursive over the weekend definition's segment list). Field
// names are neutral on purpose: only their use is proven, not their meaning.
struct Segment {
    int32_t session_id = 0;   // def +0x08
    uint32_t divisor_m1 = 0;  // def +0x1c (the step divides by this + 1)
    int32_t link_session = 0; // def +0x20 (0 = base case)
};
constexpr uint32_t kNoCut = 0x1c;              // the game's own "no cut" value (28)
constexpr uint32_t kCutUnavailable = 0xffffffff; // ours: inputs outside what this mirror reproduces
// base = championship +0x4c4, floor_grid = championship +0x4cc, grid = the count argument (r9d).
uint32_t knockout_cut(int32_t session_id, const Segment *segs, int n, uint32_t base, uint32_t floor_grid,
                      uint32_t grid);
// Results-table rule (Game_SessionResults_PopulateTable 0x1418356b8..0x141835751, 0x141838bde..0x141838bef):
// only session types 5, 6, 7, 10, 11, 12; a car is in the zone when its 0-based position index > cut (unsigned).
bool in_drop_zone(uint32_t position_index, uint32_t cut, int32_t session_type);

} // namespace tower
