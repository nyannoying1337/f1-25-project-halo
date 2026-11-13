// Host tests for the timing tower: reader (tower_reader.cpp), model (tower_model.cpp) and leaf publisher
// (tower_leaves.cpp), and since v11 the rows' motion (tower_anim.cpp). Fake game systems are built in this process with the layouts from
// docs/timing-tower/field-traces.md and read through ReadProcessMemory, exactly as in the game.
// Build and run: tests/run_tests.sh (after the halo's host tests). Writes <out>/tower_leaves.txt.
#include "../src/tower_anim.hpp"
#include "../src/tower_leaves.hpp"
#include "../src/tower_model.hpp"
#include "../src/tower_reader.hpp"
#include "../src/diag_log.hpp"

#include <swofty/mixin.hpp>

#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <memory>
#include <set>
#include <string>
#include <vector>

using namespace tower;

static int g_fail = 0, g_pass = 0;
#define CHECK(cond)                                                                                                    \
    do {                                                                                                               \
        if (cond)                                                                                                      \
            ++g_pass;                                                                                                  \
        else {                                                                                                         \
            ++g_fail;                                                                                                  \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                                               \
        }                                                                                                              \
    } while (0)

// ---------------------------------------------------------------- fake memory

static uint8_t *alloc(size_t n)
{
    auto *p = static_cast<uint8_t *>(VirtualAlloc(nullptr, n, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    std::memset(p, 0, n);
    return p;
}
static void release(uint8_t *p) { VirtualFree(p, 0, MEM_RELEASE); }
template <class T> static void put(uint8_t *b, size_t off, T v) { std::memcpy(b + off, &v, sizeof v); }

static bool rpm_copy(void *, uintptr_t addr, void *dst, size_t n)
{
    SIZE_T got = 0;
    return ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<LPCVOID>(addr), dst, n, &got) && got == n;
}
static Mem mem() { return Mem{rpm_copy, nullptr}; }

// registry keys: addresses of statics, like the game's
static uintptr_t key_results[1], key_timing[1], key_pit[1], key_sc[1], key_log[1], key_s1[1], key_tyres[1],
    key_zones[1], key_red[1], key_mode[1], key_teams[1], key_laps[1];

// the game's lap times (VehicleLapTimes): LT with the record vector at +0x58 and the fastest car at +0xb8;
// one record per vehicle id, the lap index at +0x38, 200 lap entries of 0xc8 bytes from +0x40
struct FakeLaps {
    uint8_t *LT = nullptr, *vec = nullptr, *rec[32]{};
};
static void lap_put(uint8_t *R, int lap, float t, bool valid = true, float s3 = 30.f)
{
    uint8_t *e = R + 0x40 + size_t(lap) * 0xc8;
    const float v[4] = {28.f, 31.f, s3, t};
    const size_t off[4] = {0x08, 0x18, 0x28, 0xa8};
    for (int k = 0; k < 4; ++k) {
        uint32_t bits;
        std::memcpy(&bits, &v[k], 4);
        const uint32_t mask = 0x5a3c00f1u * uint32_t(k + 1 + lap);
        std::memcpy(e + off[k], &(bits ^= mask), 4);
        std::memcpy(e + off[k] + 8, &mask, 4);
    }
    const uint64_t key = 0x9e3779b97f4a7c14ull + uint64_t(lap); // low bit: the lap's parity
    std::memcpy(e + 0xa0, &key, 8);
    e[0x98] = uint8_t((key & 1) ^ (valid ? 0 : 1));
}
// render badges: the game's source names and its none value's word (none = word + 0x5874f662 = 0x3fff)
static const char *const kSourceName[3] = {"ePreLoaded", "eUserDefined", "eNetworkReplicated"};
static uint32_t g_badge_none = 0x3fffu - 0x5874f662u;

constexpr int N = 22; // competitors; vehicle id 22 is the safety car
constexpr int kZones = 20; // marshal zones; zone i starts at lap fraction i / 20 (300 m apart on the 6000 m track)
// team badges: records 0..10 the 2026 teams (car v drives for team v / 2), 11..15 free for the broken cases
constexpr int kTeams = 16;
static const char *const kTeamKey[11] = {"mclaren_26",  "mercedes_26",     "red_bull_26", "ferrari_26",
                                         "williams_26", "alphatauri_26",   "aston_martin_26", "haas_26",
                                         "alfa_romeo_26", "alpine_26",     "gm_cadillac_26"};
constexpr const char *kHudBadge = "#overrides.osd.timing_tower.team_badges_hud.";

struct FakeTower {
    uintptr_t manager = 0; // g_Game_Manager
    uint8_t *mgr, *reg, *slots, *info;
    int n_slots = 0;
    // results
    uint8_t *R, *rvec, *rsorted, *entry[32]{};
    // timing
    uint8_t *T, *tent;
    int t_n = 0;
    // pit
    uint8_t *S, *pit[32]{};
    // safety car
    uint8_t *SC;
    // penalty log
    uint8_t *Z, *zrec;
    int z_n = 0;
    // session component with the misconduct vectors
    uint8_t *S1, *DT, *dtrec, *SG, *sgrec;
    // tyres
    uint8_t *TS, *tsvec, *V[32]{}, *vis[9]{}, *act[9]{};
    // progress
    uint8_t *PS, *pvec, *pent[32]{};
    // flags: the marshal zone list (entries, zones, zone definitions), the red flag system, the sector table block
    uint8_t *MZ, *zvec, *zone[kZones]{}, *zdef[kZones]{};
    uint8_t *RF, *sectors;
    // team badges: game mode context -> [+0x88] -> [+0x260] = the game with the entrants; the team tables system
    // with one table per kind (records 0..15 in each), the records' keys in one page
    uint8_t *GMC, *MODE, *G, *ent, *TT, *table[3]{}, *tvec[3]{}, *trec[kTeams]{}, *keys;
    int ent_n = 0;
    // the game mode's label: [MODE+0x278] points into this page (Time Trial, ModeRead)
    uint8_t *label;
    Frame frame;
};

static void place(FakeTower &f, int slot, uintptr_t key, uint8_t *value)
{
    put<uintptr_t>(f.slots, size_t(slot) * 16, key);
    put<uintptr_t>(f.slots, size_t(slot) * 16 + 8, uintptr_t(value));
    f.info[slot] = value ? 0x81 : 0;
}

static void set_pos(FakeTower &f, int vid, uint32_t pos)
{
    const uint32_t key = 0x2468ace0u ^ (uint32_t(vid) * 0x01000193u);
    put<uint32_t>(f.entry[vid], 0x48, (pos - 1) ^ key);
    put<uint32_t>(f.entry[vid], 0x50, key);
}
static void set_status(FakeTower &f, int vid, uint8_t st) { put<uint8_t>(f.entry[vid], 0x18, st); }
static void set_tpen(FakeTower &f, int vid, double s)
{
    uint64_t bits;
    std::memcpy(&bits, &s, 8);
    put<uint64_t>(f.entry[vid], 0x38, bits ^ 0x5555aaaa5555aaaaull);
    put<uint64_t>(f.entry[vid], 0x40, 0x5555aaaa5555aaaaull);
}
// sorted list: entry k = the car in position k + 1
static void sort_results(FakeTower &f, const int *order, int n)
{
    for (int k = 0; k < n; ++k)
        put<uintptr_t>(f.rsorted, size_t(k) * 8, uintptr_t(f.entry[order[k]]));
    put<uintptr_t>(f.R, 0x108, uintptr_t(f.rsorted));
    put<uintptr_t>(f.R, 0x110, uintptr_t(f.rsorted) + size_t(n) * 8);
}
// classification = order[] (vehicle ids by position)
static void classify(FakeTower &f, const int *order, int n)
{
    for (int k = 0; k < n; ++k)
        set_pos(f, order[k], uint32_t(k + 1));
    sort_results(f, order, n);
}

// T entry i for vid: gap to leader and interval (ms, valid flags), gained / lost
static void set_gap(FakeTower &f, int i, int vid, int64_t leader, bool lv, int64_t ahead, bool av)
{
    uint8_t *e = f.tent + size_t(i) * 0x98;
    put<int64_t>(e, 0x58, leader);
    put<uint8_t>(e, 0x68, lv);
    put<int64_t>(e, 0x70, ahead);
    put<uint8_t>(e, 0x80, av);
    put<uint8_t>(e, 0x90, uint8_t(vid));
}
static void set_pit(FakeTower &f, int vid, uint32_t st) { put<uint32_t>(f.pit[vid], 4, st); }
static void set_lap(FakeTower &f, int vid, int lap)
{
    put<uint16_t>(f.pent[vid], 0x38, uint16_t(lap) ^ 0x7a7a);
    put<uint64_t>(f.pent[vid], 0x40, 0x7a7a);
}
static void set_sc(FakeTower &f, uint8_t v, uint8_t extra = 0)
{
    put<uint8_t>(f.SC, 0x108, v);
    put<uint8_t>(f.SC, 0x109, extra);
}
static void add_penalty(FakeTower &f, uint8_t vid, uint8_t type, uint8_t reason, uint32_t time_s = 0, uint32_t lap = 1)
{
    uint8_t *r = f.zrec + size_t(f.z_n) * 0x30;
    put<uint8_t>(r, 8, vid);
    put<uint8_t>(r, 9, type);
    put<uint8_t>(r, 10, reason);
    put<uint8_t>(r, 11, 0xff);
    put<uint32_t>(r, 0xc, time_s);
    put<uint32_t>(r, 0x10, lap);
    ++f.z_n;
    put<uintptr_t>(f.Z, 0x50, uintptr_t(f.zrec) + size_t(f.z_n) * 0x30);
}
static void set_dt(FakeTower &f, int vid, int n)
{
    uint8_t *r = f.dtrec + size_t(vid) * 0x28;
    for (int k = 0; k < 4; ++k)
        r[8 + 8 * k] = k < n ? uint8_t(1) : uint8_t(0xff);
}
static void set_sg(FakeTower &f, int vid, uint8_t n) { f.sgrec[vid * 4 + 3] = n; }
static void set_zone(FakeTower &f, int i, int32_t flag) { put<int32_t>(f.zone[i], 0x14, flag); }
static void set_zone_count(FakeTower &f, int n)
{
    put<uintptr_t>(f.MZ, 0x88, uintptr_t(f.zvec));
    put<uintptr_t>(f.MZ, 0x90, uintptr_t(f.zvec) + size_t(n) * kZoneStride);
}
static void set_red(FakeTower &f, uint8_t v) { put<uint8_t>(f.RF, 0x40, v); }
static void set_sectors(FakeTower &f, int n, const float *ends, float len)
{
    for (int i = 0; i < n && i < 22; ++i)
        put<float>(f.sectors, size_t(i) * 4, ends[i]);
    put<float>(f.sectors, 0x58, len);
    put<uint32_t>(f.sectors, 0x5c, uint32_t(n));
}

// tyre descriptors: compound enum c (3 S, 4 M, 5 H, 7 I, 8 W) with its visual id
static void set_tyre(FakeTower &f, int vid, int compound, bool stale = false, int set_id = -1)
{
    uint8_t *V = f.V[vid];
    put<uint64_t>(V, 0x9bc0, 7);                   // version
    put<uint64_t>(V, 0x9c50, stale ? 6 : 7);       // built for
    put<uint64_t>(V, 0x9c58, 1);                   // built
    put<uint64_t>(V, 0x9c48, 2);                   // two descriptors
    const uint32_t id = set_id >= 0 ? uint32_t(set_id) : uint32_t(compound + 10);
    // descriptor 0: another set; descriptor 1: the current set
    put<uint32_t>(V, 0x9bd0, 99);
    put<uintptr_t>(V, 0x9bd0 + 0x10, uintptr_t(f.vis[3]));
    put<uint32_t>(V, 0x9bd0 + 0x18, compound + 10);
    put<uintptr_t>(V, 0x9bd0 + 0x18 + 8, uintptr_t(f.act[compound]));
    put<uintptr_t>(V, 0x9bd0 + 0x18 + 0x10, uintptr_t(f.vis[compound]));
    // set vector: one 0x78-byte record whose dword +0xc is the current set id
    uint8_t *sets = V + 0xa000;
    put<uint32_t>(sets, 0xc, id);
    put<uintptr_t>(V, 0x9c90, uintptr_t(sets));
    put<uintptr_t>(V, 0x9c98, uintptr_t(sets) + 0x78);
}

static int visual_of(int c) { return c == 3 ? 16 : c == 4 ? 17 : c == 5 ? 18 : c; }

// The entrant of a vehicle id (entries are kept in reverse vehicle order, like the timing entries).
static uint8_t *entrant(FakeTower &f, int vid)
{
    for (int i = 0; i < f.ent_n; ++i)
        if (f.ent[size_t(i) * 0x88 + 0x82] == vid)
            return f.ent + size_t(i) * 0x88;
    return nullptr;
}
// The car's team word: kind (low byte) and index (high 16 bits).
static void set_team(FakeTower &f, int vid, unsigned kind, unsigned index)
{
    put<uint32_t>(entrant(f, vid), 0x58, uint32_t(kind) | uint32_t(index) << 16);
}
// Record t's key string (64 bytes each in the key page); nullptr clears the pointer.
static void set_key(FakeTower &f, int t, const char *s)
{
    char *dst = reinterpret_cast<char *>(f.keys) + t * 64;
    std::memset(dst, 0, 64);
    if (s)
        std::memcpy(dst, s, std::min<size_t>(std::strlen(s), 63));
    put<uintptr_t>(f.trec[t], 0x4d8, s ? uintptr_t(dst) : 0);
}

// The game mode's label (the row label the game keeps at [[GMC+0x88]+0x278]); nullptr clears the pointer. The text
// goes at `off` in the label page (for the page-end case).
static void set_label(FakeTower &f, const char *s, size_t off = 0)
{
    std::memset(f.label, 0, 0x1000);
    if (s)
        std::memcpy(f.label + off, s, std::strlen(s) + (off + std::strlen(s) < 0x1000 ? 1 : 0));
    put<uintptr_t>(f.MODE, 0x278, s ? uintptr_t(f.label + off) : 0);
}

static FakeTower make_tower(int cars = N)
{
    FakeTower f;
    f.mgr = alloc(0x400);
    f.manager = uintptr_t(f.mgr);
    f.n_slots = 300;
    f.reg = alloc(0x40);
    f.slots = alloc(size_t(f.n_slots) * 17);
    f.info = f.slots + size_t(f.n_slots) * 16;
    put<uintptr_t>(f.reg, 0x18, uintptr_t(f.slots));
    put<uintptr_t>(f.reg, 0x20, uintptr_t(f.info));
    put<uintptr_t>(f.mgr, 0x30, uintptr_t(f.reg));
    for (int i = 1; i < f.n_slots; i += 4) { // other systems
        put<uintptr_t>(f.slots, size_t(i) * 16, 0x1000u + uintptr_t(i) * 0x40);
        put<uintptr_t>(f.slots, size_t(i) * 16 + 8, uintptr_t(alloc(0x40)));
        f.info[i] = 0x80;
    }
    // results
    f.R = alloc(0x200);
    f.rvec = alloc(8 * 32);
    f.rsorted = alloc(8 * 32);
    for (int i = 0; i < cars; ++i) {
        f.entry[i] = alloc(0x100);
        put<uint8_t>(f.entry[i], 0, uint8_t(i));
        set_status(f, i, 2);
        set_tpen(f, i, 0.0);
        put<uintptr_t>(f.rvec, size_t(i) * 8, uintptr_t(f.entry[i]));
    }
    put<uintptr_t>(f.R, 0x148, uintptr_t(f.rvec));
    put<uintptr_t>(f.R, 0x150, uintptr_t(f.rvec) + size_t(cars) * 8);
    int order[32];
    for (int i = 0; i < cars; ++i)
        order[i] = i;
    classify(f, order, cars);
    // timing: entries in reverse vehicle order (not guaranteed to be in vehicle order)
    f.T = alloc(0x100);
    f.tent = alloc(size_t(32) * 0x98);
    f.t_n = cars;
    for (int i = 0; i < cars; ++i) {
        const int vid = cars - 1 - i;
        set_gap(f, i, vid, vid ? 1000 * vid : 0, vid != 0, vid ? 1000 : 0, vid != 0);
    }
    put<uintptr_t>(f.T, 0x30, uintptr_t(f.tent));
    put<uintptr_t>(f.T, 0x38, uintptr_t(f.tent) + size_t(cars) * 0x98);
    // pit states
    f.S = alloc(0x300);
    for (int i = 0; i < 32; ++i) {
        f.pit[i] = alloc(0x20);
        put<uintptr_t>(f.S, 0x68 + size_t(i) * 0x10, uintptr_t(f.pit[i]));
    }
    // safety car
    f.SC = alloc(0x200);
    // penalty log (room for 200 records)
    f.Z = alloc(0x100);
    f.zrec = alloc(200 * 0x30);
    put<uintptr_t>(f.Z, 0x48, uintptr_t(f.zrec));
    put<uintptr_t>(f.Z, 0x50, uintptr_t(f.zrec));
    // session component: drive-throughs and stop-gos per car
    f.S1 = alloc(0x600);
    f.DT = alloc(0x100);
    f.SG = alloc(0x100);
    f.dtrec = alloc(size_t(cars) * 0x28);
    f.sgrec = alloc(size_t(cars) * 4);
    std::memset(f.dtrec, 0xff, size_t(cars) * 0x28);
    put<uintptr_t>(f.DT, 0x68, uintptr_t(f.dtrec));
    put<uintptr_t>(f.DT, 0x70, uintptr_t(f.dtrec) + size_t(cars) * 0x28);
    put<uintptr_t>(f.SG, 0x68, uintptr_t(f.sgrec));
    put<uintptr_t>(f.SG, 0x70, uintptr_t(f.sgrec) + size_t(cars) * 4);
    put<uintptr_t>(f.S1, 0x568, uintptr_t(f.DT));
    put<uintptr_t>(f.S1, 0x578, uintptr_t(f.SG));
    put<uintptr_t>(f.S1, 0x588, uintptr_t(alloc(0x100)));
    // tyres
    for (int c = 0; c <= 8; ++c) {
        f.vis[c] = alloc(0x60);
        put<uint8_t>(f.vis[c], 0, uint8_t(visual_of(c)));
        put<int32_t>(f.vis[c], 0x50, c);
        f.act[c] = alloc(0x10);
        put<uint8_t>(f.act[c], 0, uint8_t(c + 100));
    }
    f.TS = alloc(0x200);
    f.tsvec = alloc(8 * 32);
    for (int i = 0; i < cars; ++i) {
        f.V[i] = alloc(0xa100);
        put<uintptr_t>(f.tsvec, size_t(i) * 8, uintptr_t(f.V[i]));
        set_tyre(f, i, i % 2 ? 4 : 3);
    }
    put<uintptr_t>(f.TS, 0x110, uintptr_t(f.tsvec));
    put<uintptr_t>(f.TS, 0x118, uintptr_t(f.tsvec) + size_t(cars) * 8);
    // progress: lap counters
    f.PS = alloc(0x100);
    f.pvec = alloc(8 * 32);
    for (int i = 0; i < cars; ++i) {
        f.pent[i] = alloc(0x100);
        put<uintptr_t>(f.pvec, size_t(i) * 8, uintptr_t(f.pent[i]));
        set_lap(f, i, 9);
    }
    put<uintptr_t>(f.PS, 0x38, uintptr_t(f.pvec));
    put<uintptr_t>(f.PS, 0x40, uintptr_t(f.pvec) + size_t(cars) * 8);
    put<uintptr_t>(f.mgr, 0x2d0, uintptr_t(f.PS));
    // flags: every zone clear, no red flag, three sectors ending at 1500 / 3200 / 6000 m
    f.MZ = alloc(0x100);
    f.zvec = alloc(kZones * kZoneStride);
    for (int i = 0; i < kZones; ++i) {
        f.zdef[i] = alloc(0x20);
        put<float>(f.zdef[i], 0x10, float(i) / kZones);
        put<float>(f.zdef[i], 0x14, float(i + 1) / kZones);
        f.zone[i] = alloc(0x20);
        put<uintptr_t>(f.zone[i], 0, uintptr_t(f.zdef[i]));
        put<uintptr_t>(f.zvec, size_t(i) * kZoneStride + 8, uintptr_t(f.zone[i]));
    }
    set_zone_count(f, kZones);
    f.RF = alloc(0x80);
    f.sectors = alloc(kSectorBlock);
    const float ends[3] = {1500.f, 3200.f, 6000.f};
    set_sectors(f, 3, ends, 6000.f);
    // team badges: car v in team v / 2 (kind 0); the three kinds' tables hold the same 16 records
    f.GMC = alloc(0x100);
    f.MODE = alloc(0x300);
    f.G = alloc(0x300);
    put<uintptr_t>(f.GMC, 0x88, uintptr_t(f.MODE));
    put<uintptr_t>(f.MODE, 0x260, uintptr_t(f.G));
    // a Grand Prix (the label the game sets for one: loader.log 2026-11-10 03:08)
    f.label = alloc(0x2000);
    set_label(f, "grand_prix_23");
    f.ent = alloc(size_t(32) * 0x88);
    f.ent_n = cars;
    for (int i = 0; i < cars; ++i)
        put<uint8_t>(f.ent, size_t(i) * 0x88 + 0x82, uint8_t(cars - 1 - i));
    put<uintptr_t>(f.G, 0x2e0, uintptr_t(f.ent));
    put<uintptr_t>(f.G, 0x2e8, uintptr_t(f.ent) + size_t(cars) * 0x88);
    f.TT = alloc(0x400);
    f.keys = alloc(0x1000);
    for (int t = 0; t < kTeams; ++t)
        f.trec[t] = alloc(0x600);
    for (int k = 0; k < 3; ++k) {
        f.table[k] = alloc(0x20);
        f.tvec[k] = alloc(size_t(kTeams) * 16);
        for (int t = 0; t < kTeams; ++t)
            put<uintptr_t>(f.tvec[k], size_t(t) * 16 + 8, uintptr_t(f.trec[t]));
        put<uintptr_t>(f.table[k], 8, uintptr_t(f.tvec[k]));
        put<uintptr_t>(f.table[k], 0x10, uintptr_t(f.tvec[k]) + size_t(kTeams) * 16);
        put<uintptr_t>(f.TT, 0x2c8 + size_t(k) * 16, uintptr_t(f.table[k]));
    }
    for (int t = 0; t < kTeams; ++t)
        set_key(f, t, t < 11 ? kTeamKey[t] : "f1_generic");
    for (int i = 0; i < cars; ++i)
        set_team(f, i, 0, unsigned(i / 2));
    // the registry
    place(f, 17, uintptr_t(key_results), f.R);
    place(f, 42, uintptr_t(key_timing), f.T);
    place(f, 77, uintptr_t(key_pit), f.S);
    place(f, 103, uintptr_t(key_sc), f.SC);
    place(f, 150, uintptr_t(key_log), f.Z);
    place(f, 201, uintptr_t(key_s1), f.S1);
    place(f, 250, uintptr_t(key_tyres), f.TS);
    place(f, 120, uintptr_t(key_zones), f.MZ);
    place(f, 280, uintptr_t(key_red), f.RF);
    place(f, 34, uintptr_t(key_mode), f.GMC);
    place(f, 66, uintptr_t(key_teams), f.TT);
    // the halo's view of the table: 22 competitors and the safety car
    f.frame.session_ok = true;
    f.frame.session = 15;
    f.frame.generation = 1;
    for (int i = 0; i < cars; ++i)
        f.frame.slots[i] = '.';
    f.frame.slots[cars] = 's';
    f.frame.slots[cars + 1] = 0;
    f.frame.player = 11;
    return f;
}

static Keys fake_keys(FakeTower &f)
{
    Keys k;
    k.game_manager = uintptr_t(&f.manager);
    k.results = uintptr_t(key_results);
    k.timing = uintptr_t(key_timing);
    k.pit = uintptr_t(key_pit);
    k.safety_car = uintptr_t(key_sc);
    k.penalty_log = uintptr_t(key_log);
    k.session_component = uintptr_t(key_s1);
    k.tyres = uintptr_t(key_tyres);
    k.marshal_zones = uintptr_t(key_zones);
    k.red_flag = uintptr_t(key_red);
    k.sector_table = uintptr_t(f.sectors);
    k.game_mode_context = uintptr_t(key_mode);
    k.team_tables = uintptr_t(key_teams);
    return k;
}

static FakeLaps make_laps(FakeTower &f, int cars)
{
    FakeLaps L;
    L.LT = alloc(0x200);
    L.vec = alloc(32 * 8);
    for (int v = 0; v < cars; ++v) {
        L.rec[v] = alloc(0x40 + 200 * 0xc8);
        put<uintptr_t>(L.vec, size_t(v) * 8, uintptr_t(L.rec[v]));
    }
    put<uintptr_t>(L.LT, 0x58, uintptr_t(L.vec));
    put<uintptr_t>(L.LT, 0x60, uintptr_t(L.vec) + size_t(cars > 24 ? cars : 24) * 8);
    put<uint8_t>(L.LT, 0xb8, 0xff);
    place(f, 299, uintptr_t(key_laps), L.LT);
    return L;
}
static Keys laps_keys(FakeTower &f)
{
    Keys k = fake_keys(f);
    k.lap_times = uintptr_t(key_laps);
    k.badge_names = uintptr_t(kSourceName);
    k.badge_none = uintptr_t(&g_badge_none);
    return k;
}

// Runs the reader for `seconds` at 120 fps from t, so every job has run (all rates).
static double run(Reader &r, FakeTower &f, double t, double seconds = 0.6)
{
    for (double end = t + seconds; t < end; t += 1 / 120.0)
        r.update(t, f.frame);
    return t;
}

// ---------------------------------------------------------------- reader

static void test_reader_basic()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    run(r, f, 0.0);
    const Snapshot &s = r.snapshot();
    CHECK(s.found_results && s.found_timing && s.found_pit && s.found_sc && s.found_log && s.found_s1 &&
          s.found_tyres && s.found_progress && s.found_zones && s.found_red);
    CHECK(s.cls.ok && s.cls.n == N && s.cls.dups == 0 && s.cls.holes == 0 && s.cls.entries == N);
    CHECK(s.cls.sorted == 1);
    CHECK(s.cls.order[0] == 0 && s.cls.order[21] == 21 && s.cls.pos[11] == 12);
    CHECK(s.cls.status[5] == 2 && s.cls.tpen_ok[5] && s.cls.tpen_s[5] == 0.f);
    CHECK(s.cls.status[22] == 0xff && s.cls.pos[22] == 0); // the safety car is not part of the order
    // timing entries are found by their vehicle id byte, whatever their order
    CHECK(s.timing.ok && s.timing.entries == N);
    CHECK(s.timing.car[0].have && !s.timing.car[0].leader_valid && s.timing.car[5].leader_ms == 5000 &&
          s.timing.car[5].leader_valid && s.timing.car[5].ahead_ms == 1000 && s.timing.car[5].ahead_valid);
    CHECK(s.pitlaps.pit_ok && s.pitlaps.pit_have[3] && s.pitlaps.pit[3] == 0);
    CHECK(s.pitlaps.laps_ok && s.pitlaps.lap_have[3] && s.pitlaps.lap[3] == 9);
    CHECK(s.sc.state == 0);
    CHECK(s.pen.log_ok && s.pen.records == 0 && s.pen.mc_ok && s.pen.dt[4] == 0 && s.pen.sg[4] == 0);
    CHECK(s.tyre[0].state == 1 && s.tyre[0].letter == 'S' && s.tyre[0].visual == 16 && s.tyre[0].compound == 3 &&
          s.tyre[0].actual == 103 && s.tyre[1].letter == 'M' && s.tyre[1].visual == 17);
    CHECK(checked_letter(s.tyre[0]) == 'S' && checked_letter(s.tyre[1]) == 'M');
    CHECK(s.tyre[22].state == 0); // never read: not a competitor
}

static void test_reader_rates()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    int runs[Reader::kJobs] = {}, max_per_frame = 0;
    for (int i = 0; i < 1200; ++i) { // 10 s at 120 fps
        r.update(i / 120.0, f.frame);
        int k = 0;
        for (int j = 0; j < Reader::kJobs; ++j)
            if (r.ran() & (1u << j)) {
                ++runs[j];
                ++k;
            }
        max_per_frame = std::max(max_per_frame, k);
    }
    CHECK(max_per_frame <= 2);
    CHECK(runs[Reader::kJobCls] >= 98 && runs[Reader::kJobCls] <= 101);       // 10 Hz
    CHECK(runs[Reader::kJobTiming] >= 98 && runs[Reader::kJobTiming] <= 101); // 10 Hz
    CHECK(runs[Reader::kJobPitLaps] >= 98 && runs[Reader::kJobPitLaps] <= 101);
    CHECK(runs[Reader::kJobPen] >= 39 && runs[Reader::kJobPen] <= 41);       // 4 Hz
    CHECK(runs[Reader::kJobTyreA] >= 19 && runs[Reader::kJobTyreA] <= 21);   // 2 Hz each half
    CHECK(runs[Reader::kJobTyreB] >= 19 && runs[Reader::kJobTyreB] <= 21);
    CHECK(runs[Reader::kJobFlags] >= 39 && runs[Reader::kJobFlags] <= 41);   // 4 Hz (field-traces.md §7.6)
    CHECK(runs[Reader::kJobMode] >= 39 && runs[Reader::kJobMode] <= 41);     // 4 Hz (the game mode, Time Trial)
    CHECK(runs[Reader::kJobLaps] >= 39 && runs[Reader::kJobLaps] <= 41);     // 4 Hz (lap times, races)
    // 30 fps: the same rates (50 jobs a second), still never more than two jobs in a frame
    Reader slow(mem(), fake_keys(f));
    int jobs = 0, slow_max = 0;
    for (int i = 0; i < 300; ++i) { // 10 s at 30 fps
        slow.update(i / 30.0, f.frame);
        int k = 0;
        for (int j = 0; j < Reader::kJobs; ++j)
            k += (slow.ran() >> j) & 1;
        jobs += k;
        slow_max = std::max(slow_max, k);
    }
    CHECK(slow_max <= 2);
    CHECK(jobs >= 490 && jobs <= 505);
    // 10 fps: 20 slots a second for 50 jobs; late jobs move on instead of bursting
    Reader crawl(mem(), fake_keys(f));
    int crawl_max = 0;
    for (int i = 0; i < 100; ++i) {
        crawl.update(i / 10.0, f.frame);
        int k = 0;
        for (int j = 0; j < Reader::kJobs; ++j)
            k += (crawl.ran() >> j) & 1;
        crawl_max = std::max(crawl_max, k);
    }
    CHECK(crawl_max <= 2 && crawl.snapshot().cls.ok && crawl.snapshot().tyre[0].state == 1 &&
          crawl.snapshot().mode.ok);
}

// The game mode (Time Trial): [[GMC+0x88]+0x278] -> the label; every failed step leaves it unread with its number;
// kept over a reset and read again in the reset's frame.
static void test_reader_mode()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    double t = run(r, f, 0.0);
    const ModeRead &m = r.snapshot().mode;
    CHECK(m.ok && !m.time_trial && std::strcmp(m.label, "grand_prix_23") == 0 && m.step == 0 && m.seq >= 2);
    set_label(f, "time_trial");
    t = run(r, f, t, 0.3);
    CHECK(m.ok && m.time_trial && std::strcmp(m.label, "time_trial") == 0);
    set_label(f, "none");                                     // the menus
    t = run(r, f, t, 0.3);
    CHECK(m.ok && !m.time_trial && std::strcmp(m.label, "none") == 0);
    set_label(f, "time_trial_x");                             // only the exact label is Time Trial
    t = run(r, f, t, 0.3);
    CHECK(m.ok && !m.time_trial);
    set_label(f, "TIME_TRIAL");
    t = run(r, f, t, 0.3);
    CHECK(m.ok && !m.time_trial);
    // kept over a new car set, and read again in the reset's frame (before the classification)
    set_label(f, "time_trial");
    t = run(r, f, t, 0.3);
    const uint32_t seq = m.seq;
    f.frame.generation = 2;
    r.update(t, f.frame);
    CHECK(m.ok && m.time_trial && m.seq == seq + 1 && (r.ran() & (1u << Reader::kJobMode)) &&
          (r.ran() & (1u << Reader::kJobCls)));
    t = run(r, f, t + 0.01, 0.3);
    // not a label: a space, a control character, empty, 31 characters (fits), 32 (does not)
    set_label(f, "time trial");
    t = run(r, f, t, 0.3);
    CHECK(!m.ok && !m.time_trial && m.step == 4 && m.label[0] == 0);
    set_label(f, "time_trial\x01");
    t = run(r, f, t, 0.3);
    CHECK(!m.ok && m.step == 4);
    set_label(f, "");
    t = run(r, f, t, 0.3);
    CHECK(!m.ok && m.step == 4);
    set_label(f, "abcdefghijklmnopqrstuvwxyz_1234");
    t = run(r, f, t, 0.3);
    CHECK(m.ok && std::strlen(m.label) == 31);
    set_label(f, "abcdefghijklmnopqrstuvwxyz_12345");
    t = run(r, f, t, 0.3);
    CHECK(!m.ok && m.step == 4);
    // a label that ends a readable page: read; one that runs into an unreadable page: not read
    DWORD old = 0;
    CHECK(VirtualProtect(f.label + 0x1000, 0x1000, PAGE_NOACCESS, &old));
    set_label(f, "time_trial", 0x1000 - 11);
    t = run(r, f, t, 0.3);
    CHECK(m.ok && m.time_trial);
    set_label(f, "time_trial", 0x1000 - 10);                 // no NUL before the page end
    t = run(r, f, t, 0.3);
    CHECK(!m.ok && m.step == 4);
    CHECK(VirtualProtect(f.label + 0x1000, 0x1000, PAGE_READWRITE, &old));
    // the label pointer null (3), the mode object null (2), no game mode context in the registry (1)
    set_label(f, nullptr);
    t = run(r, f, t, 0.3);
    CHECK(!m.ok && m.step == 3);
    set_label(f, "time_trial");
    put<uintptr_t>(f.GMC, 0x88, 0);
    t = run(r, f, t, 0.3);
    CHECK(!m.ok && m.step == 2);
    put<uintptr_t>(f.GMC, 0x88, uintptr_t(f.MODE));
    place(f, 34, uintptr_t(key_mode), nullptr);
    t = run(r, f, t, 1.5);
    CHECK(!m.ok && m.step == 1);
    place(f, 34, uintptr_t(key_mode), f.GMC);
    t = run(r, f, t, 1.5);
    CHECK(m.ok && m.time_trial);
}

