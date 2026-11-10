// Host tests for the tower_state prototype readers (Phase 2). Not part of the DLL build or run_tests.sh.
// Builds a synthetic memory image (address -> bytes) with the layouts in docs/timing-tower/field-traces.md and
// checks decoding, the game's own rules and that every broken or absent input reads as unavailable.
// Build and run: sh tools/tower_re/run_tower_tests.sh [out-dir]
#include "../src/tower_state.hpp"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
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

// Synthetic address space: regions of bytes at fixed fake addresses. A read must lie inside one region.
struct Image {
    std::map<uintptr_t, std::vector<uint8_t>> regions;
    uintptr_t next = 0x10000000;

    uintptr_t alloc(size_t n)
    {
        const uintptr_t a = next;
        regions[a] = std::vector<uint8_t>(n, 0);
        next += (n + 0xfff) & ~size_t(0xfff);
        next += 0x1000; // guard gap: reads past the end fail
        return a;
    }
    uint8_t *at(uintptr_t a, size_t n)
    {
        auto it = regions.upper_bound(a);
        if (it == regions.begin())
            return nullptr;
        --it;
        if (a < it->first || a + n > it->first + it->second.size())
            return nullptr;
        return it->second.data() + (a - it->first);
    }
    template <class T> void put(uintptr_t a, T v)
    {
        uint8_t *p = at(a, sizeof v);
        if (!p) {
            std::printf("test bug: put outside a region at %#llx\n", (unsigned long long)a);
            ++g_fail;
            return;
        }
        std::memcpy(p, &v, sizeof v);
    }
    static bool read(void *ctx, uintptr_t a, void *dst, size_t n)
    {
        uint8_t *p = static_cast<Image *>(ctx)->at(a, n);
        if (!p)
            return false;
        std::memcpy(dst, p, n);
        return true;
    }
    Mem mem() { return Mem{&Image::read, this}; }
    // A vector [begin, end) stored at `at` with n elements of `stride` bytes.
    uintptr_t vec(uintptr_t at, size_t n, size_t stride)
    {
        const uintptr_t b = n ? alloc(n * stride) : 0;
        put<uintptr_t>(at, b);
        put<uintptr_t>(at + 8, b + n * stride);
        return b;
    }
};

static uint64_t bits_of(double d)
{
    uint64_t b;
    std::memcpy(&b, &d, sizeof b);
    return b;
}

static void test_registry()
{
    Image im;
    const Mem m = im.mem();
    const uintptr_t reg = im.alloc(0x40);
    const size_t n = 100; // more than one 64-slot chunk
    const uintptr_t slots = im.alloc(n * 16 + n);
    const uintptr_t info = slots + n * 16;
    im.put<uintptr_t>(reg + 0x18, slots);
    im.put<uintptr_t>(reg + 0x20, info);
    const uintptr_t k1 = 0x14607f1a0, k2 = 0x1460fdfe0, k3 = 0x146100bd8, k4 = 0x146080d28;
    auto slot = [&](size_t i, uintptr_t key, uintptr_t value, uint8_t used) {
        im.put<uintptr_t>(slots + i * 16, key);
        im.put<uintptr_t>(slots + i * 16 + 8, value);
        im.put<uint8_t>(info + i, used);
    };
    slot(3, k1, 0x20000010, 1);
    slot(70, k2, 0x20000020, 1);  // second chunk
    slot(10, k3, 0x20000030, 0);  // not in use
    slot(11, k4, 0x20000033, 1);  // misaligned value
    CHECK(find_in_registry(m, reg, k1) == 0x20000010);
    CHECK(find_in_registry(m, reg, k2) == 0x20000020);
    CHECK(find_in_registry(m, reg, k3) == 0);
    CHECK(find_in_registry(m, reg, k4) == 0);
    CHECK(find_in_registry(m, reg, 0x146000000) == 0);
    CHECK(find_in_registry(m, 0, k1) == 0);
    im.put<uintptr_t>(reg + 0x20, slots + 8); // not a whole slot
    CHECK(find_in_registry(m, reg, k1) == 0);
    im.put<uintptr_t>(reg + 0x20, slots + 5000 * 16); // too many slots
    CHECK(find_in_registry(m, reg, k1) == 0);
}

