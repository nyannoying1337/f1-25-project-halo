// In-process game-state provider for F1 25 (2026 Season Pack), build sha256 d873a1c8…
//
// Reads the game's own objects: the engine-wide vehicle table, each car's systems (engine, gearbox,
// chassis, steering, energy recovery) and the vehicle-progress system. Every pointer is validated before
// use (readable memory; the car's type and address identity and its own vehicle id read back; each system's
// vtable inside the exe image and back-pointer to its car), every value is range-checked, and anything that
// fails is reported as unavailable for that frame. Every read is a fault-free copy (ReadProcessMemory on the game's own
// process: an address that is unmapped, decommitted or freed between two frames yields "unavailable",
// never an access violation), so stale pointers cannot crash the game. No game memory is ever written.
//
// The offsets are specific to this build: f1_25_build_matches() checks the exe's PE timestamp and image
// size and the provider stays incompatible (the halo falls back to the game's own view-model data) on any
// other build. Evidence and confidence per field: docs/internal-state/fields.md.
#include "game_state_f1_25.hpp"

#include <swofty/mem.hpp>
#include <swofty/mixin.hpp>

#include <algorithm>
#include <cmath>
#include <cstring>

namespace halo::gs {
namespace {

namespace mem = swofty::mem;

constexpr uint32_t kBuildTimestamp = 1789118616; // F1_25.exe, Steam, sha256 d873a1c8d2044cef…
constexpr uint32_t kBuildImageSize = 0x193e6000;
constexpr double kScanPeriod = 0.1; // s: every car in the table re-read and the running order rebuilt (10 Hz)
constexpr double kNamePeriod = 1.0; // s: the track name re-read
constexpr double kSearchPeriod = 1.0; // s: the component registry searched again for a missing results system
// The validation log's distance reference. The progress total changes once per simulation step (60 Hz), not
// once per rendered frame (~170 fps), so a frame-to-frame difference is 0 on most frames and about 3x the speed
// on the rest (in-game logs). The reference is taken between two changes of the total at least kDistWindow apart.
constexpr double kDistWindow = 0.5;  // s
constexpr double kDistStale = 0.25;  // s without a change (stopped, paused): the window restarts
constexpr float kDistMaxSpeed = 150; // m/s: a faster step is a jump (car reset, flashback) and restarts the window
constexpr int kDistMarks = 128;      // changes kept (a power of two): >= kDistWindow up to 256 changes per second

// ---------------------------------------------------------------- layout (this build only)

// CarLive has NO vtable. +0x0 is the pending placement request's tag: the const char * the last caller passed to
// Game_Place_Vehicle (stored at 0x14473daf6, never cleared: Car_Apply_TeleportRequest 0x144644580 only zeroes the
// priority +0x8). It is 0 at create (0x144628527), "VehicleProxyActor" (0x14560eb38) while the pit-box actor holds
// the car in the garage, "PitLaneMovementManager::moveDownSpline" (0x14584366a) once the pit lane releases it.
// Reading it as a vtable rejected every car from its pit exit on (an in-game test, 2026-11-09). The car's identity is what
// Car_Chassis_Build sets once and nothing rewrites while the car lives:
//  - the systems container embedded at +0x380: vptr vt_Car_SystemsContainer 0x145c040c8 (store 0x14462877a; the
//    only other reference is its destructor 0x14473c184, run by Car_Destroy_Live 0x14473d1f2);
//  - the teleport lock pointer +0x98 == car + 0xa0, its embedded CRITICAL_SECTION (store 0x14462854d; read by
//    Game_Place_Vehicle 0x14473d850 and Car_Apply_TeleportRequest 0x14464458c).
// Both are in place before Car_Chassis_Build puts the car in the table (+0xe8 at 0x14462963e, slot at 0x144629654),
// and Car_Destroy_Live takes it out of the table (0x14473d123..0x14473d14c) before the destructor runs, so a car in
// the table always passes. Only the swap-with-last move can show a slot with the old id for a few instructions.
namespace car {
constexpr uintptr_t lock = 0x98;            // ptr == car + lock_cs                                         static
constexpr uintptr_t lock_cs = 0xa0;
constexpr uintptr_t systems_vt = 0x380;     // vptr of the embedded container == vt_Car_SystemsContainer    static
constexpr uintptr_t systems_vt_rva = 0x5c040c8;
constexpr uintptr_t vehicle_id = 0xe8;   // u8: index into the vehicle table                       KB L3
constexpr uintptr_t is_ai = 0x124;       // u32: 1 while the AI drives the car (a state, not identity) KB L3
constexpr uintptr_t throttle = 0x188;    // f32 0..1 applied throttle                               static
constexpr uintptr_t brake = 0x190;       // f32 0..1 applied brake                                  static
constexpr uintptr_t input_flags = 0x224; // u8: (flags & 0x88) == 8 swaps the pedals in reverse     static
constexpr uintptr_t engine = 0x530;      // system pointers (system+8 == car)                       KB L3
constexpr uintptr_t gearbox = 0x538;
constexpr uintptr_t chassis = 0x558;
constexpr uintptr_t steering = 0x560;
constexpr uintptr_t ers = 0x5a8;
constexpr uintptr_t lo = 0xe8, hi = 0x5b0; // the span the provider snapshots for the player's car
static_assert(lock + 8 <= hi && systems_vt + 8 <= hi && is_ai + 4 <= hi, "read_car_ref copies [0, hi)");
} // namespace car

constexpr uintptr_t kSystemCar = 0x8; // every car system: back-pointer to its CarLive               KB L3

namespace engine {
constexpr uintptr_t limiter = 0x2528; // f32 rad/s, limiter in force                                KB L3
constexpr uintptr_t rate = 0x2538;    // f32 rad/s, engine speed                                     KB L3
} // namespace engine

namespace gearbox {
constexpr uintptr_t gear_index = 0x680; // u32: 0 R, 1 N, 2 = 1st …                                 KB L3
}

namespace chassis {
constexpr uintptr_t g_lat = 0x320;      // f32 g                                                     static
constexpr uintptr_t g_long = 0x324;     // f32 g (read together with g_lat)                          static
static_assert(g_long == g_lat + 4);
constexpr uintptr_t body = 0x340;       // -> +0x18 -> +0x220 vec3 velocity, m/s                     static
constexpr uintptr_t body_state = 0x18;
constexpr uintptr_t state_velocity = 0x220;
} // namespace chassis

namespace steering {
constexpr uintptr_t lock = 0x28;  // CarObfFloat, rad                                                KB L2
constexpr uintptr_t angle = 0xe8; // CarObfFloat, rad                                                static
} // namespace steering

namespace ers {
constexpr uintptr_t max_deploy = 0x28;  // f32 W (2026: 350e3)                                       KB L2
constexpr uintptr_t capacity = 0x60;    // f32 J (4e6)                                               KB L2
constexpr uintptr_t live_lo = 0x19c8, live_hi = 0x1a6c;
constexpr uintptr_t harvest_lap = 0x19c8; // f32 J harvested by the MGU-K this lap                   KB L2
constexpr uintptr_t deploy_lap = 0x19d0;  // f32 J deployed this lap                                  KB L2
constexpr uintptr_t energy = 0x19f0;      // f32 J in the store                                      KB L3
constexpr uintptr_t lap_limit = 0x19f4;   // f32 J per-lap harvest limit in force                    KB L2
constexpr uintptr_t harvest_k = 0x1a00;   // f32 W                                                   KB L2
constexpr uintptr_t harvest_h = 0x1a04;   // f32 W                                                   KB L2
constexpr uintptr_t deploy = 0x1a14;      // f32 W                                                   KB L2
constexpr uintptr_t flags = 0x1a60;       // u8[4], meaning unconfirmed (logged only)                 L1
constexpr uintptr_t mode = 0x1a68;        // i32 0 None, 1 Medium, 2 Overtake, 3 Hotlap              KB L3
} // namespace ers

// VehicleProgressSystem entries (static-validation.md H1/H2; XOR pairs = value ^ key 8 bytes later). Lap
// distance is the game's own formula (stock UDP 0x142d00375): clamp(D - (progress lap + delta) * L, 0, L).
namespace progress {
constexpr uintptr_t from_manager = 0x2d0; // [g_Game_Manager]+0x2d0 = VehicleProgressSystem          static
constexpr uintptr_t vec_begin = 0x38, vec_end = 0x40; // entry pointers, indexed by vehicle id        static
constexpr uintptr_t lo = 0x28, hi = 0xa8;             // entry span read at once
constexpr uintptr_t vehicle = 0x28;                   // ptr: [[entry+0x28]+0x58] = the car (link)   static
constexpr uintptr_t vehicle_car = 0x58;
constexpr uintptr_t lap_a = 0x38, lap_b = 0x40;       // s16 lap counter = a ^ b                      static
constexpr uintptr_t plap_a = 0x48, plap_b = 0x50;     // s16 progress lap = a ^ b ...                 static
constexpr uintptr_t plap_delta = 0x58;                // ... plus this s16
constexpr uintptr_t total_a = 0x98, total_b = 0xa0;   // f32 bits = a ^ b, accumulated distance D (m) static
} // namespace progress

// The session classification (evidence: docs/internal-state/fields.md, "Position"). Static, L2:
// [g_Game_Manager]+0x30 is the component registry, a robin-hood map of 16-byte {key, value} slots from
// [map+0x18] up to [map+0x20], where one info byte per slot starts (0 = empty; FindIndex 0x14030ffd0).
// The results system is the value under the key 0x14607f1a0 (the key is that address: lea at 0x142c74c0e).
// Its per-vehicle entries ([R+0x148] .. [R+0x150]) hold the position the UI shows (it adds 1 at 0x141485847).
namespace registry {
constexpr uintptr_t from_manager = 0x30;
constexpr uintptr_t slots = 0x18, info = 0x20;
constexpr size_t max_slots = 4096;
} // namespace registry

namespace results {
constexpr uintptr_t key_rva = 0x607f1a0;                // image-relative key (0x14607f1a0 - 0x140000000)
constexpr uintptr_t vec_begin = 0x148, vec_end = 0x150; // entry pointers, indexed by vehicle id
constexpr uintptr_t vehicle = 0x0;                      // u8 vehicle id (Game_RaceHelper_GetVehicleByPosition)
constexpr uintptr_t pos_a = 0x48, pos_b = 0x50;         // u32: position - 1 = a ^ b
constexpr uintptr_t hi = 0x58;                          // entry span read at once
} // namespace results

// Who drives which car (RE, static L2; re-checked: ApplyInputs 0x14389a16b..0x14389a1d7, ControllerSet create
// 0x14389698c / 0x1438969fb, the global's store 0x142f43c7e, DestroySets 0x143899f8b). BuildSets makes one
// controller set per vehicle; a HumanController at set+0x20 exists only for a car a human drives on this machine,
// and an AI takeover switches the set's active-controller index without removing it.
namespace controllers {
constexpr uintptr_t cache_rva = 0x6096578;     // qword global: the ControllerSystem
constexpr uintptr_t vt_system_rva = 0x58824a0; // vt_Sess_ControllerSystem
constexpr uintptr_t vt_human_rva = 0x5882170;  // vt_Sess_HumanController
constexpr uintptr_t sets = 0x30;               // ptr: ControllerSet *[]
constexpr uintptr_t count_vec = 0x90;          // ptr: set count = byte((u32 [+0x30] - u32 [+0x28]) >> 3)
constexpr uintptr_t count_lo = 0x28, count_hi = 0x30;
constexpr uintptr_t built = 0x365;             // u8: the sets are built (DestroySets clears it)
constexpr uintptr_t set_human = 0x20;          // ptr: HumanController, null for a car no local human drives
constexpr uintptr_t set_vehicle = 0x34;        // u8: the set's vehicle index
} // namespace controllers

// The game's spectator director; the stock UDP's player index takes its car first (0x142cf988b). Static L2, and in
// game (2026-11-10 04:04-04:27 logs, kizi.spectator-hud F4/F8): +0xd1 set and +0xd6 followed the watched car through
// all 22 cars, never the safety car, never 0xff between switches; 0 in every log without spectating. +0xd0 is the
// flag the spectator HUD shows on (session.spectator_mode.active); the safety-car cinematic and the winner sequence
// also call SetActive, so the halo follows the director only while +0xd0 is set too (docs/spectator-ui.md §2).
namespace spectate {
constexpr uintptr_t key_rva = 0x6080ca8; // registry key (address of a static)
constexpr uintptr_t lo = 0xd0, hi = 0xe8; // the span copied at once, once per scan
constexpr uintptr_t ui = 0xd0;          // u8 != 0 while the spectator HUD is up                         KB L1
constexpr uintptr_t active = 0xd1;      // u8 != 0 while spectating                                      in game
constexpr uintptr_t vehicle = 0xd6;     // u8 vehicle id, 0xff none                                      in game
constexpr uintptr_t gap = 0xe4;         // u32 the spectator menu's gap mode (logged only)               KB L1
static_assert(gap + 4 <= hi);
} // namespace spectate

// ---------------------------------------------------------------- helpers

template <class T> T field(const uint8_t *buf, uintptr_t lo, uintptr_t off)
{
    T v;
    std::memcpy(&v, buf + (off - lo), sizeof v);
    return v;
}

float from_bits(uint32_t u)
{
    float f;
    std::memcpy(&f, &u, sizeof f);
    return f;
}

bool within(float v, float lo, float hi) { return std::isfinite(v) && v >= lo && v <= hi; }

// Fault-free copy from the game's memory. Unlike a VirtualQuery check followed by a plain load (whose
// answer can be stale by the time of the load), the kernel copy fails cleanly on any address that is not
// readable at that instant.
bool copy(uintptr_t addr, void *dst, size_t n)
{
    if (!addr || addr + n < addr)
        return false;
    SIZE_T got = 0;
    return ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<LPCVOID>(addr), dst, n, &got) && got == n;
}

template <class T> bool rd(uintptr_t addr, T &out) { return copy(addr, &out, sizeof(T)); }

// A NUL-terminated printable string of 1..cap-1 bytes at p.
bool c_string(uintptr_t p, char *out, size_t cap)
{
    size_t n = 0;
    while (n + 1 < cap) {
        const uintptr_t at = p + n;
        size_t chunk = std::min<size_t>(cap - 1 - n, 0x1000 - (at & 0xfff)); // never cross a page in one copy
        if (!copy(at, out + n, chunk))
            return false;
        for (size_t i = 0; i < chunk; ++i) {
            const unsigned char c = static_cast<unsigned char>(out[n + i]);
            if (!c) {
                out[n + i] = 0;
                return n + i > 0;
            }
            if (c < 0x20 || c == 0x7f)
                return false;
        }
        n += chunk;
    }
    return false;
}

// CarObfFloat: the value's bits XOR a key stored 8 bytes later.
bool read_obf_float(uintptr_t p, float &out)
{
    uint8_t b[12];
    if (!rd(p, b))
        return false;
    out = from_bits(field<uint32_t>(b, 0, 0) ^ field<uint32_t>(b, 0, 8));
    return std::isfinite(out);
}

// A car system the car points at, accepted only when it is an object that points back at the car
// (one copy: the vtable and the back-pointer).
uintptr_t system_of(uintptr_t car_ptr, uintptr_t slot_value)
{
    static_assert(kSystemCar == sizeof(uintptr_t));
    uintptr_t b[2];
    if (!slot_value || (slot_value & 7) || !copy(slot_value, b, sizeof b) || (b[0] & 7) || !mem::in_image(b[0]) ||
        b[1] != car_ptr)
        return 0;
    return slot_value;
}

struct CarRef {
    uintptr_t ptr = 0;
    uint8_t id = 0;
    uint32_t is_ai = 1;
    uintptr_t ers = 0; // 0 for cars without ERS: the safety car, and every F2 car (competitors: racer())
    uintptr_t tag = 0; // CarLive+0x0, the last placement request's tag (logged only: old_check)
};

bool is_car(SlotStatus s) { return s == kSlotCar || s == kSlotNoErs; }

} // namespace