static void test_reader_classification()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    // a shuffled order: vehicle ids by position
    int order[N];
    for (int i = 0; i < N; ++i)
        order[i] = (i * 7 + 3) % N;
    classify(f, order, N);
    double t = run(r, f, 0.0);
    const Snapshot &s = r.snapshot();
    CHECK(s.cls.ok && s.cls.n == N && s.cls.sorted == 1);
    bool same = true;
    for (int i = 0; i < N; ++i)
        same = same && s.cls.order[i] == order[i] && s.cls.pos[order[i]] == i + 1;
    CHECK(same);
    // the game's sorted list disagrees: logged, the positions still rule
    std::swap(order[3], order[4]);
    sort_results(f, order, N);
    std::swap(order[3], order[4]);
    t = run(r, f, t, 0.2);
    CHECK(s.cls.ok && s.cls.sorted == 0);
    sort_results(f, order, N);
    // two cars on one position (a torn re-sort): not ok, nothing reported
    const uint32_t seq = s.cls.seq;
    set_pos(f, order[5], 5);
    t = run(r, f, t, 0.2);
    CHECK(!s.cls.ok && s.cls.dups == 1 && s.cls.n == 0 && s.cls.pos[order[4]] == 0 && s.cls.seq == seq);
    set_pos(f, order[5], 6);
    t = run(r, f, t, 0.2);
    CHECK(s.cls.ok && s.cls.seq > seq);
    // a car the table no longer holds: a hole, the others keep their game positions
    f.frame.slots[order[2]] = 'n';
    t = run(r, f, t, 0.2);
    CHECK(s.cls.ok && s.cls.n == N - 1 && s.cls.holes == 1 && s.cls.pos[order[3]] == 4 && s.cls.order[2] == order[3]);
    f.frame.slots[order[2]] = '.';
    // an entry that does not read back its vehicle id is ignored
    put<uint8_t>(f.entry[order[0]], 0, 9);
    t = run(r, f, t, 0.2);
    CHECK(s.cls.ok && s.cls.pos[order[0]] == 0 && s.cls.holes == 1 && s.cls.order[0] == order[1]);
    put<uint8_t>(f.entry[order[0]], 0, uint8_t(order[0]));
    // statuses and time-penalty totals
    set_status(f, 4, 7);
    set_tpen(f, 6, 5.0);
    set_tpen(f, 7, -3.0);  // not a valid total
    set_status(f, 8, 0x42); // not a status
    t = run(r, f, t, 0.2);
    CHECK(s.cls.status[4] == 7 && s.cls.tpen_ok[6] && s.cls.tpen_s[6] == 5.f && !s.cls.tpen_ok[7] && s.cls.status[8] == 0xff);
    // the results system leaves the registry: searched again at most once a second
    place(f, 17, 0, nullptr);
    t = run(r, f, t, 0.2);
    CHECK(!s.cls.ok && !s.found_results);
    place(f, 60, uintptr_t(key_results), f.R);
    t = run(r, f, t, 0.3);
    const bool early = s.cls.ok;
    t = run(r, f, t, 1.2);
    CHECK(s.cls.ok && s.found_results);
    (void)early;
    // garbage vector bounds: refused without a fault
    put<uintptr_t>(f.R, 0x150, uintptr_t(f.rvec) + 3);
    t = run(r, f, t, 0.2);
    CHECK(!s.cls.ok);
    put<uintptr_t>(f.R, 0x150, uintptr_t(f.rvec) + size_t(N) * 8);
    // a freed entry: unreadable, no fault
    uint8_t *gone = f.entry[order[N - 1]];
    release(gone);
    t = run(r, f, t, 0.2);
    CHECK(s.cls.ok && s.cls.pos[order[N - 1]] == 0 && s.cls.n == N - 1);
}

// F2: no car has ERS, so the halo's scan marks every car 's' like the safety car (2026-11-10 00:07 log: 22 cars and
// the safety car all 's', 22 results entries). The results' entry count keeps the safety car (vehicle id N) out.
static void test_reader_no_ers()
{
    FakeTower f = make_tower();
    for (int i = 0; i < N; ++i)
        f.frame.slots[i] = 's';
    Reader r(mem(), fake_keys(f));
    run(r, f, 0.0);
    const Snapshot &s = r.snapshot();
    CHECK(s.cls.ok && s.cls.n == N && s.cls.entries == N && s.cls.holes == 0 && s.cls.dups == 0);
    CHECK(s.cls.order[0] == 0 && s.cls.order[21] == 21 && s.cls.pos[11] == 12);
    CHECK(s.cls.status[22] == 0xff && s.cls.pos[22] == 0); // the safety car is not part of the order
    CHECK(s.pitlaps.pit_have[3] && s.pitlaps.lap_have[3] && s.pitlaps.lap[3] == 9);
    CHECK(s.tyre[0].state == 1 && s.tyre[0].letter == 'S' && s.tyre[22].state == 0);
    CHECK(s.badges.car[0].state != kBadgeUnread && s.badges.car[22].state == kBadgeUnread);
    // before the session's first results read, only cars with ERS count
    FakeTower g = make_tower();
    for (int i = 0; i < N; ++i)
        g.frame.slots[i] = 's';
    place(g, 17, 0, nullptr); // no results system yet
    Reader q(mem(), fake_keys(g));
    run(q, g, 0.0);
    const Snapshot &u = q.snapshot();
    CHECK(!u.cls.ok && !u.found_results && u.tyre[0].state == 0 && !u.pitlaps.pit_have[3]);
    // the F1 case is unchanged: cars with ERS count from the first frame, the safety car never
    FakeTower h = make_tower();
    place(h, 17, 0, nullptr);
    Reader w(mem(), fake_keys(h));
    run(w, h, 0.0);
    CHECK(w.snapshot().tyre[0].state == 1 && w.snapshot().tyre[22].state == 0 && w.snapshot().pitlaps.pit_have[3]);
}

static void test_reader_timing_pit_sc()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    set_gap(f, 0, 21, 61234, true, 789, false);   // entry 0 holds vid 21
    set_gap(f, 5, 21, 1, true, 1, true);          // a second entry for vid 21: the game reads the first
    put<uint8_t>(f.tent, 0x98 * 3 + 0x88, 1);     // vid 18 gained a place (the game's byte)
    set_pit(f, 3, 7);
    set_pit(f, 4, 16); // not a pit state
    put<uintptr_t>(f.S, 0x68 + 5 * 0x10, 0);     // no record for vid 5
    set_sc(f, 2, 1);
    double t = run(r, f, 0.0);
    const Snapshot &s = r.snapshot();
    CHECK(s.timing.car[21].leader_ms == 61234 && s.timing.car[21].leader_valid && s.timing.car[21].ahead_ms == 789 &&
          !s.timing.car[21].ahead_valid);
    CHECK(s.timing.car[18].gained == 1 && s.timing.car[18].lost == 0);
    CHECK(s.pitlaps.pit_have[3] && s.pitlaps.pit[3] == 7 && !s.pitlaps.pit_have[4] && !s.pitlaps.pit_have[5]);
    CHECK(s.sc.state == 2 && s.sc.extra == 1);
    set_sc(f, 1);
    t = run(r, f, t, 0.2);
    CHECK(s.sc.state == 1);
    set_sc(f, 4); // outside the game's values
    t = run(r, f, t, 0.2);
    CHECK(s.sc.state == -1);
    set_sc(f, 0);
    // no timing entries at all: a valid empty vector
    put<uintptr_t>(f.T, 0x38, uintptr_t(f.tent));
    t = run(r, f, t, 0.2);
    CHECK(s.timing.ok && s.timing.entries == 0 && !s.timing.car[3].have);
    // the timing system is missing: not ok
    place(f, 42, 0, nullptr);
    t = run(r, f, t, 0.2);
    CHECK(!s.timing.ok && !s.found_timing);
    // lap counters outside the game's range are refused
    set_lap(f, 2, 4000);
    t = run(r, f, t, 0.2);
    CHECK(!s.pitlaps.lap_have[2] && s.pitlaps.lap_have[3]);
}

static void test_reader_penalties()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    add_penalty(f, 3, 5, 7);   // warning, corner cutting (track limits)
    add_penalty(f, 3, 5, 25);  // warning, track limits (25..29)
    add_penalty(f, 3, 5, 12);  // warning, another reason
    add_penalty(f, 3, 4, 7, 5);  // time penalty
    add_penalty(f, 9, 5, 29);
    add_penalty(f, 9, 5, 30);  // reason 30: not track limits (mask edge)
    set_dt(f, 3, 1);
    set_sg(f, 9, 2);
    double t = run(r, f, 0.0);
    const Snapshot &s = r.snapshot();
    CHECK(s.pen.log_ok && s.pen.records == 6 && s.pen.rec[3].penalty == 4 && s.pen.rec[3].time_s == 5);
    CHECK(s.pen.warn[3].total == 3 && s.pen.warn[3].track_limits == 2);
    CHECK(s.pen.warn[9].total == 2 && s.pen.warn[9].track_limits == 1);
    CHECK(s.pen.mc_ok && s.pen.dt[3] == 1 && s.pen.sg[9] == 2 && s.pen.dt[9] == 0);
    const uint32_t seq = s.pen.log_seq;
    t = run(r, f, t, 0.5);
    CHECK(s.pen.log_seq == seq); // unchanged log: same sequence
    // more than one chunk of records (32 per copy): counts over all of them
    for (int i = 0; i < 70; ++i)
        add_penalty(f, 5, 5, 8);
    t = run(r, f, t, 0.5);
    CHECK(s.pen.records == 76 && s.pen.warn[5].total == 70 && s.pen.warn[5].track_limits == 70 && s.pen.log_seq > seq);
    // a served drive-through: the slot empties
    set_dt(f, 3, 0);
    t = run(r, f, t, 0.5);
    CHECK(s.pen.dt[3] == 0);
    // a car past the end of the vectors has 0 (the game's rule)
    put<uintptr_t>(f.DT, 0x70, uintptr_t(f.dtrec) + 2 * 0x28);
    set_dt(f, 1, 2);
    t = run(r, f, t, 0.5);
    CHECK(s.pen.mc_ok && s.pen.dt[1] == 2 && s.pen.dt[5] == 0);
    // a broken log: not a whole number of records
    put<uintptr_t>(f.Z, 0x50, uintptr_t(f.zrec) + 0x31);
    t = run(r, f, t, 0.5);
    CHECK(!s.pen.log_ok && s.pen.warn[3].total == 0);
}

static void test_reader_tyres()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    set_tyre(f, 2, 7);           // intermediate
    set_tyre(f, 3, 8);           // wet
    set_tyre(f, 4, 5);           // hard
    set_tyre(f, 5, 3, true);     // stale cache
    set_tyre(f, 6, 4, false, 2); // set id 2 matches no descriptor; fallback id 1 neither -> unavailable
    set_tyre(f, 7, 0);           // hypersoft: no letter
    double t = run(r, f, 0.0);
    const Snapshot &s = r.snapshot();
    CHECK(s.tyre[2].letter == 'I' && checked_letter(s.tyre[2]) == 'I');
    CHECK(s.tyre[3].letter == 'W' && checked_letter(s.tyre[3]) == 'W');
    CHECK(s.tyre[4].letter == 'H' && checked_letter(s.tyre[4]) == 'H');
    CHECK(s.tyre[5].state == 2 && checked_letter(s.tyre[5]) == 0);
    CHECK(s.tyre[6].state == 3);
    CHECK(s.tyre[7].state == 1 && s.tyre[7].letter == 0 && checked_letter(s.tyre[7]) == 0);
    // the fallback descriptor (id >= 3 -> 4) when the current id has none
    set_tyre(f, 8, 4, false, 77);
    put<uint32_t>(f.V[8], 0x9bd0 + 0x18, 4);
    // a visual byte that contradicts the compound: not shown
    set_tyre(f, 9, 3);
    put<uint8_t>(f.vis[3], 0, 17);
    t = run(r, f, t, 1.0);
    CHECK(s.tyre[8].state == 1 && s.tyre[8].letter == 'M');
    CHECK(s.tyre[9].state == 1 && s.tyre[9].letter == 'S' && checked_letter(s.tyre[9]) == 0);
    CHECK(s.tyre[9].held == 'M'); // an unchecked letter is never held: still the medium from the first read
    put<uint8_t>(f.vis[3], 0, 16);
    // a stale cache keeps the last good letter (held, for the model's 1 s rule)
    t = run(r, f, t, 1.0);
    CHECK(s.tyre[9].held == 'S');
    const double held_t = s.tyre[9].held_t;
    set_tyre(f, 9, 3, true);
    t = run(r, f, t, 1.0);
    CHECK(s.tyre[9].state == 2 && s.tyre[9].held == 'S' && s.tyre[9].held_t == held_t);
    // more than 5 descriptors is not this layout
    put<uint64_t>(f.V[2], 0x9c48, 6);
    t = run(r, f, t, 1.0);
    CHECK(s.tyre[2].state == 3);
}

static void test_reader_reset()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    double t = run(r, f, 0.0);
    CHECK(r.snapshot().cls.ok && r.snapshot().tyre[0].held == 'S');
    // a new car set (generation): the snapshot starts empty, nothing carries over
    f.frame.generation = 2;
    r.update(t, f.frame);
    CHECK(r.snapshot().tyre[0].held == 0);
    t = run(r, f, t + 0.01);
    CHECK(r.snapshot().cls.ok);
    // the registry unreadable: everything unavailable, no fault
    put<uintptr_t>(f.mgr, 0x30, 0x10);
    t = run(r, f, t, 1.5);
    CHECK(!r.snapshot().cls.ok && !r.snapshot().timing.ok && r.snapshot().sc.state == -1 && !r.snapshot().pen.log_ok);
    // no keys at all (another build): nothing is read, everything unavailable
    Reader none;
    run(none, f, 0.0);
    const Snapshot &n = none.snapshot();
    CHECK(!n.cls.ok && !n.timing.ok && !n.pitlaps.pit_ok && !n.pitlaps.laps_ok && !n.pen.log_ok && !n.pen.mc_ok &&
          n.sc.state == -1 && n.tyre[0].state == 3 && !n.found_results && !n.found_progress);
    CHECK(none.copies() == 0);
}

// Flags (field-traces.md §7): yellow per marshal zone with the game's sector rule, the red flag byte, the sector
// table once per session.
static void test_reader_flags()
{
    FakeTower f = make_tower();
    f.frame.player_lap_m = 2000.f; // sector 2
    Reader r(mem(), fake_keys(f));
    double t = run(r, f, 0.0);
    const FlagRead &fl = r.snapshot().flags;
    CHECK(fl.seq > 0 && fl.zones_ok && fl.zones == kZones && fl.yellow == 0 && fl.ysec == 0 && !fl.unmapped);
    CHECK(fl.red == 0 && fl.sectors_ok && fl.sectors.count == 3 && fl.sectors.track_length == 6000.f &&
          fl.sectors.end_m[1] == 3200.f && fl.player_sector == 2);
    // yellow in zones 6 (1800 m: sector 2) and 12 (3600 m: sector 3); zone 5 starts at 1500 m, the end of sector 1
    // (the game's rule: the first sector whose end is >= the distance)
    set_zone(f, 6, 3);
    set_zone(f, 12, 3);
    set_zone(f, 3, 1); // green after a hazard
    set_zone(f, 9, 4); // a zone at 4: logged, never the red flag
    t = run(r, f, t, 0.3);
    CHECK(fl.zones_ok && fl.yellow == 2 && fl.ysec == 0b110 && !fl.unmapped && fl.flag[6] == 3 && fl.sector[6] == 2 &&
          fl.sector[12] == 3 && fl.flag[3] == 1 && fl.flag[9] == 4 && fl.sector[9] == 0 && fl.red == 0);
    set_zone(f, 6, 0);
    set_zone(f, 12, 0);
    set_zone(f, 5, 3);
    t = run(r, f, t, 0.3);
    CHECK(fl.yellow == 1 && fl.ysec == 0b001 && fl.sector[5] == 1);
    // a start outside 0..1, not a number, or an unreadable definition: yellow without a sector, never a guess
    put<float>(f.zdef[5], 0x10, 1.5f);
    t = run(r, f, t, 0.3);
    CHECK(fl.yellow == 1 && fl.ysec == 0 && fl.unmapped && fl.sector[5] == 0);
    put<float>(f.zdef[5], 0x10, -0.05f);
    t = run(r, f, t, 0.3);
    CHECK(fl.yellow == 1 && fl.ysec == 0 && fl.unmapped);
    put<float>(f.zdef[5], 0x10, std::nanf(""));
    t = run(r, f, t, 0.3);
    CHECK(fl.yellow == 1 && fl.unmapped);
    put<uintptr_t>(f.zone[5], 0, 0);
    t = run(r, f, t, 0.3);
    CHECK(fl.yellow == 1 && fl.unmapped && fl.zones_ok);
    put<uintptr_t>(f.zone[5], 0, uintptr_t(f.zdef[5]));
    put<float>(f.zdef[5], 0x10, 0.25f);
    // a start past the last sector end maps to no sector (the game's loop marks nothing); read in the next session
    const float short_ends[3] = {1500.f, 3200.f, 5000.f};
    set_sectors(f, 3, short_ends, 6000.f);
    set_zone(f, 5, 0);
    set_zone(f, 18, 3); // 5400 m
    t = run(r, f, t, 0.3);
    CHECK(fl.sectors.end_m[2] == 6000.f && fl.ysec == 0b100 && !fl.unmapped); // the table is read once per session
    f.frame.generation = 2;
    t = run(r, f, t, 0.6);
    CHECK(fl.sectors_ok && fl.sectors.end_m[2] == 5000.f && fl.yellow == 1 && fl.ysec == 0 && fl.unmapped &&
          fl.sector[18] == 0);
    set_zone(f, 18, 0);
    // the red flag byte: 1 deployed, 2 suspended, anything else unavailable
    set_red(f, 1);
    t = run(r, f, t, 0.3);
    CHECK(fl.red == 1 && fl.yellow == 0);
    set_red(f, 2);
    t = run(r, f, t, 0.3);
    CHECK(fl.red == 2);
    set_red(f, 7);
    t = run(r, f, t, 0.3);
    CHECK(fl.red == -1 && r.snapshot().found_red);
    set_red(f, 0);
    // a flag outside 0..4 or a null zone: the whole list is unavailable (no flag from a partial list)
    set_zone(f, 6, 3);
    set_zone(f, 7, 9);
    t = run(r, f, t, 0.3);
    CHECK(!fl.zones_ok && fl.yellow == 0 && fl.ysec == 0 && fl.flag[6] == 0 && fl.red == 0);
    set_zone(f, 7, 0);
    put<uintptr_t>(f.zvec, 8 * kZoneStride + 8, 0);
    t = run(r, f, t, 0.3);
    CHECK(!fl.zones_ok && fl.yellow == 0);
    put<uintptr_t>(f.zvec, 8 * kZoneStride + 8, uintptr_t(f.zone[8]));
    t = run(r, f, t, 0.3);
    CHECK(fl.zones_ok && fl.yellow == 1);
    // a broken vector (end before begin), then an empty list (valid: no flags)
    put<uintptr_t>(f.MZ, 0x90, uintptr_t(f.zvec) - 0x10);
    t = run(r, f, t, 0.3);
    CHECK(!fl.zones_ok && fl.yellow == 0);
    set_zone_count(f, 0);
    t = run(r, f, t, 0.3);
    CHECK(fl.zones_ok && fl.zones == 0 && fl.yellow == 0);
    set_zone_count(f, kZones);
    // both systems missing from the registry: nothing raised
    place(f, 120, 0, nullptr);
    place(f, 280, 0, nullptr);
    t = run(r, f, t, 1.5);
    CHECK(!r.snapshot().found_zones && !r.snapshot().found_red && !fl.zones_ok && fl.red == -1 && fl.yellow == 0);
    place(f, 120, uintptr_t(key_zones), f.MZ);
    place(f, 280, uintptr_t(key_red), f.RF);
    t = run(r, f, t, 1.5);
    CHECK(fl.zones_ok && fl.red == 0 && fl.yellow == 1);
    // no sector table: yellow without a sector; tried again at most once a second, kept once read
    Reader q(mem(), fake_keys(f));
    set_sectors(f, 0, short_ends, 6000.f);
    double u = run(q, f, 0.0, 0.3); // one attempt at 0.175 s
    CHECK(!q.snapshot().flags.sectors_ok && q.snapshot().flags.yellow == 1 && q.snapshot().flags.unmapped &&
          q.snapshot().flags.player_sector == 0);
    const float ends[3] = {1500.f, 3200.f, 6000.f};
    set_sectors(f, 3, ends, 6000.f);
    u = run(q, f, u, 0.7); // to 1.0 s: no second attempt yet
    CHECK(!q.snapshot().flags.sectors_ok);
    u = run(q, f, u, 0.5);
    CHECK(q.snapshot().flags.sectors_ok && q.snapshot().flags.ysec == 0b010 && !q.snapshot().flags.unmapped);
    // a decreasing or absurd table is rejected
    const float bad[3] = {1500.f, 1400.f, 6000.f};
    SectorTable st;
    uint8_t blk[kSectorBlock] = {};
    std::memcpy(blk, bad, sizeof bad);
    put<float>(blk, 0x58, 6000.f);
    put<uint32_t>(blk, 0x5c, 3);
    CHECK(!sector_table_from(blk, st));
    std::memcpy(blk, ends, sizeof ends);
    put<float>(blk, 0x58, 1e9f);
    CHECK(!sector_table_from(blk, st));
    put<float>(blk, 0x58, 6000.f);
    CHECK(sector_table_from(blk, st) && st.count == 3 && sector_of(st, 0.f) == 1 && sector_of(st, 1500.f) == 1 &&
          sector_of(st, 1500.5f) == 2 && sector_of(st, 6000.f) == 3 && sector_of(st, 6000.5f) == 0 &&
          sector_of(st, std::nanf("")) == 0);
    // cost: a flags read alone (20 zones, one yellow) stays a few dozen small copies
    Reader c(mem(), fake_keys(f));
    double w = 0;
    int flag_copies = 0;
    for (int i = 0; i < 240; ++i, w += 1 / 120.0) {
        c.update(w, f.frame);
        if (c.ran() == (1u << Reader::kJobFlags))
            flag_copies = std::max(flag_copies, c.copies());
    }
    CHECK(flag_copies > 0 && flag_copies <= 40);
}

// ---------------------------------------------------------------- model

// Team badges (field-traces.md §10): the game's chain per car, once per car set, a few cars a run; every failure
// unknown with its step, never a guess.
static void test_reader_badges()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    const Badges &b = r.snapshot().badges;
    // the first classification run reads kBadgeCarsPerRun cars; the others follow in the next runs
    r.update(0.0, f.frame);
    int read = 0;
    for (int vid = 0; vid < kCars; ++vid)
        read += b.car[vid].state != kBadgeUnread;
    CHECK((r.ran() & (1u << Reader::kJobCls)) && read == kBadgeCarsPerRun);
    double t = run(r, f, 1 / 120.0);
    bool all = true;
    for (int vid = 0; vid < N; ++vid)
        all = all && b.car[vid].state == kBadgeKey && b.car[vid].kind == 0 && b.car[vid].index == vid / 2 &&
              b.car[vid].key >= 0 && std::strcmp(b.key[b.car[vid].key], kTeamKey[vid / 2]) == 0;
    CHECK(all && b.keys == 11 && b.car[22].state == kBadgeUnread); // the safety car is not a competitor
    CHECK(b.car[0].key == b.car[1].key && b.car[0].key != b.car[2].key && b.car[21].key == 10);
    // once per car set: a changed record is not read again until the next generation
    set_key(f, 0, "mclaren_27");
    t = run(r, f, t, 1.5);
    CHECK(std::strcmp(b.key[b.car[0].key], "mclaren_26") == 0);
    f.frame.generation = 2;
    t = run(r, f, t, 0.6);
    CHECK(b.car[0].state == kBadgeKey && std::strcmp(b.key[b.car[0].key], "mclaren_27") == 0 && b.keys == 11);

    // the game's other paths and the broken chains, one car each (generation 3)
    set_team(f, 4, 1, 2);                     // kind 1: My Team, the game builds a render badge
    set_team(f, 5, 0, 12);                    // a record with the render flag
    put<uint8_t>(f.trec[12], 0x58d, 1);
    set_team(f, 6, 3, 0);                     // kind 3: the game writes nothing
    set_team(f, 7, 0, 200);                   // index past the table
    put<uint8_t>(entrant(f, 8), 0x82, 0x40);  // no entrant for car 8
    set_team(f, 9, 0, 13);
    set_key(f, 13, "bad\x01key");             // not printable
    set_team(f, 10, 0, 14);
    set_key(f, 14, "a_key_that_is_far_too_long_for_the_bound_x"); // 42 characters
    set_team(f, 11, 0, 15);
    set_key(f, 15, nullptr);                  // null key pointer
    set_team(f, 12, 0, 11);
    set_key(f, 11, "");                       // empty key
    put<uintptr_t>(f.tvec[2], 5 * 16 + 8, 0); // kind 2, element 5: no record
    set_team(f, 13, 2, 5);
    // haas (cars 14 and 15): the key ends on the last byte of a page whose next page is not readable
    auto *edge = static_cast<uint8_t *>(VirtualAlloc(nullptr, 0x2000, MEM_RESERVE, PAGE_NOACCESS));
    VirtualAlloc(edge, 0x1000, MEM_COMMIT, PAGE_READWRITE);
    std::memcpy(edge + 0x1000 - 8, "haas_26", 8);
    put<uintptr_t>(f.trec[7], 0x4d8, uintptr_t(edge + 0x1000 - 8));
    f.frame.generation = 3;
    t = run(r, f, t, 0.6);
    CHECK(b.car[4].state == kBadgeOther && b.car[4].kind == 1 && b.car[4].key == -1);
    CHECK(b.car[5].state == kBadgeOther && b.car[5].kind == 0 && b.car[5].index == 12);
    CHECK(b.car[6].state == kBadgeFailed && b.car[6].step == 5);
    CHECK(b.car[7].state == kBadgeFailed && b.car[7].step == 7);
    CHECK(b.car[8].state == kBadgeFailed && b.car[8].step == 4);
    CHECK(b.car[9].state == kBadgeFailed && b.car[9].step == 9);
    CHECK(b.car[10].state == kBadgeFailed && b.car[10].step == 9);
    CHECK(b.car[11].state == kBadgeFailed && b.car[11].step == 8);
    CHECK(b.car[12].state == kBadgeFailed && b.car[12].step == 9);
    CHECK(b.car[13].state == kBadgeFailed && b.car[13].step == 7);
    CHECK(b.car[14].state == kBadgeKey && std::strcmp(b.key[b.car[14].key], "haas_26") == 0 &&
          b.car[15].key == b.car[14].key);
    CHECK(b.car[3].state == kBadgeKey && std::strcmp(b.key[b.car[3].key], "mercedes_26") == 0);
    // a failed car is tried again at most once a second, and shows its key once the chain reads
    const double t_fail = b.car[11].t;
    for (; t < t_fail + 0.95; t += 1 / 120.0)
        r.update(t, f.frame);
    CHECK(b.car[11].t == t_fail && b.car[11].state == kBadgeFailed);
    set_key(f, 15, "f1_custom_team_26");
    t = run(r, f, t, 0.3);
    CHECK(b.car[11].state == kBadgeKey && std::strcmp(b.key[b.car[11].key], "f1_custom_team_26") == 0);
    CHECK(b.car[6].state == kBadgeFailed && b.car[6].step == 5 && b.car[6].t > t_fail);

    // the systems: no game mode context (step 1), [GMC+0x88] null (2), a broken entrant vector (3), no team tables (6)
    place(f, 34, 0, nullptr);
    f.frame.generation = 4;
    t = run(r, f, t, 0.6);
    bool step1 = true;
    for (int vid = 0; vid < N; ++vid)
        step1 = step1 && b.car[vid].state == kBadgeFailed && b.car[vid].step == 1;
    CHECK(step1 && b.keys == 0);
    place(f, 34, uintptr_t(key_mode), f.GMC);
    put<uintptr_t>(f.GMC, 0x88, 0);
    f.frame.generation = 5;
    t = run(r, f, t, 1.6); // the registry is searched again a second after the last search
    CHECK(b.car[0].state == kBadgeFailed && b.car[0].step == 2);
    put<uintptr_t>(f.GMC, 0x88, uintptr_t(f.MODE));
    put<uintptr_t>(f.G, 0x2e8, uintptr_t(f.ent) + 5);
    f.frame.generation = 6;
    t = run(r, f, t, 0.6);
    CHECK(b.car[0].state == kBadgeFailed && b.car[0].step == 3);
    put<uintptr_t>(f.G, 0x2e8, uintptr_t(f.ent) + size_t(N) * 0x88);
    place(f, 66, 0, nullptr);
    f.frame.generation = 7;
    t = run(r, f, t, 0.6);
    CHECK(b.car[0].state == kBadgeFailed && b.car[0].step == 6 && b.car[6].step == 5 && b.car[8].step == 4);
    VirtualFree(edge, 0, MEM_RELEASE);

    // cost: once every car is read, the badges add no copies (the same total as a reader without the badge keys)
    FakeTower g = make_tower();
    Keys nk = fake_keys(g);
    nk.game_mode_context = nk.team_tables = 0;
    Reader with(mem(), fake_keys(g)), without(mem(), nk);
    double u = run(with, g, 0.0, 1.0);
    run(without, g, 0.0, 1.0);
    int a = 0, c = 0;
    for (int i = 0; i < 240; ++i, u += 1 / 120.0) {
        with.update(u, g.frame);
        without.update(u, g.frame);
        if ((with.ran() | without.ran()) & (1u << Reader::kJobMode))
            continue; // the game mode read (Time Trial) has its own copies, with the key only: test_reader_mode
        a += with.copies();
        c += without.copies();
    }
    CHECK(a == c && a > 0 && with.snapshot().badges.keys == 11 && without.snapshot().badges.car[0].step == 1);
}

// The entrant vector as a career may hold it (2026-11-09 drive: every car failed at step 3 under the old 64-record
// cap): many records, most of them not in the session (+0x82 = 0xff), the session's cars far down the list and across
// chunk edges, and a later record with a car's id that must lose to the first. Also the vector states the log shows.
static void test_reader_badges_long()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    const Badges &b = r.snapshot().badges;
    CHECK(b.entrants == kEntrantsNotRead);
    // 180 records: 0..57 other entrants, 58..79 the session's cars (records 63/64 straddle a chunk edge), 80..179
    // other entrants, with a second record for car 0 (team 15) at 150
    constexpr int kLong = 180, kFirst = 58;
    uint8_t *lv = alloc(size_t(kLong) * 0x88);
    for (int i = 0; i < kLong; ++i) {
        put<uint8_t>(lv, size_t(i) * 0x88 + 0x82, 0xff);
        put<uint32_t>(lv, size_t(i) * 0x88 + 0x58, uint32_t(15) << 16);
    }
    for (int k = 0; k < N; ++k) // make_tower holds car 21 - k in record k
        std::memcpy(lv + size_t(kFirst + k) * 0x88, f.ent + size_t(k) * 0x88, 0x88);
    std::memcpy(lv + size_t(150) * 0x88, lv + size_t(kFirst + 21) * 0x88, 0x88);
    put<uint32_t>(lv, size_t(150) * 0x88 + 0x58, uint32_t(15) << 16);
    put<uintptr_t>(f.G, 0x2e0, uintptr_t(lv));
    put<uintptr_t>(f.G, 0x2e8, uintptr_t(lv) + size_t(kLong) * 0x88);
    double t = run(r, f, 0.0);
    bool all = true;
    for (int vid = 0; vid < N; ++vid)
        all = all && b.car[vid].state == kBadgeKey && b.car[vid].index == vid / 2 &&
              std::strcmp(b.key[b.car[vid].key], kTeamKey[vid / 2]) == 0;
    CHECK(all && b.keys == 11 && b.entrants == kLong);
    // empty: step 3, and the log says 0 records
    put<uintptr_t>(f.G, 0x2e8, uintptr_t(lv));
    f.frame.generation = 2;
    t = run(r, f, t);
    CHECK(b.car[0].state == kBadgeFailed && b.car[0].step == 3 && b.entrants == 0);
    // over the sanity bound (never copied): not sane
    put<uintptr_t>(f.G, 0x2e8, uintptr_t(lv) + (kMaxEntrants + 1) * 0x88);
    f.frame.generation = 3;
    t = run(r, f, t);
    CHECK(b.car[0].state == kBadgeFailed && b.car[0].step == 3 && b.entrants == kEntrantsNotSane);
    // exactly the bound, with only the first four pages readable (records 0..119): the walk stops once the run's cars
    // are found (record 79 at the latest, chunk 64..95), so it never reaches an unreadable record
    auto *big = static_cast<uint8_t *>(VirtualAlloc(nullptr, kMaxEntrants * 0x88, MEM_RESERVE, PAGE_NOACCESS));
    VirtualAlloc(big, 0x4000, MEM_COMMIT, PAGE_READWRITE);
    std::memcpy(big, lv, size_t(120) * 0x88);
    put<uintptr_t>(f.G, 0x2e0, uintptr_t(big));
    put<uintptr_t>(f.G, 0x2e8, uintptr_t(big) + kMaxEntrants * 0x88);
    f.frame.generation = 4;
    t = run(r, f, t);
    all = true;
    for (int vid = 0; vid < N; ++vid)
        all = all && b.car[vid].state == kBadgeKey && std::strcmp(b.key[b.car[vid].key], kTeamKey[vid / 2]) == 0;
    CHECK(all && b.entrants == int32_t(kMaxEntrants));
    // car 16 missing (record 63): its run (cars 12..17) walks into record 128's chunk, which cannot be read. Car 16 is
    // unknown (step 3, not "absent"); the cars of the run found before that keep their keys
    put<uint8_t>(big, size_t(kFirst + 5) * 0x88 + 0x82, 0xff);
    f.frame.generation = 5;
    t = run(r, f, t);
    CHECK(b.car[16].state == kBadgeFailed && b.car[16].step == 3 && b.car[12].state == kBadgeKey &&
          b.car[17].state == kBadgeKey && b.car[21].state == kBadgeKey);
    // the same car missing from a readable vector: absent (step 4)
    put<uint8_t>(lv, size_t(kFirst + 5) * 0x88 + 0x82, 0xff);
    put<uintptr_t>(f.G, 0x2e0, uintptr_t(lv));
    put<uintptr_t>(f.G, 0x2e8, uintptr_t(lv) + size_t(kLong) * 0x88);
    f.frame.generation = 6;
    t = run(r, f, t);
    CHECK(b.car[16].state == kBadgeFailed && b.car[16].step == 4 && b.car[12].state == kBadgeKey);
    // the first chunk unreadable: every car unknown, the log says 'c'
    auto *gone = static_cast<uint8_t *>(VirtualAlloc(nullptr, 0x1000, MEM_RESERVE, PAGE_NOACCESS));
    put<uintptr_t>(f.G, 0x2e0, uintptr_t(gone));
    put<uintptr_t>(f.G, 0x2e8, uintptr_t(gone) + size_t(N) * 0x88);
    f.frame.generation = 7;
    t = run(r, f, t);
    CHECK(b.car[0].state == kBadgeFailed && b.car[0].step == 3 && b.car[21].step == 3 &&
          b.entrants == kEntrantsCopyFailed);
    // misaligned: not sane
    put<uintptr_t>(f.G, 0x2e0, uintptr_t(lv));
    put<uintptr_t>(f.G, 0x2e8, uintptr_t(lv) + 0x88 * 3 + 8);
    f.frame.generation = 8;
    t = run(r, f, t);
    CHECK(b.car[0].state == kBadgeFailed && b.car[0].step == 3 && b.entrants == kEntrantsNotSane);
    // the bounds unreadable: G points into a page that cannot be read
    put<uintptr_t>(f.MODE, 0x260, uintptr_t(gone));
    f.frame.generation = 9;
    t = run(r, f, t);
    CHECK(b.car[0].state == kBadgeFailed && b.car[0].step == 3 && b.entrants == kEntrantsUnreadable);
    // a new car set clears the state until a run reaches the vector again
    put<uintptr_t>(f.GMC, 0x88, 0);
    f.frame.generation = 10;
    t = run(r, f, t);
    CHECK(b.car[0].state == kBadgeFailed && b.car[0].step == 2 && b.entrants == kEntrantsNotRead);
    VirtualFree(gone, 0, MEM_RELEASE);
    VirtualFree(big, 0, MEM_RELEASE);
    release(lv);
}