static void put_penalty(Image &im, uintptr_t r, uint8_t vid, uint8_t pen, uint8_t inf, uint32_t time_s, uint32_t lap)
{
    im.put<uint64_t>(r + 0x00, 123456); // timestamp (not decoded)
    im.put<uint8_t>(r + 0x08, vid);
    im.put<uint8_t>(r + 0x09, pen);
    im.put<uint8_t>(r + 0x0a, inf);
    im.put<uint8_t>(r + 0x0b, 0xff);
    im.put<uint32_t>(r + 0x0c, time_s);
    im.put<uint32_t>(r + 0x10, lap);
    im.put<uint32_t>(r + 0x18, 0);
    im.put<uint32_t>(r + 0x20, 0);
    im.put<uint32_t>(r + 0x2c, 2);
}

static void test_penalties()
{
    Image im;
    const Mem m = im.mem();
    const uintptr_t z = im.alloc(0xa8);
    const size_t n = 40; // more than one 32-record chunk
    const uintptr_t recs = im.vec(z + 0x48, n, kPenaltyStride);
    for (size_t i = 0; i < n; ++i) // filler for other cars
        put_penalty(im, recs + i * 0x30, 10, 3, 15, 0, 1);
    put_penalty(im, recs + 0 * 0x30, 3, 5, 7, 0, 2);   // warning, corner cutting gained time (track limits)
    put_penalty(im, recs + 1 * 0x30, 3, 4, 17, 5, 3);  // 5 s time penalty
    put_penalty(im, recs + 2 * 0x30, 3, 5, 21, 0, 4);  // warning, not in the mask
    put_penalty(im, recs + 35 * 0x30, 3, 5, 29, 0, 9); // warning, bit 29 (second chunk)
    put_penalty(im, recs + 36 * 0x30, 3, 5, 30, 0, 9); // warning, infringement > 0x1d: not track limits
    put_penalty(im, recs + 37 * 0x30, 5, 5, 26, 0, 9); // other car

    PenaltyRecord out[8];
    CHECK(read_penalties(m, z, 3, out, 8) == 5);
    CHECK(out[0].penalty == 5 && out[0].infringement == 7 && out[0].lap == 2 && out[0].safety_points == 2);
    CHECK(out[1].penalty == 4 && out[1].time_s == 5 && out[1].lap == 3);
    CHECK(read_penalties(m, z, 3, out, 2) == 5); // count beyond max, only 2 copied
    CHECK(read_penalties(m, z, 0xff, nullptr, 0) == int(n));

    WarningCounts w;
    CHECK(count_warnings(m, z, 3, w) && w.total == 4 && w.track_limits == 2);
    CHECK(count_warnings(m, z, 5, w) && w.total == 1 && w.track_limits == 1);
    CHECK(count_warnings(m, z, 7, w) && w.total == 0 && w.track_limits == 0);
    const WarningCounts w2 = count_warnings(out, 2, 3);
    CHECK(w2.total == 1 && w2.track_limits == 1);

    // Empty log: valid, nothing to show.
    const uintptr_t z2 = im.alloc(0xa8);
    CHECK(read_penalties(m, z2, 3, out, 8) == 0);
    CHECK(count_warnings(m, z2, 3, w) && w.total == 0);
    // Broken log: unavailable.
    im.put<uintptr_t>(z2 + 0x48, recs);
    im.put<uintptr_t>(z2 + 0x50, recs + 0x31);
    CHECK(read_penalties(m, z2, 3, out, 8) == -1);
    CHECK(!count_warnings(m, z2, 3, w));
    CHECK(read_penalties(m, 0, 3, out, 8) == -1);
    im.put<uintptr_t>(z2 + 0x50, recs + 2000 * 0x30); // past the sanity bound
    CHECK(read_penalties(m, z2, 3, out, 8) == -1);
}