// ---------------------------------------------------------------- provider

struct F1_25Provider::Impl {
    F1_25Symbols sym;
    bool ok = false;
    uint64_t frame = 0;
    uint32_t generation = 0;
    uintptr_t player_ptr = 0;
    uint32_t last_count = 0;
    // the player's progress total at its last kDistMarks changes (ring, newest at dist_head - 1)
    struct DistMark {
        float total;
        double t;
    };
    DistMark dist[kDistMarks] = {};
    int dist_head = 0, dist_n = 0;
    float dist_speed = 0, dist_window = 0; // the reference at the newest change; window 0 = none
    F1_25Raw raw;
    // The car table as last scanned. Every frame costs one copy of the table's slots; the cars behind them
    // are re-read in full when a slot or the count changes and at kScanPeriod, the player's car every frame.
    CarRef cars[kMaxCars];
    int n_cars = 0;
    uintptr_t slots[kMaxCars] = {};
    uint32_t slot_count = 0;
    char slot_status[kMaxCars + 1] = {}; // SlotStatus per slot from the last scan (validation log)
    double last_scan = -1e9;
    FieldState order; // running order from the last scan (player_rank is set per frame)
    size_t entrants = 0;    // the results system's entry count from the last scan, 0 when it was not read
    bool field_ers = false; // some car in the last scan has ERS (F1); none in F2
    // track name, re-read at kNamePeriod and on a new player car / session
    char name[sizeof(SessionState::track_name)] = {};
    bool name_ok = false;
    double last_name = -1e9;
    uint32_t name_generation = ~0u;
    // components found in the registry: re-checked at every scan, searched for again at most every
    // kSearchPeriod while missing
    struct Component {
        uintptr_t value = 0;
        size_t slot = ~size_t(0);
        double last_search = -1e9;
    };
    Component results, spectator;
    // who drives which car, from the last scan
    int ctrl_hits = -1, ctrl_vid = -1, spect_vid = -1;
    SpectateState spect; // the spectator director as read at the last scan (on: decided per frame)
    // the car the halo follows (the player's, or the watched one): subject_gen bumps when it changes
    uintptr_t subject_ptr = 0;
    uint32_t subject_gen = 0, subject_base = ~0u;