static void test_badge_text()
{
    char out[kBadgeTextMax];
    CHECK(badge_text("mclaren_26", out, sizeof out) &&
          std::strcmp(out, "#overrides.osd.timing_tower.team_badges_hud.mclaren_26") == 0);
    CHECK(kBadgePrefixLen == 44 && std::strcmp(kBadgePrefix, kHudBadge) == 0);
    const std::string k39(39, 'k'), k40(40, 'k'); // the bound: 39 characters (83 with the prefix)
    CHECK(badge_text(k39.c_str(), out, sizeof out) && std::strlen(out) == 83);
    CHECK(!badge_text(k40.c_str(), out, sizeof out) && out[0] == 0);
    CHECK(!badge_text("", out, sizeof out) && !badge_text(nullptr, out, sizeof out));
    CHECK(!badge_text("has space", out, sizeof out) && !badge_text("tab\tkey", out, sizeof out) &&
          !badge_text("caf\xe9", out, sizeof out) && !badge_text("del\x7f", out, sizeof out));
    CHECK(!badge_text("mclaren_26", out, kBadgeTextMax - 1) && out[0] == 0); // no room for the longest: refused
    CHECK(badge_key_ok("x", 2) && !badge_key_ok("xy", 2) && badge_key_ok("f1_tr_red", kBadgeKeyMax));
}

static void test_window()
{
    int s = 0, n = 0;
    window(22, 5, 11, Mode::compact, s, n); // P12 -> P10..P14
    CHECK(s == 9 && n == 5);
    window(22, 5, 0, Mode::compact, s, n); // P1 -> P1..P5
    CHECK(s == 0 && n == 5);
    window(22, 5, 21, Mode::compact, s, n); // last -> last five
    CHECK(s == 17 && n == 5);
    window(22, 5, 1, Mode::compact, s, n); // P2 -> P1..P5
    CHECK(s == 0 && n == 5);
    window(22, 5, 20, Mode::compact, s, n); // P21 -> P18..P22
    CHECK(s == 17 && n == 5);
    window(22, 4, 11, Mode::compact, s, n); // even N: two above, one below
    CHECK(s == 9 && n == 4);
    window(3, 5, 1, Mode::compact, s, n); // fewer cars than rows
    CHECK(s == 0 && n == 3);
    window(3, 5, 2, Mode::compact, s, n); // fewer cars than rows, the player last: never a negative start
    CHECK(s == 0 && n == 3);
    window(5, 5, 4, Mode::compact, s, n);
    CHECK(s == 0 && n == 5);
    window(22, 5, -1, Mode::compact, s, n); // no player: the top N
    CHECK(s == 0 && n == 5);
    window(22, 10, 15, Mode::top, s, n);
    CHECK(s == 0 && n == 10);
    window(20, 5, 15, Mode::full, s, n);
    CHECK(s == 0 && n == 20);
    window(24, 5, 15, Mode::full, s, n); // a 24-car field shows every car (kRows 30)
    CHECK(s == 0 && n == 24 && kRows == 30);
    window(34, 5, 15, Mode::full, s, n);
    CHECK(s == 0 && n == kRows);
    window(24, 5, 23, Mode::compact, s, n); // the player at P24 of 24
    CHECK(s == 19 && n == 5);
    window(30, 7, 29, Mode::compact, s, n);
    CHECK(s == 23 && n == 7);
    window(0, 5, -1, Mode::full, s, n);
    CHECK(s == 0 && n == 0);
    // the game's own 5-pill rule (data-and-ui.md 2.2) for every position of a 22-car field
    bool same = true;
    for (int pos = 0; pos < 22; ++pos) {
        const int game = pos < 2 ? 0 : (pos - 2 + 5 <= 22 ? pos - 2 : 22 - 5);
        window(22, 5, pos, Mode::compact, s, n);
        same = same && s == game && n == 5;
    }
    CHECK(same);
}

static void test_texts()
{
    char b[16];
    race_gap_text(5149, b, sizeof b);
    CHECK(std::strcmp(b, "+5.1") == 0);
    race_gap_text(5199, b, sizeof b); // cut, not rounded
    CHECK(std::strcmp(b, "+5.1") == 0);
    race_gap_text(0, b, sizeof b);
    CHECK(std::strcmp(b, "+0.0") == 0);
    race_gap_text(99, b, sizeof b);
    CHECK(std::strcmp(b, "+0.0") == 0);
    race_gap_text(59999, b, sizeof b);
    CHECK(std::strcmp(b, "+59.9") == 0);
    race_gap_text(65300, b, sizeof b);
    CHECK(std::strcmp(b, "+1:05.3") == 0);
    race_gap_text(600000, b, sizeof b);
    CHECK(std::strcmp(b, "+10:00.0") == 0);
    CHECK(std::strcmp(session_label(6), "Q2") == 0 && std::strcmp(session_label(15), "R") == 0 &&
          std::strcmp(session_label(11), "SQ2") == 0 && std::strcmp(session_label(3), "P3") == 0 &&
          std::strcmp(session_label(99), "") == 0);
}

// A snapshot built directly (no memory): N cars in vehicle-id order, all running, valid gaps, laps 9.
static Snapshot snap(int n = N)
{
    Snapshot s;
    s.cls.ok = true;
    s.cls.seq = 1;
    s.cls.t = 0;
    s.cls.n = n;
    for (int i = 0; i < kCars; ++i)
        s.cls.status[i] = 0xff;
    for (int i = 0; i < n; ++i) {
        s.cls.order[i] = uint8_t(i);
        s.cls.pos[i] = uint8_t(i + 1);
        s.cls.status[i] = 2;
        s.cls.tpen_ok[i] = true;
        GapRec &g = s.timing.car[i];
        g.have = true;
        g.leader_ms = 1000 * i;
        g.leader_valid = i > 0;
        g.ahead_ms = i ? 1000 : 0;
        g.ahead_valid = i > 0;
        s.pitlaps.pit_have[i] = true;
        s.pitlaps.lap_have[i] = true;
        s.pitlaps.lap[i] = 9;
        TyreRead &t = s.tyre[i];
        t.state = 1;
        t.compound = 3;
        t.visual = 16;
        t.letter = 'S';
    }
    s.timing.ok = true;
    s.timing.entries = n;
    s.pitlaps.pit_ok = s.pitlaps.laps_ok = true;
    s.pen.log_ok = s.pen.mc_ok = true;
    s.sc.state = 0;
    s.found_results = s.found_timing = s.found_pit = s.found_sc = s.found_log = s.found_s1 = s.found_tyres =
        s.found_progress = true;
    return s;
}

static Frame frame(int player = 11, uint32_t session = 15, uint32_t gen = 1)
{
    Frame f;
    f.session_ok = true;
    f.session = session;
    f.generation = gen;
    for (int i = 0; i < N; ++i)
        f.slots[i] = '.';
    f.slots[N] = 's';
    f.player = player;
    return f;
}

// these knockout fixtures stand in the vehicle ids' own order, where the zone needs a lap time
// (test_ko_game_order): every classified car gets one, in position order (80 s + 0.125 s per place)
static Snapshot timed(Snapshot s)
{
    for (int i = 0; i < s.cls.n; ++i) {
        const int vid = s.cls.order[i];
        s.cls.lap_ok[vid] = true;
        s.cls.lap_s[vid] = 80.0f + 0.125f * float(i);
    }
    return s;
}

// The spectator menu (docs/spectator-ui.md 10.4): while the tower follows the watched car the director's Gap (+0xe4)
// and Detail (+0xe8) replace the gap and tyre settings; any other value, or not spectating: the settings.
static void set_lap(FakeTower &f, int vid, float s, uint8_t none)
{
    uint32_t bits;
    std::memcpy(&bits, &s, 4);
    put<uint32_t>(f.entry[vid], 0xe8, bits ^ 0x3c3c5a5au);
    put<uint32_t>(f.entry[vid], 0xf0, 0x3c3c5a5au);
    put<uint8_t>(f.entry[vid], 0x108, uint8_t(none ^ 0x81));
    put<uint8_t>(f.entry[vid], 0x110, 0x81);
}

static void test_reader_spectator_laps()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    int order[N];
    for (int i = 0; i < N; ++i)
        order[i] = i;
    classify(f, order, N);
    set_lap(f, 0, 92.456f, 3);
    set_lap(f, 1, 0.f, 3);       // no lap time: the game's dash
    set_lap(f, 2, 93.1f, 0xff);  // the game's "none" flag: the game's dash
    set_lap(f, 3, -1.f, 3);      // not a lap time
    f.frame.session = 18;        // Time Trial: no lap times of its own (races read them)
    // not spectating, or another Gap: the short copy, no lap times
    double t = run(r, f, 0.0);
    const Snapshot &s = r.snapshot();
    CHECK(s.cls.ok && !s.cls.lap_ok[0]);
    f.frame.spect = true;
    f.frame.spect_gap = 1;
    t = run(r, f, t, 0.2);
    CHECK(s.cls.ok && !s.cls.lap_ok[0]);
    // Gap 3 while spectating: the lap times the game's board shows
    f.frame.spect_gap = 3;
    t = run(r, f, t, 0.2);
    CHECK(s.cls.ok && s.cls.n == N && s.cls.lap_ok[0] && std::fabs(s.cls.lap_s[0] - 92.456f) < 1e-3f);
    CHECK(!s.cls.lap_ok[1] && !s.cls.lap_ok[2] && !s.cls.lap_ok[3] && !s.cls.lap_ok[4]);
    CHECK(s.cls.pos[0] == 1 && s.cls.pos[N - 1] == N); // the positions as with the short copy
}

// the spectator's Detail cell: the reader decodes the grid slot and the best lap's number
// from the long results copy, the pit stop count from the pit entry (one copy with the state) and, only while the
// menu is on Best, the stints' end laps
static void set_grid(FakeTower &f, int vid, uint32_t grid)
{
    const uint32_t key = 0x13572468u ^ uint32_t(vid);
    put<uint32_t>(f.entry[vid], 0x90, (grid - 1) ^ key);
    put<uint32_t>(f.entry[vid], 0x98, key);
}
static void set_stints(FakeTower &f, int vid, uint8_t *sets, const uint16_t *ends, int n, uint32_t current_id)
{
    for (int i = 0; i < n; ++i)
        put<uint16_t>(sets, size_t(i) * 0x78 + 0x74, ends[i]);
    put<uint32_t>(sets, size_t(n - 1) * 0x78 + 0xc, current_id);
    put<uintptr_t>(f.V[vid], 0x9c90, uintptr_t(sets));
    put<uintptr_t>(f.V[vid], 0x9c98, uintptr_t(sets) + size_t(n) * 0x78);
}

static void test_reader_detail()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    int order[N];
    for (int i = 0; i < N; ++i)
        order[i] = i;
    classify(f, order, N);
    set_grid(f, 0, 3);
    set_grid(f, 1, 1);
    set_grid(f, 2, 99); // beyond the entries: not read
    set_lap(f, 0, 92.5f, 7);
    set_lap(f, 1, 93.0f, 0xff);
    put<uint32_t>(f.pit[0], 0x14, 2);
    put<uint32_t>(f.pit[1], 0x14, 0);
    put<uint32_t>(f.pit[3], 0x14, 1000); // not a count
    uint8_t *sets = alloc(0x78 * 3);
    const uint16_t ends[3] = {4, 0xffff, 0xffff};
    set_stints(f, 2, sets, ends, 3, 3 + 10); // car 2 runs softs (set id 13, set_tyre)
    f.frame.session = 15;
    double t = run(r, f, 0.0);
    const Snapshot &s = r.snapshot();
    CHECK(s.cls.ok && s.cls.grid[0] == 3 && s.cls.grid[1] == 1 && s.cls.grid[2] == 0);
    CHECK(s.cls.best_lap[0] == 7 && s.cls.best_lap[1] == 0xff);
    CHECK(s.pitlaps.stops_have[0] && s.pitlaps.stops[0] == 2 && s.pitlaps.stops_have[1] && s.pitlaps.stops[1] == 0);
    CHECK(!s.pitlaps.stops_have[3] && s.pitlaps.pit_have[3]); // the state is still read
    CHECK(!s.tyre[2].stint_ok && s.tyre[2].letter == 'S');     // stints only while the menu is on Best
    f.frame.spect = true;
    f.frame.spect_detail = 4;
    t = run(r, f, t, 1.2);
    CHECK(s.tyre[2].stint_ok && s.tyre[2].stints == 3 && s.tyre[2].prev_end == 4 && s.tyre[2].letter == 'S');
    CHECK(s.tyre[0].stint_ok && s.tyre[0].stints == 1 && s.tyre[0].prev_end == -1);
    // a stale descriptor cache keeps the stints (they are not the cache)
    set_tyre(f, 4, 3, true);
    t = run(r, f, t, 1.2);
    CHECK(s.tyre[4].state == 2 && s.tyre[4].stint_ok && s.tyre[4].stints == 1);
    // the short copy (an unknown session type, no Gap 3): neither the grid nor the best lap is read
    f.frame.session = 0;
    f.frame.session_ok = false;
    t = run(r, f, t, 0.3);
    CHECK(s.cls.ok && s.cls.grid[0] == 0 && s.cls.best_lap[0] == -1);
}

// best laps. In a timed session without the spectator menu the gap column shows P1's lap time (m:ss.fff) and
// the others' gap to it (+s.fff), in the game's own ms; the dim bar without a time, or for a time below one
// classified ahead of it. Spectator modes and races as before.
static void test_best_laps()
{
    char b[16];
    best_lap_text(87470, b, sizeof b);
    CHECK(std::strcmp(b, "1:27.470") == 0);
    best_lap_text(58123, b, sizeof b);
    CHECK(std::strcmp(b, "58.123") == 0);
    best_lap_text(60000, b, sizeof b);
    CHECK(std::strcmp(b, "1:00.000") == 0);
    best_lap_text(605009, b, sizeof b);
    CHECK(std::strcmp(b, "10:05.009") == 0);
    best_gap_text(293, b, sizeof b);
    CHECK(std::strcmp(b, "+0.293") == 0);
    best_gap_text(0, b, sizeof b);
    CHECK(std::strcmp(b, "+0.000") == 0);
    best_gap_text(12045, b, sizeof b);
    CHECK(std::strcmp(b, "+12.045") == 0);
    best_gap_text(62345, b, sizeof b);
    CHECK(std::strcmp(b, "+1:02.345") == 0);
    // the game's conversion (single precision product, cut)
    CHECK(game_lap_ms(87.47f) == 87470 && game_lap_ms(87.763f) == 87763 && game_lap_ms(149.815f) == 149815);
    {
        const float x = 92.456f;
        const float p = x * 1000.0f;
        CHECK(game_lap_ms(x) == int64_t(p));
    }

    Model m;
    Snapshot s = snap();
    Settings cfg;
    cfg.mode = Mode::full;
    Frame f = frame(11, 5); // Q1
    const View &v = m.view();
    // no time yet: every row dim, P1 too; P1's time at the number size (laps)
    m.update(s, f, cfg, 1.0);
    CHECK(v.on && v.timed && !v.race && v.best && v.laps && v.best_p1 == -1 && v.best_n == 0 && v.best_inv == 0);
    CHECK(v.row[0].gna && v.row[0].gap[0] == 0 && v.row[0].shown == kShownUnavailable && v.row[5].gna);
    const int p1 = s.cls.order[0], p2 = s.cls.order[1], p6 = s.cls.order[5], p7 = s.cls.order[6],
              p8 = s.cls.order[7];
    s.cls.lap_ok[p1] = true;
    s.cls.lap_s[p1] = 87.47f;
    s.cls.lap_ok[p2] = true;
    s.cls.lap_s[p2] = 87.763f;
    s.cls.lap_ok[p7] = true;
    s.cls.lap_s[p7] = 149.815f;
    s.cls.lap_ok[p8] = true;
    s.cls.lap_s[p8] = 88.0f; // below P7's: the order and the field disagree
    s.cls.seq = 2;
    m.update(s, f, cfg, 1.1);
    CHECK(v.best_p1 == 87470 && v.best_n == 4 && v.best_inv == 1);
    CHECK(std::strcmp(v.row[0].gap, "1:27.470") == 0 && v.row[0].shown == kShownTime && !v.row[0].gna);
    CHECK(std::strcmp(v.row[1].gap, "+0.293") == 0 && v.row[1].shown == kShownTime && !v.row[1].gna);
    CHECK(v.row[5].gap[0] == 0 && v.row[5].gna && v.row[5].shown == kShownUnavailable); // P6: no time
    CHECK(std::strcmp(v.row[6].gap, "+1:02.345") == 0 && !v.row[6].gna);
    CHECK(v.row[7].gap[0] == 0 && v.row[7].gna); // P8: below P7's time
    CHECK(v.car_row[p6] == 5 && v.car_row[p8] == 7);
    // the Intervals setting off: no column, as in a race
    cfg.gaps = false;
    m.update(s, f, cfg, 1.2);
    CHECK(v.row[0].gap[0] == 0 && !v.row[0].gna && v.row[0].shown == kShownOff);
    cfg.gaps = true;
    // status 7: a car with a best lap keeps its row and time (an in-game test's Q1 end); without one: Out
    s.cls.status[p2] = 7;
    s.cls.status[p6] = 7;
    s.cls.seq = 3;
    m.update(s, f, cfg, 1.3);
    CHECK(std::strcmp(v.row[1].gap, "+0.293") == 0 && !v.row[1].out && std::strcmp(v.row[0].gap, "1:27.470") == 0);
    CHECK(std::strcmp(v.row[5].gap, "Out") == 0 && v.row[5].out);
    s.cls.status[p2] = 2;
    s.cls.status[p6] = 2;
    // P1 without a time: no reference, every row dim
    s.cls.lap_ok[p1] = false;
    s.cls.seq = 4;
    m.update(s, f, cfg, 1.4);
    CHECK(v.best_p1 == -1 && v.row[0].gna && v.row[1].gna && v.row[1].gap[0] == 0);
    s.cls.lap_ok[p1] = true;
    // spectating: the director's Interval in a timed session shows the best-lap values (P1 its best lap, the
    // others the gap to the best lap of the car directly ahead); Gap 3: three decimals (one before)
    f.spect = true;
    f.spect_gap = 1;
    m.update(s, f, cfg, 1.5);
    CHECK(v.best && v.laps && std::strcmp(v.row[0].gap, "1:27.470") == 0 && std::strcmp(v.row[1].gap, "+0.293") == 0);
    f.spect_gap = 3;
    m.update(s, f, cfg, 1.6);
    CHECK(!v.best && v.laps && v.flap && std::strcmp(v.row[0].gap, "1:27.470") == 0 &&
          std::strcmp(v.row[1].gap, "1:27.763") == 0);
    // a race: as before (P1's word, the gaps), whatever the lap times
    f.spect = false;
    f.spect_gap = 0;
    Frame race = frame(11, 15);
    m.update(s, race, cfg, 1.7);
    CHECK(v.race && !v.best && !v.laps && std::strcmp(v.row[0].gap, "Interval") == 0 &&
          std::strcmp(v.row[5].gap, "+1.0") == 0);
    // practice (P2) and sprint shootout (SQ1): best laps too
    m.update(s, frame(11, 2), cfg, 1.8);
    CHECK(v.best && std::strcmp(v.row[0].gap, "1:27.470") == 0 && std::strcmp(v.sess, "P2") == 0);
    m.update(s, frame(11, 10), cfg, 1.9);
    CHECK(v.best && std::strcmp(v.row[1].gap, "+0.293") == 0 && std::strcmp(v.sess, "SQ1") == 0);
}

// the reader reads the lap time in timed sessions (the long copy), not in a race unless spectating on Gap 3
static void test_reader_best_laps()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    int order[N];
    for (int i = 0; i < N; ++i)
        order[i] = i;
    classify(f, order, N);
    set_lap(f, 0, 87.47f, 3);
    set_lap(f, 1, 0.f, 3);
    double t = run(r, f, 0.0); // the fake game's race: read too (the race's fastest lap)
    const Snapshot &s = r.snapshot();
    CHECK(s.cls.ok && s.cls.lap_ok[0] && std::fabs(s.cls.lap_s[0] - 87.47f) < 1e-4f && !s.cls.lap_ok[1]);
    f.frame.session = 6; // Q2
    t = run(r, f, t, 0.2);
    CHECK(s.cls.ok && s.cls.n == N && s.cls.lap_ok[0] && std::fabs(s.cls.lap_s[0] - 87.47f) < 1e-4f && !s.cls.lap_ok[1]);
    f.frame.session = 3; // P3
    t = run(r, f, t, 0.2);
    CHECK(s.cls.lap_ok[0] && s.cls.pos[0] == 1 && s.cls.pos[N - 1] == N);
    f.frame.session = 18; // Time Trial: no
    t = run(r, f, t, 0.2);
    CHECK(s.cls.ok && !s.cls.lap_ok[0]);
}

static void test_spectator_texts()
{
    char b[16];
    lap_time_text(92456, b, sizeof b);
    CHECK(std::strcmp(b, "1:32.4") == 0);
    lap_time_text(58799, b, sizeof b);
    CHECK(std::strcmp(b, "58.7") == 0);
    lap_time_text(60000, b, sizeof b);
    CHECK(std::strcmp(b, "1:00.0") == 0);
    penalty_text(0, 0, true, 5.f, b, sizeof b);
    CHECK(std::strcmp(b, "5s") == 0);
    penalty_text(0, 0, true, 10.f, b, sizeof b);
    CHECK(std::strcmp(b, "10s") == 0);
    penalty_text(1, 0, true, 5.f, b, sizeof b);
    CHECK(std::strcmp(b, "DT") == 0);
    penalty_text(0, 2, true, 0.f, b, sizeof b);
    CHECK(std::strcmp(b, "SG") == 0);
    penalty_text(0, 0, true, 0.f, b, sizeof b);
    CHECK(b[0] == 0);
    penalty_text(0, 0, false, 5.f, b, sizeof b);
    CHECK(b[0] == 0);
}

static void test_model_spectator()
{
    Model m;
    Snapshot s = snap();
    Settings cfg;
    cfg.mode = Mode::full;
    Frame f = frame();
    const View &v = m.view();
    // not spectating: the settings (interval, tyres), whatever the director holds
    f.spect_gap = 2;
    f.spect_detail = 0;
    m.update(s, f, cfg, 1.0);
    CHECK(v.sgap == -1 && v.sdet == -1 && !v.lead && v.set.gaps && v.set.tyres && v.row[0].tyre == 'S');
    CHECK(std::strcmp(v.row[0].gap, "Interval") == 0 && std::strcmp(v.row[5].gap, "+1.0") == 0);
    f.spect = true;
    // Gap 1 interval, Detail 3 tyre
    f.spect_gap = 1;
    f.spect_detail = 3;
    m.update(s, f, cfg, 1.1);
    CHECK(v.sgap == 1 && v.sdet == 3 && !v.lead && !v.laps && v.set.gaps && v.set.tyres);
    CHECK(std::strcmp(v.row[0].gap, "Interval") == 0 && std::strcmp(v.row[5].gap, "+1.0") == 0);
    CHECK(v.row[5].tyre == 'S' && !v.row[5].tna && v.row[5].det[0] == 0);
    // Gap 2 leader, even with the setting on interval; Detail 4: the tyre of the best lap's set, the dim bar
    // without a best lap or its stints
    f.spect_gap = 2;
    f.spect_detail = 4;
    m.update(s, f, cfg, 1.2);
    CHECK(v.lead && std::strcmp(v.row[0].gap, "Leader") == 0 && std::strcmp(v.row[5].gap, "+5.0") == 0);
    CHECK(v.row[5].tyre == 0 && v.row[5].tna && v.row[5].det[0] == 0);
    // best lap 7 on the current set (the earlier stint ended on lap 4): its letter. Best lap 3: an earlier set,
    // whose compound the DLL does not read: the dim bar. No best lap (0xff): the dim bar
    s.cls.lap_ok[5] = true;
    s.cls.lap_s[5] = 93.07f;
    s.cls.best_lap[5] = 7;
    s.tyre[5].stint_ok = true;
    s.tyre[5].stints = 2;
    s.tyre[5].prev_end = 4;
    s.cls.lap_ok[6] = true;
    s.cls.lap_s[6] = 91.0f;
    s.cls.best_lap[6] = 3;
    s.tyre[6].stint_ok = true;
    s.tyre[6].stints = 2;
    s.tyre[6].prev_end = 4;
    s.cls.best_lap[7] = 0xff;
    s.tyre[7].stint_ok = true;
    s.tyre[7].stints = 1;
    s.cls.best_lap[8] = 2;
    s.cls.lap_ok[8] = true;
    s.cls.lap_s[8] = 95.0f;
    s.tyre[8].stint_ok = true;
    s.tyre[8].stints = 1;
    m.update(s, f, cfg, 1.25);
    CHECK(v.row[5].tyre == 'S' && !v.row[5].tna);
    CHECK(v.row[6].tyre == 0 && v.row[6].tna);
    CHECK(v.row[7].tyre == 0 && v.row[7].tna);
    CHECK(v.row[8].tyre == 'S' && !v.row[8].tna); // one stint: the current set
    // a stale cache: the held letter for up to 1 s, as Detail 3
    s.tyre[8].state = 2;
    s.tyre[8].held = 'M';
    s.tyre[8].held_t = 1.0;
    m.update(s, f, cfg, 1.26);
    CHECK(v.row[8].tyre == 'M' && !v.row[8].tna);
    m.update(s, f, cfg, 2.2);
    CHECK(v.row[8].tyre == 0 && v.row[8].tna);
    s.tyre[8].state = 1;
    // Gap 0: no gap column, as Intervals off (nothing, no dim bar); Detail 0: no detail cell
    f.spect_gap = 0;
    f.spect_detail = 0;
    m.update(s, f, cfg, 1.3);
    CHECK(!v.set.gaps && !v.set.tyres && v.row[0].gap[0] == 0 && !v.row[0].gna && v.row[0].shown == kShownOff);
    CHECK(v.row[5].gap[0] == 0 && !v.row[5].gna && v.row[5].tyre == 0 && !v.row[5].tna);
    // Gap 3: each car's lap time (P1 too), the dim bar without one; never the interval. In a race the lap
    // table's best lap (the results entry's time alone shows nothing)
    s.cls.lap_ok[0] = true;
    s.cls.lap_s[0] = 92.456f;
    s.cls.lap_ok[5] = true;
    s.cls.lap_s[5] = 93.07f;
    s.cls.lap_ok[6] = true;
    s.cls.lap_s[6] = 91.0f;
    s.laps.best_ok[0] = true;
    s.laps.best_ms[0] = 92456;
    s.laps.best_ok[5] = true;
    s.laps.best_ms[5] = 93070;
    f.spect_gap = 3;
    f.spect_detail = 1;
    m.update(s, f, cfg, 1.4);
    CHECK(v.laps && !v.lead && std::strcmp(v.row[0].gap, "1:32.4") == 0 && v.row[0].shown == kShownTime);
    CHECK(std::strcmp(v.row[5].gap, "1:33.0") == 0 && !v.row[5].gna);
    CHECK(v.row[6].gap[0] == 0 && v.row[6].gna && v.row[6].shown == kShownUnavailable);
    // Detail 1: places gained or lost since the grid (grid slot minus position), "-" none; the dim bar
    // without a grid slot. snap(): car i is P(i + 1)
    CHECK(v.set.tyres && v.row[5].tyre == 0 && v.row[5].tna && v.row[5].det[0] == 0 && !v.row[5].dup &&
          !v.row[5].ddn);
    s.cls.grid[5] = 9;  // P6 from 9th: 3 gained
    s.cls.grid[6] = 2;  // P7 from 2nd: 5 lost
    s.cls.grid[7] = 8;  // P8 from 8th: none
    s.cls.grid[3] = 16; // P4 from 16th: 12 gained
    m.update(s, f, cfg, 1.45);
    CHECK(std::strcmp(v.row[5].det, "3") == 0 && v.row[5].dup && !v.row[5].ddn && !v.row[5].tna && v.row[5].tyre == 0);
    CHECK(std::strcmp(v.row[6].det, "5") == 0 && v.row[6].ddn && !v.row[6].dup && !v.row[6].tna);
    CHECK(std::strcmp(v.row[7].det, "-") == 0 && !v.row[7].dup && !v.row[7].ddn && !v.row[7].tna);
    CHECK(std::strcmp(v.row[3].det, "12") == 0 && v.row[3].dup);
    CHECK(v.row[8].det[0] == 0 && v.row[8].tna && !v.row[8].dup); // no grid slot read
    s.cls.grid[9] = 9; // two cars on one slot: not a grid, the dim bar for every car
    m.update(s, f, cfg, 1.455);
    CHECK(v.row[5].det[0] == 0 && v.row[5].tna && !v.row[5].dup && v.row[7].tna && v.row[7].det[0] == 0);
    s.cls.grid[9] = 0;
    // outside races the dim bar (the menu offers it in races only; the slot means nothing there)
    f.session = 5;
    m.update(s, f, cfg, 1.46);
    CHECK(v.row[5].det[0] == 0 && v.row[5].tna && !v.row[5].dup);
    f.session = 15;
    // Detail 2: the game's pit stop count, "-" for none; the dim bar unread
    s.pitlaps.stops_have[5] = true;
    s.pitlaps.stops[5] = 2;
    s.pitlaps.stops_have[6] = true;
    s.pitlaps.stops[6] = 0;
    f.spect_detail = 2;
    m.update(s, f, cfg, 1.5);
    CHECK(std::strcmp(v.row[5].det, "2") == 0 && !v.row[5].tna && v.row[5].tyre == 0 && !v.row[5].dup);
    CHECK(std::strcmp(v.row[6].det, "-") == 0 && !v.row[6].tna);
    CHECK(v.row[7].det[0] == 0 && v.row[7].tna);
    // Detail 5: the penalty text; nothing for a car without one; unreadable state: the dim bar
    s.cls.tpen_s[4] = 5.f;
    s.pen.dt[6] = 1;
    s.pen.sg[7] = 1;
    s.cls.seq = 2;
    f.spect_detail = 5;
    m.update(s, f, cfg, 1.6);
    CHECK(std::strcmp(v.row[4].det, "5s") == 0 && v.row[4].tyre == 0 && !v.row[4].tna);
    CHECK(std::strcmp(v.row[6].det, "DT") == 0 && std::strcmp(v.row[7].det, "SG") == 0);
    CHECK(v.row[5].det[0] == 0 && !v.row[5].tna && v.row[5].tyre == 0);
    s.pen.mc_ok = false;
    s.cls.tpen_ok[4] = false;
    m.update(s, f, cfg, 1.7);
    CHECK(v.row[4].det[0] == 0 && v.row[4].tna && v.row[5].det[0] == 0 && !v.row[5].tna); // 5 still has its total
    // a retired car: Out, no detail
    s.cls.status[8] = 7;
    m.update(s, f, cfg, 1.8);
    CHECK(std::strcmp(v.row[8].gap, "Out") == 0 && v.row[8].det[0] == 0 && !v.row[8].tna);
    // values the menu never writes: the settings
    f.spect_gap = 4;
    f.spect_detail = 6;
    m.update(s, f, cfg, 1.9);
    CHECK(v.sgap == -1 && v.sdet == -1 && v.set.gaps && v.set.tyres && std::strcmp(v.row[0].gap, "Interval") == 0);
    CHECK(v.row[5].tyre == 'S');
    // the debug line names the modes the tower follows
    cfg.debug = true;
    f.spect_gap = 3;
    f.spect_detail = 5;
    m.update(s, f, cfg, 2.0);
    CHECK(std::strstr(v.dbg, " sG3D5") != nullptr && std::strlen(v.dbg) < sizeof v.dbg - 1);
}

// rNN_det: a text leaf after bdg; the spectator's Detail cell
static int spect_ok_set(void *, const char *, LeafType, const void *) { return 0; }
static void test_spectator_leaves()
{
    Model m;
    Snapshot s = snap();
    Settings cfg;
    cfg.mode = Mode::full;
    Frame f = frame();
    f.spect = true;
    f.spect_gap = 0;
    f.spect_detail = 5;
    s.cls.tpen_s[3] = 10.f;
    m.update(s, f, cfg, 1.0);
    Publisher pub;
    pub.set_sink(LeafSink{spect_ok_set, nullptr});
    for (int i = 0; i < 400; ++i)
        pub.publish(m.view(), 1.0, kFrameBudget);
    CHECK(pub.type(Publisher::row_leaf(3, kRowDet)) == LeafType::text);
    CHECK(std::strcmp(pub.path(Publisher::row_leaf(3, kRowDet)), "view_model_data.hud_tt_r03_det") == 0);
    CHECK(std::strcmp(pub.sent_text(Publisher::row_leaf(3, kRowDet)), "10s") == 0);
    CHECK(pub.sent_text(Publisher::row_leaf(2, kRowDet))[0] == 0);
    CHECK(pub.sent(kInts) && pub.sent_int(kInts) == 0 && pub.sent(kTyres) && pub.sent_int(kTyres) == 1);
    CHECK(pub.sent_int(Publisher::row_leaf(3, kRowTS)) == 0);
    // Position Change: the count in rNN_det, the direction in rNN_dup / rNN_ddn
    s.cls.grid[3] = 7; // P4 from 7th
    s.cls.grid[4] = 2; // P5 from 2nd
    f.spect_detail = 1;
    m.update(s, f, cfg, 1.05);
    for (int i = 0; i < 400; ++i)
        pub.publish(m.view(), 1.05, kFrameBudget);
    CHECK(std::strcmp(pub.path(Publisher::row_leaf(3, kRowDup)), "view_model_data.hud_tt_r03_dup") == 0 &&
          std::strcmp(pub.path(Publisher::row_leaf(3, kRowDdn)), "view_model_data.hud_tt_r03_ddn") == 0);
    CHECK(std::strcmp(pub.sent_text(Publisher::row_leaf(3, kRowDet)), "3") == 0 &&
          pub.sent_int(Publisher::row_leaf(3, kRowDup)) == 1 && pub.sent_int(Publisher::row_leaf(3, kRowDdn)) == 0);
    CHECK(std::strcmp(pub.sent_text(Publisher::row_leaf(4, kRowDet)), "3") == 0 &&
          pub.sent_int(Publisher::row_leaf(4, kRowDup)) == 0 && pub.sent_int(Publisher::row_leaf(4, kRowDdn)) == 1);
    CHECK(pub.sent_text(Publisher::row_leaf(2, kRowDet))[0] == 0 && pub.sent_int(Publisher::row_leaf(2, kRowTna)) == 1);
    f.spect_detail = 5;
    m.update(s, f, cfg, 1.08);
    for (int i = 0; i < 400; ++i)
        pub.publish(m.view(), 1.08, kFrameBudget);
    CHECK(std::strcmp(pub.sent_text(Publisher::row_leaf(3, kRowDet)), "10s") == 0 &&
          pub.sent_int(Publisher::row_leaf(3, kRowDup)) == 0 && pub.sent_int(Publisher::row_leaf(4, kRowDdn)) == 0);
    // laps: the gap column holds lap times (Gap 3) - the template draws P1's at the number size
    CHECK(pub.type(kLaps) == LeafType::boolean && std::strcmp(pub.path(kLaps), "view_model_data.hud_tt_laps") == 0);
    CHECK(pub.sent(kLaps) && pub.sent_int(kLaps) == 0);
    // flap: Gap 3 only - the template sets every lap time of the column at its lap time size
    CHECK(pub.type(kFlap) == LeafType::boolean && std::strcmp(pub.path(kFlap), "view_model_data.hud_tt_flap") == 0);
    CHECK(pub.sent(kFlap) && pub.sent_int(kFlap) == 0);
    f.spect_gap = 3;
    m.update(s, f, cfg, 1.1);
    for (int i = 0; i < 400; ++i)
        pub.publish(m.view(), 1.1, kFrameBudget);
    CHECK(pub.sent_int(kLaps) == 1 && pub.sent_int(kInts) == 1 && pub.sent_int(kFlap) == 1);
    f.spect = false;
    m.update(s, f, cfg, 1.2);
    for (int i = 0; i < 400; ++i)
        pub.publish(m.view(), 1.2, kFrameBudget);
    CHECK(pub.sent_int(kLaps) == 0 && pub.sent_int(kFlap) == 0);
}