static void test_misconduct()
{
    Image im;
    const Mem m = im.mem();
    const uintptr_t s1 = im.alloc(0x7b8);
    const uintptr_t dt = im.alloc(0x80), sg = im.alloc(0x80);
    im.put<uintptr_t>(s1 + misconduct::drive_through, dt);
    im.put<uintptr_t>(s1 + misconduct::stop_go, sg);
    const uintptr_t dts = im.vec(dt + 0x68, 4, 0x28);
    for (int i = 0; i < 4; ++i)
        for (int s = 0; s < 4; ++s)
            im.put<uint8_t>(dts + i * 0x28 + 8 + s * 8, 0xff);
    im.put<uint8_t>(dts + 1 * 0x28 + 0x08, 2);
    im.put<uint8_t>(dts + 1 * 0x28 + 0x18, 7);
    const uintptr_t sgs = im.vec(sg + 0x68, 4, 4);
    im.put<uint8_t>(sgs + 2 * 4 + 3, 1);

    int n = -1;
    CHECK(unserved_drive_throughs(m, s1, 1, n) && n == 2);
    CHECK(unserved_drive_throughs(m, s1, 0, n) && n == 0);
    CHECK(unserved_drive_throughs(m, s1, 9, n) && n == 0); // past the end: the game's 0
    CHECK(unserved_stop_gos(m, s1, 2, n) && n == 1);
    CHECK(unserved_stop_gos(m, s1, 3, n) && n == 0);
    CHECK(unserved_stop_gos(m, s1, 30, n) && n == 0);
    im.put<uintptr_t>(s1 + misconduct::stop_go, 0); // object absent
    CHECK(!unserved_stop_gos(m, s1, 2, n));
    im.put<uintptr_t>(dt + 0x70, dts + 0x29); // broken vector
    CHECK(!unserved_drive_throughs(m, s1, 1, n));
    CHECK(!unserved_drive_throughs(m, 0, 1, n));
}

static void test_results_fields()
{
    Image im;
    const Mem m = im.mem();
    const uintptr_t r = im.alloc(0x160);
    const uintptr_t ptrs = im.vec(r + 0x148, 4, 8);
    uintptr_t p[4];
    for (int i = 0; i < 4; ++i) {
        p[i] = im.alloc(0x98);
        im.put<uintptr_t>(ptrs + i * 8, p[i]);
        im.put<uint8_t>(p[i], uint8_t(i));
        const uint64_t key = 0x5a5a1234deadbeefull + i;
        im.put<uint64_t>(p[i] + 0x38, bits_of(0.0) ^ key);
        im.put<uint64_t>(p[i] + 0x40, key);
        im.put<uint8_t>(p[i] + 0x18, 2);
    }
    im.put<uint64_t>(p[2] + 0x38, bits_of(10.0) ^ (0x5a5a1234deadbeefull + 2));
    im.put<uint8_t>(p[3] + 0x18, 5);

    double s = -1;
    CHECK(time_penalty_seconds(m, r, 2, s) && s == 10.0);
    CHECK(time_penalty_seconds(m, r, 1, s) && s == 0.0);
    CHECK(!time_penalty_seconds(m, r, 4, s)); // no entry
    uint8_t st = 0;
    CHECK(result_status(m, r, 3, st) && st == 5);
    CHECK(result_status(m, r, 0, st) && st == 2);
    im.put<uint8_t>(p[3] + 0x18, 9);
    CHECK(!result_status(m, r, 3, st));
    im.put<uint8_t>(p[1], 7); // entry does not read back its vehicle id
    CHECK(!time_penalty_seconds(m, r, 1, s));
    im.put<uint64_t>(p[2] + 0x40, 0); // NaN-ish / garbage after a bad XOR key
    im.put<uint64_t>(p[2] + 0x38, 0x7ff8000000000000ull);
    CHECK(!time_penalty_seconds(m, r, 2, s));
    im.put<uint64_t>(p[2] + 0x38, bits_of(-5.0));
    CHECK(!time_penalty_seconds(m, r, 2, s));
}

