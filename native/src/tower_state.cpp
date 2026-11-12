// tower_state.cpp - prototype readers for the timing tower (Phase 2). Not part of the DLL build.
// Offsets and rules: tower_state.hpp and docs/timing-tower/field-traces.md.
#include "tower_state.hpp"

#include <cmath>
#include <cstring>

namespace tower {
namespace {

constexpr size_t kMaxRegistrySlots = 4096;

template <class T> T field(const uint8_t *b, size_t off)
{
    T v;
    std::memcpy(&v, b + off, sizeof v);
    return v;
}

// A std::vector-like [begin, end) pair at `at`. Empty (both equal) is valid; n is the element count.
bool span(const Mem &m, uintptr_t at, size_t stride, size_t max_n, uintptr_t &begin, size_t &n)
{
    uintptr_t be[2];
    if (!m.read(at, be, sizeof be))
        return false;
    begin = be[0];
    if (be[1] == be[0]) {
        n = 0;
        return true;
    }
    if (!be[0] || be[1] < be[0] || (be[1] - be[0]) % stride || (be[1] - be[0]) / stride > max_n)
        return false;
    n = (be[1] - be[0]) / stride;
    return true;
}

PenaltyRecord decode_penalty(const uint8_t *r)
{
    PenaltyRecord p;
    p.vehicle = r[0x08];
    p.penalty = r[0x09];
    p.infringement = r[0x0a];
    p.other_vehicle = r[0x0b];
    p.time_s = field<uint32_t>(r, 0x0c);
    p.lap = field<uint32_t>(r, 0x10);
    p.places = field<uint32_t>(r, 0x18);
    p.points = field<uint32_t>(r, 0x20);
    p.safety_points = field<uint32_t>(r, 0x2c);
    return p;
}

// Calls fn(record) for every record of the log; false when the log is unreadable.
template <class Fn> bool scan_penalties(const Mem &m, uintptr_t log, Fn fn)
{
    uintptr_t begin = 0;
    size_t n = 0;
    if (!log || !span(m, log + 0x48, kPenaltyStride, kMaxPenaltyRecords, begin, n))
        return false;
    uint8_t chunk[32 * kPenaltyStride];
    for (size_t i = 0; i < n; i += 32) {
        const size_t c = n - i < 32 ? n - i : 32;
        if (!m.read(begin + i * kPenaltyStride, chunk, c * kPenaltyStride))
            return false;
        for (size_t j = 0; j < c; ++j)
            fn(decode_penalty(chunk + j * kPenaltyStride));
    }
    return true;
}

bool is_track_limits(uint8_t infringement)
{
    return infringement <= 0x1d && ((kTrackLimitsMask >> infringement) & 1u);
}

// Results entry P of a car; P+0 must read back the vehicle id (the provider's rule).
bool results_entry(const Mem &m, uintptr_t results, uint8_t vehicle, uintptr_t &p)
{
    uintptr_t begin = 0;
    size_t n = 0;
    uint8_t id = 0xff;
    if (!results || !span(m, results + 0x148, sizeof(uintptr_t), 64, begin, n) || vehicle >= n ||
        !m.get(begin + vehicle * sizeof(uintptr_t), p) || !p || (p & 7) || !m.get(p, id) || id != vehicle)
        return false;
    return true;
}

// [S1+off] -> per-car vector [obj+0x68, obj+0x70) of `stride`-byte records.
bool misconduct_vector(const Mem &m, uintptr_t s1, uintptr_t off, size_t stride, uintptr_t &begin, size_t &n)
{
    uintptr_t obj = 0;
    return s1 && m.get(s1 + off, obj) && obj && span(m, obj + 0x68, stride, kMaxPenaltyCars, begin, n);
}

} // namespace

uintptr_t find_in_registry(const Mem &m, uintptr_t reg, uintptr_t key)
{
    uintptr_t sl[2];
    if (!reg || !key || !m.read(reg + 0x18, sl, sizeof sl))
        return 0;
    const uintptr_t base = sl[0], info = sl[1];
    if (!base || (base & 7) || info <= base || (info - base) % 16 || (info - base) / 16 > kMaxRegistrySlots)
        return 0;
    const size_t n = (info - base) / 16;
    uintptr_t chunk[2 * 64];
    for (size_t i = 0; i < n; i += 64) {
        const size_t c = n - i < 64 ? n - i : 64;
        if (!m.read(base + i * 16, chunk, c * 16))
            return 0;
        for (size_t j = 0; j < c; ++j) {
            const uintptr_t value = chunk[2 * j + 1];
            uint8_t used = 0;
            if (chunk[2 * j] == key && value && !(value & 7) && m.get(info + i + j, used) && used)
                return value;
        }
    }
    return 0;
}

int read_penalties(const Mem &m, uintptr_t log, uint8_t vehicle, PenaltyRecord *out, int max)
{
    int count = 0;
    const bool ok = scan_penalties(m, log, [&](const PenaltyRecord &r) {
        if (vehicle != 0xff && r.vehicle != vehicle)
            return;
        if (out && count < max)
            out[count] = r;
        ++count;
    });
    return ok ? count : -1;
}

WarningCounts count_warnings(const PenaltyRecord *recs, int n, uint8_t vehicle)
{
    WarningCounts w;
    for (int i = 0; i < n; ++i) {
        if (recs[i].vehicle != vehicle || recs[i].penalty != kPenaltyWarning)
            continue;
        ++w.total;
        if (is_track_limits(recs[i].infringement))
            ++w.track_limits;
    }
    return w;
}

bool count_warnings(const Mem &m, uintptr_t log, uint8_t vehicle, WarningCounts &out)
{
    WarningCounts w;
    const bool ok = scan_penalties(m, log, [&](const PenaltyRecord &r) {
        if (r.vehicle != vehicle || r.penalty != kPenaltyWarning)
            return;
        ++w.total;
        if (is_track_limits(r.infringement))
            ++w.track_limits;
    });
    if (ok)
        out = w;
    return ok;
}

bool unserved_drive_throughs(const Mem &m, uintptr_t s1, uint8_t vehicle, int &out)
{
    uintptr_t begin = 0;
    size_t n = 0;
    if (!misconduct_vector(m, s1, misconduct::drive_through, 0x28, begin, n))
        return false;
    if (vehicle >= n) { // the game writes 0 for a car past the end (0x142cfd87d -> 0x142cfd8c0)
        out = 0;
        return true;
    }
    uint8_t r[0x28];
    if (!m.read(begin + vehicle * 0x28, r, sizeof r))
        return false;
    out = (r[0x08] != 0xff) + (r[0x10] != 0xff) + (r[0x18] != 0xff) + (r[0x20] != 0xff);
    return true;
}

bool unserved_stop_gos(const Mem &m, uintptr_t s1, uint8_t vehicle, int &out)
{
    uintptr_t begin = 0;
    size_t n = 0;
    if (!misconduct_vector(m, s1, misconduct::stop_go, 4, begin, n))
        return false;
    if (vehicle >= n) { // 0x142cfd8eb -> 0x142cfd900
        out = 0;
        return true;
    }
    uint8_t b = 0;
    if (!m.get(begin + vehicle * 4 + 3, b))
        return false;
    out = b;
    return true;
}

bool time_penalty_seconds(const Mem &m, uintptr_t results, uint8_t vehicle, double &out)
{
    uintptr_t p = 0;
    uint64_t x[2];
    if (!results_entry(m, results, vehicle, p) || !m.read(p + 0x38, x, sizeof x))
        return false;
    const uint64_t bits = x[0] ^ x[1];
    double d;
    std::memcpy(&d, &bits, sizeof d);
    // The game only adds whole seconds to it; negative, non-finite or absurd totals are not a valid state.
    if (!std::isfinite(d) || d < 0.0 || d > 3600.0)
        return false;
    out = d;
    return true;
}

bool result_status(const Mem &m, uintptr_t results, uint8_t vehicle, uint8_t &out)
{
    uintptr_t p = 0;
    uint8_t s = 0xff;
    if (!results_entry(m, results, vehicle, p) || !m.get(p + 0x18, s) || s > 7)
        return false;
    out = s;
    return true;
}

SafetyCar safety_car_state(const Mem &m, uintptr_t sc)
{
    uint8_t s = 0xff;
    if (!sc || !m.get(sc + 0x108, s) || s > 3)
        return SafetyCar::unavailable;
    return static_cast<SafetyCar>(s);
}

namespace {
// The table's checks: count 1..kMaxSectors, a finite positive length, finite positive ends that never decrease.
constexpr float kMaxTrackM = 100000.f; // sanity bound (the longest calendar track is about 7 km)
bool sector_table_ok(uint32_t n, float len, const float *e)
{
    if (n < 1 || n > uint32_t(kMaxSectors) || !std::isfinite(len) || len <= 0.f || len > kMaxTrackM)
        return false;
    for (uint32_t i = 0; i < n; ++i)
        if (!std::isfinite(e[i]) || e[i] <= 0.f || e[i] > kMaxTrackM || (i && e[i] < e[i - 1]))
            return false;
    return true;
}
} // namespace

bool read_sector_table(const Mem &m, uintptr_t image_base, SectorTable &out)
{
    out = SectorTable{};
    uint32_t n = 0;
    float len = 0.f;
    if (!image_base || !m.get(image_base + track_globals::sector_count, n) ||
        !m.get(image_base + track_globals::track_length, len))
        return false;
    if (n < 1 || n > uint32_t(kMaxSectors))
        return false;
    float e[kMaxSectors];
    if (!m.read(image_base + track_globals::sector_end, e, n * sizeof(float)) || !sector_table_ok(n, len, e))
        return false;
    std::memcpy(out.end_m, e, n * sizeof(float));
    out.count = int(n);
    out.track_length = len;
    return true;
}

bool sector_table_from(const uint8_t *b, SectorTable &out)
{
    out = SectorTable{};
    const uint32_t n = field<uint32_t>(b, track_globals::sector_count - track_globals::sector_end);
    const float len = field<float>(b, track_globals::track_length - track_globals::sector_end);
    if (n < 1 || n > uint32_t(kMaxSectors))
        return false;
    float e[kMaxSectors];
    std::memcpy(e, b, n * sizeof(float));
    if (!sector_table_ok(n, len, e))
        return false;
    std::memcpy(out.end_m, e, n * sizeof(float));
    out.count = int(n);
    out.track_length = len;
    return true;
}

int sector_of(const SectorTable &t, float metres)
{
    if (!std::isfinite(metres))
        return 0;
    for (int s = 0; s < t.count && s < kMaxSectors; ++s)
        if (t.end_m[s] >= metres)
            return s + 1;
    return 0;
}

bool read_zone_flags(const Mem &m, uintptr_t mz, const SectorTable *sectors, ZoneFlags &out)
{
    out = ZoneFlags{};
    uintptr_t begin = 0;
    size_t n = 0;
    if (!mz || !span(m, mz + 0x88, kZoneStride, kMaxMarshalZones, begin, n))
        return false;
    uint8_t entries[kMaxMarshalZones * kZoneStride];
    if (n && !m.read(begin, entries, n * kZoneStride))
        return false;
    for (size_t i = 0; i < n; ++i) {
        const uintptr_t z = field<uintptr_t>(entries, i * kZoneStride + 8);
        int32_t flag = -1;
        if (!z || !m.get(z + 0x14, flag) || flag < zone_none || flag > zone_red)
            return false;
        if (flag == zone_red)
            ++out.red_zones;
        if (flag != zone_yellow)
            continue;
        ++out.yellow_zones;
        uintptr_t def = 0;
        float start = 0.f;
        if (!sectors || !m.get(z, def) || !def || !m.get(def + 0x10, start) || !std::isfinite(start))
            continue; // the zone still counts as yellow; only its sector stays unknown
        if (const int s = sector_of(*sectors, sectors->track_length * start))
            out.yellow_sectors |= uint8_t(1u << (s - 1));
    }
    out.zones = int(n);
    return true;
}

RedFlag red_flag_state(const Mem &m, uintptr_t rfs)
{
    uint8_t s = 0xff;
    if (!rfs || !m.get(rfs + 0x40, s) || s > 2)
        return RedFlag::unavailable;
    return static_cast<RedFlag>(s);
}

int flag_header_state(RedFlag red, SafetyCar sc, const ZoneFlags *zones)
{
    if (red == RedFlag::deployed || red == RedFlag::suspended)
        return 3;
    if (sc == SafetyCar::full)
        return 1;
    if (sc == SafetyCar::virtual_sc)
        return 2;
    if (zones && zones->yellow_zones > 0)
        return 5;
    return 0;
}

char tyre_letter(int32_t compound)
{
    switch (compound) {
    case 3: return 'S';
    case 4: return 'M';
    case 5: return 'H';
    case 7: return 'I';
    case 8: return 'W';
    default: return 0;
    }
}

bool tyre_compound(const Mem &m, uintptr_t ts, uint8_t vehicle, Tyre &out)
{
    uintptr_t begin = 0, v = 0;
    size_t n = 0;
    if (!ts || !span(m, ts + 0x110, sizeof(uintptr_t), 64, begin, n) || vehicle >= n ||
        !m.get(begin + vehicle * sizeof(uintptr_t), v) || !v)
        return false;
    // Cache state: built flag, the version it was built for, the current version.
    uint64_t built = 0, built_for = 0, now = 0, count = 0;
    if (!m.get(v + 0x9c58, built) || !m.get(v + 0x9c50, built_for) || !m.get(v + 0x9bc0, now) || !built ||
        built_for != now || !m.get(v + 0x9c48, count) || count == 0 || count > 5)
        return false;
    uintptr_t sets[2];
    if (!m.read(v + 0x9c90, sets, sizeof sets) || !sets[0] || sets[1] < sets[0] || sets[1] - sets[0] < 0x78)
        return false;
    uint32_t id = 0;
    if (!m.get(sets[1] - 0x6c, id))
        return false;
    uint8_t list[5 * 0x18];
    if (!m.read(v + 0x9bd0, list, size_t(count) * 0x18))
        return false;
    const uint8_t *desc = nullptr;
    for (size_t i = 0; i < count && !desc; ++i)
        if (field<uint32_t>(list, i * 0x18) == id)
            desc = list + i * 0x18;
    const uint32_t fallback = id >= 3 ? 4 : 1; // 0x142d00ca2..0x142d00cad
    for (size_t i = 0; i < count && !desc; ++i)
        if (field<uint32_t>(list, i * 0x18) == fallback)
            desc = list + i * 0x18;
    if (!desc)
        return false;
    const uintptr_t actual = field<uintptr_t>(desc, 8), visual = field<uintptr_t>(desc, 0x10);
    Tyre t;
    int32_t c = -1;
    if (!visual || !m.get(visual, t.visual_id) || !m.get(visual + 0x50, c) || c < -1 || c > 8)
        return false;
    if (actual && !m.get(actual, t.actual_id))
        return false;
    t.compound = c;
    t.letter = tyre_letter(c);
    out = t;
    return true;
}

bool read_gap(const Mem &m, uintptr_t timing, uint8_t vehicle, GapKind kind, Gap &out)
{
    uintptr_t begin = 0;
    size_t n = 0;
    if (!timing || !span(m, timing + 0x30, 0x98, kMaxTimingEntries, begin, n))
        return false;
    for (size_t i = 0; i < n; ++i) {
        uint8_t e[0x98];
        if (!m.read(begin + i * 0x98, e, sizeof e))
            return false;
        if (e[0x90] != vehicle)
            continue;
        const size_t r = static_cast<size_t>(kind);
        out.ms = field<int64_t>(e, r);
        out.valid = e[r + 0x10] != 0;
        return true;
    }
    return false;
}

namespace {
uint32_t cut_rec(int32_t sid, const Segment *segs, int n, uint32_t base, uint32_t floor_grid, uint32_t grid,
                 int depth)
{
    if (static_cast<uint32_t>(sid - 5) > 9) // 0x140afa139..0x140afa13f
        return kNoCut;
    const Segment *d = nullptr;
    for (int i = 0; i < n && !d; ++i)
        if (segs[i].session_id == sid)
            d = &segs[i];
    if (!d) // 0x140afa172
        return kNoCut;
    if (d->link_session == 0) // 0x140afa1ab: base - 1
        return base - 1;
    if (depth >= 8) // the game recurses without a limit; a cycle would never return
        return kCutUnavailable;
    const uint32_t c = cut_rec(d->link_session, segs, n, base, floor_grid, grid, depth + 1);
    if (c == kNoCut || c == kCutUnavailable)
        return c;
    const uint32_t m = floor_grid > grid ? floor_grid : grid; // cmova (unsigned)
    const uint32_t x = m + ~c;                                 // m - c - 1, 32-bit
    const uint32_t y = d->divisor_m1 + 1;
    if (y == 0 || x >= (1u << 24)) // outside what float division reproduces exactly here
        return kCutUnavailable;
    const float q = std::floor(static_cast<float>(x) / static_cast<float>(y)); // vroundss mode 9 = floor
    return static_cast<uint32_t>(static_cast<int64_t>(q)) + c;
}
} // namespace

uint32_t knockout_cut(int32_t sid, const Segment *segs, int n, uint32_t base, uint32_t floor_grid, uint32_t grid)
{
    return cut_rec(sid, segs, n, base, floor_grid, grid, 0);
}

bool in_drop_zone(uint32_t position_index, uint32_t cut, int32_t session_type)
{
    if (static_cast<uint32_t>(session_type - 5) > 9) // 0x1418356bc..0x1418356cd
        return false;
    const uint32_t t = static_cast<uint32_t>(session_type - 8);
    if (t < 7 && ((0x63u >> t) & 1u)) // 8, 9, 13, 14: 0x1418356d3..0x1418356e3
        return false;
    return position_index > cut; // seta 0x141838bef
}

bool badge_key_ok(const char *s, size_t cap)
{
    if (!s)
        return false;
    const size_t lim = cap < kBadgeKeyMax ? cap : kBadgeKeyMax;
    for (size_t i = 0; i < lim; ++i) {
        const unsigned char c = static_cast<unsigned char>(s[i]);
        if (!c)
            return i > 0;
        if (c < 0x21 || c > 0x7e)
            return false;
    }
    return false; // no NUL within the bound
}

bool render_key_ok(const char *s, size_t cap)
{
    if (!s || !cap)
        return false;
    size_t n = 0;
    for (; n < cap && s[n]; ++n)
        if ((unsigned char)s[n] < 0x20 || (unsigned char)s[n] > 0x7e)
            return false;
    return n > 0 && n < cap && n < kBadgeKeyMax && s[0] != ' ' && s[n - 1] != ' ';
}

bool badge_text(const char *key, char *out, size_t cap, bool render)
{
    if (!out || !cap)
        return false;
    out[0] = 0;
    static_assert(kRenderBadgePrefixLen <= kBadgePrefixLen, "the render path fits the leaf text");
    if (cap < kBadgeTextMax || !(render ? render_key_ok(key, kBadgeKeyMax) : badge_key_ok(key, kBadgeKeyMax)))
        return false;
    const size_t n = std::strlen(key);
    const char *pre = render ? kRenderBadgePrefix : kBadgePrefix;
    const size_t pn = render ? kRenderBadgePrefixLen : kBadgePrefixLen;
    std::memcpy(out, pre, pn);
    std::memcpy(out + pn, key, n + 1);
    return true;
}

} // namespace tower