static void test_model_race()
{
    Model m;
    Snapshot s = snap();
    Settings cfg;
    m.update(s, frame(), cfg, 1.0);
    const View &v = m.view();
    CHECK(v.on && v.race && !v.timed && v.count == N && v.rows == 5 && v.start == 9 && v.player_index == 11);
    CHECK(std::strcmp(v.sess, "R") == 0 && std::strcmp(v.lap, "10") == 0 && !v.lapna); // counter 9 -> lap 10
    CHECK(v.row[0].vid == 9 && v.row[0].pos == 10 && std::strcmp(v.row[0].gap, "+1.0") == 0 && !v.row[0].gna &&
          v.row[0].shown == kShownTime);
    CHECK(v.row[2].vid == 11 && v.row[2].me && !v.row[1].me);
    CHECK(v.row[0].tyre == 'S' && !v.row[0].tna);
    CHECK(v.car_row[11] == 2 && v.car_row[0] == -1);
    CHECK(v.hs == 0 && !v.sc && !v.vsc && !v.chq);
    // full: P1 shows the mode's word
    cfg.mode = Mode::full;
    m.update(s, frame(), cfg, 1.1);
    CHECK(v.rows == N && v.row[0].p1 && std::strcmp(v.row[0].gap, "Interval") == 0 && v.row[0].shown == kShownWord);
    cfg.gap_mode = GapMode::leader;
    m.update(s, frame(), cfg, 1.2);
    CHECK(v.lead && std::strcmp(v.row[0].gap, "Leader") == 0 && std::strcmp(v.row[5].gap, "+5.0") == 0);
    cfg.gap_mode = GapMode::interval;
    // a cleared flag on a running car in the pits: PIT
    s.timing.car[6].ahead_valid = false;
    s.pitlaps.pit[6] = 3;
    // a cleared flag for a lapped car: +1 LAP from the game's lap counters (interval: to the car ahead)
    s.timing.car[7].ahead_valid = false;
    s.pitlaps.lap[7] = 8;
    s.timing.car[8].ahead_valid = false; // the car ahead (7) is a lap down too: 0 laps between 7 and 8
    s.pitlaps.lap[8] = 8;
    // a valid flag on a car whose status leaves it stale (0): unavailable, never the old value
    s.cls.status[9] = 0;
    // retired, disqualified, not classified
    s.cls.status[19] = 7;
    s.cls.status[20] = 5;
    s.cls.status[21] = 6;
    // a valid flag with an absurd value, in the pit lane: the game's flag says "a time", so never PIT or LAP
    s.timing.car[10].ahead_ms = -5;
    s.pitlaps.pit[10] = 3;
    // no T entry
    s.timing.car[12].have = false;
    s.cls.seq = 2;
    m.update(s, frame(), cfg, 1.3);
    CHECK(std::strcmp(v.row[6].gap, "PIT") == 0 && v.row[6].pit && v.row[6].shown == kShownPit);
    CHECK(std::strcmp(v.row[7].gap, "+1 LAP") == 0 && v.row[7].shown == kShownLapped && !v.row[7].gna);
    CHECK(v.row[8].gap[0] == 0 && v.row[8].gna && v.row[8].shown == kShownUnavailable);
    CHECK(v.row[9].gap[0] == 0 && v.row[9].gna);
    CHECK(std::strcmp(v.row[19].gap, "Out") == 0 && v.row[19].out && v.row[19].tyre == 0 && !v.row[19].tna &&
          !v.row[19].gna);
    CHECK(std::strcmp(v.row[20].gap, "DSQ") == 0 && v.row[20].out);
    CHECK(std::strcmp(v.row[21].gap, "NC") == 0 && v.row[21].out);
    CHECK(v.row[10].gna && v.row[10].gap[0] == 0 && v.row[10].pit && v.row[12].gna);
    // leader mode: lapped to the leader, two laps
    cfg.gap_mode = GapMode::leader;
    s.timing.car[8].leader_valid = false;
    s.pitlaps.lap[8] = 7;
    m.update(s, frame(), cfg, 1.4);
    CHECK(std::strcmp(v.row[8].gap, "+2 LAPS") == 0);
    // a cleared flag without a reason we know (same lap count, not in the pits): unavailable
    s.timing.car[13].leader_valid = false;
    m.update(s, frame(), cfg, 1.5);
    CHECK(v.row[13].gna && v.row[13].gap[0] == 0);
    // the timing system missing: every gap unavailable, P1 still shows the word
    s.timing.ok = false;
    m.update(s, frame(), cfg, 1.6);
    CHECK(v.row[3].gna && !v.row[0].gna && std::strcmp(v.row[0].gap, "Leader") == 0);
    // intervals off: empty and not unavailable
    cfg.gaps = false;
    m.update(s, frame(), cfg, 1.7);
    CHECK(v.row[3].gap[0] == 0 && !v.row[3].gna && v.row[3].shown == kShownOff && v.row[19].gap[0] == 0);
}

static void test_model_flags()
{
    Model m;
    Snapshot s = snap();
    Settings cfg;
    cfg.mode = Mode::full;
    s.pen.dt[2] = 1;          // unserved drive-through
    s.pen.sg[3] = 1;          // unserved stop-go
    s.cls.tpen_s[4] = 5.f;    // a 5 s time penalty
    s.pen.mc_ok = true;
    s.pitlaps.pit[5] = 15;    // garage: P box (the full-grid list's rule, 2..15)
    s.pitlaps.pit[6] = 1;     // not a pit state
    m.update(s, frame(), cfg, 1.0);
    const View &v = m.view();
    CHECK(v.row[2].pen && v.row[3].pen && v.row[4].pen && !v.row[5].pen);
    CHECK(v.row[5].pit && !v.row[6].pit);
    // a cleared flag in pit states 8..13: the PIT badge (the list's rule) but no "PIT" gap text (the gap rule
    // is 2..7 and 14..15), so the cell is unavailable
    s.pitlaps.pit[10] = 10;
    s.timing.car[10].ahead_valid = false;
    m.update(s, frame(), cfg, 1.0);
    CHECK(v.row[10].pit && v.row[10].gna && v.row[10].gap[0] == 0 && v.row[10].shown == kShownUnavailable);
    s.pitlaps.pit[10] = 14;
    m.update(s, frame(), cfg, 1.0);
    CHECK(v.row[10].pit && !v.row[10].gna && std::strcmp(v.row[10].gap, "PIT") == 0);
    s.pitlaps.pit[10] = 0;
    s.timing.car[10].ahead_valid = true;
    // tyres: unavailable, held over a stale cache for at most 1 s, off
    s.tyre[7].state = 3;
    s.tyre[8].state = 2;
    s.tyre[8].held = 'M';
    s.tyre[8].held_t = 0.5;
    s.tyre[9].visual = 17; // contradicts the compound
    m.update(s, frame(), cfg, 1.0);
    CHECK(v.row[7].tna && v.row[7].tyre == 0);
    CHECK(v.row[8].tyre == 'M' && v.row[8].tyre_held && !v.row[8].tna);
    CHECK(v.row[9].tna && v.row[9].tyre == 0);
    m.update(s, frame(), cfg, 1.6);
    CHECK(v.row[8].tna && v.row[8].tyre == 0);
    cfg.tyres = false;
    m.update(s, frame(), cfg, 1.7);
    CHECK(!v.row[7].tna && v.row[1].tyre == 0);
    // highlight off
    cfg.highlight = false;
    m.update(s, frame(), cfg, 1.8);
    CHECK(!v.row[11].me);
    // the header: safety car, VSC, chequered (wins), the leader's lap after the finish
    s.sc.state = 2;
    m.update(s, frame(), cfg, 1.9);
    CHECK(v.vsc && !v.sc && v.hs == 2);
    s.sc.state = 1;
    m.update(s, frame(), cfg, 2.0);
    CHECK(v.sc && v.hs == 1);
    s.sc.state = 3; // formation lap: the normal header
    m.update(s, frame(), cfg, 2.1);
    CHECK(v.hs == 0 && !v.sc && !v.vsc);
    s.cls.status[0] = 3;
    s.pitlaps.lap[0] = 57;
    s.sc.state = 1;
    m.update(s, frame(), cfg, 2.2);
    CHECK(v.chq && v.hs == 4 && std::strcmp(v.lap, "57") == 0);
    // the leader's lap unreadable: unavailable
    s.pitlaps.lap_have[0] = false;
    m.update(s, frame(), cfg, 2.3);
    CHECK(v.lapna && v.lap[0] == 0);
    // timed sessions: no gaps (no verified best-lap source), the label, no lap
    Model q;
    Snapshot sq = snap();
    sq.cls.status[3] = 7;
    q.update(sq, frame(11, 6), cfg, 1.0);
    const View &w = q.view();
    CHECK(w.on && w.timed && !w.race && std::strcmp(w.sess, "Q2") == 0 && w.lap[0] == 0 && !w.lapna);
    CHECK(w.row[0].gna && w.row[0].gap[0] == 0 && w.row[1].gna && std::strcmp(w.row[3].gap, "Out") == 0);
    CHECK(w.hs == 0 && !w.chq);
    // time trial, an unknown session type, the setting off: no tower
    q.update(sq, frame(11, 18), cfg, 1.1);
    CHECK(!w.on && w.rows == 0);
    Frame unk = frame();
    unk.session_ok = false;
    q.update(sq, unk, cfg, 1.2);
    CHECK(!w.on);
    cfg.enabled = false;
    q.update(sq, frame(), cfg, 1.3);
    CHECK(!w.on);
}

// The flag header (leaves.md v3): 4 chequered > 3 red > 1 SC > 2 VSC > 5 yellow > 0, red and yellow in every tower
// session, the yellow held over one non-yellow read.
static void flag_read(Snapshot &s, double t, int yellow, uint8_t ysec, bool unmapped = false, int red = 0,
                      bool zones_ok = true)
{
    FlagRead &fl = s.flags;
    ++fl.seq;
    fl.t = t;
    fl.zones_ok = zones_ok;
    fl.zones = zones_ok ? 20 : 0;
    fl.yellow = zones_ok ? yellow : 0;
    fl.ysec = zones_ok ? ysec : 0;
    fl.unmapped = zones_ok && unmapped;
    fl.red = int8_t(red);
}

static void test_model_flag_header()
{
    Model m;
    Snapshot s = snap();
    s.found_zones = s.found_red = true;
    Settings cfg;
    const View &v = m.view();
    flag_read(s, 1.0, 0, 0);
    m.update(s, frame(), cfg, 1.0);
    CHECK(v.hs == 0 && !v.red && !v.yel && v.ysec[0] == 0 && !v.ysna);
    CHECK(std::strstr(v.dbg, "yel0 red0") != nullptr);
    // a yellow in sector 2
    flag_read(s, 1.25, 1, 0b010);
    m.update(s, frame(), cfg, 1.25);
    CHECK(v.hs == 5 && v.yel && std::strcmp(v.ysec, "2") == 0 && !v.ysna && !v.red && !v.sc);
    // two sectors, in track order
    flag_read(s, 1.5, 3, 0b101);
    m.update(s, frame(), cfg, 1.5);
    CHECK(v.hs == 5 && std::strcmp(v.ysec, "1 3") == 0 && std::strstr(v.dbg, "yel3 red0") != nullptr);
    // the same read on later frames changes nothing
    m.update(s, frame(), cfg, 1.6);
    CHECK(v.hs == 5 && std::strcmp(v.ysec, "1 3") == 0);
    // one non-yellow read (the writer's 0 between two 3s): held, with the last sectors
    flag_read(s, 1.75, 0, 0);
    m.update(s, frame(), cfg, 1.75);
    CHECK(v.hs == 5 && v.yel && std::strcmp(v.ysec, "1 3") == 0);
    // the second one clears it
    flag_read(s, 2.0, 0, 0);
    m.update(s, frame(), cfg, 2.0);
    CHECK(v.hs == 0 && !v.yel && v.ysec[0] == 0);
    // a yellow zone without a sector: yellow, no sector text, ysna
    flag_read(s, 2.25, 2, 0b001, true);
    m.update(s, frame(), cfg, 2.25);
    CHECK(v.hs == 5 && v.yel && v.ysec[0] == 0 && v.ysna);
    // an unreadable list clears the yellow at once (nothing is held over a failed read)
    flag_read(s, 2.5, 0, 0, false, 0, false);
    m.update(s, frame(), cfg, 2.5);
    CHECK(v.hs == 0 && !v.yel && !v.ysna && std::strstr(v.dbg, "yel?") != nullptr);
    // SC with a yellow zone: the SC header, the yellow bool still set (the template may show both)
    flag_read(s, 2.75, 1, 0b010);
    s.sc.state = 1;
    m.update(s, frame(), cfg, 2.75);
    CHECK(v.hs == 1 && v.sc && v.yel && std::strcmp(v.ysec, "2") == 0);
    s.sc.state = 2;
    m.update(s, frame(), cfg, 2.8);
    CHECK(v.hs == 2 && v.vsc && v.yel);
    // the red flag: the SC byte reads 1 under a red flag (in-game log 2026-11-09 16:39); the red flag wins and the
    // SC block is cleared
    s.sc.state = 1;
    flag_read(s, 3.0, 1, 0b010, false, 1);
    m.update(s, frame(), cfg, 3.0);
    CHECK(v.hs == 3 && v.red && !v.sc && !v.vsc && v.yel && std::strstr(v.dbg, "red1") != nullptr);
    flag_read(s, 3.25, 0, 0, false, 2); // suspended
    m.update(s, frame(), cfg, 3.25);
    CHECK(v.hs == 3 && v.red && !v.sc);
    s.sc.state = 2; // with the VSC byte as well
    m.update(s, frame(), cfg, 3.3);
    CHECK(v.hs == 3 && !v.vsc);
    // the red flag byte unreadable: nothing raised, the header falls back to the SC
    s.sc.state = 1;
    flag_read(s, 3.5, 0, 0, false, -1);
    m.update(s, frame(), cfg, 3.5);
    CHECK(v.hs == 1 && v.sc && !v.red && std::strstr(v.dbg, "red?") != nullptr);
    // the red flag ends: back to the SC
    flag_read(s, 3.75, 0, 0, false, 0);
    m.update(s, frame(), cfg, 3.75);
    CHECK(v.hs == 1 && v.sc && !v.red);
    // the chequered flag stays on top
    flag_read(s, 4.0, 0, 0, false, 1);
    s.cls.status[0] = 3;
    m.update(s, frame(), cfg, 4.0);
    CHECK(v.hs == 4 && v.chq && v.red);
    s.cls.status[0] = 2;
    s.sc.state = 0;
    // a flags read older than kFlagMaxAge (the reader fell behind): nothing raised
    m.update(s, frame(), cfg, 5.1);
    CHECK(v.hs == 0 && !v.red && !v.yel);
    // a new car set: the yellow does not carry over
    flag_read(s, 5.25, 1, 0b100);
    m.update(s, frame(), cfg, 5.25);
    CHECK(v.hs == 5);
    Snapshot fresh = snap();
    m.update(fresh, frame(11, 15, 2), cfg, 5.3);
    CHECK(v.hs == 0 && !v.yel);
    // timed sessions: red and yellow show; the SC byte does not (race only)
    Model q;
    Snapshot sq = snap();
    sq.sc.state = 1;
    flag_read(sq, 1.0, 1, 0b001);
    q.update(sq, frame(11, 6), cfg, 1.0);
    const View &w = q.view();
    CHECK(w.timed && w.hs == 5 && w.yel && std::strcmp(w.ysec, "1") == 0 && !w.sc);
    flag_read(sq, 1.25, 1, 0b001, false, 1);
    q.update(sq, frame(11, 6), cfg, 1.25);
    CHECK(w.hs == 3 && w.red);
    // the tower off: nothing
    cfg.enabled = false;
    q.update(sq, frame(11, 6), cfg, 1.3);
    CHECK(!w.on && w.hs == 0 && !w.red && !w.yel);
}

// every zone at 4 raises the red flag with the red flag byte at 0 (in-game log 2026-11-09 17:44: SC deployed with
// every zone yellow, then every zone 4 with the SC byte still 1 and the red flag byte 0)
static void set_zone_flags(Snapshot &s, int8_t value, int zones = 20)
{
    FlagRead &fl = s.flags;
    fl.zones = zones;
    for (int i = 0; i < int(kMaxMarshalZones); ++i)
        fl.flag[i] = i < zones ? value : 0;
}

static void test_model_flag_zones_red()
{
    Model m;
    Snapshot s = snap();
    s.found_zones = s.found_red = true;
    Settings cfg;
    const View &v = m.view();
    // the SC with every zone yellow: the SC block
    s.sc.state = 1;
    flag_read(s, 1.0, 20, 0b111);
    set_zone_flags(s, 3);
    m.update(s, frame(), cfg, 1.0);
    CHECK(v.hs == 1 && v.sc && !v.red && v.yel);
    // every zone at 4, the byte 0: red, the SC block cleared, 'z' in the debug line
    flag_read(s, 1.25, 0, 0);
    set_zone_flags(s, 4);
    m.update(s, frame(), cfg, 1.25);
    CHECK(v.hs == 3 && v.red && !v.sc && !v.vsc && std::strstr(v.dbg, "redz") != nullptr);
    // one zone caught at 0 between the writer's two stores: held for one read
    flag_read(s, 1.5, 0, 0);
    set_zone_flags(s, 4);
    s.flags.flag[7] = 0;
    m.update(s, frame(), cfg, 1.5);
    CHECK(v.hs == 3 && v.red);
    // a second read without every zone at 4: back to the SC
    flag_read(s, 1.75, 0, 0);
    set_zone_flags(s, 4);
    s.flags.flag[7] = 1;
    m.update(s, frame(), cfg, 1.75);
    CHECK(v.hs == 1 && v.sc && !v.red && std::strstr(v.dbg, "red0") != nullptr);
    // some zones at 4 never raise it
    for (double t = 2.0; t < 3.0; t += 0.25) {
        flag_read(s, t, 0, 0);
        set_zone_flags(s, 4);
        s.flags.flag[0] = 0;
        m.update(s, frame(), cfg, t);
        CHECK(v.hs == 1 && !v.red);
    }
    // red again, then an unreadable list: dropped at once (no hold over a failed read)
    flag_read(s, 3.0, 0, 0);
    set_zone_flags(s, 4);
    m.update(s, frame(), cfg, 3.0);
    CHECK(v.hs == 3 && v.red);
    flag_read(s, 3.25, 0, 0, false, 0, false);
    set_zone_flags(s, 0, 0);
    m.update(s, frame(), cfg, 3.25);
    CHECK(v.hs == 1 && !v.red && std::strstr(v.dbg, "yel?") != nullptr);
    // an empty zone list (valid, no zones) raises nothing
    flag_read(s, 3.5, 0, 0);
    set_zone_flags(s, 4, 0);
    m.update(s, frame(), cfg, 3.5);
    CHECK(v.hs == 1 && !v.red);
    // the byte and the zones together: the debug line shows the byte
    flag_read(s, 3.75, 0, 0, false, 1);
    set_zone_flags(s, 4);
    m.update(s, frame(), cfg, 3.75);
    CHECK(v.hs == 3 && v.red && std::strstr(v.dbg, "red1") != nullptr);
    // a stale flags read (older than kFlagMaxAge): nothing raised, and nothing held afterwards
    m.update(s, frame(), cfg, 5.0);
    CHECK(v.hs == 1 && !v.red);
    flag_read(s, 5.25, 0, 0);
    set_zone_flags(s, 0);
    m.update(s, frame(), cfg, 5.25);
    CHECK(v.hs == 1 && !v.red);
    // a timed session: the zones' red shows there too (the SC byte does not)
    Model q;
    Snapshot sq = snap();
    sq.found_zones = sq.found_red = true;
    flag_read(sq, 1.0, 0, 0);
    set_zone_flags(sq, 4);
    q.update(sq, frame(11, 6), cfg, 1.0);
    CHECK(q.view().timed && q.view().hs == 3 && q.view().red);
}

static void test_model_arrows()
{
    Model m;
    Snapshot s = snap();
    Settings cfg;
    cfg.mode = Mode::full;
    m.update(s, frame(), cfg, 1.0);
    const View &v = m.view();
    bool none = true;
    for (int k = 0; k < v.rows; ++k)
        none = none && !v.row[k].up && !v.row[k].dn;
    CHECK(none); // the first classification has no previous one: no arrows
    // car 6 passes car 5: 6 up, 5 down; the arrow follows the car (vehicle id), not the row
    std::swap(s.cls.order[5], s.cls.order[6]);
    s.cls.pos[6] = 6;
    s.cls.pos[5] = 7;
    s.cls.seq = 2;
    s.cls.t = 1.1;
    m.update(s, frame(), cfg, 1.1);
    CHECK(v.row[5].vid == 6 && v.row[5].up && !v.row[5].dn && v.row[6].vid == 5 && v.row[6].dn);
    CHECK(m.arrow(6, 1.1) == 1 && m.arrow(5, 1.1) == -1 && m.arrow(4, 1.1) == 0);
    // the same read again (no new classification): unchanged
    m.update(s, frame(), cfg, 3.0);
    CHECK(v.row[5].up && v.row[6].dn);
    // gone after kArrowSeconds
    m.update(s, frame(), cfg, 1.1 + kArrowSeconds + 0.01);
    CHECK(!v.row[5].up && !v.row[6].dn);
    // a newer change restarts it and can flip it
    std::swap(s.cls.order[5], s.cls.order[6]);
    s.cls.pos[6] = 7;
    s.cls.pos[5] = 6;
    s.cls.seq = 3;
    m.update(s, frame(), cfg, 6.0);
    CHECK(m.arrow(6, 6.0) == -1 && m.arrow(5, 6.0) == 1);
    // arrows off: none shown, the state is still tracked
    cfg.arrows = false;
    m.update(s, frame(), cfg, 6.1);
    CHECK(!v.row[5].up && !v.row[6].dn && m.arrow(5, 6.1) == 1);
    cfg.arrows = true;
    // a new car set (generation): every arrow cleared; its first read is only the reference, even when it differs
    std::swap(s.cls.order[0], s.cls.order[1]);
    s.cls.pos[0] = 2;
    s.cls.pos[1] = 1;
    s.cls.seq = 4;
    m.update(s, frame(11, 15, 2), cfg, 6.2);
    CHECK(m.arrow(5, 6.2) == 0 && m.arrow(6, 6.2) == 0 && m.arrow(0, 6.2) == 0 && m.arrow(1, 6.2) == 0);
    // the next change in the new set has arrows
    std::swap(s.cls.order[0], s.cls.order[1]);
    s.cls.pos[0] = 1;
    s.cls.pos[1] = 2;
    s.cls.seq = 5;
    s.cls.t = 6.3;
    m.update(s, frame(11, 15, 2), cfg, 6.3);
    CHECK(m.arrow(0, 6.3) == 1 && m.arrow(1, 6.3) == -1);
    // an invalid read is held for 0.3 s after the last valid read (no arrows from it), then the tower goes off
    Snapshot bad = s;
    bad.cls.ok = false;
    bad.cls.n = 0;
    m.update(bad, frame(11, 15, 2), cfg, 6.35);
    CHECK(v.on && v.held && v.count == N);
    m.update(bad, frame(11, 15, 2), cfg, 6.3 + kClsHold + 0.05);
    CHECK(!v.on && v.rows == 0);
    // road order never moves anything: only positions do (a gap change alone is no position change)
    s.timing.car[3].ahead_ms = 99999;
    s.cls.seq = 6;
    s.cls.t = 7.0;
    m.update(s, frame(11, 15, 2), cfg, 7.0);
    CHECK(m.arrow(3, 7.0) == 0 && v.on && !v.held);
    // the tower switched off and on: nothing is kept, the next read is a new reference
    cfg.enabled = false;
    m.update(s, frame(11, 15, 2), cfg, 7.1);
    CHECK(!v.on && m.arrow(0, 7.1) == 0);
    cfg.enabled = true;
    std::swap(s.cls.order[2], s.cls.order[3]);
    s.cls.pos[2] = 4;
    s.cls.pos[3] = 3;
    s.cls.seq = 7;
    m.update(s, frame(11, 15, 2), cfg, 7.2);
    CHECK(v.on && m.arrow(2, 7.2) == 0 && m.arrow(3, 7.2) == 0);
    // off and on again over the very same read (same sequence): that read is the new reference
    cfg.enabled = false;
    m.update(s, frame(11, 15, 2), cfg, 7.3);
    cfg.enabled = true;
    m.update(s, frame(11, 15, 2), cfg, 7.4);
    std::swap(s.cls.order[4], s.cls.order[5]);
    s.cls.pos[4] = 6;
    s.cls.pos[5] = 5;
    s.cls.seq = 8;
    m.update(s, frame(11, 15, 2), cfg, 7.5);
    CHECK(m.arrow(5, 7.5) == 1 && m.arrow(4, 7.5) == -1);
}

static void test_model_auto()
{
    Model m;
    Snapshot s = snap();
    Settings cfg;
    cfg.mode = Mode::full;
    cfg.gap_mode = GapMode::autoswitch;
    cfg.auto_period = 10;
    m.update(s, frame(), cfg, 100.0);
    CHECK(!m.view().lead && std::strcmp(m.view().row[0].gap, "Interval") == 0);
    m.update(s, frame(), cfg, 109.9);
    CHECK(!m.view().lead);
    m.update(s, frame(), cfg, 110.1);
    CHECK(m.view().lead && std::strcmp(m.view().row[0].gap, "Leader") == 0 && std::strcmp(m.view().row[3].gap, "+3.0") == 0);
    m.update(s, frame(), cfg, 120.1);
    CHECK(!m.view().lead);
    cfg.auto_period = 2; // clamped to 5 s
    m.update(s, frame(), cfg, 125.2);
    CHECK(m.view().lead);
    // choosing Auto again restarts with Interval
    cfg.gap_mode = GapMode::leader;
    m.update(s, frame(), cfg, 126.0);
    cfg.gap_mode = GapMode::autoswitch;
    m.update(s, frame(), cfg, 126.1);
    CHECK(!m.view().lead);
}

static void test_model_modes()
{
    Model m;
    Snapshot s = snap();
    Settings cfg;
    cfg.mode = Mode::top;
    cfg.rows = 10;
    m.update(s, frame(15), cfg, 1.0);
    CHECK(m.view().rows == 10 && m.view().start == 0 && m.view().row[9].pos == 10);
    cfg.mode = Mode::compact;
    cfg.rows = 5;
    m.update(s, frame(0), cfg, 1.1); // the player leads
    CHECK(m.view().start == 0 && m.view().row[0].me);
    m.update(s, frame(21), cfg, 1.2); // the player is last
    CHECK(m.view().start == 17 && m.view().row[4].me && m.view().row[4].pos == 22);
    m.update(s, frame(-1), cfg, 1.3); // no player: the top five
    CHECK(m.view().start == 0 && m.view().rows == 5 && m.view().player_index == -1);
    // a 20-car field in full mode
    Snapshot s20 = snap(20);
    cfg.mode = Mode::full;
    m.update(s20, frame(), cfg, 1.4);
    CHECK(m.view().rows == 20 && !m.view().trunc);
    // classification with a hole: the game's numbers stay
    Snapshot h = snap();
    h.cls.n = N - 1;
    for (int i = 4; i < N - 1; ++i)
        h.cls.order[i] = uint8_t(i + 1);
    h.cls.pos[4] = 0;
    h.cls.holes = 1;
    m.update(h, frame(), cfg, 1.5);
    CHECK(m.view().rows == N - 1 && m.view().row[4].pos == 6 && m.view().row[3].pos == 4);
}

// ---------------------------------------------------------------- publisher

// Badges for the rows around the player 11 (cars 9..13): 9 failed, 10 the game's other path, 11 McLaren, 12 and 13
// Ferrari.
static void set_badges(Snapshot &s)
{
    Badges &b = s.badges;
    b.keys = 2;
    std::strcpy(b.key[0], "mclaren_26");
    std::strcpy(b.key[1], "ferrari_26");
    b.car[9].state = kBadgeFailed;
    b.car[9].step = 4;
    b.car[10].state = kBadgeOther;
    b.car[11].state = kBadgeKey;
    b.car[11].key = 0;
    b.car[12].state = kBadgeKey;
    b.car[12].key = 1;
    b.car[13].state = kBadgeKey;
    b.car[13].key = 1;
}

static void test_model_badges()
{
    Snapshot s = snap();
    set_badges(s);
    Model m;
    Settings cfg;
    cfg.team_colours = false; // the badge does not depend on it
    m.update(s, frame(), cfg, 1.0);
    const View &v = m.view();
    CHECK(v.rows == 5 && v.row[2].vid == 11 && v.row[2].bdg && v.row[2].bkey == 0 &&
          std::strcmp(v.row[2].badge, "mclaren_26") == 0);
    CHECK(v.row[3].bdg && std::strcmp(v.row[3].badge, "ferrari_26") == 0 && v.row[4].bdg && v.row[4].bkey == 1);
    CHECK(!v.row[0].bdg && v.row[0].badge[0] == 0 && v.row[0].bkey == -1 && !v.row[1].bdg && v.row[1].badge[0] == 0);
    CHECK(std::strstr(v.dbg, " bdg3") != nullptr);
    // an out car keeps its badge (the game's pill shows every car in the standings)
    s.cls.status[13] = 4;
    m.update(s, frame(), cfg, 1.1);
    CHECK(v.row[4].out && v.row[4].bdg);
    // the badge follows its car: 12 passes 11, the player's window moves with the player
    std::swap(s.cls.order[11], s.cls.order[12]);
    s.cls.pos[11] = 13;
    s.cls.pos[12] = 12;
    s.cls.seq = 2;
    m.update(s, frame(), cfg, 1.2);
    CHECK(v.row[1].vid == 12 && std::strcmp(v.row[1].badge, "ferrari_26") == 0 && v.row[2].vid == 11 &&
          std::strcmp(v.row[2].badge, "mclaren_26") == 0 && v.row[0].vid == 10 && !v.row[0].bdg);
    // a key index outside the table is not shown
    s.badges.car[12].key = 5;
    m.update(s, frame(), cfg, 1.3);
    CHECK(!v.row[1].bdg && v.row[1].badge[0] == 0);
    // the tower off: no badge anywhere
    cfg.enabled = false;
    m.update(s, frame(), cfg, 1.4);
    CHECK(!v.on && !v.row[2].bdg);
}

struct Recorder {
    int writes = 0;
    int fail = 0; // fail the next n writes
    std::vector<std::string> paths;
};
static int rec_set(void *ctx, const char *path, LeafType, const void *)
{
    Recorder &r = *static_cast<Recorder *>(ctx);
    if (r.fail > 0) {
        --r.fail;
        return 2;
    }
    ++r.writes;
    r.paths.push_back(path);
    return 0;
}

static int id_of(const Publisher &p, const char *key)
{
    const std::string want = std::string("view_model_data.hud_tt_") + key;
    for (int i = 0; i < p.count(); ++i)
        if (want == p.path(i))
            return i;
    return -1;
}

static ModeRead mode_read(const char *label, double t)
{
    ModeRead md;
    md.ok = true;
    md.seq = 1;
    md.t = t;
    std::snprintf(md.label, sizeof md.label, "%s", label);
    md.time_trial = std::strcmp(label, "time_trial") == 0;
    return md;
}

// Time Trial (leaves.md §2): the game mode label "time_trial", read within kModeMaxAge, turns the standings tower off
// whatever the session type reads (0 in Time Trial; the last race's after one) and the Time Trial board on.
static void test_model_trial()
{
    Settings cfg;
    Model m;
    Snapshot s = snap(1); // Time Trial: the player alone in the classification (log 2026-11-10 03:05)
    s.mode = mode_read("time_trial", 1.0);
    m.update(s, frame(0, 0), cfg, 1.1); // the session type reads 0 in Time Trial
    CHECK(!m.view().on && m.view().trial && m.view().show && std::strcmp(m.view().dbg, "time trial") == 0);
    m.update(s, frame(0, 16), cfg, 1.2); // the last race's session type, held after it
    CHECK(!m.view().on && m.view().trial && m.view().show && m.view().rows == 0 && !m.view().race);
    // stale (over kModeMaxAge), or newer than now (the clock went back): no Time Trial, the rule as before
    m.update(s, frame(0, 16), cfg, 2.2);
    CHECK(m.view().on && !m.view().trial && m.view().show);
    m.update(s, frame(0, 16), cfg, 0.5);
    CHECK(!m.view().trial);
    // another mode: as before (a race session type: on; 0: off)
    s.mode = mode_read("grand_prix_23", 3.0);
    m.update(s, frame(0, 16), cfg, 3.1);
    CHECK(m.view().on && !m.view().trial && m.view().show);
    m.update(s, frame(0, 0), cfg, 3.2);
    CHECK(!m.view().on && !m.view().trial && !m.view().show && std::strcmp(m.view().dbg, "off") == 0);
    // the menus between: "none"
    s.mode = mode_read("none", 3.3);
    m.update(s, frame(0, 0), cfg, 3.4);
    CHECK(!m.view().on && !m.view().trial && !m.view().show);
    // an unread mode (a failed step) is no Time Trial
    s.mode = ModeRead{};
    s.mode.seq = 5;
    s.mode.step = 3;
    s.mode.t = 3.5;
    m.update(s, frame(0, 16), cfg, 3.6);
    CHECK(m.view().on && !m.view().trial);
    // the setting off: nothing
    s.mode = mode_read("time_trial", 3.7);
    cfg.enabled = false;
    m.update(s, frame(0, 0), cfg, 3.8);
    CHECK(!m.view().on && !m.view().trial && !m.view().show);
}