    // One car from its table slot: a CarLive (its systems container's vptr, its teleport lock pointing into the
    // car itself: see namespace car) whose vehicle id reads back as the slot index. One copy of the car's header,
    // one of its ERS system's vtable and back-pointer. is_ai is a controller state, not an identity: it is
    // recorded as read (the game writes only 0 or 1; anything else counts as "not a human driver").
    SlotStatus read_car_ref(uintptr_t p, uint32_t index, CarRef &c) const
    {
        uint8_t b[car::hi];
        if (!p || (p & 7))
            return kSlotNull;
        if (!copy(p, b, sizeof b))
            return kSlotUnreadable;
        if (!sym.vt_car_systems || field<uintptr_t>(b, 0, car::systems_vt) != sym.vt_car_systems ||
            field<uintptr_t>(b, 0, car::lock) != p + car::lock_cs)
            return kSlotType;
        const uint8_t id = field<uint8_t>(b, 0, car::vehicle_id);
        if (id != index)
            return kSlotId;
        c.ptr = p;
        c.id = id;
        c.is_ai = field<uint32_t>(b, 0, car::is_ai);
        c.ers = system_of(p, field<uintptr_t>(b, 0, car::ers));
        c.tag = field<uintptr_t>(b, 0, 0);
        return c.ers ? kSlotCar : kSlotNoErs;
    }