static void test_safety_car()
{
    Image im;
    const Mem m = im.mem();
    const uintptr_t sc = im.alloc(0x200);
    CHECK(safety_car_state(m, sc) == SafetyCar::none);
    im.put<uint8_t>(sc + 0x108, 1);
    CHECK(safety_car_state(m, sc) == SafetyCar::full);
    im.put<uint8_t>(sc + 0x108, 2);
    CHECK(safety_car_state(m, sc) == SafetyCar::virtual_sc);
    im.put<uint8_t>(sc + 0x108, 3);
    CHECK(safety_car_state(m, sc) == SafetyCar::formation_lap);
    im.put<uint8_t>(sc + 0x108, 4);
    CHECK(safety_car_state(m, sc) == SafetyCar::unavailable);
    CHECK(safety_car_state(m, 0) == SafetyCar::unavailable);
}

struct TyreFixture {
    Image im;
    uintptr_t ts = 0, v = 0, visual[5] = {}, actual[5] = {}, sets = 0;

    TyreFixture()
    {
        ts = im.alloc(0x120);
        const uintptr_t ptrs = im.vec(ts + 0x110, 3, 8);
        v = im.alloc(0x9d00);
        im.put<uintptr_t>(ptrs + 2 * 8, v); // vehicle 2
        im.put<uint64_t>(v + 0x9bc0, 77);   // current version
        im.put<uint64_t>(v + 0x9c50, 77);   // built for
        im.put<uint64_t>(v + 0x9c58, 1);    // built
        // Visual records (0x58 each): +0 id byte, +0x50 compound enum.
        const uintptr_t table = im.alloc(5 * 0x58);
        const uint8_t ids[5] = {16, 17, 18, 7, 8};
        const int32_t enums[5] = {3, 4, 5, 7, 8};
        for (int i = 0; i < 5; ++i) {
            visual[i] = table + i * 0x58;
            im.put<uint8_t>(visual[i], ids[i]);
            im.put<int32_t>(visual[i] + 0x50, enums[i]);
            actual[i] = im.alloc(8);
            im.put<uint8_t>(actual[i], uint8_t(20 + i));
        }
        // Descriptor list: set ids 1, 4, 9 -> soft, medium, hard.
        const uint32_t set_ids[3] = {1, 4, 9};
        for (int i = 0; i < 3; ++i) {
            const uintptr_t d = v + 0x9bd0 + i * 0x18;
            im.put<uint32_t>(d, set_ids[i]);
            im.put<uintptr_t>(d + 8, actual[i]);
            im.put<uintptr_t>(d + 0x10, visual[i]);
        }
        im.put<uint64_t>(v + 0x9c48, 3);
        sets = im.vec(v + 0x9c90, 2, 0x78);
        set_current(9);
    }
    void set_current(uint32_t id) { im.put<uint32_t>(sets + 0x78 + 0xc, id); }
};

// Marshal zones as the UDP session builder reads them: entries [MZ+0x88, MZ+0x90) of 0x10 bytes, zone Z at
// entry+8, flag int32 Z+0x14, start fraction f32 [[Z]+0x10].
struct ZoneFixture {
    uintptr_t mz = 0, entries = 0;
    std::vector<uintptr_t> zone;
};
static ZoneFixture make_zones(Image &im, const std::vector<std::pair<float, int32_t>> &zs)
{
    ZoneFixture f;
    f.mz = im.alloc(0x100);
    f.entries = im.vec(f.mz + 0x88, zs.size(), kZoneStride);
    for (size_t i = 0; i < zs.size(); ++i) {
        const uintptr_t z = im.alloc(0x40), def = im.alloc(0x20);
        im.put<uintptr_t>(z, def);
        im.put<int32_t>(z + 0x14, zs[i].second);
        im.put<float>(def + 0x10, zs[i].first);
        im.put<float>(def + 0x14, zs[i].first + 0.05f);
        im.put<uintptr_t>(f.entries + i * kZoneStride + 8, z);
        f.zone.push_back(z);
    }
    return f;
}