// trial and show: bools right after on, so the three go out in one frame; in Time Trial every row and header leaf
// of the standings tower is off.
static void test_trial_leaves()
{
    auto pub = std::make_unique<Publisher>();
    Publisher &p = *pub;
    CHECK(id_of(p, "on") == kOn && id_of(p, "trial") == kTrial && id_of(p, "show") == kShow && kTrial == 1 &&
          kShow == 2 && p.type(kTrial) == LeafType::boolean && p.type(kShow) == LeafType::boolean);
    Recorder rec;
    p.set_sink(LeafSink{rec_set, &rec});
    Model m;
    Settings cfg;
    Snapshot s = snap();
    s.mode = mode_read("grand_prix_23", 1.0);
    m.update(s, frame(), cfg, 1.0); // a race: the standings tower
    for (int k = 0; k < 100 && p.dirty(); ++k)
        p.publish(m.view(), 1.0, 56);
    CHECK(p.sent_int(kOn) == 1 && p.sent_int(kTrial) == 0 && p.sent_int(kShow) == 1 &&
          p.sent_int(id_of(p, "r00_on")) == 1);
    // then Time Trial: the first three writes of the next frame are on, trial and show (show stays true)
    s.mode = mode_read("time_trial", 2.0);
    m.update(s, frame(), cfg, 2.0);
    rec.paths.clear();
    p.publish(m.view(), 2.0, 2);
    CHECK(rec.paths.size() == 2 && rec.paths[0] == "view_model_data.hud_tt_on" &&
          rec.paths[1] == "view_model_data.hud_tt_trial");
    CHECK(p.sent_int(kOn) == 0 && p.sent_int(kTrial) == 1 && p.sent_int(kShow) == 1);
    for (int k = 0; k < 100 && p.dirty(); ++k)
        p.publish(m.view(), 2.0, 56);
    bool rows_off = true;
    for (int r = 0; r < kRows; ++r)
        rows_off = rows_off && p.sent_int(Publisher::row_leaf(r, kRowOn)) == 0;
    CHECK(rows_off && p.sent_int(id_of(p, "race")) == 0 && p.sent_int(id_of(p, "timed")) == 0 &&
          p.sent_int(kShow) == 1 && p.dirty() == 0);
    // and back to the menus: show false
    s.mode = mode_read("none", 3.0);
    m.update(s, frame(0, 0), cfg, 3.0);
    for (int k = 0; k < 100 && (k == 0 || p.dirty()); ++k) // publish() marks what the new view changes
        p.publish(m.view(), 3.0, 56);
    CHECK(p.sent_int(kOn) == 0 && p.sent_int(kTrial) == 0 && p.sent_int(kShow) == 0 && p.dirty() == 0);
}

static void test_leaves(const char *out_dir)
{
    auto pub = std::make_unique<Publisher>();
    Publisher &p = *pub;
    // names and types
    CHECK(p.count() == kAllLeaves && kLeaves == kGlobals + kCars + kRows * kRowLeaves &&
          kAllLeaves == kLeaves + kRows * kAnimLeaves + 14); // v11: the anim leaves after every older leaf;
                                                             // v13: the header's 14 after them
    std::set<std::string> names;
    bool clean = true;
    for (int i = 0; i < p.count(); ++i) {
        const std::string s = p.path(i);
        names.insert(s);
        clean = clean && s.rfind("view_model_data.hud_tt_", 0) == 0 && s.size() < 40 &&
                s.find_first_of("[] ") == std::string::npos;
    }
    CHECK(clean && int(names.size()) == p.count());
    CHECK(p.type(id_of(p, "on")) == LeafType::boolean && p.type(id_of(p, "mode")) == LeafType::int32 &&
          p.type(id_of(p, "lap")) == LeafType::text && p.type(id_of(p, "r00_vid")) == LeafType::int32 &&
          p.type(id_of(p, "r21_c23")) == LeafType::boolean && p.type(id_of(p, "r05_gap")) == LeafType::text &&
          p.type(id_of(p, "c07_row")) == LeafType::int32 && p.type(id_of(p, "bg")) == LeafType::int32 &&
          p.type(id_of(p, "hs")) == LeafType::int32 && p.type(id_of(p, "r03_tS")) == LeafType::boolean);
    // rows r00..r29, each with a code leaf per vehicle id c00..c29; car leaves c00_row..c29_row
    CHECK(p.type(id_of(p, "r29_c29")) == LeafType::boolean && p.type(id_of(p, "r22_on")) == LeafType::boolean &&
          p.type(id_of(p, "c29_row")) == LeafType::int32 && id_of(p, "r30_on") == -1 && id_of(p, "c30_row") == -1 &&
          id_of(p, "r00_c30") == -1);
    CHECK(p.type(id_of(p, "red")) == LeafType::boolean && p.type(id_of(p, "yel")) == LeafType::boolean &&
          p.type(id_of(p, "ysec")) == LeafType::text && p.type(id_of(p, "ysna")) == LeafType::boolean &&
          id_of(p, "ysna") == kGlobals - 4);
    // laps after ysna (docs/spectator-ui.md 10.4)
    CHECK(p.type(id_of(p, "laps")) == LeafType::boolean && id_of(p, "laps") == kGlobals - 3);
    // flap after clock, the last global (bool)
    CHECK(p.type(id_of(p, "flap")) == LeafType::boolean && id_of(p, "flap") == kGlobals - 1);
    // clock after laps (text), rNN_ko after rNN_det (bool)
    CHECK(p.type(id_of(p, "clock")) == LeafType::text && id_of(p, "clock") == kGlobals - 2 &&
          p.type(id_of(p, "r07_ko")) == LeafType::boolean &&
          id_of(p, "r07_ko") == Publisher::row_leaf(7, kRowDet) + 1 &&
          id_of(p, "r29_ko") == Publisher::row_leaf(29, kRowDet) + 1 && id_of(p, "r30_ko") == -1);
    // rNN_dup, rNN_ddn after rNN_fl, before rNN_c00 (bool)
    CHECK(p.type(id_of(p, "r07_dup")) == LeafType::boolean && p.type(id_of(p, "r07_ddn")) == LeafType::boolean &&
          id_of(p, "r07_dup") == Publisher::row_leaf(7, kRowFl) + 1 &&
          id_of(p, "r07_ddn") == Publisher::row_leaf(7, kRowFl) + 2 &&
          id_of(p, "r07_c00") == Publisher::row_leaf(7, kRowFl) + 3 && id_of(p, "r29_ddn") > 0);
    if (out_dir) { // the leaf list with template type tags (contract §6; tools/tower_re/check_tower_leaves.py)
        const std::string typed = std::string(out_dir) + "/tower_leaves.txt";
        FILE *f = std::fopen(typed.c_str(), "w");
        CHECK(f != nullptr);
        for (int i = 0; f && i < p.count(); ++i) {
            const LeafType t = p.type(i);
            std::fprintf(f, "%s %s\n", p.path(i), t == LeafType::text ? "stri" : t == LeafType::int32 ? "si32" : "bool");
        }
        if (f)
            std::fclose(f);
    }

    Recorder rec;
    p.set_sink(LeafSink{rec_set, &rec});
    Model m;
    Snapshot s = snap();
    Settings cfg;
    m.update(s, frame(), cfg, 1.0);
    // the first frames write everything, within the budget each frame
    int frames = 0, worst = 0;
    while (p.dirty() && frames < 100) {
        const int w = p.publish(m.view(), 1.0, 30);
        worst = std::max(worst, w);
        ++frames;
    }
    CHECK(p.dirty() == 0 && worst <= 30 && frames >= kLeaves / 30);
    CHECK(p.sent_int(id_of(p, "on")) == 1 && p.sent_int(id_of(p, "rows")) == 5 && p.sent_int(id_of(p, "mode")) == 1 &&
          std::strcmp(p.sent_text(id_of(p, "r02_pos")), "12") == 0 && p.sent_int(id_of(p, "r02_me")) == 1 &&
          p.sent_int(id_of(p, "r02_c11")) == 1 && p.sent_int(id_of(p, "r02_c10")) == 0 &&
          p.sent_int(id_of(p, "r02_vid")) == 11 && p.sent_int(id_of(p, "c11_row")) == 2 &&
          p.sent_int(id_of(p, "c00_row")) == -1 && std::strcmp(p.sent_text(id_of(p, "r00_gap")), "+1.0") == 0 &&
          std::strcmp(p.sent_text(id_of(p, "r00_tyre")), "S") == 0 && p.sent_int(id_of(p, "r00_tS")) == 1 &&
          p.sent_int(id_of(p, "r05_on")) == 0 && std::strcmp(p.sent_text(id_of(p, "lap")), "10") == 0 &&
          p.sent_int(id_of(p, "race")) == 1 && p.sent_int(id_of(p, "lapna")) == 0);
    // exactly one car per shown row, none on hidden rows
    int ones = 0;
    for (int r = 0; r < kRows; ++r)
        for (int vid = 0; vid < kCars; ++vid)
            ones += p.sent_int(Publisher::row_leaf(r, kRowCar + vid));
    CHECK(ones == 5);
    // steady state: nothing changes, only the round-robin refresh writes (a few per frame)
    rec.writes = 0;
    for (int i = 0; i < 10; ++i)
        p.publish(m.view(), 1.0, 56);
    CHECK(rec.writes == 10 * kRefreshPerFrame);
    // every leaf is rewritten within one refresh cycle
    rec.paths.clear();
    for (int i = 0; i < kLeaves / kRefreshPerFrame + 1; ++i)
        p.publish(m.view(), 1.0, 56);
    std::set<std::string> again(rec.paths.begin(), rec.paths.end());
    CHECK(int(again.size()) == kLeaves);
    // a yellow in sectors 1 and 3: hs, yel and ysec change, nothing else (plus the refresh)
    {
        Snapshot fs = s;
        fs.flags.seq = 1;
        fs.flags.t = 1.0;
        fs.flags.zones_ok = true;
        fs.flags.zones = 20;
        fs.flags.yellow = 2;
        fs.flags.ysec = 0b101;
        fs.flags.red = 0;
        Model fm;
        fm.update(s, frame(), cfg, 1.0);
        fm.update(fs, frame(), cfg, 1.0);
        rec.writes = 0;
        rec.paths.clear();
        p.publish(fm.view(), 1.0, 56);
        CHECK(rec.writes == 3 + kRefreshPerFrame && p.sent_int(id_of(p, "hs")) == 5 && p.sent_int(id_of(p, "yel")) == 1 &&
              std::strcmp(p.sent_text(id_of(p, "ysec")), "1 3") == 0 && p.sent_int(id_of(p, "ysna")) == 0 &&
              p.sent_int(id_of(p, "red")) == 0);
        CHECK(rec.paths.size() >= 3 && rec.paths[0] == "view_model_data.hud_tt_hs" &&
              rec.paths[1] == "view_model_data.hud_tt_yel" && rec.paths[2] == "view_model_data.hud_tt_ysec");
        // back to the plain view: the same leaves again
        rec.writes = 0;
        p.publish(m.view(), 1.0, 56);
        CHECK(rec.writes == 3 + kRefreshPerFrame && p.sent_int(id_of(p, "hs")) == 0 && p.sent_text(id_of(p, "ysec"))[0] == 0);
    }
    // a pass below the player (rows 3 and 4: cars 12 and 13; the window stays): only the changed leaves, one frame
    std::swap(s.cls.order[12], s.cls.order[13]);
    s.cls.pos[12] = 14;
    s.cls.pos[13] = 13;
    s.cls.seq = 2;
    m.update(s, frame(), cfg, 1.1);
    rec.writes = 0;
    p.publish(m.view(), 1.1, 56);
    CHECK(p.dirty() == 0 && rec.writes <= 56 && rec.writes >= 8);
    CHECK(p.sent_int(id_of(p, "r03_c13")) == 1 && p.sent_int(id_of(p, "r03_c12")) == 0 &&
          p.sent_int(id_of(p, "r04_c12")) == 1 && p.sent_int(id_of(p, "r04_c13")) == 0 &&
          p.sent_int(id_of(p, "r03_vid")) == 13 && p.sent_int(id_of(p, "r03_up")) == 1 &&
          p.sent_int(id_of(p, "r04_dn")) == 1 && p.sent_int(id_of(p, "r02_me")) == 1 &&
          std::strcmp(p.sent_text(id_of(p, "r03_pos")), "13") == 0 && p.sent_int(id_of(p, "c13_row")) == 3 &&
          p.sent_int(id_of(p, "c12_row")) == 4);
    // the player passes: the window follows (the player stays in the middle row), every row's content changes
    std::swap(s.cls.order[10], s.cls.order[11]);
    s.cls.pos[10] = 12;
    s.cls.pos[11] = 11;
    s.cls.seq = 3;
    m.update(s, frame(), cfg, 1.15);
    p.publish(m.view(), 1.15, 56);
    CHECK(p.dirty() == 0 && m.view().start == 8 && p.sent_int(id_of(p, "r02_c11")) == 1 &&
          p.sent_int(id_of(p, "r02_me")) == 1 && p.sent_int(id_of(p, "r02_up")) == 1 &&
          std::strcmp(p.sent_text(id_of(p, "r02_pos")), "11") == 0 && p.sent_int(id_of(p, "r03_c10")) == 1 &&
          p.sent_int(id_of(p, "r03_dn")) == 1 && p.sent_int(id_of(p, "r00_c08")) == 1 && p.sent_int(id_of(p, "c09_row")) == 1);
    std::swap(s.cls.order[10], s.cls.order[11]);
    s.cls.pos[10] = 11;
    s.cls.pos[11] = 12;
    s.cls.seq = 4;
    m.update(s, frame(), cfg, 1.18);
    for (int i = 0; i < 3; ++i)
        p.publish(m.view(), 1.18, 56);
    CHECK(p.dirty() == 0 && m.view().start == 9);
    // a small budget: whole rows only (a row is never half old, half new); the second row waits a frame
    std::swap(s.cls.order[12], s.cls.order[13]);
    s.cls.pos[12] = 13;
    s.cls.pos[13] = 14;
    s.cls.seq = 5;
    m.update(s, frame(), cfg, 1.2);
    const int w1 = p.publish(m.view(), 1.2, 6);
    CHECK(w1 <= 6);
    CHECK(p.sent_int(id_of(p, "r03_c12")) == 1 && p.sent_int(id_of(p, "r03_c13")) == 0 &&
          p.sent_int(id_of(p, "r03_vid")) == 12); // row 3: complete
    CHECK(p.sent_int(id_of(p, "r04_c12")) == 1 && p.sent_int(id_of(p, "r04_c13")) == 0 &&
          p.sent_int(id_of(p, "r04_vid")) == 12); // row 4: entirely the old car
    p.publish(m.view(), 1.2, 6);
    CHECK(p.dirty() == 0 && p.sent_int(id_of(p, "r04_c13")) == 1 && p.sent_int(id_of(p, "r04_c12")) == 0 &&
          p.sent_int(id_of(p, "r04_vid")) == 13);
    // a budget of 0 (the halo used the frame's writes): nothing is written
    rec.writes = 0;
    CHECK(p.publish(m.view(), 1.2, 0) == 0 && rec.writes == 0);
    // a failed write stays dirty and goes out later
    cfg.rows = 6;
    m.update(s, frame(), cfg, 1.3);
    rec.fail = 1000;
    p.publish(m.view(), 1.3, 56);
    CHECK(p.dirty() > 0 && p.sent_int(id_of(p, "rows")) == 5);
    rec.fail = 0;
    for (int i = 0; i < 5; ++i)
        p.publish(m.view(), 1.3, 56);
    CHECK(p.dirty() == 0 && p.sent_int(id_of(p, "rows")) == 6 && p.sent_int(id_of(p, "r05_on")) == 1);
    // unavailable: text "" and the flag
    s.tyre[11].state = 3;
    s.timing.car[11].ahead_valid = false;
    s.timing.car[11].have = false;
    s.cls.seq = 4;
    m.update(s, frame(), cfg, 1.4);
    for (int i = 0; i < 5; ++i)
        p.publish(m.view(), 1.4, 56);
    const int r11 = m.view().car_row[11];
    char key[16];
    std::snprintf(key, sizeof key, "r%02d_tna", r11);
    CHECK(p.sent_int(id_of(p, key)) == 1);
    std::snprintf(key, sizeof key, "r%02d_tyre", r11);
    CHECK(std::strcmp(p.sent_text(id_of(p, key)), "") == 0);
    std::snprintf(key, sizeof key, "r%02d_gna", r11);
    CHECK(p.sent_int(id_of(p, key)) == 1);
    std::snprintf(key, sizeof key, "r%02d_gap", r11);
    CHECK(std::strcmp(p.sent_text(id_of(p, key)), "") == 0);
    // the tower off: every row off and empty, every car hidden
    cfg.enabled = false;
    m.update(s, frame(), cfg, 1.5);
    for (int i = 0; i < 40; ++i)
        p.publish(m.view(), 1.5, 56);
    bool off = p.sent_int(id_of(p, "on")) == 0 && p.sent_int(id_of(p, "rows")) == 0;
    for (int r = 0; r < kRows; ++r) {
        off = off && p.sent_int(Publisher::row_leaf(r, kRowOn)) == 0 && p.sent_text(Publisher::row_leaf(r, kRowGap))[0] == 0 &&
              p.sent_int(Publisher::row_leaf(r, kRowVid)) == -1;
        for (int vid = 0; vid < kCars; ++vid)
            off = off && p.sent_int(Publisher::row_leaf(r, kRowCar + vid)) == 0;
    }
    for (int vid = 0; vid < kCars; ++vid)
        off = off && p.sent_int(kCarRowBase + vid) == -1;
    CHECK(off && p.sent_int(id_of(p, "dbg")) == 0);
}

// rNN_badge / rNN_bdg: the pill's own string, written whatever teamcol says; "" and false when unknown or hidden;
// a row's badge goes out in the same frame as its car.
// 1806 leaves (+ rNN_dup, rNN_ddn, flap; 1745: 30 rows and cars).
// 1159 leaves (+ rNN_pb, rNN_ob, rNN_fl; 1093: + clock, rNN_ko; 1070: + rNN_det,
// laps; 1047 before).
static void test_badge_leaves()
{
    auto pub = std::make_unique<Publisher>();
    Publisher &p = *pub;
    CHECK(kLeaves == 1806 && p.type(id_of(p, "r00_badge")) == LeafType::text &&
          p.type(id_of(p, "r29_bdg")) == LeafType::boolean && id_of(p, "r30_badge") == -1 &&
          id_of(p, "r00_bdg") == Publisher::row_leaf(0, kRowBdg) && id_of(p, "r00_c00") == Publisher::row_leaf(0, kRowCar));
    Recorder rec;
    p.set_sink(LeafSink{rec_set, &rec});
    Snapshot s = snap();
    set_badges(s);
    Model m;
    Settings cfg;
    cfg.team_colours = false;
    m.update(s, frame(), cfg, 1.0);
    for (int i = 0; i < 80 && p.dirty(); ++i)
        p.publish(m.view(), 1.0, 56);
    const std::string mcl = std::string(kHudBadge) + "mclaren_26", fer = std::string(kHudBadge) + "ferrari_26";
    CHECK(p.dirty() == 0 && mcl == p.sent_text(id_of(p, "r02_badge")) && p.sent_int(id_of(p, "r02_bdg")) == 1 &&
          fer == p.sent_text(id_of(p, "r03_badge")) && p.sent_int(id_of(p, "r04_bdg")) == 1 &&
          p.sent_int(id_of(p, "teamcol")) == 0);
    CHECK(p.sent_text(id_of(p, "r00_badge"))[0] == 0 && p.sent_int(id_of(p, "r00_bdg")) == 0 &&
          p.sent_text(id_of(p, "r01_badge"))[0] == 0 && p.sent_int(id_of(p, "r01_bdg")) == 0);
    CHECK(p.sent_text(id_of(p, "r05_badge"))[0] == 0 && p.sent_int(id_of(p, "r05_bdg")) == 0); // hidden row
    // steady state: the badges add no writes beyond the refresh
    rec.writes = 0;
    for (int i = 0; i < 5; ++i)
        p.publish(m.view(), 1.0, 56);
    CHECK(rec.writes == 5 * kRefreshPerFrame);
    // 12 passes 11: every row's badge matches its car after every frame, whatever the budget
    const auto consistent = [&]() {
        for (int r = 0; r < 5; ++r) {
            const int vid = p.sent_int(Publisher::row_leaf(r, kRowVid));
            const std::string want = vid == 11 ? mcl : (vid == 12 || vid == 13) ? fer : std::string();
            if (want != p.sent_text(Publisher::row_leaf(r, kRowBadge)) ||
                p.sent_int(Publisher::row_leaf(r, kRowBdg)) != int(!want.empty()))
                return false;
        }
        return true;
    };
    std::swap(s.cls.order[11], s.cls.order[12]);
    s.cls.pos[11] = 13;
    s.cls.pos[12] = 12;
    s.cls.seq = 2;
    m.update(s, frame(), cfg, 1.1);
    bool ok = consistent();
    for (int i = 0; i < 12; ++i) {
        p.publish(m.view(), 1.1, 20);
        ok = ok && consistent();
    }
    CHECK(ok && p.dirty() == 0 && fer == p.sent_text(id_of(p, "r01_badge")) && mcl == p.sent_text(id_of(p, "r02_badge")));
    // the reader loses the key (a new car set not read yet): "" and false
    s.badges = Badges{};
    m.update(s, frame(), cfg, 1.2);
    for (int i = 0; i < 5; ++i)
        p.publish(m.view(), 1.2, 56);
    CHECK(p.sent_text(id_of(p, "r02_badge"))[0] == 0 && p.sent_int(id_of(p, "r02_bdg")) == 0);
}

// The model and the reader together on the fake game: what a race frame shows.
static void test_end_to_end()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    Model m;
    Settings cfg;
    cfg.mode = Mode::full;
    set_pit(f, 4, 3);
    set_gap(f, N - 1 - 4, 4, 0, false, 0, false); // the car in the pit lane: the game cleared both flags
    set_status(f, 21, 4);                         // DNF
    set_tyre(f, 21, 4);
    add_penalty(f, 3, 1, 9);
    set_sg(f, 3, 1);
    double t = 0;
    for (int i = 0; i < 120; ++i, t += 1 / 120.0) {
        r.update(t, f.frame);
        m.update(r.snapshot(), f.frame, cfg, t);
    }
    const View &v = m.view();
    CHECK(v.on && v.rows == N && v.row[0].p1 && std::strcmp(v.row[0].gap, "Interval") == 0);
    CHECK(std::strcmp(v.row[4].gap, "PIT") == 0 && v.row[4].pit);
    CHECK(std::strcmp(v.row[5].gap, "+1.0") == 0 && v.row[5].tyre == 'M');
    CHECK(v.row[3].pen && !v.row[2].pen);
    CHECK(v.row[21].out && std::strcmp(v.row[21].gap, "Out") == 0 && v.row[21].tyre == 0);
    CHECK(v.row[11].me && std::strcmp(v.lap, "10") == 0);
    // team badges from the fake game's chain (the out car keeps its own)
    CHECK(v.row[0].bdg && std::strcmp(v.row[0].badge, "mclaren_26") == 0 && v.row[21].bdg &&
          std::strcmp(v.row[21].badge, "gm_cadillac_26") == 0 && std::strstr(v.dbg, " bdg22") != nullptr);
    // car 8 overtakes car 7 in the game's classification
    int order[N];
    for (int i = 0; i < N; ++i)
        order[i] = i;
    std::swap(order[7], order[8]);
    classify(f, order, N);
    for (int i = 0; i < 24; ++i, t += 1 / 120.0) {
        r.update(t, f.frame);
        m.update(r.snapshot(), f.frame, cfg, t);
    }
    CHECK(v.row[7].vid == 8 && v.row[7].up && v.row[8].vid == 7 && v.row[8].dn && v.row[7].pos == 8);
}

// The in-game case (2026-11-09 16:39 log): the game's SC byte reads 1 during a red flag. Reader, model and leaves
// must show the red flag, not the safety car; a yellow in sector 1 before it shows YELLOW with "1".
static void test_end_to_end_flags()
{
    FakeTower f = make_tower();
    Reader r(mem(), fake_keys(f));
    Model m;
    Settings cfg;
    auto pub = std::make_unique<Publisher>();
    Publisher &p = *pub;
    Recorder rec;
    p.set_sink(LeafSink{rec_set, &rec});
    double t = 0;
    auto step = [&](double seconds) {
        for (double end = t + seconds; t < end; t += 1 / 120.0) {
            r.update(t, f.frame);
            m.update(r.snapshot(), f.frame, cfg, t);
            p.publish(m.view(), t, kFrameBudget);
        }
    };
    step(1.0);
    CHECK(m.view().hs == 0 && p.sent_int(id_of(p, "hs")) == 0 && !(p.sent_int(id_of(p, "red")) != 0) && !(p.sent_int(id_of(p, "yel")) != 0));
    set_zone(f, 2, 3); // 600 m: sector 1
    step(0.6);
    CHECK(m.view().hs == 5 && p.sent_int(id_of(p, "hs")) == 5 && (p.sent_int(id_of(p, "yel")) != 0) &&
          std::strcmp(p.sent_text(id_of(p, "ysec")), "1") == 0 && !(p.sent_int(id_of(p, "ysna")) != 0));
    set_zone(f, 2, 0);
    step(0.6);
    CHECK(m.view().hs == 0 && !(p.sent_int(id_of(p, "yel")) != 0) && p.sent_text(id_of(p, "ysec"))[0] == 0);
    set_sc(f, 1, 2); // the SC byte as logged in game during the red flag (sc 1, extra 2)
    step(0.6);
    CHECK(m.view().hs == 1 && p.sent_int(id_of(p, "hs")) == 1 && (p.sent_int(id_of(p, "sc")) != 0));
    set_red(f, 1);
    step(0.6);
    CHECK(m.view().hs == 3 && p.sent_int(id_of(p, "hs")) == 3 && (p.sent_int(id_of(p, "red")) != 0) && !(p.sent_int(id_of(p, "sc")) != 0) &&
          !(p.sent_int(id_of(p, "vsc")) != 0));
    set_red(f, 2);
    step(0.6);
    CHECK(p.sent_int(id_of(p, "hs")) == 3 && (p.sent_int(id_of(p, "red")) != 0) && !(p.sent_int(id_of(p, "sc")) != 0));
    set_red(f, 0);
    step(0.6);
    CHECK(p.sent_int(id_of(p, "hs")) == 1 && (p.sent_int(id_of(p, "sc")) != 0) && !(p.sent_int(id_of(p, "red")) != 0));
}

// ---------------------------------------------------------------- bench

static int ok_set(void *, const char *, LeafType, const void *) { return 0; }

// Per-frame cost of the tower with a 22-car field at 120 fps: reader (ReadProcessMemory, as in game), model and
// leaf publisher (a sink that accepts every write; the core's own queue work is not included).
// The validation log's tower file, written by the real writer (diag_log.cpp) from the reader and the model on the
// fake game, 10 records a second as in the DLL: every line has the header's 66 columns. Copied to
// <out>/tower_sample.csv for tools/ingame/analyze_diag.py, whose "Tower: shown values" check must pass on it
// (the C++ writer and the Python parser agree on the format).
// A stand-in for the core's storage table: appends under <out>/nick.f1-2026-halo/, and refuses any path that is not
// a plain relative one, as the core does.
static std::string g_store_root;
static int g_store_bad = 0;
static int fake_available(void) { return 1; }
static int fake_append(const char *path, const void *data, size_t len)
{
    std::string rel = path ? path : "";
    if (rel.empty() || rel[0] == '/' || rel[0] == '\\' || rel.find(':') != std::string::npos ||
        rel.find("..") != std::string::npos) {
        ++g_store_bad;
        return SWOFTY_ASSET_INVALID;
    }
    std::string full = g_store_root;
    for (size_t a = 0, b; a <= rel.size(); a = b + 1) {
        b = rel.find('/', a);
        if (b == std::string::npos)
            b = rel.size();
        CreateDirectoryA(full.c_str(), nullptr);
        full += "/" + rel.substr(a, b - a);
    }
    FILE *f = std::fopen(full.c_str(), "ab");
    if (!f)
        return SWOFTY_ASSET_INVALID;
    bool ok = std::fwrite(data, 1, len, f) == len;
    std::fclose(f);
    return ok ? SWOFTY_ASSET_OK : SWOFTY_ASSET_INVALID;
}

static void test_log_writer(const char *out_dir)
{
    if (!out_dir)
        return;
    CHECK(!halo::diag::path_utf8()[0]);
    static SwoftyStorage store{};
    store.available = fake_available;
    store.append = fake_append;
    static SwoftyApi fake{};
    fake.version = SWOFTY_API_VERSION;
    fake.storage = &store;
    g_store_root = std::string(out_dir) + "/nick.f1-2026-halo";
    swofty::api = &fake;
    CHECK(halo::diag::start());
    CHECK(std::string(halo::diag::path_utf8()).rfind("diag/halo_", 0) == 0); // relative: inside the addon's folder
    FakeTower f = make_tower();
    set_pit(f, 4, 3);
    set_gap(f, N - 1 - 4, 4, 0, false, 0, false); // in the pit lane: the game cleared both flags
    set_status(f, 21, 7);                         // retired
    add_penalty(f, 3, 5, 7);
    add_penalty(f, 3, 4, 7, 5);
    set_tpen(f, 3, 5.0);
    set_sg(f, 9, 1);
    Reader r(mem(), fake_keys(f));
    Model m;
    Settings cfg;
    cfg.gap_mode = GapMode::autoswitch;
    cfg.auto_period = 5;
    cfg.debug = true;
    auto pub = std::make_unique<Publisher>();
    pub->set_sink(LeafSink{ok_set, nullptr});
    static halo::diag::TowerRec rec;
    static Anim an;
    double last = -1, last_slow = -1;
    uint32_t last_seq = 0;
    int records = 0, order[N];
    for (int i = 0; i < N; ++i)
        order[i] = i;
    f.frame.player_lap_m = 2000.f; // sector 2
    for (int i = 0; i < 1440; ++i) { // 12 s at 120 fps
        const double t = i / 120.0;
        if (i == 600) { // car 8 passes car 7
            std::swap(order[7], order[8]);
            classify(f, order, N);
        }
        if (i == 240)
            set_zone(f, 6, 3); // a yellow in sector 2 for 2 s
        if (i == 480)
            set_zone(f, 6, 0);
        if (i == 960) { // a red flag with the SC byte at 1 (as in game), for 2 s
            set_sc(f, 1, 2);
            set_red(f, 1);
        }
        if (i == 1200) {
            set_red(f, 0);
            set_sc(f, 0);
        }
        if (i == 900)
            set_tyre(f, 6, 3, true); // a stale cache for a while
        r.update(t, f.frame);
        m.update(r.snapshot(), f.frame, cfg, t);
        an.update(m.view(), f.frame, m, t);
        const int w = pub->publish(m.view(), t, 46, &an);
        if (t - last < 0.1)
            continue;
        last = t;
        rec.t = 100.0 + t;
        rec.frame = uint64_t(i);
        rec.generation = f.frame.generation;
        rec.session = f.frame.session;
        rec.session_ok = f.frame.session_ok;
        rec.player = f.frame.player;
        rec.snap = r.snapshot();
        rec.view = m.view();
        rec.slow = t - last_slow >= 1.0;
        if (rec.slow)
            last_slow = t;
        rec.pen_changed = rec.snap.pen.log_seq != last_seq;
        last_seq = rec.snap.pen.log_seq;
        rec.read_us = 3.0f;
        rec.model_us = 1.0f;
        rec.publish_us = 2.0f;
        rec.writes = w;
        rec.halo_writes = 10;
        rec.copies = r.copies();
        rec.jobs = r.ran();
        rec.anim = an.stats();
        an.clear_snap_bits();
        // the apk column, from the publisher's started codes and the anim layer's row snaps; one record also
        // gets two fixed events, to pin the format
        rec.started = pub->events();
        rec.rowsnaps = an.events();
        rec.hdpub = pub->head_events(); // the hdk column
        rec.hdanim = an.head_events();
        pub->clear_events();
        an.clear_events();
        pub->clear_head_events();
        an.clear_head_events();
        if (records == 3) {
            rec.started.add(100.5, 5, uint16_t(kAnU1 | kAnEu));
            rec.rowsnaps.add(100.25, 6, uint16_t(kEvSnap | kRowSnapBusy));
            // a card's entry (its state and its code in frame 4021), a busy snap two frames later
            rec.hdpub.add(HeadEvent{100.5f, 4021, 'c', uint8_t(kCardSc), 0, 0, true});
            rec.hdpub.add(HeadEvent{100.5f, 4021, 'k', 0, 1, 0, true});
            rec.hdanim.add(HeadEvent{100.53125f, 4023, '!', uint8_t(kCardNone), 0, uint8_t(kHwBusy), false});
            rec.hdpub.add(HeadEvent{100.53125f, 4023, 'k', 0, 6, 0, true});
        }
        halo::diag::record_tower(rec);
        ++records;
    }
    Sleep(1500); // the writer drains every 0.5 s
    CHECK(g_store_bad == 0);
    WIN32_FIND_DATAA fd;
    const std::string dir = std::string(out_dir) + "/nick.f1-2026-halo/diag/";
    HANDLE h = FindFirstFileA((dir + "tower_*.csv").c_str(), &fd);
    CHECK(h != INVALID_HANDLE_VALUE);
    if (h == INVALID_HANDLE_VALUE)
        return;
    std::string newest = fd.cFileName;
    FILETIME best = fd.ftLastWriteTime;
    while (FindNextFileA(h, &fd))
        if (CompareFileTime(&fd.ftLastWriteTime, &best) > 0) {
            best = fd.ftLastWriteTime;
            newest = fd.cFileName;
        }
    FindClose(h);
    FILE *in = std::fopen((dir + newest).c_str(), "rb");
    CHECK(in != nullptr);
    if (!in)
        return;
    std::string all;
    char buf[65536];
    for (size_t k; (k = std::fread(buf, 1, sizeof buf, in)) > 0;)
        all.append(buf, k);
    std::fclose(in);
    std::vector<std::string> lines;
    for (size_t a = 0, b; a < all.size(); a = b + 1) {
        b = all.find('\n', a);
        if (b == std::string::npos)
            b = all.size();
        if (b > a)
            lines.push_back(all.substr(a, b - a));
    }
    const auto columns = [](const std::string &s) { return 1 + int(std::count(s.begin(), s.end(), ',')); };
    CHECK(!lines.empty() && lines[0].rfind("t,frame,generation,session,on,", 0) == 0 && columns(lines[0]) == 82 &&
          lines[0].find(",sc,sc_extra,zones,red,psec,fseq,fshown,ysec,sectors,tyre,") != std::string::npos &&
          lines[0].find(",dropped,set,bdg,rbdg,bdgkeys,bdgvec,gmode,trial,blap,ko,fx,fl,lbest,lfc,mtb,grid,stops,bst,anim,apk,hdk") !=
              std::string::npos);
    CHECK(int(lines.size()) == records + 1);
    bool same = true;
    int slow = 0, pen = 0, yellow = 0, red = 0, sectors = 0, found = 0, bdg = 0, keys = 0, partial = 0, vec = 0;
    // lbest, lfc (no lap times key), mtb; grid (the fake entries hold no grid field: every car on slot 1,
    // which the model takes for no grid), stops (0 for every car), bst (Detail Best not on: none)
    const std::string tail = ",22,grand_prix_23,0,-,-,-,-,-,-:x,-,1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1,"
                             "0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0,-";
    int anim_ok = 0, apk_ok = 0, apk_slides = 0, apk_fixed = 0, hdk_ok = 0, hdk_fixed = 0;
    for (size_t k = 1; k < lines.size(); ++k) {
        same = same && columns(lines[k]) == 82;
        // hdk last: '-' or "what@t#frame" items (frames in order)
        const std::string hdk = lines[k].substr(lines[k].rfind(',') + 1);
        bool hok = hdk == "-";
        if (!hok) {
            hok = true;
            unsigned last_f = 0;
            for (size_t a = 0, b; hok && a < hdk.size(); a = b + 1) {
                b = hdk.find(' ', a);
                if (b == std::string::npos)
                    b = hdk.size();
                const std::string item = hdk.substr(a, b - a);
                const size_t at = item.find('@'), hash = item.find('#');
                double et = -1;
                unsigned ef = 0;
                hok = at != std::string::npos && hash != std::string::npos && at < hash &&
                      std::sscanf(item.c_str() + at + 1, "%lf", &et) == 1 &&
                      std::sscanf(item.c_str() + hash + 1, "%u", &ef) == 1 && ef >= last_f;
                last_f = ef;
            }
        }
        hdk_ok += hok;
        hdk_fixed += hdk == "card:sc@100.500#4021 in2@100.500#4021 !b:none@100.531#4023 rs@100.531#4023";
        lines[k].erase(lines[k].rfind(','));
        // apk last: '-' or "RR:codes@t" / "RR:!why@t" items in time order
        const std::string apk = lines[k].substr(lines[k].rfind(',') + 1);
        bool ok = apk == "-";
        if (!ok) {
            ok = true;
            double last_t = -1;
            for (size_t a = 0, b; ok && a < apk.size(); a = b + 1) {
                b = apk.find(' ', a);
                if (b == std::string::npos)
                    b = apk.size();
                const std::string item = apk.substr(a, b - a);
                const size_t at = item.find('@');
                double et = -1;
                ok = item.size() > 4 && item[2] == ':' && at != std::string::npos &&
                     std::sscanf(item.c_str() + at + 1, "%lf", &et) == 1 && et >= last_t;
                last_t = et;
                apk_slides += item.find(":u1+eu@") != std::string::npos || item.find(":d1+ed@") != std::string::npos;
            }
        }
        apk_ok += ok;
        apk_fixed += apk == "06:!busy@100.250 05:u1+eu@100.500";
        lines[k].erase(lines[k].rfind(','));
        // the anim column: "slides entries nf ff rests moving snaps" (the setting on in this test)
        const std::string an = lines[k].substr(lines[k].rfind(',') + 1);
        unsigned n6[6] = {};
        char snaps[16] = {};
        anim_ok += std::sscanf(an.c_str(), "%u %u %u %u %u %u %15s", &n6[0], &n6[1], &n6[2], &n6[3], &n6[4], &n6[5],
                               snaps) == 7 &&
                   std::strspn(snaps, "-ofstjpwb") == std::strlen(snaps);
        lines[k].erase(lines[k].rfind(','));
        // bdgvec (the fake game's entrant vector holds the 22 cars), then gmode (the fake game's mode label),
        // trial, blap (a race: no lap time read) and ko (a race: none), the last columns
        vec += lines[k].size() > tail.size() && lines[k].compare(lines[k].size() - tail.size(), tail.size(), tail) == 0;
        // badges: the cars' letters by vehicle id, then the rows' letters, then the table on the 1 Hz records
        bdg += lines[k].find(",aabbccddeeffgghhiijjkk,") != std::string::npos;
        keys += lines[k].find(",a=mclaren_26 b=mercedes_26 c=red_bull_26 d=ferrari_26 e=williams_26 f=alphatauri_26 "
                              "g=aston_martin_26 h=haas_26 i=alfa_romeo_26 j=alpine_26 k=gm_cadillac_26") !=
                std::string::npos;
        partial += lines[k].find(",aabbcc................,") != std::string::npos; // the first run: six cars
        slow += lines[k].find(",1.13.13.16.") != std::string::npos; // car 0's tyre token: soft, set 13
        pen += lines[k].find("3:5:7:0:1:255;3:4:7:5:1:255") != std::string::npos;
        // zone 6 yellow in sector 2 (B), red byte 0, the player in sector 2, the view: yellow, "2"
        yellow += lines[k].find(",0,0,000000B0000000000000,0,2,") != std::string::npos &&
                  lines[k].find(",y,2,") != std::string::npos;
        // the SC byte 1 (extra 2) under the red flag: the view shows the red flag only
        red += lines[k].find(",1,2,00000000000000000000,1,2,") != std::string::npos && lines[k].find(",r,-,") != std::string::npos;
        sectors += lines[k].find(",1500.0/3200.0/6000.0@6000.0,") != std::string::npos;
        found += lines[k].find(",RTPSZ1YGMF,") != std::string::npos;
    }
    CHECK(same && slow >= 10 && pen == 1);
    CHECK(yellow >= 15 && yellow <= 25 && red >= 15 && red <= 25 && sectors >= 10 && found >= int(lines.size()) - 3);
    CHECK(bdg >= int(lines.size()) - 6 && keys >= 12 && partial <= 1 && vec >= int(lines.size()) - 3);
    // (the fake game's pass at i == 600 shows no slide in this rig's view: apk_slides is not checked)
    CHECK(anim_ok == int(lines.size()) - 1 && apk_ok == int(lines.size()) - 1 && apk_fixed == 1 && apk_slides >= 0);
    CHECK(hdk_ok == int(lines.size()) - 1 && hdk_fixed == 1);
    FILE *out = std::fopen((std::string(out_dir) + "/tower_sample.csv").c_str(), "wb");
    CHECK(out != nullptr);
    if (out) {
        std::fwrite(all.data(), 1, all.size(), out);
        std::fclose(out);
    }
}