    // VehicleProgressSystem's per-car entries: [begin, begin + n) pointers indexed by vehicle id.
    bool progress_table(uintptr_t &begin, size_t &n) const
    {
        static_assert(progress::vec_end == progress::vec_begin + sizeof(uintptr_t));
        uintptr_t mgr = 0, sys = 0, be[2] = {};
        if (!rd(sym.game_manager, mgr) || !mgr || !rd(mgr + progress::from_manager, sys) || !sys ||
            !copy(sys + progress::vec_begin, be, sizeof be))
            return false;
        const uintptr_t b = be[0], e = be[1];
        if (!b || e < b || (e - b) % sizeof(uintptr_t) || (e - b) / sizeof(uintptr_t) > 64)
            return false;
        begin = b;
        n = (e - b) / sizeof(uintptr_t);
        return true;
    }

    struct Progress {
        float total = 0;        // D, m
        int lap = 0;            // the lap counter
        int plap = 0;           // progress lap + delta: the lap D is counted from
        uintptr_t vehicle = 0;  // the entry's vehicle component
    };

    // One copy of the entry; a torn XOR pair decodes to garbage, which the ranges reject.
    static bool progress_entry(uintptr_t entry, Progress &p)
    {
        uint8_t b[progress::hi - progress::lo];
        if (!entry || (entry & 7) || !copy(entry + progress::lo, b, sizeof b))
            return false;
        const auto s16 = [&](uintptr_t off) { return int(int16_t(field<uint16_t>(b, progress::lo, off))); };
        p.lap = int(int16_t(field<uint16_t>(b, progress::lo, progress::lap_a) ^ field<uint16_t>(b, progress::lo, progress::lap_b)));
        p.plap = int(int16_t(field<uint16_t>(b, progress::lo, progress::plap_a) ^ field<uint16_t>(b, progress::lo, progress::plap_b))) +
                 s16(progress::plap_delta);
        p.total = from_bits(field<uint32_t>(b, progress::lo, progress::total_a) ^ field<uint32_t>(b, progress::lo, progress::total_b));
        p.vehicle = field<uintptr_t>(b, progress::lo, progress::vehicle);
        return within(p.total, -2.0e4f, 2.0e7f) && p.lap >= -2 && p.lap <= 1000 && p.plap >= -2 && p.plap <= 1000;
    }

    static bool progress_of(uintptr_t begin, size_t n, uint8_t id, Progress &p)
    {
        uintptr_t entry = 0;
        return id < n && rd(begin + id * sizeof(uintptr_t), entry) && progress_entry(entry, p);
    }

    // A component in the registry: the cached slot while it still holds the key and the same value, else a
    // search of the registry's slots (read 64 at a time; a few hundred slots).
    bool find_component(Component &c, uintptr_t key, double now)
    {
        static_assert(registry::info == registry::slots + sizeof(uintptr_t));
        const uintptr_t cached = c.value;
        c.value = 0; // known again only once this call has validated it
        uintptr_t mgr = 0, reg = 0, sl[2] = {};
        if (!key || !rd(sym.game_manager, mgr) || !mgr || !rd(mgr + registry::from_manager, reg) || !reg ||
            !copy(reg + registry::slots, sl, sizeof sl))
            return false;
        const uintptr_t base = sl[0], info = sl[1];
        if (!base || (base & 7) || info <= base || (info - base) % 16 || (info - base) / 16 > registry::max_slots)
            return false;
        const size_t n = (info - base) / 16;
        uintptr_t kv[2];
        uint8_t used = 0;
        if (cached && c.slot < n && copy(base + c.slot * 16, kv, sizeof kv) && kv[0] == key && kv[1] == cached &&
            rd(info + c.slot, used) && used) {
            c.value = cached;
            return true;
        }
        c.slot = ~size_t(0);
        if (now - c.last_search < kSearchPeriod && now >= c.last_search)
            return false;
        c.last_search = now;
        uintptr_t chunk[2 * 64];
        for (size_t i = 0; i < n; i += 64) {
            const size_t m = std::min<size_t>(64, n - i);
            if (!copy(base + i * 16, chunk, m * 16))
                return false;
            for (size_t j = 0; j < m; ++j) {
                const uintptr_t value = chunk[2 * j + 1];
                if (chunk[2 * j] == key && value && !(value & 7) && rd(info + i + j, used) && used) {
                    c.value = value;
                    c.slot = i + j;
                    return true;
                }
            }
        }
        return false;
    }

    // A competitor, not the safety car (which the car table holds too). In F1 the safety car is the only car
    // without ERS (2026-11-09 23:58 log, 2025 grid: 20 cars with ERS, the safety car without at id 20), so there
    // only cars with ERS count, as before. In F2 no car has ERS (2026-11-10 00:07 and 01:36 logs: 22 cars and the
    // safety car all without, the safety car at id 22, 22 results entries): there a car counts when its id is
    // below the results' entry count, and before the scan's results read (entrants 0) none does. The tower's
    // Reader::racer uses the entry count in every field.
    bool racer(const CarRef &c) const { return c.ers || (!field_ers && c.id < entrants); }

    // Each car's classification position (scan time): entry +0 must read back the vehicle id, positions must
    // be 1..count, and no two cars may share one (else nothing is reported). Competitors only (racer), the same
    // rule as the road order: the results system's entry for the safety car's id, if any, is not part of the
    // session's order.
    void classify(uint32_t count, double now)
    {
        static_assert(results::vec_end == results::vec_begin + sizeof(uintptr_t));
        uintptr_t v[2];
        if (!find_component(results, sym.results_key, now) || !copy(results.value + results::vec_begin, v, sizeof v) ||
            !v[0] || (v[0] & 7) ||
            v[1] <= v[0] || (v[1] - v[0]) % sizeof(uintptr_t) || (v[1] - v[0]) / sizeof(uintptr_t) > 64)
            return;
        const size_t ne = (v[1] - v[0]) / sizeof(uintptr_t);
        uintptr_t entries[64];
        if (!copy(v[0], entries, ne * sizeof(uintptr_t)))
            return;
        entrants = ne;
        uint64_t seen = 0;
        bool dup = false;
        for (int i = 0; i < n_cars; ++i) {
            const uint8_t vid = cars[i].id;
            uint8_t b[results::hi];
            if (!racer(cars[i]) || vid >= ne || !entries[vid] || (entries[vid] & 7) || !copy(entries[vid], b, sizeof b) ||
                field<uint8_t>(b, 0, results::vehicle) != vid)
                continue;
            const uint32_t p = (field<uint32_t>(b, 0, results::pos_a) ^ field<uint32_t>(b, 0, results::pos_b)) + 1;
            if (p < 1 || p > count)
                continue;
            dup = dup || ((seen >> p) & 1);
            seen |= uint64_t(1) << p;
            order.pos[vid] = uint8_t(p);
        }
        order.classified = !dup;
        if (dup)
            std::memset(order.pos, 0, sizeof order.pos);
    }