static void test_flags()
{
    Image im;
    const Mem m = im.mem();
    // image globals at a fake image base: sector ends 1500 / 3200 / 6000 m, track 6000 m, 3 sectors
    const uintptr_t base = 0x140000000;
    im.regions[base + 0x6ce6600] = std::vector<uint8_t>(0x100, 0);
    im.put<float>(base + track_globals::sector_end + 0, 1500.f);
    im.put<float>(base + track_globals::sector_end + 4, 3200.f);
    im.put<float>(base + track_globals::sector_end + 8, 6000.f);
    im.put<float>(base + track_globals::track_length, 6000.f);
    im.put<uint32_t>(base + track_globals::sector_count, 3);
    SectorTable st;
    CHECK(read_sector_table(m, base, st) && st.count == 3 && st.track_length == 6000.f && st.end_m[1] == 3200.f);

    // zone 0 yellow at 0.10 (600 m, S1), zone 1 green at 0.20, zone 2 yellow at 0.70 (4200 m, S3), zone 3 red,
    // zone 4 yellow exactly on the S1 end (0.25 x 6000 = 1500 m: the game's ">=" keeps it in S1), zone 5 none
    ZoneFixture f = make_zones(im, {{0.10f, 3}, {0.20f, 1}, {0.70f, 3}, {0.80f, 4}, {0.25f, 3}, {0.90f, 0}});
    ZoneFlags z;
    CHECK(read_zone_flags(m, f.mz, &st, z) && z.zones == 6 && z.yellow_zones == 3 && z.red_zones == 1);
    CHECK(z.yellow_sectors == 0b101);
    CHECK(read_zone_flags(m, f.mz, nullptr, z) && z.yellow_zones == 3 && z.yellow_sectors == 0); // no table
    im.put<int32_t>(f.zone[2] + 0x14, 0);
    CHECK(read_zone_flags(m, f.mz, &st, z) && z.yellow_zones == 2 && z.yellow_sectors == 0b001);
    im.put<int32_t>(f.zone[1] + 0x14, 3); // green -> yellow at 0.20 = 1200 m: S1
    CHECK(read_zone_flags(m, f.mz, &st, z) && z.yellow_sectors == 0b001 && z.yellow_zones == 3);
    im.put<float>(base + track_globals::track_length, 6400.f); // 0.25 x 6400 = 1600 m: now S2
    CHECK(read_sector_table(m, base, st));
    CHECK(read_zone_flags(m, f.mz, &st, z) && z.yellow_sectors == 0b011);
    im.put<uintptr_t>(f.zone[4], 0); // unreadable start: still yellow, no sector of its own
    CHECK(read_zone_flags(m, f.mz, &st, z) && z.yellow_zones == 3 && z.yellow_sectors == 0b001);
    im.put<int32_t>(f.zone[5] + 0x14, 3); // 0.90 x 7000 = 6300 m, past the last end (6000): yellow, no sector
    im.put<float>(base + track_globals::track_length, 7000.f);
    CHECK(read_sector_table(m, base, st));
    CHECK(read_zone_flags(m, f.mz, &st, z) && z.yellow_zones == 4 && z.yellow_sectors == 0b001);
    im.put<float>(base + track_globals::track_length, 6000.f);
    CHECK(read_sector_table(m, base, st));

    // unavailable: flag outside 0..4, null zone, broken vector, missing system
    im.put<int32_t>(f.zone[5] + 0x14, 5);
    CHECK(!read_zone_flags(m, f.mz, &st, z));
    im.put<int32_t>(f.zone[5] + 0x14, -1);
    CHECK(!read_zone_flags(m, f.mz, &st, z));
    im.put<int32_t>(f.zone[5] + 0x14, 0);
    im.put<uintptr_t>(f.entries + 3 * kZoneStride + 8, 0);
    CHECK(!read_zone_flags(m, f.mz, &st, z));
    im.put<uintptr_t>(f.entries + 3 * kZoneStride + 8, f.zone[3]);
    CHECK(read_zone_flags(m, f.mz, &st, z));
    im.put<uintptr_t>(f.mz + 0x90, f.entries + 3); // not a whole number of entries
    CHECK(!read_zone_flags(m, f.mz, &st, z));
    CHECK(!read_zone_flags(m, 0, &st, z));
    ZoneFixture empty = make_zones(im, {});
    CHECK(read_zone_flags(m, empty.mz, &st, z) && z.zones == 0 && z.yellow_zones == 0); // no zones: valid

    // sector table limits
    im.put<uint32_t>(base + track_globals::sector_count, 0);
    CHECK(!read_sector_table(m, base, st));
    im.put<uint32_t>(base + track_globals::sector_count, 9);
    CHECK(!read_sector_table(m, base, st));
    im.put<uint32_t>(base + track_globals::sector_count, 3);
    im.put<float>(base + track_globals::sector_end + 4, 1000.f); // decreasing
    CHECK(!read_sector_table(m, base, st));
    im.put<float>(base + track_globals::sector_end + 4, 3200.f);
    im.put<float>(base + track_globals::track_length, std::nanf(""));
    CHECK(!read_sector_table(m, base, st));
    CHECK(!read_sector_table(m, 0, st));

    // red flag state byte +0x40
    const uintptr_t rfs = im.alloc(0x80);
    CHECK(red_flag_state(m, rfs) == RedFlag::none);
    im.put<uint8_t>(rfs + 0x40, 1);
    CHECK(red_flag_state(m, rfs) == RedFlag::deployed);
    im.put<uint8_t>(rfs + 0x40, 2);
    CHECK(red_flag_state(m, rfs) == RedFlag::suspended);
    im.put<uint8_t>(rfs + 0x40, 3);
    CHECK(red_flag_state(m, rfs) == RedFlag::unavailable);
    CHECK(red_flag_state(m, 0) == RedFlag::unavailable);

    // header priority: red > SC > VSC > yellow > none; unavailable inputs never raise a state; red comes from
    // the red flag system only (a red zone alone has writers that do not depend on it)
    ZoneFlags yellow, red, clear;
    yellow.yellow_zones = 1;
    red.red_zones = 1;
    CHECK(flag_header_state(RedFlag::deployed, SafetyCar::full, &yellow) == 3);
    CHECK(flag_header_state(RedFlag::suspended, SafetyCar::none, nullptr) == 3);
    CHECK(flag_header_state(RedFlag::unavailable, SafetyCar::none, &red) == 0);
    CHECK(flag_header_state(RedFlag::none, SafetyCar::full, &yellow) == 1);
    CHECK(flag_header_state(RedFlag::none, SafetyCar::virtual_sc, &yellow) == 2);
    CHECK(flag_header_state(RedFlag::none, SafetyCar::none, &yellow) == 5);
    CHECK(flag_header_state(RedFlag::unavailable, SafetyCar::unavailable, &yellow) == 5);
    CHECK(flag_header_state(RedFlag::none, SafetyCar::formation_lap, &clear) == 0);
    CHECK(flag_header_state(RedFlag::unavailable, SafetyCar::unavailable, nullptr) == 0);
}