static void bench(bool spect = false, int cars = N, bool full = false) // full: every row (the anim worst case)
{
    FakeTower f = make_tower(cars);
    for (int i = 0; i < 12; ++i)
        add_penalty(f, uint8_t(i), 5, 7);
    // spectating with the menu's Gap 3 (each car's lap time: the longer results copy) and Detail 5
    f.frame.spect = spect;
    f.frame.spect_gap = 3;
    f.frame.spect_detail = 5;
    // the lap tables (40 laps driven per car; two cars end a lap at every pass below)
    FakeLaps L = make_laps(f, cars);
    for (int v = 0; v < cars; ++v) {
        for (int lap = 0; lap < 40; ++lap)
            lap_put(L.rec[v], lap, 90.0f + 0.01f * float((v * 7 + lap * 13) % 50));
        put<uint8_t>(L.rec[v], 0x38, 39);
    }
    put<uint8_t>(L.LT, 0xb8, 3);
    Reader r(mem(), laps_keys(f));
    Model m;
    auto an = std::make_unique<Anim>();
    auto pub = std::make_unique<Publisher>();
    pub->set_sink(LeafSink{ok_set, nullptr});
    Settings cfg;
    if (full)
        cfg.mode = Mode::full;
    LARGE_INTEGER fq;
    QueryPerformanceFrequency(&fq);
    const int n = 6000;
    std::vector<double> rd, md, pb, tot;
    int copies = 0, max_copies = 0, writes = 0;
    int order[32];
    for (int i = 0; i < cars; ++i)
        order[i] = i;
    for (int i = 0; i < n; ++i) {
        const double t = i / 120.0;
        if (i % 600 == 300) { // a pass every 5 s: two rows change
            std::swap(order[9], order[10]);
            classify(f, order, cars);
            for (int v : {order[9], order[10]}) { // and two cars end a lap
                const uint8_t lap = uint8_t(std::min(198, 40 + i / 600));
                lap_put(L.rec[v], lap, 89.0f);
                put<uint8_t>(L.rec[v], 0x38, lap);
            }
        }
        LARGE_INTEGER q[4];
        QueryPerformanceCounter(&q[0]);
        r.update(t, f.frame);
        QueryPerformanceCounter(&q[1]);
        m.update(r.snapshot(), f.frame, cfg, t);
        an->update(m.view(), f.frame, m, t); // the motion layer, timed with the model as in the DLL
        QueryPerformanceCounter(&q[2]);
        writes += pub->publish(m.view(), t, 46, an.get());
        QueryPerformanceCounter(&q[3]);
        const auto us = [&](int a, int b) { return double(q[b].QuadPart - q[a].QuadPart) / double(fq.QuadPart) * 1e6; };
        rd.push_back(us(0, 1));
        md.push_back(us(1, 2));
        pb.push_back(us(2, 3));
        tot.push_back(us(0, 3));
        copies += r.copies();
        max_copies = std::max(max_copies, r.copies());
    }
    CHECK(m.view().on && m.view().rows == (full ? std::min(cars, kRows) : 5));
    auto stat = [](std::vector<double> v, double &mean, double &p50, double &p99, double &worst) {
        mean = 0;
        for (double x : v)
            mean += x;
        mean /= double(v.size());
        std::sort(v.begin(), v.end());
        p50 = v[v.size() / 2];
        p99 = v[std::min(v.size() - 1, size_t(0.99 * double(v.size())))];
        worst = v.back();
    };
    double a[4], b[4], c[4], d[4];
    stat(rd, a[0], a[1], a[2], a[3]);
    stat(md, b[0], b[1], b[2], b[3]);
    stat(pb, c[0], c[1], c[2], c[3]);
    stat(tot, d[0], d[1], d[2], d[3]);
    std::printf("tower bench%s%s (%d cars, 120 fps, %d frames): reader %.1f us mean / %.1f p50 / %.1f p99 / %.1f worst "
                "(%.1f copies per frame, %d worst); model %.1f us mean / %.1f worst; leaves %.1f us mean / %.1f worst "
                "(%.2f writes per frame); total %.1f us mean / %.1f p99 / %.1f worst\n",
                spect ? " spectating, Gap 3, Detail 5" : "", full ? " full" : "", cars, n, a[0], a[1], a[2], a[3], double(copies) / n, max_copies, b[0],
                b[3], c[0], c[3], double(writes) / n, d[0],
                d[2], d[3]);
}

// the lap time flash. Practice / Qualifying best laps: a car's new best lap shows in its gap cell for 2 s,
// purple below every other car's time, else green (a tie too); none on the first read, a new session type, a time
// that rises or goes, a fill (4 or more cars in one read), a race or the spectator menu's Gap.
static void test_flash()
{
    Model m;
    Snapshot s = snap();
    Settings cfg;
    cfg.mode = Mode::full;
    const View &v = m.view();
    for (int i = 0; i < N; ++i) {
        s.cls.lap_ok[i] = true;
        s.cls.lap_s[i] = 80.0f + 0.125f * float(i);
    }
    const auto flashes = [&v]() {
        int n = 0;
        for (int r = 0; r < v.rows; ++r)
            n += int(v.row[r].pb) + int(v.row[r].ob);
        return n;
    };
    m.update(s, frame(11, 5), cfg, 1.0);
    CHECK(v.on && v.best && v.rows == 22 && flashes() == 0);
    // car 5 improves, still behind car 4: green, its new time for 2 s, then the gap to P1
    s.cls.lap_s[5] = 80.5625f;
    m.update(s, frame(11, 5), cfg, 2.0);
    CHECK(v.row[5].pb && !v.row[5].ob && std::strcmp(v.row[5].gap, "1:20.562") == 0 && !v.row[5].gna &&
          v.row[5].shown == kShownTime && v.fx[5] == 1 && flashes() == 1);
    m.update(s, frame(11, 5), cfg, 3.99);
    CHECK(v.row[5].pb && flashes() == 1);
    m.update(s, frame(11, 5), cfg, 4.0);
    CHECK(!v.row[5].pb && v.fx[5] == 0 && flashes() == 0 && std::strcmp(v.row[5].gap, "+0.562") == 0);
    // below every other time: purple
    s.cls.lap_s[12] = 79.75f;
    m.update(s, frame(11, 5), cfg, 5.0);
    CHECK(v.row[12].ob && !v.row[12].pb && std::strcmp(v.row[12].gap, "1:19.750") == 0 && v.fx[12] == 2);
    // the same time as the best: green
    s.cls.lap_s[13] = 79.75f;
    m.update(s, frame(11, 5), cfg, 5.5);
    CHECK(v.row[13].pb && !v.row[13].ob && v.row[12].ob);
    // a time that rises (a flashback): taken over quietly, that car's flash ends
    s.cls.lap_s[12] = 81.5f;
    m.update(s, frame(11, 5), cfg, 6.0);
    CHECK(!v.row[12].ob && !v.row[12].pb && v.row[13].pb);
    // a time that goes: no flash; a time again: a first time, a flash
    s.cls.lap_ok[14] = false;
    m.update(s, frame(11, 5), cfg, 6.5);
    CHECK(!v.row[14].pb && !v.row[14].ob && v.row[14].gna);
    s.cls.lap_ok[14] = true;
    s.cls.lap_s[14] = 81.0f;
    m.update(s, frame(11, 5), cfg, 7.0);
    CHECK(v.row[14].pb && std::strcmp(v.row[14].gap, "1:21.000") == 0);
    // four cars in one read: the game filling laps, no flash; three: three flashes
    for (int i : {15, 16, 17, 18})
        s.cls.lap_s[i] -= 0.5f;
    m.update(s, frame(11, 5), cfg, 7.5);
    CHECK(!v.row[15].pb && !v.row[16].pb && !v.row[17].pb && !v.row[18].pb && !v.row[15].ob && v.row[14].pb);
    for (int i : {19, 20, 21})
        s.cls.lap_s[i] -= 0.5f;
    m.update(s, frame(11, 5), cfg, 8.0);
    CHECK(v.row[19].pb && v.row[20].pb && v.row[21].pb);
    // a new session type: taken without a flash
    s.cls.lap_s[2] = 79.0f;
    m.update(s, frame(11, 6), cfg, 9.0);
    CHECK(v.on && flashes() == 0);
    // a race, the spectator menu's None (no gap column): no flash
    s.cls.lap_s[3] = 78.0f;
    m.update(s, frame(11, 15), cfg, 10.0);
    CHECK(v.on && flashes() == 0);
    Frame sp = frame(11, 6);
    sp.spect = true;
    sp.spect_gap = 0;
    s.cls.lap_s[4] = 77.0f;
    m.update(s, sp, cfg, 11.0);
    CHECK(v.on && !v.best && !v.set.gaps && flashes() == 0);
    // back to the best laps: taken first, then flashes again
    m.update(s, frame(11, 6), cfg, 12.0);
    CHECK(flashes() == 0);
    s.cls.lap_s[6] = 76.0f;
    m.update(s, frame(11, 6), cfg, 13.0);
    CHECK(v.row[6].ob && flashes() == 1);
    // the tower off: no flash kept, taken again when it comes back
    cfg.enabled = false;
    m.update(s, frame(11, 6), cfg, 13.5);
    cfg.enabled = true;
    s.cls.lap_s[7] = 75.0f;
    m.update(s, frame(11, 6), cfg, 14.0);
    CHECK(v.on && flashes() == 0);
}

// the spectator menu in Practice / Qualifying. Interval and Leader show the best-lap values (P1 its best lap;
// Leader: +gap to P1's best; Interval: +gap to the best lap of the car directly ahead; the dim bar without a time or
// out of order); Fastest Lap keeps the game's lap time. The flash in all three; None: no column, no flash; races as
// before.
static void test_spectator_best_laps()
{
    Model m;
    Snapshot s = snap();
    Settings cfg;
    cfg.mode = Mode::full;
    const View &v = m.view();
    for (int i = 0; i < N; ++i) {
        s.cls.lap_ok[i] = true;
        s.cls.lap_s[i] = 80.0f + 0.125f * float(i) + (i >= 5 ? 0.25f : 0.f);
    }
    s.cls.lap_ok[20] = s.cls.lap_ok[21] = false; // no time yet
    Frame f = frame(11, 5);
    f.spect = true;
    f.spect_gap = 1; // Interval
    m.update(s, f, cfg, 1.0);
    CHECK(v.on && v.best && v.laps && v.sgap == 1 && std::strcmp(v.row[0].gap, "1:20.000") == 0);
    CHECK(std::strcmp(v.row[1].gap, "+0.125") == 0 && std::strcmp(v.row[4].gap, "+0.125") == 0 &&
          std::strcmp(v.row[5].gap, "+0.375") == 0 && std::strcmp(v.row[6].gap, "+0.125") == 0 &&
          v.row[5].shown == kShownTime && !v.row[5].gna);
    CHECK(v.row[20].gna && v.row[20].gap[0] == 0 && v.row[21].gna && v.row[19].shown == kShownTime);
    // the order and the field disagree (car 9 slower than car 10 behind it): car 10 and 11 out of order, car 12's car
    // ahead out of order: the dim bar; car 13 its interval again
    {
        Model m2;
        Snapshot o = s;
        o.cls.lap_s[9] = 81.75f;
        m2.update(o, f, cfg, 1.0);
        const View &w = m2.view();
        CHECK(std::strcmp(w.row[9].gap, "+0.500") == 0 && w.row[10].gna && w.row[11].gna && w.row[12].gna &&
              std::strcmp(w.row[13].gap, "+0.125") == 0);
    }
    // Leader: the gap to P1's best, as the HUD tower
    f.spect_gap = 2;
    m.update(s, f, cfg, 1.3);
    CHECK(v.best && v.sgap == 2 && std::strcmp(v.row[0].gap, "1:20.000") == 0 &&
          std::strcmp(v.row[5].gap, "+0.875") == 0 && std::strcmp(v.row[19].gap, "+2.625") == 0 && v.row[20].gna);
    // the flash in Leader: green, the new lap time (m:ss.fff) for 2 s; no flash for the mode switch itself
    int fl = 0;
    for (int r = 0; r < v.rows; ++r)
        fl += int(v.row[r].pb) + int(v.row[r].ob);
    CHECK(fl == 0);
    s.cls.lap_s[10] = 81.4375f;
    m.update(s, f, cfg, 2.0);
    CHECK(v.row[10].pb && !v.row[10].ob && std::strcmp(v.row[10].gap, "1:21.437") == 0);
    // Interval: the flash goes on across the mode switch, then the interval again
    f.spect_gap = 1;
    m.update(s, f, cfg, 2.5);
    CHECK(v.row[10].pb && std::strcmp(v.row[10].gap, "1:21.437") == 0);
    m.update(s, f, cfg, 4.0);
    CHECK(!v.row[10].pb && std::strcmp(v.row[10].gap, "+0.062") == 0 && std::strcmp(v.row[11].gap, "+0.188") == 0);
    // Fastest Lap: the game's lap time (three decimals); a session best flashes purple with that same text
    f.spect_gap = 3;
    m.update(s, f, cfg, 4.5);
    CHECK(!v.best && v.laps && v.flap && std::strcmp(v.row[0].gap, "1:20.000") == 0 && !v.row[0].pb && !v.row[0].ob);
    s.cls.lap_s[3] = 79.5f;
    m.update(s, f, cfg, 5.0);
    CHECK(v.row[3].ob && !v.row[3].pb && std::strcmp(v.row[3].gap, "1:19.500") == 0 && v.fx[3] == 2);
    m.update(s, f, cfg, 7.0);
    CHECK(!v.row[3].ob && std::strcmp(v.row[3].gap, "1:19.500") == 0);
    // None: no column, no flash; back to Interval: taken first (no flash for what changed meanwhile)
    f.spect_gap = 0;
    s.cls.lap_s[4] = 79.0f;
    m.update(s, f, cfg, 7.5);
    CHECK(!v.set.gaps && !v.row[4].pb && !v.row[4].ob && v.row[4].shown == kShownOff);
    f.spect_gap = 1;
    m.update(s, f, cfg, 8.0);
    CHECK(v.set.gaps && !v.row[4].pb && !v.row[4].ob);
    // a race while spectating: the menu's Interval as before (the game's interval), no flash
    f.session = 15;
    s.cls.lap_s[6] = 70.0f;
    m.update(s, f, cfg, 9.0);
    m.update(s, f, cfg, 9.1);
    CHECK(v.race && !v.best && std::strcmp(v.row[0].gap, "Interval") == 0 && std::strcmp(v.row[5].gap, "+1.0") == 0 &&
          !v.row[6].pb && !v.row[6].ob);
}

// the race's fastest lap: the game's own fastest car (VehicleLapTimes +0xb8) when it is classified, its time
// from its lap table (-1 unknown, the mark shows anyway); a retired holder keeps the mark; none, an id outside the
// cars or a car without a position: no mark; no mark outside races; the results-entry lap times play no part.
static void test_race_fastest_lap()
{
    Model m;
    Snapshot s = snap();
    Settings cfg;
    cfg.mode = Mode::full;
    const View &v = m.view();
    m.update(s, frame(11, 15), cfg, 1.0);
    CHECK(v.on && v.race && v.fl_vid == -1 && v.fl_ms == -1 && !v.row[0].fl);
    for (int i = 0; i < N; ++i) {
        s.cls.lap_ok[i] = true;
        s.cls.lap_s[i] = 90.0f + 0.125f * float(i);
    }
    s.cls.lap_s[7] = 89.5f;
    m.update(s, frame(11, 15), cfg, 1.1);
    CHECK(v.fl_vid == -1 && !v.row[7].fl); // an earlier build's source: no longer a mark
    s.laps.fastest_ok = true;
    s.laps.fastest = 9;
    m.update(s, frame(11, 15), cfg, 1.2);
    int marks = 0;
    for (int r = 0; r < v.rows; ++r)
        marks += v.row[r].fl;
    CHECK(v.fl_vid == 9 && v.fl_ms == -1 && v.row[9].fl && marks == 1 && !v.row[7].fl);
    s.laps.best_ok[9] = true;
    s.laps.best_ms[9] = 89512;
    m.update(s, frame(11, 15), cfg, 1.3);
    CHECK(v.fl_vid == 9 && v.fl_ms == 89512 && v.row[9].fl);
    s.laps.fastest = 3; // the game moves it to car 3, retired: the mark stays on its row
    s.cls.status[3] = 4;
    m.update(s, frame(11, 15), cfg, 1.4);
    CHECK(v.fl_vid == 3 && v.fl_ms == -1 && v.row[3].fl && v.row[3].out && !v.row[9].fl);
    s.laps.fastest = laptimes::none;
    m.update(s, frame(11, 15), cfg, 1.5);
    CHECK(v.fl_vid == -1 && !v.row[3].fl);
    s.laps.fastest = 23; // a vehicle id without a position
    m.update(s, frame(11, 15), cfg, 1.6);
    CHECK(v.fl_vid == -1);
    s.laps.fastest = 3;
    s.laps.fastest_ok = false; // not read
    m.update(s, frame(11, 15), cfg, 1.7);
    CHECK(v.fl_vid == -1 && !v.row[3].fl);
    s.laps.fastest_ok = true;
    m.update(s, frame(11, 5), cfg, 1.8); // qualifying: none
    CHECK(v.fl_vid == -1 && !v.row[3].fl);
}

// the spectator menu's Fastest Lap in a race: each car's lap table best (one decimal), the dim bar without one;
// the results entry's time is not used in races; timed sessions keep it.
static void test_spectator_race_best()
{
    Model m;
    Snapshot s = snap();
    Settings cfg;
    cfg.mode = Mode::full;
    const View &v = m.view();
    for (int i = 0; i < N; ++i) {
        s.cls.lap_ok[i] = true;
        s.cls.lap_s[i] = 95.0f;
    }
    s.laps.best_ok[2] = true;
    s.laps.best_ms[2] = 81234;
    Frame f = frame(11, 15);
    f.spect = true;
    f.spect_gap = 3;
    m.update(s, f, cfg, 1.0);
    CHECK(v.on && v.race && v.laps && std::strcmp(v.row[2].gap, "1:21.2") == 0 && v.row[2].shown == kShownTime &&
          !v.row[2].gna);
    CHECK(v.row[3].gna && v.row[3].gap[0] == 0 && v.row[0].gna);
    CHECK(v.flap); // races keep one decimal (three decimals are the timed sessions')
    f.session = 5; // qualifying: the results entry's time, as before (three decimals)
    m.update(s, f, cfg, 1.1);
    CHECK(std::strcmp(v.row[3].gap, "1:35.000") == 0 && std::strcmp(v.row[2].gap, "1:35.000") == 0 && v.flap);
}

// the spectator menu's Fastest Lap in a timed session converts the results entry's f32 seconds by the game's own
// rule (game_lap_ms: the f32 product by 1000, cut), as the best laps and the flash do. Earlier builds took a double product,
// so a time just under a tenth in f32 lost that tenth: 88.6f (88.59999847 s) read "1:28.5" while the game's ms are
// 88600. The cell, the flash's time and the best laps now agree (and show three decimals with the flap leaf).
static void test_spectator_lap_rule()
{
    Model m;
    Snapshot s = snap();
    Settings cfg;
    cfg.mode = Mode::full;
    const View &v = m.view();
    for (int i = 0; i < N; ++i) {
        s.cls.lap_ok[i] = true;
        s.cls.lap_s[i] = 90.0f + 0.25f * float(i);
    }
    s.cls.lap_s[0] = 88.6f;
    s.cls.lap_s[1] = 88.7f;
    Frame f = frame(11, 5);
    f.spect = true;
    f.spect_gap = 3;
    m.update(s, f, cfg, 1.0);
    CHECK(game_lap_ms(88.6f) == 88600 && int64_t(double(88.6f) * 1000.0) == 88599);
    CHECK(v.laps && !v.best && v.row[0].shown == kShownTime && std::strcmp(v.row[0].gap, "1:28.600") == 0);
    CHECK(game_lap_ms(88.7f) == 88700 && std::strcmp(v.row[1].gap, "1:28.700") == 0);
}

// the reader's lap times (VehicleLapTimes, races only): the game's fastest car byte; each car's best valid lap
// by the game's rule (three non-zero sector times, the invalid flag 0, the lowest lap time; a time outside 1..1000 s
// is no value); read again when the lap index moves or kLapRefresh after the last read; nothing outside races.
static void test_reader_laptimes()
{
    FakeTower f = make_tower();
    FakeLaps L = make_laps(f, N + 1);
    for (int v = 0; v < N; ++v) {
        lap_put(L.rec[v], 0, 95.0f + 0.25f * float(v));
        put<uint8_t>(L.rec[v], 0x38, 1);
    }
    lap_put(L.rec[0], 1, 90.25f);
    lap_put(L.rec[0], 2, 91.0f);
    put<uint8_t>(L.rec[0], 0x38, 2);
    lap_put(L.rec[1], 0, 91.0f);
    lap_put(L.rec[1], 1, 89.0f, false);       // invalid: not a best lap
    lap_put(L.rec[2], 0, 85.0f, true, 0.f);   // sector 3 missing: not a whole lap
    lap_put(L.rec[3], 0, 0.5f);               // not a lap time
    put<uintptr_t>(L.vec, 4 * 8, 0);          // car 4: no record
    put<uint8_t>(L.LT, 0xb8, 0);
    Reader r(mem(), laps_keys(f));
    double t = run(r, f, 0.0, 2.0);
    const LapTimes &lt = r.snapshot().laps;
    CHECK(lt.ok && lt.fastest_ok && lt.fastest == 0 && r.snapshot().found_laps);
    CHECK(lt.best_ok[0] && lt.best_ms[0] == 90250 && lt.best_lap[0] == 1);
    CHECK(lt.best_ok[1] && lt.best_ms[1] == 91000 && lt.best_lap[1] == 0);
    CHECK(!lt.best_ok[2] && !lt.best_ok[3] && !lt.best_ok[4] && !lt.best_ok[22]);
    CHECK(lt.best_ok[21] && lt.best_ms[21] == 100250);
    // car 1 ends lap 2 in 88.75 s and the game names it the fastest car
    lap_put(L.rec[1], 2, 88.75f);
    put<uint8_t>(L.rec[1], 0x38, 2);
    put<uint8_t>(L.LT, 0xb8, 1);
    t = run(r, f, t, 0.6);
    CHECK(lt.fastest == 1 && lt.best_ms[1] == 88750 && lt.best_lap[1] == 2);
    // a lap changed without the index moving: seen after kLapRefresh, not before
    lap_put(L.rec[0], 0, 90.125f);
    t = run(r, f, t, 1.0);
    CHECK(lt.best_ms[0] == 90250);
    t = run(r, f, t, kLapRefresh + 1.5);
    CHECK(lt.best_ms[0] == 90125 && lt.best_lap[0] == 0);
    // the game's reset: no fastest car
    put<uint8_t>(L.LT, 0xb8, 0xff);
    t = run(r, f, t, 0.6);
    CHECK(lt.fastest_ok && lt.fastest == laptimes::none);
    // an unreadable vector: nothing
    put<uintptr_t>(L.LT, 0x60, uintptr_t(L.vec) - 8);
    t = run(r, f, t, 0.6);
    CHECK(!lt.ok && !lt.fastest_ok);
    put<uintptr_t>(L.LT, 0x60, uintptr_t(L.vec) + 24 * 8);
    // qualifying: no lap times read (and a new session clears them)
    f.frame.session = 5;
    t = run(r, f, t, 0.6);
    CHECK(!lt.ok && !lt.fastest_ok && !lt.best_ok[0] && !r.snapshot().found_laps);
}

// render badges (record +0x58d, not My Team): the reader builds the game's key "<source name> <id>" from the
// entrant's badge word (+0x68), "default.tga" for the none id, nothing for an unknown source; the leaf is
// kRenderBadgePrefix + key. My Team (kind 1) stays unknown; the log keeps the entrant's word.
static void test_render_badges()
{
    char out[kBadgeTextMax];
    CHECK(badge_text("eUserDefined 5", out, sizeof out, true) &&
          std::strcmp(out, "eaid://ui_package/art/textures/render_badge_eUserDefined 5") == 0);
    CHECK(badge_text("default.tga", out, sizeof out, true) &&
          std::strcmp(out, "eaid://ui_package/art/textures/render_badge_default.tga") == 0);
    CHECK(!badge_text("eUserDefined 5", out, sizeof out) && !badge_text(" x", out, sizeof out, true) &&
          !badge_text("x ", out, sizeof out, true) && !badge_text("", out, sizeof out, true));
    FakeTower f = make_tower();
    make_laps(f, N);
    set_team(f, 5, 0, 12);
    put<uint8_t>(f.trec[12], 0x58d, 1);
    put<uint32_t>(entrant(f, 5), 0x68, (5u << 16) | 1u);
    set_team(f, 6, 0, 12);
    put<uint32_t>(entrant(f, 6), 0x68, (0x3fffu << 16) | 1u);
    set_team(f, 7, 0, 12);
    put<uint32_t>(entrant(f, 7), 0x68, (9u << 16) | 3u);   // a source the game's table has no name for
    set_team(f, 8, 1, 2);                                   // My Team
    put<uint32_t>(entrant(f, 8), 0x68, (7u << 16) | 1u);
    Reader r(mem(), laps_keys(f));
    run(r, f, 0.0, 1.0);
    const Badges &b = r.snapshot().badges;
    CHECK(b.car[5].state == kBadgeRender && b.car[5].key >= 0 && b.render[b.car[5].key] &&
          std::strcmp(b.key[b.car[5].key], "eUserDefined 5") == 0 && b.car[5].ref_ok && b.car[5].ref == 0x50001u);
    CHECK(b.car[6].state == kBadgeRender && std::strcmp(b.key[b.car[6].key], "default.tga") == 0);
    CHECK(b.car[7].state == kBadgeOther && b.car[7].key == -1 && b.car[7].ref_ok);
    CHECK(b.car[8].state == kBadgeOther && b.car[8].kind == 1 && b.car[8].ref_ok && b.car[8].ref == 0x70001u);
    CHECK(b.car[0].state == kBadgeKey && !b.render[b.car[0].key] && !b.car[0].ref_ok);
    // the model and the leaf
    Model m;
    Settings cfg;
    cfg.mode = Mode::full;
    m.update(r.snapshot(), f.frame, cfg, 1.0);
    const View &v = m.view();
    int row5 = v.car_row[5];
    CHECK(row5 >= 0 && v.row[row5].bdg && v.row[row5].brender && std::strcmp(v.row[row5].badge, "eUserDefined 5") == 0);
    CHECK(!v.row[v.car_row[7]].bdg && !v.row[v.car_row[8]].bdg && v.row[v.car_row[0]].bdg && !v.row[v.car_row[0]].brender);
    auto pub = std::make_unique<Publisher>();
    Publisher &p = *pub;
    Recorder rec;
    p.set_sink(LeafSink{rec_set, &rec});
    for (int i = 0; i < 80 && p.dirty(); ++i)
        p.publish(v, 1.0, 56);
    char key[16];
    std::snprintf(key, sizeof key, "r%02d_badge", row5);
    CHECK(p.dirty() == 0 &&
          std::string(p.sent_text(id_of(p, key))) == "eaid://ui_package/art/textures/render_badge_eUserDefined 5" &&
          p.sent_int(id_of(p, "r00_bdg")) == 1);
}

// the two glitches of an in-game test. a) The knockout field is held per session type: the next segment's
// smaller field read while the type still says Q1 moves no cut; a new type, or the tower off for more than 5 s,
// starts it again. b) Timed sessions: a car with a best lap keeps its row and time whatever its status; without
// one: Out. A race: Out as before.
static void test_rc19_glitches()
{
    Model m;
    Settings cfg;
    cfg.mode = Mode::full;
    const View &v = m.view();
    m.update(timed(snap()), frame(11, 5, 1), cfg, 1.0);
    CHECK(v.ko_safe == 16 && v.row[16].ko);
    Snapshot off = snap();
    off.cls.ok = false;
    m.update(off, frame(11, 5, 2), cfg, 1.5); // Q1 -> Q2: the field rebuilt (0.9 s off in game)
    CHECK(!v.on);
    m.update(timed(snap(16)), frame(11, 5, 3), cfg, 2.4); // Q2's 16 cars, the type still Q1
    bool none = v.on && v.rows == 16 && v.ko_safe == 16;
    for (int r = 0; r < v.rows; ++r)
        none = none && !v.row[r].ko;
    CHECK(none);
    m.update(timed(snap(16)), frame(11, 6, 4), cfg, 5.7); // Q2 proper
    CHECK(v.ko_safe == 10 && !v.row[9].ko && v.row[10].ko && v.row[15].ko);
    m.update(timed(snap()), frame(11, 5, 5), cfg, 7.0); // another event's Q1 (22 cars)
    CHECK(v.ko_safe == 16);
    m.update(off, frame(11, 5, 6), cfg, 8.0); // the tower off for 7 s, then a 20-car Q1: its own field
    m.update(timed(snap(20)), frame(11, 5, 7), cfg, 14.0);
    CHECK(v.ko_safe == 15 && !v.row[14].ko && v.row[15].ko);
    // b) Q1's end: status 7 for a car with a best lap (the player): row and time stay; without a lap: Out
    Snapshot q = snap();
    for (int i = 0; i < N; ++i) {
        q.cls.lap_ok[i] = true;
        q.cls.lap_s[i] = 80.0f + 0.125f * float(i);
    }
    q.cls.lap_ok[21] = false;
    q.cls.status[5] = 7;
    q.cls.status[21] = 7;
    m.update(q, frame(5, 5, 8), cfg, 30.0);
    CHECK(!v.row[5].out && v.row[5].me && std::strcmp(v.row[5].gap, "+0.625") == 0 && v.row[21].out &&
          std::strcmp(v.row[21].gap, "Out") == 0 && !v.row[21].ko && v.row[20].ko);
    m.update(q, frame(5, 15, 8), cfg, 31.0); // a race: Out whatever the lap time
    CHECK(v.row[5].out && std::strcmp(v.row[5].gap, "Out") == 0);
}