    // The ControllerSystem's local human cars (scan time). ctrl_hits: -1 when the system is not readable (other
    // layout, a mode without it), 0 before its sets are built or with no local human, else the number of cars
    // with a HumanController whose set reads back its vehicle index; ctrl_vid: that car when exactly one.
    void read_controllers()
    {
        static_assert(controllers::count_hi == controllers::count_lo + 8);
        ctrl_hits = -1;
        ctrl_vid = -1;
        uintptr_t sys = 0, vt = 0, cv = 0, sets = 0;
        uint8_t built = 0;
        if (!sym.controllers || !sym.vt_controllers || !rd(sym.controllers, sys) || !sys || (sys & 7) || !rd(sys, vt) ||
            vt != sym.vt_controllers)
            return;
        ctrl_hits = 0;
        uint32_t c[3];
        if (!rd(sys + controllers::built, built) || !built || !rd(sys + controllers::count_vec, cv) || !cv || (cv & 7) ||
            !copy(cv + controllers::count_lo, c, sizeof c) || !rd(sys + controllers::sets, sets) || !sets || (sets & 7))
            return;
        const size_t n = uint8_t((c[2] - c[0]) >> 3);
        uintptr_t set[kMaxCars];
        if (!n || n > size_t(kMaxCars) || !copy(sets, set, n * sizeof(uintptr_t)))
            return;
        for (size_t i = 0; i < n; ++i) {
            uint8_t b[controllers::set_vehicle + 1 - controllers::set_human];
            if (!set[i] || (set[i] & 7) || !copy(set[i] + controllers::set_human, b, sizeof b))
                continue;
            const uintptr_t hc = field<uintptr_t>(b, controllers::set_human, controllers::set_human);
            uintptr_t hvt = 0;
            if (!hc || (hc & 7) || field<uint8_t>(b, controllers::set_human, controllers::set_vehicle) != i || !rd(hc, hvt) ||
                hvt != sym.vt_human)
                continue;
            ++ctrl_hits;
            ctrl_vid = int(i);
        }
        if (ctrl_hits != 1)
            ctrl_vid = -1;
    }

    // The spectator director (scan time): one copy of +0xd0..+0xe7. spect_vid (the log's column since 2026-11-09)
    // keeps its rule: the director active and its car below the table count.
    void read_spectate(uint32_t count, double now)
    {
        spect_vid = -1;
        spect = SpectateState{};
        uint8_t b[spectate::hi - spectate::lo];
        spect.found = find_component(spectator, sym.spectate_key, now);
        if (!spect.found || !copy(spectator.value + spectate::lo, b, sizeof b))
            return;
        spect.read = true;
        spect.ui = field<uint8_t>(b, spectate::lo, spectate::ui);
        spect.active = field<uint8_t>(b, spectate::lo, spectate::active);
        spect.vehicle = field<uint8_t>(b, spectate::lo, spectate::vehicle);
        spect.gap = field<uint32_t>(b, spectate::lo, spectate::gap);
        if (spect.active && spect.vehicle < count)
            spect_vid = spect.vehicle;
    }

    // The watched car's index in cars[] while the spectator HUD is up (+0xd0 and +0xd1 set, +0xd6 a car of the
    // table), else -1: the halo then follows the player.
    int watched() const
    {
        if (!spect.read || !spect.ui || !spect.active || spect.vehicle >= slot_count)
            return -1;
        return index_of(spect.vehicle);
    }

    int index_of(int vid) const
    {
        for (int i = 0; i < n_cars; ++i)
            if (cars[i].id == vid)
                return i;
        return -1;
    }

    void forget_cars()
    {
        n_cars = 0;
        slot_count = 0;
        slot_status[0] = 0;
        order = FieldState{};
        entrants = 0;
        field_ers = false;
        spect = SpectateState{};
        spect_vid = -1;
    }

    // Re-read every car behind the table's slots and rebuild the running order.
    void scan(const uintptr_t *now_slots, uint32_t count, double now)
    {
        last_scan = now;
        slot_count = count;
        std::memcpy(slots, now_slots, count * sizeof(uintptr_t));
        n_cars = 0;
        field_ers = false;
        for (uint32_t i = 0; i < count; ++i) {
            CarRef c;
            const SlotStatus st = read_car_ref(slots[i], i, c);
            slot_status[i] = char(st);
            if (is_car(st)) {
                cars[n_cars++] = c;
                field_ers = field_ers || c.ers;
            } else
                ++raw.rejects;
        }
        slot_status[count] = 0;
        read_controllers();
        read_spectate(count, now);
        // running order by the game's distance-covered counter (racers only: not the safety car)
        order = FieldState{};
        entrants = 0;
        if (n_cars)
            classify(count, now);
        uintptr_t begin = 0;
        size_t entries = 0;
        uintptr_t ptrs[64];
        if (!n_cars || !progress_table(begin, entries) || !entries || !copy(begin, ptrs, entries * sizeof(uintptr_t)))
            return;
        for (int i = 0; i < n_cars; ++i) {
            Progress pr;
            if (!racer(cars[i]) || cars[i].id >= entries || !progress_entry(ptrs[cars[i].id], pr))
                continue;
            order.id[order.n] = cars[i].id;
            order.total_m[order.n] = pr.total;
            ++order.n;
        }
        // insertion sort, leader first (at most kMaxCars entries)
        for (int i = 1; i < order.n; ++i)
            for (int j = i; j > 0 && order.total_m[j] > order.total_m[j - 1]; --j) {
                std::swap(order.total_m[j], order.total_m[j - 1]);
                std::swap(order.id[j], order.id[j - 1]);
            }
    }