static void test_tyres()
{
    TyreFixture f;
    const Mem m = f.im.mem();
    Tyre t;
    CHECK(tyre_compound(m, f.ts, 2, t) && t.letter == 'H' && t.compound == 5 && t.visual_id == 18 && t.actual_id == 22);
    f.set_current(1);
    CHECK(tyre_compound(m, f.ts, 2, t) && t.letter == 'S' && t.visual_id == 16);
    f.set_current(2); // no descriptor 2 -> fallback id 1 (id < 3)
    CHECK(tyre_compound(m, f.ts, 2, t) && t.letter == 'S');
    f.set_current(6); // no descriptor 6 -> fallback id 4 (id >= 3)
    CHECK(tyre_compound(m, f.ts, 2, t) && t.letter == 'M');
    f.im.put<int32_t>(f.visual[1] + 0x50, 6); // SuperHard: a compound, but no tower letter
    CHECK(tyre_compound(m, f.ts, 2, t) && t.compound == 6 && t.letter == 0);
    f.im.put<int32_t>(f.visual[1] + 0x50, 12); // outside the loader's values
    CHECK(!tyre_compound(m, f.ts, 2, t));
    f.im.put<int32_t>(f.visual[1] + 0x50, 4);
    f.im.put<uint32_t>(f.v + 0x9bd0 + 1 * 0x18, 5); // descriptor 4 becomes 5
    f.set_current(6);                               // no 6, no fallback 4
    CHECK(!tyre_compound(m, f.ts, 2, t));
    f.im.put<uint32_t>(f.v + 0x9bd0 + 1 * 0x18, 4);
    CHECK(tyre_compound(m, f.ts, 2, t) && t.letter == 'M');
    // Wet and intermediate records.
    f.im.put<uintptr_t>(f.v + 0x9bd0 + 0x10, f.visual[4]);
    f.set_current(1);
    CHECK(tyre_compound(m, f.ts, 2, t) && t.letter == 'W' && t.visual_id == 8);
    f.im.put<uintptr_t>(f.v + 0x9bd0 + 0x10, f.visual[3]);
    CHECK(tyre_compound(m, f.ts, 2, t) && t.letter == 'I' && t.visual_id == 7);
    // Stale cache: the game would rebuild it first; we report unavailable.
    f.im.put<uint64_t>(f.v + 0x9bc0, 78);
    CHECK(!tyre_compound(m, f.ts, 2, t));
    f.im.put<uint64_t>(f.v + 0x9bc0, 77);
    f.im.put<uint64_t>(f.v + 0x9c58, 0);
    CHECK(!tyre_compound(m, f.ts, 2, t));
    f.im.put<uint64_t>(f.v + 0x9c58, 1);
    CHECK(tyre_compound(m, f.ts, 2, t));
    // Count 0 and count beyond the inline list.
    f.im.put<uint64_t>(f.v + 0x9c48, 0);
    CHECK(!tyre_compound(m, f.ts, 2, t));
    f.im.put<uint64_t>(f.v + 0x9c48, 6);
    CHECK(!tyre_compound(m, f.ts, 2, t));
    f.im.put<uint64_t>(f.v + 0x9c48, 3);
    // No set records.
    f.im.put<uintptr_t>(f.v + 0x9c98, f.sets);
    CHECK(!tyre_compound(m, f.ts, 2, t));
    f.im.put<uintptr_t>(f.v + 0x9c98, f.sets + 2 * 0x78);
    // Vehicles without a tyre entry.
    CHECK(!tyre_compound(m, f.ts, 0, t));
    CHECK(!tyre_compound(m, f.ts, 3, t));
    CHECK(tyre_letter(0) == 0 && tyre_letter(-1) == 0 && tyre_letter(3) == 'S');
}