// rNN_pb, rNN_ob, rNN_fl go out with their rows
static void test_flash_leaves()
{
    auto pub = std::make_unique<Publisher>();
    Publisher &p = *pub;
    Recorder rec;
    p.set_sink(LeafSink{rec_set, &rec});
    CHECK(p.type(id_of(p, "r00_pb")) == LeafType::boolean && p.type(id_of(p, "r21_fl")) == LeafType::boolean &&
          id_of(p, "r00_pb") == Publisher::row_leaf(0, kRowKo) + 1 && id_of(p, "r00_ob") == Publisher::row_leaf(0, kRowPb) + 1 &&
          id_of(p, "r00_fl") == Publisher::row_leaf(0, kRowCar) - 3);
    Model m;
    Settings cfg;
    cfg.mode = Mode::full;
    Snapshot s = snap();
    for (int i = 0; i < N; ++i) {
        s.cls.lap_ok[i] = true;
        s.cls.lap_s[i] = 80.0f + 0.125f * float(i);
    }
    const auto flush = [&](double t) {
        for (int i = 0; i < 100 && (i == 0 || p.dirty()); ++i)
            p.publish(m.view(), t, 56);
    };
    m.update(s, frame(11, 5), cfg, 1.0);
    flush(1.0);
    s.cls.lap_s[9] = 79.875f;  // purple
    s.cls.lap_s[4] = 80.4375f; // green
    m.update(s, frame(11, 5), cfg, 2.0);
    flush(2.0);
    CHECK(p.sent_int(id_of(p, "r09_ob")) == 1 && p.sent_int(id_of(p, "r09_pb")) == 0 &&
          p.sent_int(id_of(p, "r04_pb")) == 1 && p.sent_int(id_of(p, "r04_ob")) == 0 &&
          std::strcmp(p.sent_text(id_of(p, "r09_gap")), "1:19.875") == 0 &&
          std::strcmp(p.sent_text(id_of(p, "r04_gap")), "1:20.437") == 0 && p.sent_int(id_of(p, "r00_fl")) == 0);
    m.update(s, frame(11, 5), cfg, 4.0);
    flush(4.0);
    CHECK(p.sent_int(id_of(p, "r09_ob")) == 0 && p.sent_int(id_of(p, "r04_pb")) == 0 &&
          std::strcmp(p.sent_text(id_of(p, "r04_gap")), "+0.437") == 0);
    s.laps.fastest_ok = true; // the game's fastest car
    s.laps.fastest = 9;
    m.update(s, frame(11, 15), cfg, 5.0); // a race: the fastest lap's row
    flush(5.0);
    CHECK(p.sent_int(id_of(p, "r09_fl")) == 1 && p.sent_int(id_of(p, "r00_fl")) == 0 &&
          p.sent_int(id_of(p, "r09_ob")) == 0 && p.sent_int(id_of(p, "r04_pb")) == 0);
}

// the knockout zone. Q1 / SQ1 keep 10 + (n - 10) / 2 cars, Q2 / SQ2 keep 10; Q3, SQ3, short and one-shot
// qualifying, practice, races and Time Trial: none. A car below the last safe position gets rNN_ko unless it is out.
static void test_knockout()
{
    CHECK(knockout_safe(5, 22) == 16 && knockout_safe(5, 20) == 15 && knockout_safe(10, 22) == 16 &&
          knockout_safe(10, 20) == 15 && knockout_safe(5, 21) == 15 && knockout_safe(5, 11) == 10);
    CHECK(knockout_safe(6, 16) == 10 && knockout_safe(6, 15) == 10 && knockout_safe(11, 16) == 10 &&
          knockout_safe(6, 10) == -1 && knockout_safe(5, 10) == -1 && knockout_safe(5, 9) == -1);
    for (uint32_t t : {0u, 1u, 2u, 3u, 4u, 7u, 8u, 9u, 12u, 13u, 14u, 15u, 16u, 17u, 18u, 99u})
        CHECK(knockout_safe(t, 22) == -1);

    Model m;
    Snapshot s = timed(snap());
    Settings cfg;
    cfg.mode = Mode::full;
    const View &v = m.view();
    // Q1, 22 cars: P17-P22 in the zone, P1-P16 not
    m.update(s, frame(11, 5), cfg, 1.0);
    CHECK(v.on && v.ko_safe == 16 && v.rows == 22);
    bool ok = true;
    for (int r = 0; r < 22; ++r)
        ok = ok && v.row[r].ko == (v.row[r].pos > 16);
    CHECK(ok && !v.row[0].ko && v.row[0].p1 && !v.row[15].ko && v.row[16].ko && v.row[21].ko);
    // an out car in the zone: no hatch (its row is dimmed as before). Without a lap time, as a timed session's
    // car with a best lap keeps its row
    s.cls.status[s.cls.order[20]] = 7;
    s.cls.lap_ok[s.cls.order[20]] = false;
    s.cls.seq = 2;
    m.update(s, frame(11, 5), cfg, 1.1);
    CHECK(v.row[20].out && !v.row[20].ko && v.row[21].ko && v.row[19].ko);
    // the player in the zone: the hatch and the highlight both
    m.update(s, frame(18, 5), cfg, 1.2);
    CHECK(v.row[18].me && v.row[18].ko);
    // Q2, 16 cars: P11-P16
    Snapshot q2 = timed(snap(16));
    m.update(q2, frame(11, 6), cfg, 1.3);
    CHECK(v.ko_safe == 10 && v.rows == 16 && !v.row[9].ko && v.row[10].ko && v.row[15].ko && v.row[11].me);
    // SQ1 with 20 cars: P16-P20; SQ2 with 15: P11-P15
    m.update(timed(snap(20)), frame(3, 10), cfg, 1.4);
    CHECK(v.ko_safe == 15 && !v.row[14].ko && v.row[15].ko && v.row[19].ko);
    m.update(timed(snap(15)), frame(3, 11), cfg, 1.5);
    CHECK(v.ko_safe == 10 && !v.row[9].ko && v.row[10].ko && v.row[14].ko);
    // Q3, short qualifying, one-shot qualifying, practice, a race: no zone
    for (uint32_t t : {7u, 8u, 9u, 2u, 15u}) {
        m.update(timed(snap()), frame(11, t), cfg, 1.6);
        bool none = v.ko_safe == -1;
        for (int r = 0; r < v.rows; ++r)
            none = none && !v.row[r].ko;
        CHECK(none);
    }
    // compact window: the rows follow their cars (P17 in row 2 of 5 around the player at P19)
    cfg.mode = Mode::compact;
    cfg.rows = 5;
    m.update(timed(snap()), frame(18, 5), cfg, 1.7);
    CHECK(v.rows == 5 && v.row[0].pos == 17 && v.row[0].ko && v.row[2].me && v.row[2].ko);
    m.update(timed(snap()), frame(2, 5), cfg, 1.8);
    CHECK(v.row[0].pos == 1 && !v.row[0].ko && !v.row[4].ko);
}

// the knockout zone needs the game's own order for the session. An in-game log holds a Q2 -> race
// switch where the session type still read Q2 (6) for 8 records (t 787.8-788.5), after the tower had been off for
// 68 s, with the race's 22 cars in vehicle-id order and no lap times: earlier builds' rule hatched P11-P22 for 0.8 s.
// At the four segment starts in the logs (t 90.5 and 498.9 in one, 476.7 and 612.8 in another) the cars had no times
// either, but stood in the game's own order. So: no zone while no classified car has a lap time and the order is the
// vehicle ids' own; a time, or the game's order, and the zone follows the rules as before.
static Snapshot game_order(Snapshot s)    // a start order that is not the vehicle ids' (a permutation: 7 and 22 coprime)
{
    for (int i = 0; i < s.cls.n; ++i) {
        const int vid = (i * 7) % s.cls.n;
        s.cls.order[i] = uint8_t(vid);
        s.cls.pos[vid] = uint8_t(i + 1);
    }
    return s;
}

static void test_ko_game_order()
{
    Model m;
    Settings cfg;
    cfg.mode = Mode::full;
    const View &v = m.view();
    Snapshot off = snap();
    off.cls.ok = false;
    m.update(off, frame(11, 6, 17), cfg, 719.2);   // Q2 over: the tower off
    m.update(snap(), frame(11, 6, 17), cfg, 787.8); // 22 cars in vehicle-id order, no times, the type still Q2
    bool none = v.on && v.rows == 22 && v.ko_safe == -1;
    for (int r = 0; r < v.rows; ++r)
        none = none && !v.row[r].ko;
    CHECK(none);
    Snapshot q = snap();
    q.cls.lap_ok[4] = true;   // one time: the zone as the type's rule says
    q.cls.lap_s[4] = 66.5f;
    m.update(q, frame(11, 6, 17), cfg, 787.9);
    CHECK(v.ko_safe == 10 && !v.row[9].ko && v.row[10].ko && v.row[21].ko);
    // a Q1 start in the game's order, no times: the zone at once, as earlier builds (P17-P22)
    Model m2;
    const View &v2 = m2.view();
    m2.update(game_order(snap()), frame(11, 5, 1), cfg, 90.4);
    CHECK(v2.on && v2.ko_safe == 16 && !v2.row[15].ko && v2.row[16].ko && v2.row[21].ko && v2.row[16].pos == 17);
    // a start in vehicle-id order, no times: none until the first lap
    Model m3;
    const View &v3 = m3.view();
    m3.update(snap(), frame(11, 5, 1), cfg, 90.4);
    none = v3.on && v3.ko_safe == -1;
    for (int r = 0; r < v3.rows; ++r)
        none = none && !v3.row[r].ko;
    CHECK(none);
    Snapshot q1 = snap();
    q1.cls.lap_ok[0] = true;
    q1.cls.lap_s[0] = 66.506f;
    m3.update(q1, frame(11, 5, 1), cfg, 171.0);
    CHECK(v3.ko_safe == 16 && !v3.row[15].ko && v3.row[16].ko && v3.row[21].ko);
}

// rNN_ko goes out with its row; the clock leaf is "" while the header is not timed and never written while it is
static void test_ko_clock_leaves()
{
    auto pub = std::make_unique<Publisher>();
    Publisher &p = *pub;
    Recorder rec;
    p.set_sink(LeafSink{rec_set, &rec});
    Model m;
    Settings cfg;
    cfg.mode = Mode::full;
    const int clock = id_of(p, "clock");
    // a race: the clock leaf is written ("") and refreshed like any other leaf; no hatch
    m.update(snap(), frame(11, 15), cfg, 1.0);
    for (int i = 0; i < 100 && p.dirty(); ++i)
        p.publish(m.view(), 1.0, 56);
    CHECK(p.dirty() == 0 && p.sent(clock) && p.sent_text(clock)[0] == 0 && p.sent_int(id_of(p, "r20_ko")) == 0);
    // Q1: the hatch on P17-P22's rows; the clock leaf is never written while timed (neither change nor refresh)
    m.update(timed(snap()), frame(11, 5), cfg, 2.0);
    for (int i = 0; i < 100 && (i == 0 || p.dirty()); ++i) // publish() marks what the new view changes
        p.publish(m.view(), 2.0, 56);
    CHECK(p.dirty() == 0 && p.sent_int(id_of(p, "timed")) == 1 && p.sent_int(id_of(p, "r15_ko")) == 0 &&
          p.sent_int(id_of(p, "r16_ko")) == 1 && p.sent_int(id_of(p, "r21_ko")) == 1);
    rec.paths.clear();
    for (int i = 0; i < 3 * (kLeaves / kRefreshPerFrame + 1); ++i)
        p.publish(m.view(), 2.0, 56);
    const std::string cp = p.path(clock);
    bool clock_written = false;
    for (const std::string &x : rec.paths)
        clock_written = clock_written || x == cp;
    CHECK(!clock_written && !rec.paths.empty());
    // back to a race: the DLL keeps the node existing again (written within one refresh cycle)
    m.update(snap(), frame(11, 15), cfg, 3.0);
    rec.paths.clear();
    for (int i = 0; i < kLeaves / kRefreshPerFrame + 2; ++i)
        p.publish(m.view(), 3.0, 56);
    clock_written = false;
    for (const std::string &x : rec.paths)
        clock_written = clock_written || x == cp;
    CHECK(clock_written && p.sent_int(id_of(p, "r16_ko")) == 0 && p.sent_int(id_of(p, "timed")) == 0);
    // a fresh table straight into Q2: the clock leaf is never sent while timed
    auto pub2 = std::make_unique<Publisher>();
    Publisher &p2 = *pub2;
    Recorder rec2;
    p2.set_sink(LeafSink{rec_set, &rec2});
    m.update(timed(snap(16)), frame(11, 6), cfg, 4.0);
    for (int i = 0; i < 200; ++i)
        p2.publish(m.view(), 4.0, 56);
    CHECK(!p2.sent(clock) && p2.dirty() == 0 && p2.sent_int(id_of(p2, "r10_ko")) == 1 &&
          p2.sent_int(id_of(p2, "r09_ko")) == 0);
}

// ---------------------------------------------------------------- the rows' motion (tower_anim.cpp)
// Which rows slide, which arrows ride in, which numbers and flashes fade in; the snap rules; the
// packets the publisher writes after the row's data; Animations off = the static tower's writes.

struct AnimRig {
    Model m;
    Anim a;
    Snapshot s;
    Settings cfg;
    Frame f;
    std::vector<int> ord;
    uint32_t seq = 1;
    double t = 0;
    explicit AnimRig(int n = N, uint32_t session = 15, Mode mode = Mode::full) : s(snap(n)), f(frame(11, session))
    {
        cfg.mode = mode;
        for (int i = 0; i < n; ++i)
            ord.push_back(i);
        for (int i = N; i < n && i < 32; ++i)
            f.slots[i] = '.';
    }
    const View &v() const { return m.view(); }
    void step(double now)
    {
        t = now;
        s.cls.t = now;
        m.update(s, f, cfg, now);
        a.update(m.view(), f, m, now);
    }
    // frames at 60 fps after the current time, up to (not including) `until`; the packets they made
    int run(double until)
    {
        int n = 0;
        const double t0 = t;
        for (int k = 1; t0 + k / 60.0 < until; ++k) {
            step(t0 + k / 60.0);
            n += a.packets();
        }
        return n;
    }
    void apply()
    {
        for (size_t i = 0; i < ord.size(); ++i) {
            s.cls.order[i] = uint8_t(ord[i]);
            s.cls.pos[ord[i]] = uint8_t(i + 1);
        }
        s.cls.seq = ++seq;
    }
    // the car at classification index `from` moves to index `to`; the cars between shift by one
    void move(int from, int to)
    {
        const int car = ord[from];
        ord.erase(ord.begin() + from);
        ord.insert(ord.begin() + to, car);
        apply();
    }
    void swap(int i, int j)
    {
        std::swap(ord[i], ord[j]);
        apply();
    }
    uint16_t codes(int r) const { return a.row(r).codes; }
};

constexpr uint16_t kUp1 = kAnU1 | kAnEu, kDn1 = kAnD1 | kAnEd;

static void test_anim_slide()
{
    AnimRig r;
    r.step(1.0);
    CHECK(r.a.on() && r.a.snap() == kSnapFirst && r.a.packets() == 0 && r.v().rows == N);
    // the first frame's session read starts a settle: a swap within it snaps
    r.swap(3, 4);
    r.step(2.0);
    CHECK(r.a.snap() == kSnapSettle && r.a.packets() == 0 && r.a.row(3).seq == 0);
    CHECK(r.run(3.2) == 0 && r.a.snap() == kSnapNone);
    // car 6 passes car 5: row 5 slides up one row with its ▲ entry, row 6 down with its ▼ entry, nothing else
    const int up = r.ord[6], dn = r.ord[5];
    r.swap(5, 6);
    r.step(3.3);
    CHECK(r.v().row[5].vid == up && r.v().row[5].up && r.v().row[6].vid == dn && r.v().row[6].dn);
    CHECK(r.a.snap() == kSnapNone && r.a.packets() == 2 && r.codes(5) == kUp1 && r.codes(6) == kDn1 &&
          r.a.row(5).seq == 1 && r.a.row(6).seq == 1 && r.a.row(4).seq == 0 && r.a.row(7).seq == 0);
    CHECK(r.a.moving(5) && r.a.moving(6) && !r.a.moving(4) && r.a.stats().slides == 2 && r.a.stats().entries == 2);
    // nothing more until the rest packets, 0.8 s after the slide
    CHECK(r.run(3.3 + kSlideRest - 0.01) == 0 && r.a.moving(5));
    r.step(3.3 + kSlideRest + 0.01);
    CHECK(r.a.packets() == 2 && r.codes(5) == kAnRs && r.codes(6) == kAnRs && !r.a.moving(5) && !r.a.moving(6) &&
          r.a.row(5).seq == 2 && r.a.stats().rests == 2);
    // the number fades back in as the arrow ends: up to two frames before (the arrow still shows), once per row
    // (rows 3 and 4, swapped within the settle, slid no row but still had their arrows: their numbers fade at 5.0)
    double nf_t = -1;
    bool arrow_then = false;
    for (int k = 1; k < 260 && nf_t < 0; ++k) {
        r.step(4.11 + k / 60.0);
        if (r.a.row(5).seq != 2) {
            nf_t = r.t;
            arrow_then = r.v().row[5].up && r.v().row[6].dn;
        }
    }
    CHECK(r.a.row(3).seq == 2 && r.a.row(4).seq == 2 && r.codes(3) == kAnRs);
    CHECK(nf_t > 0 && arrow_then && r.codes(5) == kAnNf && r.codes(6) == kAnNf && r.a.packets() == 2);
    CHECK(3.3 + kArrowSeconds - nf_t > 1 / 60.0 && 3.3 + kArrowSeconds - nf_t <= 2 / 60.0 + 1e-9);
    // the arrow ends within the next two frames, without a second packet
    r.step(nf_t + 1 / 60.0);
    CHECK(r.a.packets() == 0);
    r.step(nf_t + 2 / 60.0);
    CHECK(!r.v().row[5].up && !r.v().row[6].dn && r.a.packets() == 0);
    CHECK(r.run(nf_t + kFadeRest - 0.01) == 0);
    r.step(nf_t + kFadeRest + 0.01);
    CHECK(r.a.packets() == 2 && r.codes(5) == kAnRs && r.codes(6) == kAnRs && r.a.stats().nf == 4);
    CHECK(r.run(nf_t + 3.0) == 0); // and nothing more
    // arrows off: the slide without the entries, and no number fade
    r.cfg.arrows = false;
    r.swap(9, 10);
    r.step(r.t + 0.02);
    CHECK(r.codes(9) == kAnU1 && r.codes(10) == kAnD1);
    r.step(r.t + kSlideRest + 0.01);
    CHECK(r.codes(9) == kAnRs && r.codes(10) == kAnRs && r.run(r.t + 4.0) == 0);
}

// Frame times vary. A row's number fade is armed when its arrow ends within the next two frames, so a frame
// that comes late across the arrow's end does not lose it (armed within one frame, the 18:44 log replayed at 60 fps
// between its 10 Hz records lost some)
static void test_anim_nf_late_frame()
{
    AnimRig r;
    r.step(1.0);
    CHECK(r.run(3.2) == 0 && r.a.snap() == kSnapNone);
    r.swap(5, 6);
    r.step(3.3);
    CHECK(r.codes(5) == kUp1 && r.codes(6) == kDn1);
    const double end = 3.3 + kArrowSeconds, tb = end - 0.025; // the arrows end 1.5 frames after tb
    int n = 0;
    for (int j = int((tb - 3.3) * 60) - 1; j >= 1; --j) {
        r.step(tb - j / 60.0);
        n += r.a.packets();
    }
    CHECK(n == 2 && r.v().row[5].up && r.a.row(5).seq == 2); // only the slides' rest packets
    r.step(tb); // a steady frame
    CHECK(r.v().row[5].up && r.v().row[6].dn && r.a.packets() == 2 && r.codes(5) == kAnNf && r.codes(6) == kAnNf);
    r.step(tb + 0.055); // the next frame comes 3.3 frames late, after the arrows' end
    CHECK(!r.v().row[5].up && !r.v().row[6].dn && r.a.packets() == 0);
    r.step(tb + kFadeRest + 0.01);
    CHECK(r.a.packets() == 2 && r.codes(5) == kAnRs && r.codes(6) == kAnRs);
}

static void test_anim_rows()
{
    // a car gains three places: it slides up 3 rows, the three cars it passes down one row each
    AnimRig r;
    r.step(1.0);
    r.run(3.5);
    r.move(10, 7);
    r.step(3.6);
    CHECK(r.a.snap() == kSnapNone && r.a.packets() == 4 && r.codes(7) == (kAnU3 | kAnEu) && r.codes(8) == kDn1 &&
          r.codes(9) == kDn1 && r.codes(10) == kDn1 && r.a.row(11).seq == 0);
    r.step(3.6 + kSlideRest + 0.01);
    // five places: the car snaps onto its row (nothing moving there: no packet), the five it passes slide
    r.move(15, 10);
    r.step(r.t + 0.02);
    CHECK(r.a.snap() == kSnapNone && !r.a.moving(10) && r.codes(10) == kAnRs);
    bool slid = true;
    for (int k = 11; k <= 15; ++k)
        slid = slid && r.codes(k) == kDn1;
    CHECK(slid && r.a.packets() == 5);
    r.step(r.t + kSlideRest + 0.01);
    // the leader and the last row: no ▲ entry from below the last row, no ▼ entry from above the first
    auto pe = std::make_unique<AnimRig>(30);
    AnimRig &e = *pe;
    e.step(1.0);
    e.run(3.5);
    CHECK(e.v().rows == 30);
    e.swap(28, 29);
    e.swap(0, 1);
    e.step(3.6);
    CHECK(e.codes(28) == kAnU1 && e.codes(29) == kDn1 && e.codes(0) == kUp1 && e.codes(1) == kAnD1 &&
          e.a.packets() == 4);
    // two-place moves of up to four cars slide; five or more snap every row (bulk), a row in motion to rest
    e.step(3.6 + kSlideRest + 0.01);
    e.swap(3, 5);
    e.swap(10, 12);
    e.step(e.t + 0.02);
    CHECK(e.a.snap() == kSnapNone && e.codes(3) == (kAnU2 | kAnEu) && e.codes(5) == (kAnD2 | kAnEd) &&
          e.codes(10) == (kAnU2 | kAnEu) && e.codes(12) == (kAnD2 | kAnEd) && e.a.row(4).seq == 0);
    e.swap(20, 22); // 2 cars
    e.swap(24, 26); // 4
    e.swap(14, 16); // 6 cars moving two rows in one frame
    e.step(e.t + 0.02);
    CHECK(e.a.snap() == kSnapBulk && e.codes(3) == kAnRs && e.codes(5) == kAnRs && e.codes(10) == kAnRs &&
          e.codes(12) == kAnRs && e.a.row(20).seq == 0 && e.a.row(14).seq == 0 && e.a.packets() == 4);
    // top 10: a car from P16 enters at P8 (snap), P8 and P9 slide down, P10 leaves the window
    auto pt = std::make_unique<AnimRig>(N, 15, Mode::top);
    AnimRig &t = *pt;
    t.cfg.rows = 10;
    t.step(1.0);
    t.run(3.5);
    t.move(15, 7);
    t.step(3.6);
    CHECK(t.v().rows == 10 && t.a.snap() == kSnapNone && t.a.row(7).seq == 0 && t.codes(8) == kDn1 &&
          t.codes(9) == kDn1 && t.a.packets() == 2);
}

static void test_anim_flicker()
{
    // a back and forth within kFlicker snaps back; the rows moving go to rest at once
    AnimRig r;
    r.step(1.0);
    r.run(3.5);
    r.swap(5, 6);
    r.step(3.6);
    CHECK(r.codes(5) == kUp1 && r.codes(6) == kDn1);
    r.swap(5, 6);
    r.step(3.9);
    CHECK(r.a.snap() == kSnapNone && r.codes(5) == kAnRs && r.codes(6) == kAnRs && !r.a.moving(5) &&
          r.a.packets() == 2);
    // again 0.5 s later: each car goes back to a row it left 0.3 s ago: snap (no packet: nothing moving)
    r.swap(5, 6);
    r.step(4.4);
    CHECK(r.a.packets() == 0 && r.codes(5) == kAnRs);
    // more than kFlicker after the last change: a real pass slides again
    r.swap(5, 6);
    r.step(4.4 + kFlicker + 0.05);
    CHECK(r.codes(5) == kUp1 && r.codes(6) == kDn1);
    // the next change on a row whose slide may still be playing (kBusy) snaps: that row goes to rest at once
    // (its own rest packet); the pair rule: the other car of that move snaps with it (its slide would start on the
    // busy row; row 7 was at rest: no packet); row snaps are log events
    r.a.clear_events();
    const uint32_t seq7 = r.a.row(7).seq;
    r.swap(6, 7);
    r.step(r.t + 0.3);
    CHECK(r.codes(6) == kAnRs && !r.a.moving(6) && r.a.row(7).seq == seq7 && !r.a.moving(7) && r.a.moving(5) &&
          r.a.stats().busy == 1 && r.a.stats().pair == 1 && r.a.busy(6, r.t) && r.a.events().n == 2 &&
          r.a.events().e[0].row == 6 && r.a.events().e[0].what == (kEvSnap | kRowSnapBusy) &&
          r.a.events().e[1].row == 7 && r.a.events().e[1].what == (kEvSnap | kRowSnapPair));
    r.step(r.t + kSlideRest - 0.25);
    CHECK(r.codes(5) == kAnRs && !r.a.moving(5)); // row 5's rest came
    r.step(r.t + 0.3);
    CHECK(!r.a.busy(6, r.t) && r.run(r.t + 2.0) <= 3); // the number fades still to come
    // the busy rule ends with kBusy: a pass 0.86 s after a slide slides again (kBusy = kSlideRest: its rest packet
    // came first)
    r.run(r.t + 1.5);
    r.swap(12, 13);
    r.step(r.t + 0.02);
    CHECK(r.codes(12) == kUp1);
    const double t12 = r.t;
    r.run(t12 + kBusy - 0.01);
    r.swap(12, 11);
    r.step(t12 + kBusy - 0.005);
    CHECK(r.codes(12) == kAnRs && r.a.stats().busy == 2 && r.a.stats().pair == 2);
    // the pair rule follows the move: P16 to P14 while only row 14 may still be sliding (P15 and P18 swapped 0.3 s
    // before). Row 14 snaps (busy); row 15's slide would start on row 14 (pair, first pass); row 13's would start on
    // row 15 (pair, second pass): the whole move switches at once; row 14 goes to rest, rows 13 and 15 were at rest
    r.run(r.t + 4.0);
    r.swap(14, 17);
    r.step(r.t + 0.02);
    CHECK((r.codes(14) & kAnSlide) == kAnU3 && (r.codes(17) & kAnSlide) == kAnD3);
    r.a.clear_events();
    const uint32_t seq13 = r.a.row(13).seq, seq15 = r.a.row(15).seq;
    r.move(15, 13);
    r.step(r.t + 0.3);
    CHECK(r.a.stats().busy == 3 && r.a.stats().pair == 4 && r.codes(14) == kAnRs && r.a.row(13).seq == seq13 &&
          r.a.row(15).seq == seq15 && r.a.packets() == 1 && r.a.events().n == 3 &&
          r.a.events().e[0].row == 13 && r.a.events().e[0].what == (kEvSnap | kRowSnapPair) &&
          r.a.events().e[1].row == 14 && r.a.events().e[1].what == (kEvSnap | kRowSnapBusy) &&
          r.a.events().e[2].row == 15 && r.a.events().e[2].what == (kEvSnap | kRowSnapPair));
    // a far move keeps its slides: P20 to P12 snaps (more than 3 rows), the cars it passes slide down one row
    r.run(r.t + 4.0);
    r.a.clear_events();
    r.move(19, 11);
    r.step(r.t + 0.02);
    CHECK(r.a.events().n == 1 && r.a.events().e[0].row == 11 && r.a.events().e[0].what == (kEvSnap | kRowSnapFar) &&
          r.codes(12) == kDn1 && r.codes(19) == kDn1 && r.a.stats().pair == 4);
}

static void test_anim_snaps()
{
    // a session or car-set change: every row snaps, then a settle of kSettle; moving rows to rest at once
    AnimRig r;
    r.step(1.0);
    r.run(3.5);
    r.swap(5, 6);
    r.step(3.6);
    r.f.session = 16;
    r.swap(8, 9);
    r.step(3.7);
    CHECK(r.a.snap() == kSnapSession && r.codes(5) == kAnRs && r.codes(6) == kAnRs && r.a.row(8).seq == 0);
    r.swap(10, 11);
    r.step(5.6);
    CHECK(r.a.snap() == kSnapSettle && r.a.packets() == 0);
    r.swap(12, 13);
    r.step(5.75);
    CHECK(r.a.snap() == kSnapNone && r.codes(12) == kUp1);
    r.f.generation = 2; // a restart, a car joining or leaving
    r.step(6.8);
    CHECK(r.a.snap() == kSnapSession);
    r.run(8.9);
    // the followed car changes (a spectator switch): the frame snaps, the next one moves again
    r.f.player = 4;
    r.swap(14, 15);
    r.step(9.0);
    CHECK(r.a.snap() == kSnapPlayer && r.a.packets() == 0);
    r.swap(16, 17);
    r.step(9.1);
    CHECK(r.a.snap() == kSnapNone && r.codes(16) == kUp1);
    // a replay jump or rewind: the followed car's lap distance jumps; a settle follows. Across the line: no jump
    r.f.player_lap_m = 1000.f;
    r.step(9.9);
    r.f.player_lap_m = 1001.5f;
    r.step(9.92);
    CHECK(r.a.snap() == kSnapNone);
    r.f.player_lap_m = 400.f;
    r.swap(18, 19);
    r.step(9.94);
    // (rows 16 and 17 slid at 9.1 and still move until 9.1 + kSlideRest: the snap sends their rest packets)
    CHECK(r.a.snap() == kSnapJump && r.a.row(18).seq == 0 && r.a.row(19).seq == 0 && r.codes(16) == kAnRs &&
          r.codes(17) == kAnRs && r.a.packets() == 2);
    r.swap(2, 3);
    r.f.player_lap_m = 405.f;
    r.step(11.9);
    CHECK(r.a.snap() == kSnapSettle && r.a.packets() == 0);
    r.f.player_lap_m = -1.f; // unknown for a frame: no jump either way
    r.step(12.0);
    CHECK(r.a.snap() == kSnapNone);
    r.f.player_lap_m = 5280.f;
    r.step(12.02);
    CHECK(r.a.snap() == kSnapNone);
    r.f.player_lap_m = 12.f; // the lap wraps
    r.swap(18, 19);
    r.step(12.04);
    CHECK(r.a.snap() == kSnapNone && r.codes(18) == kUp1);
    // the compact window around the player: the player's own pass moves the window (every row snaps); a pass between
    // two other cars inside it slides; no ▲ entry from below the window's last row
    auto pc = std::make_unique<AnimRig>(N, 15, Mode::compact);
    AnimRig &c = *pc;
    c.cfg.rows = 5;
    c.step(1.0);
    c.run(3.5);
    CHECK(c.v().start == 9 && c.v().rows == 5);
    c.swap(10, 11); // car 11 (the player) passes car 10
    c.step(3.6);
    CHECK(c.v().start == 8 && c.a.snap() == kSnapWindow && c.a.packets() == 0);
    c.swap(11, 12); // rows 3 and 4 of the window
    c.step(3.7);
    CHECK(c.a.snap() == kSnapNone && c.codes(3) == kAnU1 && c.codes(4) == kDn1);
}

static void test_anim_off()
{
    // Animations off: no packet, ever; on again: the first frame snaps, then motion
    AnimRig r;
    r.cfg.animation = false;
    r.step(1.0);
    r.run(3.5);
    r.swap(5, 6);
    r.step(3.6);
    CHECK(!r.a.on() && r.a.snap() == kSnapOff && r.a.packets() == 0 && r.a.row(5).seq == 0 &&
          r.a.stats().packets == 0);
    r.cfg.animation = true;
    r.step(3.7);
    CHECK(r.a.on() && r.a.snap() == kSnapFirst && r.a.packets() == 0);
    r.swap(5, 6);
    r.step(3.8);
    CHECK(r.codes(5) == kUp1);
    // turned off while a row moves: its rest packet, then nothing
    r.cfg.animation = false;
    r.swap(8, 9);
    r.step(3.9);
    CHECK(r.a.snap() == kSnapOff && r.codes(5) == kAnRs && r.codes(6) == kAnRs && r.a.packets() == 2 &&
          r.a.row(8).seq == 0 && r.run(6.0) == 0);
    // the tower off (setting, Time Trial board): the same
    r.cfg.animation = true;
    r.run(6.2);
    r.swap(5, 6);
    r.step(6.3);
    CHECK(r.codes(5) == kUp1);
    r.cfg.enabled = false;
    r.step(6.4);
    CHECK(!r.v().on && r.a.snap() == kSnapOff && r.codes(5) == kAnRs && r.a.packets() == 2 && r.run(7.0) == 0);
    r.cfg.enabled = true;
    r.step(7.1);
    CHECK(r.v().on && r.a.snap() == kSnapFirst && r.a.packets() == 0);
}

static void test_anim_flash()
{
    // Qualifying: a car's new best lap fades in (by vehicle id), with its slide when it gains places
    AnimRig r(N, 5);
    r.s = timed(r.s);
    r.step(1.0);
    r.run(3.5);
    const int car = r.ord[5];
    r.s.cls.lap_s[car] = 80.2f; // between P2 (80.125) and P3 (80.25): P3, green
    r.move(5, 2);
    r.step(3.6);
    CHECK(r.v().row[2].vid == car && r.v().row[2].pb && r.v().fx[car] == 1);
    CHECK(r.codes(2) == (kAnU3 | kAnEu | kAnFf) && r.codes(3) == kDn1 && r.codes(4) == kDn1 && r.codes(5) == kDn1);
    // a new best that keeps the place: the fade alone; the green row pushed down by a later pass: no second fade
    r.run(4.55);
    CHECK(r.codes(2) == kAnRs && r.codes(5) == kAnRs);
    const int c8 = r.ord[8];
    r.s.cls.lap_s[c8] -= 0.01f;
    r.step(4.6);
    CHECK(r.v().row[8].pb && r.codes(8) == kAnFf && r.a.packets() == 1);
    r.step(4.6 + kFadeRest + 0.01);
    CHECK(r.codes(8) == kAnRs);
    const int c9 = r.ord[9];
    r.s.cls.lap_s[c9] = 79.9f; // purple: P1
    r.move(9, 0);
    r.step(5.2);
    CHECK(r.v().row[0].ob && r.codes(0) == kAnFf && r.v().row[9].pb);
    // (a 9-place move: the car snaps, its fade still runs; rows 1-9 slide down one, row 9 keeps car 8's flash: no ff)
    CHECK((r.codes(9) & kAnFf) == 0 && r.codes(9) == kDn1 && r.codes(1) == (kAnD1));
    // the session changes with a new time: no fade (every row snaps)
    r.run(8.0);
    r.f.session = 6;
    const int c12 = r.ord[12];
    r.s.cls.lap_s[c12] -= 0.01f;
    r.step(8.1);
    CHECK(r.a.snap() == kSnapSession && (r.codes(12) & kAnFf) == 0);
    // the compact window: the player's own new best moves the window; its fade still runs
    auto pc = std::make_unique<AnimRig>(N, 5, Mode::compact);
    AnimRig &c = *pc;
    c.cfg.rows = 5;
    c.s = timed(c.s);
    c.step(1.0);
    c.run(3.5);
    c.s.cls.lap_s[11] = 80.9f; // the player (car 11, P12) to P9: between 80.875 (P8) and 81.0 (P9)
    c.move(11, 8);
    c.step(3.6);
    CHECK(c.a.snap() == kSnapWindow && c.v().start == 6 && c.v().row[2].vid == 11 && c.v().row[2].pb &&
          c.codes(2) == kAnFf && c.a.packets() == 1);
}

// what the publisher wrote: path and value, in order
struct ValueRec {
    std::vector<std::string> path;
    std::vector<int32_t> value;
    std::vector<std::string> text;
};
static int value_set(void *ctx, const char *path, LeafType type, const void *v)
{
    ValueRec &r = *static_cast<ValueRec *>(ctx);
    r.path.push_back(path);
    r.value.push_back(type == LeafType::text ? 0 : *static_cast<const int32_t *>(v));
    r.text.push_back(type == LeafType::text ? static_cast<const char *>(v) : "");
    return 0;
}