    // The player's car (static-validation.md A5: is_ai is a controller state, not an identity).
    // 1. The game's own record: the one car with a local HumanController (it stays through AI takeovers).
    // 2. Two or more (split-screen): none; one set of leaves cannot show two cars.
    // 3. The ControllerSystem unreadable or without a human car: the is_ai rule. Exactly one human-driven car;
    //    with none (an AI handover) or several (loading: every car reads 0) the car already held; else none.
    //    Kept as the fallback until a drive confirms 1 (both are logged).
    int find_player(bool &ai_driving)
    {
        ai_driving = false;
        int human = -1, humans = 0, held = -1;
        for (int i = 0; i < n_cars; ++i) {
            if (cars[i].is_ai == 0) {
                human = i;
                ++humans;
            }
            if (player_ptr && cars[i].ptr == player_ptr)
                held = i;
        }
        const int by_ai = humans == 1 ? human : held;
        raw.humans = uint8_t(humans);
        raw.isai_vid = int8_t(by_ai >= 0 ? cars[by_ai].id : -1);
        int me = -1;
        if (ctrl_hits == 1 && (me = index_of(ctrl_vid)) >= 0)
            raw.player_source = 2;
        else if (ctrl_hits >= 2)
            me = -1;
        else if ((me = by_ai) >= 0)
            raw.player_source = 3;
        if (me >= 0)
            ai_driving = cars[me].is_ai != 0;
        return me;
    }

    void sample(double now, GameState &o)
    {
        o = GameState{};
        o.time = now;
        o.frame = ++frame;
        o.compatible = ok;
        raw = F1_25Raw{};
        if (!ok)
            return;

        // session globals
        uint32_t type = 0;
        if (rd(sym.session_type, type) && type <= 64) {
            o.session.type_ok = true;
            o.session.type = type;
        }
        float len = 0;
        if (rd(sym.track_length, len) && within(len, 500.f, 20000.f)) {
            o.session.track_ok = true;
            o.session.track_length_m = len;
        }

        // the cars: the count is written as a byte (mov [g_Sess_VehicleCount], al)
        uint8_t count = 0;
        uintptr_t now_slots[kMaxCars];
        const bool count_read = rd(sym.vehicle_count, count);
        raw.vcount = count_read ? count : 0;
        if (!count_read || count == 0 || count > kMaxCars ||
            !copy(sym.vehicle_table, now_slots, count * sizeof(uintptr_t))) {
            forget_cars();
            lose_player();
            o.session.generation = generation;
            o.session.subject = subject_gen;
            return;
        }
        const bool changed = count != slot_count || std::memcmp(now_slots, slots, count * sizeof(uintptr_t)) != 0;
        bool scanned = false;
        if (changed || now - last_scan >= kScanPeriod - 1e-6 || now < last_scan) {
            scan(now_slots, count, now);
            scanned = true;
        } else {
            // between scans the player's car itself is still re-read every frame, and the watched car while the
            // halo follows it (one header copy each)
            const int w = watched();
            const uintptr_t follow = w >= 0 ? cars[w].ptr : 0;
            for (int i = 0; i < n_cars && !scanned; ++i)
                if (cars[i].ptr == player_ptr || (follow && cars[i].ptr == follow)) {
                    CarRef c;
                    const SlotStatus st = read_car_ref(slots[cars[i].id], cars[i].id, c);
                    if (is_car(st)) {
                        cars[i] = c;
                    } else {
                        scan(now_slots, count, now);
                        scanned = true;
                    }
                }
        }
        raw.scanned = scanned;
        std::memcpy(raw.slots, slot_status, sizeof raw.slots);
        raw.results_found = results.value != 0;
        raw.ctrl_hits = int8_t(ctrl_hits);
        raw.ctrl_vid = int8_t(ctrl_vid);
        raw.spect_vid = int8_t(spect_vid);
        o.session.cars = uint32_t(n_cars);
        o.session.active = n_cars > 0;
        bool ai_driving = false;
        const int me = find_player(ai_driving);
        o.spectate = spect; // the director as read at the last scan (logged); on: below
        if (me < 0) {
            lose_player();
            o.session.generation = generation;
            o.session.subject = subject_gen;
            return;
        }
        if (cars[me].ptr != player_ptr || count != last_count) {
            ++generation;
            dist_n = 0;
        }
        last_count = count;
        o.session.generation = generation;
        player_ptr = cars[me].ptr;
        raw.old_check = int8_t(!(cars[me].tag & 7) && mem::in_image(cars[me].tag));
        // the car the halo follows: the watched one while the spectator HUD is up, else the player's. A switch bumps
        // the subject generation only (the halo starts afresh); the car set's generation (the tower's) stays.
        const int w = watched();
        const int sub = w >= 0 ? w : me;
        if (cars[sub].ptr != subject_ptr || generation != subject_base) {
            ++subject_gen;
            subject_ptr = cars[sub].ptr;
            subject_base = generation;
            dist_n = 0;
        }
        o.session.subject = subject_gen;
        o.spectate.on = w >= 0;
        read_track_name(now, o.session);
        read_car(cars[sub], sub == me ? ai_driving : cars[sub].is_ai != 0, o);
        o.vehicle.player = sub == me;
        o.vehicle.player_id = cars[me].id;
        // re-validated after the reads (static-validation.md, safe read plan step 6): a car destroyed or moved
        // to another slot meanwhile discards this frame's car values (never replaced by another car's)
        uintptr_t slot_now = 0;
        uint8_t id_now = 0xff;
        if (!rd(sym.vehicle_table + size_t(cars[sub].id) * sizeof(uintptr_t), slot_now) || slot_now != cars[sub].ptr ||
            !rd(cars[sub].ptr + car::vehicle_id, id_now) || id_now != cars[sub].id) {
            o.vehicle = VehicleState{};
            o.power_unit = PowerUnitState{};
            o.energy = EnergyState{};
            o.input = DriverInputState{};
            ++raw.rejects;
            return;
        }

        // the followed car's own progress every frame; the field's order from the last scan
        uintptr_t begin = 0, linked = 0;
        size_t entries = 0;
        Progress pr;
        if (progress_table(begin, entries) && progress_of(begin, entries, cars[sub].id, pr)) {
            // the entry's link back to the car is logged, not required, until a drive confirms it (T8)
            raw.progress_link = pr.vehicle && !(pr.vehicle & 7) && rd(pr.vehicle + progress::vehicle_car, linked) &&
                                linked == cars[sub].ptr;
            o.progress.total_m = pr.total;
            o.progress.lap = pr.lap;
            if (o.session.track_ok) {
                const float L = o.session.track_length_m;
                o.progress.ok = true;
                o.progress.lap_m = std::clamp(pr.total - float(pr.plap) * L, 0.f, L);
            }
            distance_reference(pr.total, now);
        }
        o.field = order;
        for (int i = 0; i < order.n; ++i)
            if (order.id[i] == cars[sub].id)
                o.field.player_rank = i;
        o.field.ok = o.field.n > 0 && o.field.player_rank >= 0;
        o.field.classified = order.classified && order.pos[cars[sub].id] > 0;
    }