static void test_gaps()
{
    Image im;
    const Mem m = im.mem();
    const uintptr_t t = im.alloc(0x100);
    const uintptr_t e = im.vec(t + 0x30, 3, 0x98);
    const uint8_t vids[3] = {0, 7, 4}; // entries are not in vehicle order
    for (int i = 0; i < 3; ++i)
        im.put<uint8_t>(e + i * 0x98 + 0x90, vids[i]);
    const uintptr_t e4 = e + 2 * 0x98;
    im.put<int64_t>(e4 + 0x58, 12345);
    im.put<uint8_t>(e4 + 0x68, 1);
    im.put<int64_t>(e4 + 0x70, 733);
    im.put<uint8_t>(e4 + 0x80, 0); // invalid (lapped / pit / no car ahead)

    Gap g;
    CHECK(read_gap(m, t, 4, GapKind::leader, g) && g.valid && g.ms == 12345);
    CHECK(read_gap(m, t, 4, GapKind::ahead, g) && !g.valid);
    CHECK(read_gap(m, t, 0, GapKind::leader, g) && !g.valid);
    CHECK(!read_gap(m, t, 9, GapKind::leader, g)); // no entry
    im.put<uintptr_t>(t + 0x38, e + 0x99);          // broken vector
    CHECK(!read_gap(m, t, 4, GapKind::leader, g));
    CHECK(!read_gap(m, 0, 4, GapKind::leader, g));
}