static int first_index(const ValueRec &w, size_t from, const std::string &p)
{
    for (size_t i = from; i < w.path.size(); ++i)
        if (w.path[i] == p)
            return int(i);
    return -1;
}

// the row of an anim leaf's path (hud_tt_rNN_<xu1 ... xrs>, v12), -1 for any other leaf
static int anim_row_of(const std::string &q)
{
    static const char *const kKeys[] = {"xu1", "xu2", "xu3", "xd1", "xd2", "xd3", "xeu", "xed", "xnf", "xff", "xrs"};
    const std::string P = "view_model_data.hud_tt_r";
    if (q.size() != P.size() + 6 || q.compare(0, P.size(), P) != 0 || q[P.size() + 2] != '_')
        return -1;
    for (const char *k : kKeys)
        if (q.compare(P.size() + 3, 3, k) == 0)
            return (q[P.size()] - '0') * 10 + (q[P.size() + 1] - '0');
    return -1;
}

static int last_index(const ValueRec &w, size_t from, const std::string &p)
{
    int at = -1;
    for (size_t i = from; i < w.path.size(); ++i)
        if (w.path[i] == p)
            at = int(i);
    return at;
}

static void test_anim_leaves()
{
    auto pub = std::make_unique<Publisher>();
    Publisher &p = *pub;
    // contract v12: per row xu1 xu2 xu3 xd1 xd2 xd3 xeu xed xnf xff xrs (bool), after every older leaf; v11's
    // u1 ... rs and its trigger st are gone (st and u2 shared tS's hash)
    CHECK(p.count() == kAllLeaves && kHeadBase == kLeaves + kRows * 11 && kAnimLeaves == 11);
    CHECK(id_of(p, "r00_xu1") == kAnimBase && id_of(p, "r29_xrs") == kHeadBase - 1 &&
          id_of(p, "r07_xrs") == Publisher::anim_leaf(7, 10) && id_of(p, "r07_xff") == Publisher::anim_leaf(7, 9) &&
          id_of(p, "r30_xrs") == -1 && id_of(p, "r05_st") == -1 && id_of(p, "r05_u2") == -1 &&
          p.type(id_of(p, "r12_xeu")) == LeafType::boolean && p.type(id_of(p, "r12_xrs")) == LeafType::boolean);
    ValueRec w;
    p.set_sink(LeafSink{value_set, &w});
    AnimRig r;
    r.step(1.0);
    for (int k = 0; k < 200 && (k == 0 || p.dirty()); ++k)
        p.publish(r.v(), 1.0, kFrameBudget, &r.a);
    // on: every anim leaf went out false (at rest every code is false)
    bool all_false = p.dirty() == 0;
    for (int row = 0; row < kRows; ++row)
        for (int k = 0; k < kAnimLeaves; ++k)
            all_false = all_false && p.sent(Publisher::anim_leaf(row, k)) && p.sent_int(Publisher::anim_leaf(row, k)) == 0;
    CHECK(all_false);
    r.run(3.5);
    for (int k = 0; k < 5; ++k)
        p.publish(r.v(), r.t, kFrameBudget, &r.a);
    p.clear_events();
    // a swap: in one frame, each row's data, then its codes go true (row 5: xu1 and xeu; row 6: xd1 and xed)
    r.swap(5, 6);
    r.step(3.6);
    size_t from = w.path.size();
    p.publish(r.v(), 3.6, kFrameBudget, &r.a);
    const std::string P = "view_model_data.hud_tt_";
    const int u5 = last_index(w, from, P + "r05_xu1"), eu5 = last_index(w, from, P + "r05_xeu"),
              vid5 = last_index(w, from, P + "r05_vid"), d6 = last_index(w, from, P + "r06_xd1"),
              vid6 = last_index(w, from, P + "r06_vid");
    CHECK(vid5 > 0 && u5 > vid5 && eu5 > u5 && w.value[u5] == 1 && w.value[eu5] == 1 && vid6 > eu5 && d6 > vid6 &&
          w.value[d6] == 1 && last_index(w, from, P + "r05_xrs") == -1 && last_index(w, from, P + "r05_xd1") == -1 &&
          last_index(w, from, P + "r04_xu1") == -1);
    CHECK(p.events().n == 2 && p.events().e[0].row == 5 && p.events().e[0].what == (kAnU1 | kAnEu) &&
          p.events().e[1].row == 6 && p.events().e[1].what == (kAnD1 | kAnEd) && p.pending(5) == 0);
    // the pulse: true for kPulse, then false once; a true is never written twice
    from = w.path.size();
    for (int k = 1; 3.6 + k / 60.0 < 3.6 + kPulse - 1e-6; ++k)
        p.publish(r.v(), 3.6 + k / 60.0, kFrameBudget, &r.a);
    CHECK(last_index(w, from, P + "r05_xu1") == -1 && p.sent_int(id_of(p, "r05_xu1")) == 1);
    p.publish(r.v(), 3.6 + kPulse + 0.001, kFrameBudget, &r.a);
    const int u5off = last_index(w, from, P + "r05_xu1");
    CHECK(u5off >= 0 && w.value[u5off] == 0 && first_index(w, from, P + "r05_xu1") == u5off &&
          p.sent_int(id_of(p, "r05_xeu")) == 0 && p.sent_int(id_of(p, "r06_xd1")) == 0 && p.dirty() == 0);
    // ... and at least kPulseFrames frames apart, whatever the frame rate
    r.run(5.0);
    for (int k = 0; k < 5; ++k)
        p.publish(r.v(), r.t, kFrameBudget, &r.a);
    r.swap(8, 9);
    r.step(5.1);
    p.publish(r.v(), 5.1, kFrameBudget, &r.a);
    CHECK(p.sent_int(id_of(p, "r08_xu1")) == 1);
    p.publish(r.v(), 5.3, kFrameBudget, &r.a); // one frame later, kPulse passed
    CHECK(p.sent_int(id_of(p, "r08_xu1")) == 1);
    p.publish(r.v(), 5.31, kFrameBudget, &r.a);
    CHECK(p.sent_int(id_of(p, "r08_xu1")) == 0);
    // the rest packet once the play is over: xrs alone, as a pulse
    r.step(5.1 + kSlideRest + 0.01);
    CHECK(r.codes(8) == kAnRs && r.codes(9) == kAnRs);
    from = w.path.size();
    p.publish(r.v(), r.t, kFrameBudget, &r.a);
    const int rs8 = last_index(w, from, P + "r08_xrs");
    CHECK(rs8 >= 0 && w.value[rs8] == 1 && last_index(w, from, P + "r08_xu1") == -1);
    for (int k = 1; k <= 12; ++k)
        p.publish(r.v(), r.t + k / 60.0, kFrameBudget, &r.a);
    CHECK(p.sent_int(id_of(p, "r08_xrs")) == 0 && p.dirty() == 0);
    // re-arm: a code wanted again while its pulse still runs waits for its false, then kPulseFrames frames, then goes
    // true (here the publisher's clock lags the anim layer's; in the game both run on one clock and kBusy keeps a
    // row's slides apart, but the publisher keeps the rule on its own)
    r.run(8.0);
    const double tp = 20.0;
    for (int k = 0; k < 5; ++k)
        p.publish(r.v(), tp, kFrameBudget, &r.a);
    r.swap(14, 15);
    r.step(8.1);
    p.publish(r.v(), tp, kFrameBudget, &r.a);
    CHECK(r.codes(14) == kUp1 && p.sent_int(id_of(p, "r14_xu1")) == 1);
    r.run(8.1 + kFlicker + 0.1);
    r.swap(14, 15); // the car that left row 14 at 8.1 passes back, more than kFlicker later: a slide again
    r.step(r.t + 0.02);
    CHECK(r.codes(14) == kUp1);
    from = w.path.size();
    p.publish(r.v(), tp + 0.03, kFrameBudget, &r.a); // on the publisher's clock xu1's pulse still runs
    CHECK(last_index(w, from, P + "r14_xu1") == -1 && p.pending(14) == kUp1);
    p.publish(r.v(), tp + kPulse + 0.01, kFrameBudget, &r.a); // its false
    const int off14 = last_index(w, from, P + "r14_xu1");
    CHECK(off14 >= 0 && w.value[off14] == 0 && p.pending(14) == kUp1);
    p.publish(r.v(), tp + kPulse + 0.02, kFrameBudget, &r.a); // one frame later: still waits
    CHECK(p.sent_int(id_of(p, "r14_xu1")) == 0 && p.pending(14) == kUp1);
    p.publish(r.v(), tp + kPulse + 0.03, kFrameBudget, &r.a); // two frames: true again
    CHECK(p.sent_int(id_of(p, "r14_xu1")) == 1 && p.sent_int(id_of(p, "r14_xeu")) == 1 && p.pending(14) == 0);
    // a small budget: the row's codes wait with its data, never before it
    r.run(r.t + 3.0);
    for (int k = 0; k < 400 && p.dirty(); ++k)
        p.publish(r.v(), tp + 1.0 + k / 60.0, kFrameBudget, &r.a);
    for (int k = 0; k < 12; ++k)
        p.publish(r.v(), tp + 8.0 + k / 60.0, kFrameBudget, &r.a);
    CHECK(p.dirty() == 0);
    r.swap(5, 6);
    r.step(r.t + 0.02);
    CHECK(r.codes(5) == kUp1);
    from = w.path.size();
    const int u5id = id_of(p, "r05_xu1");
    double tq = tp + 9.0;
    for (int k = 0; k < 40 && (k == 0 || !p.sent_int(u5id)); ++k, tq += 1 / 60.0)
        p.publish(r.v(), tq, 3, &r.a);
    const int u5c = first_index(w, from, P + "r05_xu1"), vid5c = first_index(w, from, P + "r05_vid"),
              c05c = first_index(w, from, P + "r05_c05"), c06c = first_index(w, from, P + "r05_c06");
    CHECK(u5c > 0 && w.value[u5c] == 1 && vid5c >= 0 && vid5c < u5c && c05c >= 0 && c05c < u5c && c06c >= 0 &&
          c06c < u5c);
    // no anim leaf is ever rewritten at rest (the anim refresh is gone)
    for (int k = 0; k < 40; ++k, tq += 1 / 60.0)
        p.publish(r.v(), tq, kFrameBudget, &r.a);
    r.run(r.t + 2.0);
    for (int k = 0; k < 40; ++k, tq += 1 / 60.0)
        p.publish(r.v(), tq, kFrameBudget, &r.a);
    from = w.path.size();
    for (int k = 0; k < 300; ++k, tq += 1 / 60.0)
        p.publish(r.v(), tq, kFrameBudget, &r.a);
    int anim_writes = 0;
    for (size_t i = from; i < w.path.size(); ++i)
        anim_writes += anim_row_of(w.path[i]) >= 0;
    CHECK(anim_writes == 0 && w.path.size() - from >= 300);
}

// Animations off writes the static tower's leaves exactly: the same paths, values and frames as a publisher without the anim
// layer (the static tower's own code path), apart from hud_tt_anim's value (always true before; nothing binds it). On: the same
// static leaves end in the same values, with the packets on top.
static void test_anim_off_is_rc22()
{
    auto pa = std::make_unique<Publisher>(), pb = std::make_unique<Publisher>(), pc = std::make_unique<Publisher>();
    ValueRec wa, wb, wc;
    pa->set_sink(LeafSink{value_set, &wa});
    pb->set_sink(LeafSink{value_set, &wb});
    pc->set_sink(LeafSink{value_set, &wc});
    auto ra = std::make_unique<AnimRig>(N, 5), rb = std::make_unique<AnimRig>(N, 5), rc = std::make_unique<AnimRig>(N, 5);
    AnimRig &a = *ra, &b = *rb, &c = *rc;
    for (AnimRig *r : {&a, &b, &c})
        r->s = timed(r->s);
    b.cfg.animation = false;
    std::vector<int> fa, fb; // writes per frame
    double t = 1.0;
    for (int k = 0; k < 700; ++k, t += 1 / 60.0) {
        for (AnimRig *r : {&a, &b, &c}) {
            if (k == 250 || k == 400) // passes
                r->swap(5, 6);
            if (k == 300) { // a new best: P10 to P4
                r->s.cls.lap_s[r->ord[9]] = 80.3f;
                r->move(9, 3);
            }
            if (k == 500) // a big move
                r->move(20, 2);
            r->cfg.enabled = !(k >= 600 && k < 620); // the tower off and on
            r->step(t);
        }
        const int budget = k % 7 == 3 ? 9 : kFrameBudget; // some frames with a small budget (the halo took the rest)
        const size_t na = wa.path.size(), nb = wb.path.size();
        pa->publish(a.v(), t, budget); // no anim layer
        pb->publish(b.v(), t, budget, &b.a);
        pc->publish(c.v(), t, budget, &c.a);
        fa.push_back(int(wa.path.size() - na));
        fb.push_back(int(wb.path.size() - nb));
    }
    bool same = wa.path.size() == wb.path.size() && fa == fb;
    int anim_diff = 0, anim_b = 0, starts_c = 0;
    for (size_t i = 0; same && i < wa.path.size(); ++i) {
        same = wa.path[i] == wb.path[i] && wa.text[i] == wb.text[i];
        if (wa.path[i] == "view_model_data.hud_tt_anim")
            anim_diff += wa.value[i] == 1 && wb.value[i] == 0;
        else
            same = same && wa.value[i] == wb.value[i];
    }
    for (const std::string &q : wb.path)
        anim_b += anim_row_of(q) >= 0;
    for (size_t i = 0; i < wc.path.size(); ++i)
        starts_c += anim_row_of(wc.path[i]) >= 0 && wc.value[i] == 1;
    CHECK(same && anim_diff >= 1 && anim_b == 0 && wa.path.size() > 3000 && b.a.stats().packets == 0);
    CHECK(starts_c >= 8 && c.a.stats().slides >= 4 && c.a.stats().ff >= 1);
    // every static leaf ends in the same value with the layer on, off, or absent
    for (int k = 0; k < 400 && (k == 0 || pa->dirty() || pb->dirty() || pc->dirty()); ++k) {
        pa->publish(a.v(), t, kFrameBudget);
        pb->publish(b.v(), t, kFrameBudget, &b.a);
        pc->publish(c.v(), t, kFrameBudget, &c.a);
    }
    bool end_same = !pa->dirty() && !pb->dirty() && !pc->dirty();
    for (int id = 0; id < kLeaves; ++id) {
        end_same = end_same && pa->sent_int(id) == pc->sent_int(id) &&
                   std::strcmp(pa->sent_text(id), pc->sent_text(id)) == 0 &&
                   std::strcmp(pa->sent_text(id), pb->sent_text(id)) == 0 &&
                   (id == kAnim || pa->sent_int(id) == pb->sent_int(id));
    }
    CHECK(end_same && pa->sent_int(kAnim) == 1 && pb->sent_int(kAnim) == 0 && pc->sent_int(kAnim) == 1);
}


// ---------------------------------------------------------------- the header's card motion

static bool is_head_path(const std::string &q)
{
    static const char *const k[] = {"kin1",   "kin2",   "kin3",  "kout1",  "kout2",  "kout3",   "krs",
                                    "gh_chq", "gh_red", "gh_sc", "gh_vsc", "gh_yel", "gh_ysec", "gh_ysna"};
    for (const char *x : k)
        if (q == std::string("view_model_data.hud_tt_") + x)
            return true;
    return false;
}

// a race (session 15) with the model, the Anim and a publisher writing into a value recorder; the flags read fresh
// every frame (one read per frame: a yellow clears on the second non-yellow read)
struct HeadRig {
    std::unique_ptr<AnimRig> rig;
    AnimRig &r;
    std::unique_ptr<Publisher> pub = std::make_unique<Publisher>();
    ValueRec w;
    int yellow = 0;
    uint8_t ysec = 0;
    bool with_anim = true;
    explicit HeadRig(bool anim = true) : rig(std::make_unique<AnimRig>(N, 15)), r(*rig)
    {
        r.cfg.animation = anim;
        r.s.found_zones = r.s.found_red = true;
        r.f.player_lap_m = 500.f;
        pub->set_sink(LeafSink{value_set, &w});
    }
    // one frame at `now` -> the index of its first write
    size_t frame(double now)
    {
        ++r.f.frame_no;
        flag_read(r.s, now, yellow, ysec);
        r.step(now);
        const size_t from = w.path.size();
        pub->publish(r.v(), now, kFrameBudget, with_anim ? &r.a : nullptr);
        return from;
    }
    // frames at 60 fps up to (not including) `until` -> the header packets they made
    int run(double until)
    {
        int n = 0;
        for (double t = r.t + 1 / 60.0; t < until - 1e-9; t += 1 / 60.0) {
            frame(t);
            n += r.a.head_packets();
        }
        return n;
    }
    // the first write of hud_tt_<key> at or after `from` (value: any when < 0) -> its index, -1 none
    int at(size_t from, const char *key, int value = -1) const
    {
        const std::string q = std::string("view_model_data.hud_tt_") + key;
        for (size_t i = from; i < w.path.size(); ++i)
            if (w.path[i] == q && (value < 0 || w.value[i] == value))
                return int(i);
        return -1;
    }
    int head_writes(size_t from) const
    {
        int n = 0;
        for (size_t i = from; i < w.path.size(); ++i)
            n += is_head_path(w.path[i]);
        return n;
    }
};

static void test_head_leaves()
{
    auto pub = std::make_unique<Publisher>();
    Publisher &p = *pub;
    // contract v13: kin1 kin2 kin3 kout1 kout2 kout3 krs gh_chq gh_red gh_sc gh_vsc gh_yel (bool), gh_ysec (text),
    // gh_ysna (bool), after every older leaf
    CHECK(p.count() == kAllLeaves && kAllLeaves == kHeadBase + 14 && kHeadBase == kAnimBase + kRows * kAnimLeaves);
    CHECK(id_of(p, "kin1") == Publisher::head_leaf(0) && id_of(p, "kin3") == Publisher::head_leaf(2) &&
          id_of(p, "kout1") == Publisher::head_leaf(3) && id_of(p, "krs") == Publisher::head_leaf(6) &&
          id_of(p, "gh_chq") == Publisher::ghost_leaf(kCardChq) && id_of(p, "gh_red") == Publisher::ghost_leaf(kCardRed) &&
          id_of(p, "gh_yel") == Publisher::ghost_leaf(kCardYel) && id_of(p, "gh_ysec") == kHeadYsec &&
          id_of(p, "gh_ysna") == kHeadYsna && kHeadYsna == kAllLeaves - 1 && kHeadGhost == kHeadBase + kHeadCodes);
    bool types = p.type(kHeadYsec) == LeafType::text;
    for (int id = kHeadBase; id < kAllLeaves; ++id)
        types = types && (id == kHeadYsec || p.type(id) == LeafType::boolean);
    CHECK(types && card_size(kCardChq) == 1 && card_size(kCardRed) == 2 && card_size(kCardSc) == 2 &&
          card_size(kCardVsc) == 3 && card_size(kCardYel) == 2 && card_size(kCardNone) == 0);
}

static void test_head_motion()
{
    HeadRig h;
    AnimRig &r = h.r;
    Publisher &p = *h.pub;
    h.frame(1.0);
    CHECK(r.a.head_packets() == 0 && r.a.head().seq == 0);
    h.run(3.5); // past the first frame's settle
    bool rest = p.dirty() == 0;
    for (int id = kHeadBase; id < kAllLeaves; ++id)
        rest = rest && p.sent(id) && p.sent_int(id) == 0;
    CHECK(rest && p.sent_text(kHeadYsec)[0] == 0 && p.sent_card() == kCardNone);
    // 1. the safety car: in one frame hud_tt_sc goes true, then kin2 (the 2 p card)
    r.s.sc.state = 1;
    size_t f0 = h.frame(3.5);
    CHECK(r.v().sc && r.a.head_packets() == 1 && r.a.head().codes == kHdIn2 && r.a.head().ghost == kCardNone &&
          r.a.head_moving());
    const int sc1 = h.at(f0, "sc", 1), in2 = h.at(f0, "kin2", 1);
    CHECK(sc1 >= 0 && in2 > sc1 && p.sent_card() == kCardSc && h.head_writes(f0) == 1);
    // the publisher's events: the card and its code in one frame (the hdk column)
    const HeadEvents &he = p.head_events();
    bool same_frame = false;
    for (int i = 0; i + 1 < he.n; ++i)
        same_frame = same_frame || (he.e[i].kind == 'c' && he.e[i].card == kCardSc && he.e[i + 1].kind == 'k' &&
                                    he.e[i + 1].code == 1 && he.e[i].frame == he.e[i + 1].frame && he.e[i].frame == r.f.frame_no);
    CHECK(same_frame);
    // kin2 goes back to false kPulse later; nothing else until the rest packet kSlideRest after the start
    CHECK(h.run(3.5 + kSlideRest - 0.01) == 0 && p.sent_int(Publisher::head_leaf(1)) == 0 && r.a.head_moving());
    f0 = h.frame(3.5 + kSlideRest + 0.005);
    CHECK(r.a.head_packets() == 1 && r.a.head().codes == kHdRs && !r.a.head_moving() && h.at(f0, "krs", 1) >= 0);
    CHECK(h.run(6.0) == 0);
    // 2. the safety car goes: in one frame sc false, the copy gh_sc, then kout2
    r.s.sc.state = 0;
    f0 = h.frame(6.0);
    CHECK(r.a.head().codes == kHdOut2 && r.a.head().ghost == kCardSc && r.a.stats().hd_out == 1);
    const int sc0 = h.at(f0, "sc", 0), gsc = h.at(f0, "gh_sc", 1), out2 = h.at(f0, "kout2", 1);
    CHECK(sc0 >= 0 && gsc > sc0 && out2 > gsc && p.sent_card() == kCardNone);
    // the copy holds kGhost; it goes in the frame of the rest packet
    CHECK(h.run(6.0 + kGhost - 0.01) == 0 && p.sent_int(Publisher::ghost_leaf(kCardSc)) == 1);
    f0 = h.frame(6.0 + kGhost + 0.005);
    CHECK(r.a.head().codes == kHdRs && r.a.head().ghost == kCardNone && h.at(f0, "gh_sc", 0) >= 0 &&
          h.at(f0, "krs", 1) >= 0);
    h.run(8.0);
    // 3. a yellow (sector 2, then sector 1) whose sectors clear in the very frame its card goes: the copy holds the
    //    sector the card showed
    h.yellow = 1;
    h.ysec = 0b010;
    f0 = h.frame(8.0);
    CHECK(r.v().yel && std::strcmp(r.v().ysec, "2") == 0 && r.a.head().codes == kHdIn2 && h.at(f0, "kin2", 1) >= 0);
    h.run(10.0);
    h.ysec = 0b001;
    h.run(10.5);
    CHECK(std::strcmp(p.sent_text(kYsec), "1") == 0 && p.sent_card() == kCardYel);
    h.yellow = 0;
    h.frame(10.5); // one non-yellow read: held, with its sectors
    CHECK(r.v().yel && r.a.head_packets() == 0);
    f0 = h.frame(10.5 + 1 / 60.0); // the second: the card and its sectors go in one frame
    CHECK(!r.v().yel && r.v().ysec[0] == 0 && r.a.head().codes == kHdOut2 && r.a.head().ghost == kCardYel);
    const int ys0 = h.at(f0, "ysec"), gys = h.at(f0, "gh_ysec"), gy = h.at(f0, "gh_yel", 1), o2 = h.at(f0, "kout2", 1);
    CHECK(ys0 >= 0 && h.w.text[ys0].empty() && gys > ys0 && h.w.text[gys] == "1" && gy > gys && o2 > gy);
    CHECK(h.at(f0, "gh_ysna", 1) < 0 && std::strcmp(p.sent_text(kHeadYsec), "1") == 0);
    h.run(13.0);
    CHECK(p.sent_int(Publisher::ghost_leaf(kCardYel)) == 0 && std::strcmp(p.sent_text(kHeadYsec), "1") == 0);
    // 4. busy: a VSC (the 2.5 p card) that goes again within its play: at once, the motion to rest, no copy
    r.s.sc.state = 2;
    f0 = h.frame(13.0);
    CHECK(r.a.head().codes == kHdIn3 && h.at(f0, "kin3", 1) >= 0);
    h.run(13.3);
    r.s.sc.state = 0;
    f0 = h.frame(13.3);
    CHECK(r.a.head().codes == kHdRs && r.a.head().ghost == kCardNone && r.a.stats().hd_busy == 1 &&
          h.at(f0, "krs", 1) >= 0 && h.at(f0, "vsc", 0) >= 0 && h.at(f0, "gh_vsc", 1) < 0 && !r.a.head_moving());
    CHECK(h.run(15.0) == 0);
    // 5. one card for another (SC, then VSC once the SC's play is over): at once, nothing written but the state
    r.s.sc.state = 1;
    h.frame(15.0);
    CHECK(r.a.head().codes == kHdIn2);
    h.run(17.0);
    r.s.sc.state = 2;
    const uint32_t seq = r.a.head().seq;
    f0 = h.frame(17.0);
    CHECK(r.a.head().seq == seq && r.a.head_packets() == 0 && p.sent_card() == kCardVsc && h.head_writes(f0) == 0);
    h.run(19.0);
    r.s.sc.state = 0; // the VSC goes: kout3 with its copy
    f0 = h.frame(19.0);
    CHECK(r.a.head().codes == kHdOut3 && r.a.head().ghost == kCardVsc && h.at(f0, "gh_vsc", 1) >= 0 &&
          h.at(f0, "kout3", 1) >= 0);
    h.run(21.0);
    // 6. the chequered flag: the 1 p card
    r.s.cls.status[r.ord[0]] = 3;
    f0 = h.frame(21.0);
    CHECK(r.v().chq && r.a.head().codes == kHdIn1 && h.at(f0, "kin1", 1) >= 0);
    h.run(23.0);
    r.s.cls.status[r.ord[0]] = 2;
    f0 = h.frame(23.0);
    CHECK(r.a.head().codes == kHdOut1 && r.a.head().ghost == kCardChq && h.at(f0, "kout1", 1) >= 0);
    h.run(25.0);
    CHECK(r.a.stats().hd_in == 5 && r.a.stats().hd_out == 4 && !r.a.head_moving() && r.a.head().ghost == kCardNone);
}

// every way the card may change without its motion: the Tower header setting, its return with a card on, a replay
// jump, the settle after it, a spectator switch, a session change, Animations off
static void test_head_snaps()
{
    HeadRig h;
    AnimRig &r = h.r;
    Publisher &p = *h.pub;
    h.frame(1.0);
    h.run(3.5);
    // the header setting goes off while an exit's copy shows: the copy goes, the motion to rest
    r.s.sc.state = 1;
    h.frame(3.5);
    h.run(5.0);
    r.s.sc.state = 0;
    h.frame(5.0);
    CHECK(r.a.head().ghost == kCardSc && p.sent_int(Publisher::ghost_leaf(kCardSc)) == 1);
    h.run(5.2);
    r.cfg.header = false;
    size_t f0 = h.frame(5.2);
    CHECK(r.a.head().codes == kHdRs && r.a.head().ghost == kCardNone && h.at(f0, "gh_sc", 0) >= 0 &&
          h.at(f0, "krs", 1) >= 0 && r.a.stats().hd_cut == 1 && !r.a.head_moving());
    // a card comes while the header is off, the header comes back with it on: no motion
    h.run(7.0);
    r.s.sc.state = 1;
    h.run(8.0);
    CHECK(p.sent_int(kSc) == 1 && p.sent_int(kHdr) == 0);
    r.cfg.header = true;
    uint32_t seq = r.a.head().seq;
    f0 = h.frame(8.0);
    CHECK(r.a.head().seq == seq && h.head_writes(f0) == 0 && p.sent_card() == kCardSc);
    h.run(10.0);
    // a replay jump in the frame the card goes: at once, no copy; within the settle after it, a card comes at once
    r.s.sc.state = 0;
    r.f.player_lap_m = 900.f;
    seq = r.a.head().seq;
    f0 = h.frame(10.0);
    CHECK(r.a.snap() == kSnapJump && r.a.head().seq == seq && r.a.head().ghost == kCardNone && h.head_writes(f0) == 0);
    h.run(10.5);
    r.s.sc.state = 2;
    f0 = h.frame(10.5);
    CHECK(r.a.snap() == kSnapSettle && r.a.head().seq == seq && h.head_writes(f0) == 0 && p.sent_card() == kCardVsc);
    h.run(13.0);
    // a spectator switch in the frame the card goes
    r.s.sc.state = 0;
    r.f.player = 12;
    f0 = h.frame(13.0);
    CHECK(r.a.snap() == kSnapPlayer && r.a.head().seq == seq && h.head_writes(f0) == 0 && p.sent_card() == kCardNone);
    h.run(15.0);
    // a session change in the frame a card comes
    r.s.sc.state = 1;
    r.f.session = 16;
    f0 = h.frame(15.0);
    CHECK(r.a.snap() == kSnapSession && r.a.head().seq == seq && h.head_writes(f0) == 0 && p.sent_card() == kCardSc);
    h.run(18.0);
    // a motion in flight is cut by a jump: the rest packet, the copy goes
    r.s.sc.state = 0;
    f0 = h.frame(18.0);
    CHECK(r.a.head().codes == kHdOut2 && r.a.head().ghost == kCardSc);
    h.run(18.3);
    r.f.player_lap_m = 100.f;
    f0 = h.frame(18.3);
    CHECK(r.a.snap() == kSnapJump && r.a.head().codes == kHdRs && r.a.head().ghost == kCardNone &&
          h.at(f0, "gh_sc", 0) >= 0 && h.at(f0, "krs", 1) >= 0 && r.a.stats().hd_cut == 2);
    h.run(21.0);
    // the Animations setting goes off right after an exit: the copy goes and the rest packet finishes the motion;
    // then not one header leaf is written, whatever the card does
    r.s.sc.state = 1;
    h.frame(21.0);
    h.run(23.0);
    r.s.sc.state = 0;
    h.frame(23.0);
    CHECK(r.a.head().ghost == kCardSc);
    r.cfg.animation = false;
    f0 = h.frame(23.0 + 1 / 60.0);
    CHECK(r.a.head().codes == kHdRs && r.a.head().ghost == kCardNone && h.at(f0, "gh_sc", 0) >= 0 &&
          h.at(f0, "krs", 1) >= 0);
    h.run(23.5); // the rest's pulse goes back to false
    CHECK(p.sent_int(Publisher::head_leaf(6)) == 0 && p.dirty() == 0);
    const size_t from = h.w.path.size();
    for (double t = 24.0; t < 30.0; t += 2.0) {
        r.s.sc.state = r.s.sc.state ? 0 : 1;
        h.run(t);
    }
    CHECK(h.head_writes(from) == 0 && h.w.path.size() > from && p.sent_card() != kCardNone);
}

// Animations off: v12's writes exactly (the same paths, values and frames as without the anim layer) through card
// changes; not one header leaf; on: the header's leaves on top, every v12 leaf ending in the same value
static void test_head_off_is_rc23b()
{
    HeadRig a(false), b(false), c(true);
    a.with_anim = false;
    std::vector<int> fa, fb;
    double t = 1.0;
    for (int k = 0; k < 1500; ++k, t += 1 / 60.0) {
        for (HeadRig *h : {&a, &b, &c}) {
            AnimRig &r = h->r;
            if (k == 300 || k == 700)
                r.s.sc.state = 1;
            if (k == 500 || k == 740) // the second within the play
                r.s.sc.state = 0;
            if (k == 900)
                r.s.sc.state = 2;
            if (k == 1000)
                r.s.sc.state = 1; // VSC -> SC
            if (k == 1100)
                r.s.sc.state = 0;
            h->yellow = k >= 1200 && k < 1350 ? 1 : 0;
            h->ysec = 0b100;
            if (k == 1400)
                r.cfg.header = false;
            const size_t n0 = h->w.path.size();
            h->frame(t);
            if (h != &c)
                (h == &a ? fa : fb).push_back(int(h->w.path.size() - n0));
        }
    }
    bool same = a.w.path.size() == b.w.path.size() && fa == fb;
    for (size_t i = 0; same && i < a.w.path.size(); ++i)
        same = a.w.path[i] == b.w.path[i] && a.w.text[i] == b.w.text[i] && a.w.value[i] == b.w.value[i];
    CHECK(same && a.head_writes(0) == 0 && b.head_writes(0) == 0 && a.w.path.size() > 3000);
    CHECK(c.head_writes(0) > 20 && c.r.a.stats().hd_in == 4 && c.r.a.stats().hd_out == 3 && c.r.a.stats().hd_busy == 1 &&
          c.r.a.stats().hd_cut == 1);
    for (HeadRig *h : {&a, &b, &c})
        for (int k = 0; k < 400 && (k == 0 || h->pub->dirty()); ++k)
            h->frame(t);
    bool end_same = true;
    for (int id = 0; id < kLeaves; ++id)
        end_same = end_same && a.pub->sent_int(id) == b.pub->sent_int(id) &&
                   std::strcmp(a.pub->sent_text(id), b.pub->sent_text(id)) == 0 &&
                   std::strcmp(a.pub->sent_text(id), c.pub->sent_text(id)) == 0 &&
                   (id == kAnim || a.pub->sent_int(id) == c.pub->sent_int(id));
    CHECK(end_same && c.pub->sent_int(kAnim) == 1 && a.pub->sent_int(kAnim) == 0);
}

int main(int argc, char **argv)
{
    test_reader_basic();
    test_reader_rates();
    test_reader_classification();
    test_reader_no_ers();
    test_reader_timing_pit_sc();
    test_reader_penalties();
    test_reader_tyres();
    test_reader_reset();
    test_reader_flags();
    test_reader_badges();
    test_reader_badges_long();
    test_reader_mode();
    test_badge_text();
    test_window();
    test_texts();
    test_model_race();
    test_model_flags();
    test_model_flag_header();
    test_reader_spectator_laps();
    test_reader_detail();
    test_spectator_texts();
    test_model_spectator();
    test_best_laps();
    test_reader_best_laps();
    test_knockout();
    test_ko_clock_leaves();
    test_ko_game_order();
    test_flash();
    test_race_fastest_lap();
    test_spectator_race_best();
    test_spectator_lap_rule();
    test_reader_laptimes();
    test_render_badges();
    test_rc19_glitches();
    test_flash_leaves();
    test_spectator_best_laps();
    test_spectator_leaves();
    test_model_flag_zones_red();
    test_model_arrows();
    test_model_auto();
    test_model_modes();
    test_model_badges();
    test_model_trial();
    test_trial_leaves();
    test_leaves(argc > 1 ? argv[1] : nullptr);
    test_anim_slide();
    test_anim_nf_late_frame();
    test_anim_rows();
    test_anim_flicker();
    test_anim_snaps();
    test_anim_off();
    test_anim_flash();
    test_anim_leaves();
    test_anim_off_is_rc22();
    test_head_leaves();
    test_head_motion();
    test_head_snaps();
    test_head_off_is_rc23b();
    test_badge_leaves();
    test_end_to_end();
    test_end_to_end_flags();
    test_log_writer(argc > 1 ? argv[1] : nullptr);
    bench();
    bench(true);
    bench(false, 30); // 30 cars
    bench(false, 30, true); // every row, with the motion layer
    std::printf("tower: %d passed, %d failed\n", g_pass, g_fail);
    return g_fail ? 1 : 0;
}