    // The loaded track's internal name: [[[track_world]+0xd0]+0xe8]+0xa0 -> char * (the ERS reader's
    // TrackSettings lookup, 0x1446d062b). Optional: turn numbers fall back to the track length without it.
    void read_track_name(double now, SessionState &s)
    {
        if (generation != name_generation || now - last_name >= kNamePeriod || now < last_name) {
            name_generation = generation;
            last_name = now;
            uintptr_t w = 0, a = 0, t = 0, str = 0;
            name_ok = sym.track_world && rd(sym.track_world, w) && w && rd(w + 0xd0, a) && a && rd(a + 0xe8, t) && t &&
                      rd(t + 0xa0, str) && c_string(str, name, sizeof name);
            if (!name_ok)
                name[0] = 0;
        }
        if (name_ok) {
            s.track_name_ok = true;
            std::memcpy(s.track_name, name, sizeof name);
        }
    }

    // Speed along the track from the progress total, for the validation log only (raw.speed_from_distance): the
    // distance between two changes of the total >= kDistWindow apart over the time between them. Both ends are
    // changes, so the frames between simulation steps add no error. O(1) per frame: one comparison, and on a
    // change one push and a trim that drops each mark once.
    void distance_reference(float total, double now)
    {
        constexpr int mask = kDistMarks - 1;
        if (dist_n > 0) {
            const DistMark &last = dist[(dist_head - 1) & mask];
            const double dt = now - last.t;
            if (total == last.total) { // no simulation step since the last change
                if (dt < kDistStale && dt >= 0) {
                    raw.speed_from_distance = dist_speed;
                    raw.distance_window = dist_window;
                }
                return;
            }
            if (dt >= kDistStale || dt <= 0 || std::fabs(total - last.total) > kDistMaxSpeed * float(dt) + 1.f)
                dist_n = 0;
        }
        if (dist_n == 0)
            dist_speed = dist_window = 0;
        dist[dist_head] = {total, now};
        dist_head = (dist_head + 1) & mask;
        dist_n = std::min(dist_n + 1, kDistMarks);
        while (dist_n > 2 && now - dist[(dist_head - dist_n + 1) & mask].t >= kDistWindow)
            --dist_n; // the second-oldest mark is far enough back: the oldest is not needed
        const DistMark &old = dist[(dist_head - dist_n) & mask];
        if (now - old.t >= kDistWindow) {
            dist_window = float(now - old.t);
            dist_speed = float((double(total) - double(old.total)) / (now - old.t));
        }
        raw.speed_from_distance = dist_speed;
        raw.distance_window = dist_window;
    }

    void lose_player()
    {
        if (player_ptr) {
            player_ptr = 0;
            ++generation;
        }
        if (subject_ptr) {
            subject_ptr = 0;
            ++subject_gen;
        }
        last_count = 0;
        dist_n = 0;
    }

    // One car's values (the car the halo follows): its systems as read from this car only. A system that is
    // missing or fails its checks leaves its values not ok.
    void read_car(const CarRef &c, bool ai_driving, GameState &o)
    {
        uint8_t live[car::hi - car::lo];
        if (!copy(c.ptr + car::lo, live, sizeof live))
            return;
        VehicleState &v = o.vehicle;
        v.ok = true;
        v.id = c.id;
        v.ai_driving = ai_driving;
        raw.is_ai = c.is_ai;
        raw.input_flags = field<uint8_t>(live, car::lo, car::input_flags);

        const uintptr_t eng = system_of(c.ptr, field<uintptr_t>(live, car::lo, car::engine));
        const uintptr_t gb = system_of(c.ptr, field<uintptr_t>(live, car::lo, car::gearbox));
        const uintptr_t ch = system_of(c.ptr, field<uintptr_t>(live, car::lo, car::chassis));
        const uintptr_t st = system_of(c.ptr, field<uintptr_t>(live, car::lo, car::steering));
        const uintptr_t es = c.ers;

        // gear
        uint32_t gi = 0;
        if (gb && rd(gb + gearbox::gear_index, gi) && gi <= 10) {
            v.gear_ok = true;
            v.gear = int(gi) - 1;
            raw.gear_index = gi;
        }

        // pedals (swapped while reversing with the "brake to reverse" style flag)
        const float th = field<float>(live, car::lo, car::throttle);
        const float br = field<float>(live, car::lo, car::brake);
        raw.throttle_field = th;
        raw.brake_field = br;
        if (within(th, -0.05f, 1.05f) && within(br, -0.05f, 1.05f)) {
            const bool swap = v.gear_ok && gi == 0 && (raw.input_flags & 0x88) == 0x08;
            o.input.ok = true;
            o.input.throttle = std::clamp(swap ? br : th, 0.f, 1.f);
            o.input.brake = std::clamp(swap ? th : br, 0.f, 1.f);
        }

        // engine
        float rate = 0, limiter = 0;
        if (eng && rd(eng + engine::rate, rate) && within(rate, 0.f, 3000.f)) {
            o.power_unit.rpm_ok = true;
            o.power_unit.rpm = rate * 9.5492966f;
            raw.engine_rate = rate;
        }
        if (eng && rd(eng + engine::limiter, limiter) && within(limiter, 300.f, 3000.f)) {
            o.power_unit.limiter_ok = true;
            o.power_unit.limiter_rpm = limiter * 9.5492966f;
        }

        // chassis: g-forces and velocity
        if (ch) {
            float g[2];
            if (rd(ch + chassis::g_lat, g) && within(g[0], -12.f, 12.f) && within(g[1], -12.f, 12.f)) {
                v.accel_ok = true;
                v.g_lat = g[0];
                v.g_long = g[1];
            }
            uintptr_t body = 0, state = 0;
            float vel[3];
            if (rd(ch + chassis::body, body) && body && rd(body + chassis::body_state, state) && state &&
                rd(state + chassis::state_velocity, vel) && within(vel[0], -200.f, 200.f) &&
                within(vel[1], -200.f, 200.f) && within(vel[2], -200.f, 200.f)) {
                const float s = std::sqrt(vel[0] * vel[0] + vel[1] * vel[1] + vel[2] * vel[2]);
                if (s <= 160.f) {
                    v.speed_ok = true;
                    v.speed_mps = s;
                    std::memcpy(raw.vel, vel, sizeof vel);
                }
            }
        }

        // steering, normalised to the lock
        float angle = 0, lock = 0;
        if (st && read_obf_float(st + steering::angle, angle) && read_obf_float(st + steering::lock, lock) &&
            within(lock, 0.05f, 1.6f) && within(angle, -1.7f, 1.7f)) {
            v.steer_ok = true;
            v.steer = std::clamp(-angle / lock, -1.f, 1.f);
            raw.steer_angle = angle;
            raw.steer_lock = lock;
        }

        // energy recovery
        if (es) {
            EnergyState &e = o.energy;
            uint8_t b[ers::live_hi - ers::live_lo];
            float cfg[2];
            if (copy(es + ers::live_lo, b, sizeof b)) {
                const float energy = field<float>(b, ers::live_lo, ers::energy);
                const float hk = field<float>(b, ers::live_lo, ers::harvest_k);
                const float hh = field<float>(b, ers::live_lo, ers::harvest_h);
                const float dp = field<float>(b, ers::live_lo, ers::deploy);
                const int32_t mode = field<int32_t>(b, ers::live_lo, ers::mode);
                const float hl = field<float>(b, ers::live_lo, ers::harvest_lap);
                const float dl = field<float>(b, ers::live_lo, ers::deploy_lap);
                const float ll = field<float>(b, ers::live_lo, ers::lap_limit);
                if (within(energy, -1.0e5f, 2.0e7f)) {
                    e.store_ok = true;
                    e.store_j = std::max(0.f, energy);
                }
                if (within(hk, -2.0e6f, 2.0e6f) && within(hh, -2.0e6f, 2.0e6f) && within(dp, -2.0e6f, 2.0e6f)) {
                    e.power_ok = true;
                    e.harvest_k_w = hk;
                    e.harvest_h_w = hh;
                    e.deploy_w = dp;
                }
                if (mode >= 0 && mode <= 3) {
                    e.mode_ok = true;
                    e.mode = mode;
                }
                if (within(hl, -1.0e5f, 1.0e8f) && within(dl, -1.0e5f, 1.0e8f) && within(ll, 0.f, 1.0e8f)) {
                    e.lap_ok = true;
                    e.harvested_lap_j = hl;
                    e.deployed_lap_j = dl;
                    e.harvest_limit_lap_j = ll;
                }
                std::memcpy(raw.ers_flags, b + (ers::flags - ers::live_lo), sizeof raw.ers_flags);
            }
            if (rd(es + ers::max_deploy, cfg[0]) && within(cfg[0], 1.0e4f, 2.0e6f)) {
                e.max_deploy_ok = true;
                e.max_deploy_w = cfg[0];
            }
            if (rd(es + ers::capacity, cfg[1]) && within(cfg[1], 1.0e5f, 5.0e7f)) {
                e.capacity_ok = true;
                e.capacity_j = cfg[1];
            }
        }
    }
};