static void test_knockout()
{
    // Synthetic segment lists only: the inputs are not wired to the game (see field-traces.md, knockout).
    const Segment segs[2] = {{5, 1, 6}, {6, 0, 0}};
    CHECK(knockout_cut(6, segs, 2, 10, 20, 20) == 9);  // base case: base - 1
    CHECK(knockout_cut(5, segs, 2, 10, 20, 20) == 14); // 9 + floor((20 - 9 - 1) / 2)
    CHECK(knockout_cut(5, segs, 2, 10, 20, 22) == 15); // 9 + floor(12 / 2)
    CHECK(knockout_cut(5, segs, 2, 10, 20, 21) == 14); // floor(11 / 2) = 5
    CHECK(knockout_cut(5, segs, 2, 10, 20, 16) == 14); // max(grid, floor_grid) = 20
    CHECK(knockout_cut(7, segs, 2, 10, 20, 20) == kNoCut);  // not in the list
    CHECK(knockout_cut(15, segs, 2, 10, 20, 20) == kNoCut); // race: outside 5..14
    CHECK(knockout_cut(4, segs, 2, 10, 20, 20) == kNoCut);
    const Segment no_cut_link[2] = {{5, 1, 7}, {6, 0, 0}};
    CHECK(knockout_cut(5, no_cut_link, 2, 10, 20, 20) == kNoCut); // linked segment has no cut
    const Segment cycle[2] = {{5, 1, 6}, {6, 1, 5}};
    CHECK(knockout_cut(5, cycle, 2, 10, 20, 20) == kCutUnavailable);
    const Segment bad_div[2] = {{5, 0xffffffffu, 6}, {6, 0, 0}};
    CHECK(knockout_cut(5, bad_div, 2, 10, 20, 20) == kCutUnavailable);

    CHECK(in_drop_zone(15, 14, 5));
    CHECK(!in_drop_zone(14, 14, 5));
    CHECK(in_drop_zone(10, 9, 6) && in_drop_zone(10, 9, 10) && in_drop_zone(10, 9, 12) && in_drop_zone(10, 9, 7));
    CHECK(!in_drop_zone(20, 9, 8) && !in_drop_zone(20, 9, 9) && !in_drop_zone(20, 9, 13) && !in_drop_zone(20, 9, 14));
    CHECK(!in_drop_zone(20, 9, 15) && !in_drop_zone(20, 9, 4));
    CHECK(!in_drop_zone(27, kNoCut, 5));
}

int main()
{
    test_registry();
    test_penalties();
    test_misconduct();
    test_results_fields();
    test_safety_car();
    test_flags();
    test_tyres();
    test_gaps();
    test_knockout();
    std::printf("%d passed, %d failed\n", g_pass, g_fail);
    return g_fail ? 1 : 0;
}