F1_25Provider::F1_25Provider(const F1_25Symbols &symbols, bool build_ok) : impl_(std::make_unique<Impl>())
{
    impl_->sym = symbols;
    impl_->ok = build_ok && symbols.vehicle_table && symbols.vehicle_count && symbols.game_manager &&
                symbols.track_length && symbols.session_type && symbols.vt_car_systems;
}

F1_25Provider::~F1_25Provider() = default;

const char *F1_25Provider::describe() const
{
    return impl_->ok ? "F1 25 d873a1c8 (in-process memory)" : "F1 25 (unsupported build: in-process reads disabled)";
}

bool F1_25Provider::compatible() const { return impl_->ok; }

void F1_25Provider::sample(double now, GameState &out) { impl_->sample(now, out); }

const F1_25Raw &F1_25Provider::raw() const { return impl_->raw; }

bool f1_25_build_matches()
{
    const auto *base = reinterpret_cast<const uint8_t *>(GetModuleHandleW(nullptr));
    if (!base)
        return false;
    const auto *dos = reinterpret_cast<const IMAGE_DOS_HEADER *>(base);
    const auto *nt = reinterpret_cast<const IMAGE_NT_HEADERS64 *>(base + dos->e_lfanew);
    return nt->FileHeader.TimeDateStamp == kBuildTimestamp && nt->OptionalHeader.SizeOfImage == kBuildImageSize;
}

bool f1_25_resolve(F1_25Symbols &out, const char **missing)
{
    struct Want {
        const char *id;
        uintptr_t *slot;
    } wants[] = {
        {"g_Sess_VehicleTable", &out.vehicle_table},
        {"g_Sess_VehicleCount", &out.vehicle_count},
        {"g_Game_Manager", &out.game_manager},
        {"g_Game_TrackLength", &out.track_length},
        {"g_Sess_TyreRulesSessionType", &out.session_type},
    };
    for (Want &w : wants) {
        *w.slot = swofty::api && swofty::api->version >= 2 && swofty::api->resolve ? swofty::api->resolve(w.id) : 0;
        if (!*w.slot) {
            if (missing)
                *missing = w.id;
            return false;
        }
    }
    // Addresses inside this build's image (the provider runs only when f1_25_build_matches()). The car type's
    // vptr is required (the provider stays off without it); the rest is optional.
    if (const auto *base = reinterpret_cast<const uint8_t *>(GetModuleHandleW(nullptr))) {
        const uintptr_t b = uintptr_t(base);
        out.vt_car_systems = b + car::systems_vt_rva;
        out.results_key = b + results::key_rva;
        out.controllers = b + controllers::cache_rva;
        out.vt_controllers = b + controllers::vt_system_rva;
        out.vt_human = b + controllers::vt_human_rva;
        out.spectate_key = b + spectate::key_rva;
    }
    // Optional: the track singleton has no Swofty binding; find the one instruction that loads it
    // (mov rax,[rip+X]; mov rax,[rax+0xd0]; mov rax,[rax+0xe8] — unique in this build) and decode X.
    uintptr_t at = 0;
    int32_t disp = 0;
    if (swofty::api && swofty::api->scan &&
        swofty::api->scan(".xtls", "48 8B 05 ?? ?? ?? ?? 48 8B 80 D0 00 00 00 48 8B 80 E8 00 00 00", &at) == 1 && at &&
        rd(at + 3, disp))
        out.track_world = at + 7 + intptr_t(disp);
    return true;
}

}
