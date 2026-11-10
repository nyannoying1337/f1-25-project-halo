// tower_reader.cpp - the timing tower's in-process reads. Layouts and evidence: tower_reader.hpp,
// docs/timing-tower/field-traces.md, docs/internal-state/fields.md "Timing tower".
#include "tower_reader.hpp"

#include <cmath>
#include <cstring>

namespace tower {
namespace {

template <class T> T at(const uint8_t *b, size_t off)
{
    T v;
    std::memcpy(&v, b + off, sizeof v);
    return v;
}

constexpr size_t kMaxSlots = 4096;     // registry slots (the provider's bound)
constexpr size_t kMaxEntries = 64;     // per-vehicle vectors (sanity bound, not a game value)
constexpr size_t kTimingStride = 0x98; // T entry
constexpr size_t kResultsSpan = 0x58;  // [P, P+0x58): vid +0, status +0x18, time penalty +0x38/+0x40, position +0x48/+0x50
constexpr size_t kTyreLo = 0x9bc0, kTyreHi = 0x9ca0; // one copy: version, descriptor list, count, cache stamps, set vector
constexpr int kMaxPenaltyChunk = 32;

// An empty [b, e) vector is valid (n = 0); otherwise aligned bounds holding a whole number of elements.
bool vec_ok(uintptr_t b, uintptr_t e, size_t stride, size_t max_n, size_t &n)
{
    if (b == e) {
        n = 0;
        return true;
    }
    if (!b || e < b || (e - b) % stride || (e - b) / stride > max_n)
        return false;
    n = (e - b) / stride;
    return true;
}

uint64_t record_hash(const uint8_t *r)
{
    uint64_t h = 1469598103934665603ull;
    for (size_t i = 0; i < kPenaltyStride; ++i)
        h = (h ^ r[i]) * 1099511628211ull;
    return h;
}

} // namespace

char checked_letter(const TyreRead &t)
{
    if (t.state != 1 || !t.letter)
        return 0;
    int want = -1;
    switch (t.visual) { // the game's own visual ids (the car-status builder sends them; public meaning)
    case 16: want = 3; break;
    case 17: want = 4; break;
    case 18: want = 5; break;
    case 7: want = 7; break;
    case 8: want = 8; break;
    default: return 0;
    }
    return want == t.compound ? t.letter : 0;
}

Keys keys_from_image(uintptr_t b, uintptr_t gm)
{
    Keys k;
    k.game_manager = gm;
    if (!b)
        return k;
    k.results = b + keys::results;
    k.timing = b + keys::timing;
    k.pit = b + kRvaPit;
    k.safety_car = b + keys::safety_car_logic;
    k.penalty_log = b + keys::penalty_log;
    k.session_component = b + keys::session_component;
    k.tyres = b + keys::tyre_system;
    k.marshal_zones = b + keys::marshal_zones;
    k.red_flag = b + keys::red_flag;
    k.sector_table = b + track_globals::sector_end;
    k.game_mode_context = b + keys::game_mode_context;
    k.team_tables = b + keys::team_tables;
    return k;
}

bool Reader::rd(uintptr_t a, void *dst, size_t n)
{
    ++copies_;
    return m_.read(a, dst, n);
}

// [[g_Game_Manager]+0x30]: 16-byte {key, value} slots from [reg+0x18] to [reg+0x20], one "used" byte per slot from
// [reg+0x20] (the provider's find_component).
bool Reader::registry(uintptr_t &base, size_t &n, uintptr_t &info)
{
    uintptr_t mgr = 0, reg = 0, sl[2] = {};
    if (!k_.game_manager || !get(k_.game_manager, mgr) || !mgr || !get(mgr + 0x30, reg) || !reg ||
        !rd(reg + 0x18, sl, sizeof sl))
        return false;
    base = sl[0];
    info = sl[1];
    if (!base || (base & 7) || info <= base || (info - base) % 16 || (info - base) / 16 > kMaxSlots)
        return false;
    n = (info - base) / 16;
    return true;
}

// The cached slot while it still holds the key and the same value; else a search, at most once a second.
uintptr_t Reader::find(Component &c, uintptr_t key, double now)
{
    const uintptr_t cached = c.value;
    c.value = 0;
    uintptr_t base = 0, info = 0;
    size_t n = 0;
    if (!key || !registry(base, n, info))
        return 0;
    uintptr_t kv[2];
    uint8_t used = 0;
    if (cached && c.slot < n && rd(base + c.slot * 16, kv, sizeof kv) && kv[0] == key && kv[1] == cached &&
        get(info + c.slot, used) && used) {
        c.value = cached;
        return cached;
    }
    c.slot = ~size_t(0);
    if (now - c.last_search < 1.0 && now >= c.last_search)
        return 0;
    c.last_search = now;
    uintptr_t chunk[2 * 64];
    for (size_t i = 0; i < n; i += 64) {
        const size_t m = n - i < 64 ? n - i : 64;
        if (!rd(base + i * 16, chunk, m * 16))
            return 0;
        for (size_t j = 0; j < m; ++j) {
            const uintptr_t value = chunk[2 * j + 1];
            if (chunk[2 * j] == key && value && !(value & 7) && get(info + i + j, used) && used) {
                c.value = value;
                c.slot = i + j;
                return value;
            }
        }
    }
    return 0;
}

void Reader::reset(double now)
{
    const ModeRead mode = s_.mode; // the game mode is not a car set's: kept (read again at once, below)
    s_ = Snapshot{};
    s_.mode = mode;
    // staggered so two heavy jobs rarely share a frame; the light game mode read runs first, in the reset's frame
    const double offset[kJobs] = {0.0, 0.033, 0.066, 0.05, 0.02, 0.27, 0.175, -0.001};
    for (int j = 0; j < kJobs; ++j)
        due_[j] = now + offset[j];
    pen_count_ = ~0u;
    pen_last_ = 0;
    sector_try_ = -1e9; // a new session (or generation) reads its sector table again
    entrants_ = 0;
}

// Cars without ERS: the halo's scan marks them 's'. In F1 that is only the safety car, at the vehicle id after the
// field's (2026-11-09 23:58 log, 2025 grid: 20 cars '.', the safety car 's' at id 20, 20 results entries). In F2
// every car has none (2026-11-10 00:07 log: 22 cars and the safety car all 's', the safety car at id 22, 22 results
// entries), so the results' entry count is what keeps the safety car out. Before the session's first results
// read only cars with ERS count.
bool Reader::racer(const Frame &f, int vid) const
{
    const char s = f.slot(vid);
    return s == '.' || (s == 's' && vid < entrants_);
}

void Reader::update(double now, const Frame &f)
{
    copies_ = 0;
    ran_ = 0;
    const uint32_t session = f.session_ok ? f.session : ~0u;
    if (f.generation != generation_ || session != session_ || now < last_now_) {
        generation_ = f.generation;
        session_ = session;
        reset(now);
    }
    last_now_ = now;
    for (int k = 0; k < 2; ++k) {
        int pick = -1;
        for (int j = 0; j < kJobs; ++j)
            if (due_[j] <= now && !(ran_ & (1u << j)) && (pick < 0 || due_[j] < due_[pick]))
                pick = j;
        if (pick < 0)
            break;
        due_[pick] = now - due_[pick] > kPeriod[pick] ? now + kPeriod[pick] : due_[pick] + kPeriod[pick];
        ran_ |= 1u << pick;
        switch (pick) {
        case kJobCls: job_cls(now, f); break;
        case kJobTiming: job_timing(now, f); break;
        case kJobPitLaps: job_pitlaps(now, f); break;
        case kJobPen: job_pen(now, f); break;
        case kJobTyreA: job_tyres(now, f, 0); break;
        case kJobTyreB: job_tyres(now, f, 1); break;
        case kJobFlags: job_flags(now, f); break;
        case kJobMode: job_mode(now); break;
        default: break;
        }
    }
}

// ---------------------------------------------------------------- classification (R)

void Reader::job_cls(double now, const Frame &f)
{
    Classification c;
    c.seq = s_.cls.seq;
    c.t = now;
    std::memset(c.status, 0xff, sizeof c.status);
    const uintptr_t R = find(c_results_, k_.results, now);
    s_.found_results = R != 0;
    uintptr_t v[2];
    size_t ne = 0;
    if (!R || !rd(R + 0x148, v, sizeof v) || !vec_ok(v[0], v[1], 8, kMaxEntries, ne) || !ne) {
        s_.cls = c;
        return;
    }
    c.entries = int(ne);
    entrants_ = int(ne);
    uintptr_t ptr[kMaxEntries];
    if (!rd(v[0], ptr, ne * 8)) {
        s_.cls = c;
        return;
    }
    int8_t owner[kMaxEntries + 1];
    std::memset(owner, -1, sizeof owner);
    int maxpos = 0;
    for (int vid = 0; vid < kCars && size_t(vid) < ne; ++vid) {
        const uintptr_t P = ptr[vid];
        uint8_t b[kResultsSpan];
        if (!racer(f, vid) || !P || (P & 7) || !rd(P, b, sizeof b) || b[0] != vid)
            continue;
        const uint8_t st = b[0x18];
        c.status[vid] = st <= 7 ? st : 0xff;
        const uint64_t bits = at<uint64_t>(b, 0x38) ^ at<uint64_t>(b, 0x40);
        double d;
        std::memcpy(&d, &bits, sizeof d);
        if (std::isfinite(d) && d >= 0.0 && d <= 3600.0) { // the game adds whole seconds (Sess_Issue_TimePenalty)
            c.tpen_ok[vid] = true;
            c.tpen_s[vid] = float(d);
        }
        const uint32_t p = (at<uint32_t>(b, 0x48) ^ at<uint32_t>(b, 0x50)) + 1;
        if (p < 1 || p > ne || p > kMaxEntries)
            continue;
        if (owner[p] >= 0) {
            ++c.dups;
            continue;
        }
        owner[p] = int8_t(vid);
        c.pos[vid] = uint8_t(p);
        maxpos = p > uint32_t(maxpos) ? int(p) : maxpos;
    }
    for (int p = 1; p <= maxpos; ++p) {
        if (owner[p] < 0) {
            ++c.holes;
            continue;
        }
        if (c.n < kCars)
            c.order[c.n++] = uint8_t(owner[p]);
    }
    if (c.dups) { // two cars on one position: a torn read during the game's re-sort, or not this layout
        std::memset(c.pos, 0, sizeof c.pos);
        c.n = 0;
    }
    c.ok = c.n > 0 && !c.dups;
    // the game's own sorted list (the stock pills read it): entry k is the car in position k + 1
    if (c.ok && rd(R + 0x108, v, sizeof v)) {
        size_t ns = 0;
        uintptr_t sorted[kMaxEntries];
        if (vec_ok(v[0], v[1], 8, kMaxEntries, ns) && ns && rd(v[0], sorted, ns * 8)) {
            c.sorted = 1;
            for (int i = 0; i < c.n; ++i) {
                const int vid = c.order[i], p = c.pos[vid];
                if (size_t(p) > ns || sorted[p - 1] != ptr[vid])
                    c.sorted = 0;
            }
        }
    }
    if (c.ok)
        ++c.seq;
    s_.cls = c;
    read_badges(now, f);
}

// ---------------------------------------------------------------- team badges (field-traces.md §10)

// A C string of at most cap bytes (with the NUL) at p. The first copy stops at the page end, so a short string near
// the end of the last readable page still reads; a second copy continues when the first held no NUL.
bool Reader::read_cstr(uintptr_t p, char *out, size_t cap)
{
    const size_t room = 0x1000 - (p & 0xfff);
    const size_t first = cap < room ? cap : room;
    if (!rd(p, out, first))
        return false;
    if (first == cap || std::memchr(out, 0, first))
        return true;
    return rd(p + first, out + first, cap - first);
}

// The game's Team_Set_TimingPillBadge 0x141760020 for the cars due (never read, or failed over a second ago): the
// entrant with the car's vehicle id, its team word, the team record, then the record's key. Kind 1 and records with
// the render flag get another path from the game (protected code, not followed): unknown. Never a guess: any step
// that fails leaves the car unknown with the step's number.
void Reader::read_badges(double now, const Frame &f)
{
    Badges &B = s_.badges;
    int due[kBadgeCarsPerRun];
    int nd = 0;
    for (int vid = 0; vid < kCars && nd < kBadgeCarsPerRun; ++vid) {
        const BadgeRead &b = B.car[vid];
        if (racer(f, vid) &&
            (b.state == kBadgeUnread || (b.state == kBadgeFailed && (now - b.t >= 1.0 || now < b.t))))
            due[nd++] = vid;
    }
    if (!nd)
        return;
    const auto fail = [&](int vid, uint8_t step) {
        BadgeRead &b = B.car[vid];
        if (b.state != kBadgeFailed || b.step != step)
            ++B.seq;
        b = BadgeRead{};
        b.state = kBadgeFailed;
        b.step = step;
        b.t = now;
    };
    const auto fail_all = [&](uint8_t step) {
        for (int i = 0; i < nd; ++i)
            fail(due[i], step);
    };
    const uintptr_t GMC = find(c_mode_, k_.game_mode_context, now);
    if (!GMC)
        return fail_all(1);
    uintptr_t mode = 0, game = 0, ev[2];
    if (!get(GMC + badge::mode, mode) || !mode || (mode & 7) || !get(mode + badge::game, game) || !game || (game & 7))
        return fail_all(2);
    // the entrants of the game, [G+0x2e0, G+0x2e8): walked in order, kEntrantChunk records per copy, until every due
    // car has its first entrant (the game takes the first entrant with the id). The vector has no cap in the game.
    size_t ne = 0;
    if (!rd(game + badge::entrants, ev, sizeof ev)) {
        B.entrants = kEntrantsUnreadable;
        return fail_all(3);
    }
    if (!vec_ok(ev[0], ev[1], badge::entrant_stride, kMaxEntrants, ne)) {
        B.entrants = kEntrantsNotSane;
        return fail_all(3);
    }
    B.entrants = int32_t(ne);
    if (!ne)
        return fail_all(3);
    uint32_t word[kBadgeCarsPerRun] = {};
    bool hit[kBadgeCarsPerRun] = {};
    bool walked = true; // false: a chunk was unreadable, so a car not found yet is unknown (step 3), not absent (4)
    int left = nd;
    for (size_t j0 = 0; j0 < ne && left; j0 += kEntrantChunk) {
        const size_t m = ne - j0 < kEntrantChunk ? ne - j0 : kEntrantChunk;
        if (!rd(ev[0] + j0 * badge::entrant_stride, ebuf_, m * badge::entrant_stride)) {
            B.entrants = kEntrantsCopyFailed;
            walked = false;
            break;
        }
        for (size_t j = 0; j < m && left; ++j) {
            const uint8_t *e = ebuf_ + j * badge::entrant_stride;
            for (int i = 0; i < nd; ++i)
                if (!hit[i] && e[badge::entrant_vid] == due[i]) {
                    hit[i] = true;
                    word[i] = at<uint32_t>(e, badge::entrant_team);
                    --left;
                }
        }
    }
    // the team tables: kind k's table pointer at TT + 0x2c8 + k * 16 (one copy of the three, when a car needs it);
    // each kind's bounds are read at most once a run
    const uintptr_t TT = find(c_teams_, k_.team_tables, now);
    constexpr unsigned kKinds = badge::max_kind + 1;
    bool tread = false;
    uintptr_t tptr[kKinds] = {}, tbeg[kKinds] = {};
    size_t tn[kKinds] = {};
    bool tok[kKinds] = {}, tdone[kKinds] = {};
    uint8_t span[badge::record_render + 1 - badge::record_key]; // [record+0x4d8, record+0x58e): key pointer, render flag
    for (int i = 0; i < nd; ++i) {
        const int vid = due[i];
        if (!hit[i]) {
            fail(vid, walked ? 4 : 3);
            continue;
        }
        const unsigned kind = word[i] & 0xff, index = word[i] >> 16;
        if (kind > badge::max_kind) {
            fail(vid, 5);
            continue;
        }
        if (!tread) {
            tread = true;
            uintptr_t slots[kKinds * 2];
            if (TT && rd(TT + badge::tables, slots, sizeof slots))
                for (unsigned k = 0; k < kKinds; ++k)
                    tptr[k] = slots[k * 2];
        }
        if (!tdone[kind]) {
            tdone[kind] = true;
            uintptr_t v[2] = {};
            tok[kind] = tptr[kind] && !(tptr[kind] & 7) && rd(tptr[kind] + badge::table_vec, v, sizeof v) &&
                        vec_ok(v[0], v[1], 16, 4096, tn[kind]);
            tbeg[kind] = v[0];
        }
        if (!tok[kind]) {
            fail(vid, 6);
            continue;
        }
        uintptr_t rec = 0;
        if (index >= tn[kind] || !get(tbeg[kind] + size_t(index) * 16 + 8, rec) || !rec || (rec & 7)) {
            fail(vid, 7);
            continue;
        }
        BadgeRead got;
        got.kind = uint8_t(kind);
        got.index = uint16_t(index);
        got.t = now;
        if (kind == badge::my_team_kind) { // the game's My Team path (0x141760107): a render badge
            got.state = kBadgeOther;
        } else {
            if (!rd(rec + badge::record_key, span, sizeof span)) {
                fail(vid, 8);
                continue;
            }
            const uintptr_t kp = at<uintptr_t>(span, 0);
            if (span[badge::record_render - badge::record_key]) {
                got.state = kBadgeOther; // 0x14176028c: Team_Format_RenderBadgePath
            } else {
                char key[kBadgeKeyMax];
                if (!kp || !read_cstr(kp, key, sizeof key)) {
                    fail(vid, 8);
                    continue;
                }
                if (!badge_key_ok(key, sizeof key)) {
                    fail(vid, 9);
                    continue;
                }
                int id = -1;
                for (int k = 0; k < B.keys && id < 0; ++k)
                    if (std::strcmp(B.key[k], key) == 0)
                        id = k;
                if (id < 0 && B.keys < kCars) {
                    id = B.keys++;
                    std::memcpy(B.key[id], key, std::strlen(key) + 1);
                }
                if (id < 0) {
                    fail(vid, 9);
                    continue;
                }
                got.state = kBadgeKey;
                got.key = int8_t(id);
            }
        }
        B.car[vid] = got;
        ++B.seq;
    }
}

// ---------------------------------------------------------------- gaps (T) and the safety car

void Reader::job_timing(double now, const Frame &)
{
    Timing t;
    t.t = now;
    const uintptr_t T = find(c_timing_, k_.timing, now);
    s_.found_timing = T != 0;
    uintptr_t v[2];
    size_t n = 0;
    uint8_t *buf = tbuf_;
    if (T && rd(T + 0x30, v, sizeof v) && vec_ok(v[0], v[1], kTimingStride, kMaxEntries, n) &&
        (!n || rd(v[0], buf, n * kTimingStride))) {
        t.ok = true;
        t.entries = int(n);
        for (size_t i = 0; i < n; ++i) {
            const uint8_t *e = buf + i * kTimingStride;
            const uint8_t vid = e[0x90];
            if (vid >= kCars || t.car[vid].have) // the game's readers take the first entry with the id
                continue;
            GapRec &g = t.car[vid];
            g.have = true;
            g.leader_ms = at<int64_t>(e, 0x58);
            g.leader_valid = e[0x68] != 0;
            g.ahead_ms = at<int64_t>(e, 0x70);
            g.ahead_valid = e[0x80] != 0;
            g.gained = e[0x88];
            g.lost = e[0x89];
        }
    }
    s_.timing = t;

    SafetyCarRead sc;
    sc.t = now;
    const uintptr_t S = find(c_sc_, k_.safety_car, now);
    s_.found_sc = S != 0;
    uint8_t b[2];
    if (S && rd(S + 0x108, b, sizeof b) && b[0] <= 3) {
        sc.state = int8_t(b[0]);
        sc.extra = b[1];
    }
    s_.sc = sc;
}

// ---------------------------------------------------------------- pit state and laps

void Reader::job_pitlaps(double now, const Frame &f)
{
    PitLaps p;
    p.t = now;
    const uintptr_t S = find(c_pit_, k_.pit, now);
    s_.found_pit = S != 0;
    uintptr_t rec[kCars * 2];
    if (S && rd(S + 0x68, rec, sizeof rec)) {
        for (int vid = 0; vid < kCars; ++vid) {
            const uintptr_t q = rec[vid * 2];
            uint32_t st = 0;
            if (!racer(f, vid) || !q || (q & 3) || !get(q + 4, st) || st > 15)
                continue;
            p.pit_have[vid] = true;
            p.pit[vid] = uint8_t(st);
            p.pit_ok = true;
        }
    }
    // VehicleProgressSystem [[g_Game_Manager]+0x2d0]: entries [sys+0x38, sys+0x40) by vehicle id; lap counter
    // = u16 +0x38 ^ u16 +0x40 (the provider's progress_entry)
    uintptr_t mgr = 0, sys = 0, v[2];
    size_t n = 0;
    uintptr_t ptr[kMaxEntries];
    s_.found_progress = false;
    if (k_.game_manager && get(k_.game_manager, mgr) && mgr && get(mgr + 0x2d0, sys) && sys &&
        rd(sys + 0x38, v, sizeof v) && vec_ok(v[0], v[1], 8, kMaxEntries, n) && n && rd(v[0], ptr, n * 8)) {
        s_.found_progress = true;
        for (int vid = 0; vid < kCars && size_t(vid) < n; ++vid) {
            uint8_t b[0x10];
            if (!racer(f, vid) || !ptr[vid] || (ptr[vid] & 7) || !rd(ptr[vid] + 0x38, b, sizeof b))
                continue;
            const int lap = int(int16_t(at<uint16_t>(b, 0) ^ at<uint16_t>(b, 8)));
            if (lap < -2 || lap > 1000)
                continue;
            p.lap_have[vid] = true;
            p.lap[vid] = int16_t(lap);
            p.laps_ok = true;
        }
    }
    s_.pitlaps = p;
}

// ---------------------------------------------------------------- penalties

void Reader::job_pen(double now, const Frame &f)
{
    Penalties &P = s_.pen;
    const uint32_t seq = P.log_seq;
    P = Penalties{};
    P.log_seq = seq;
    P.t = now;
    const uintptr_t Z = find(c_log_, k_.penalty_log, now);
    s_.found_log = Z != 0;
    uintptr_t v[2];
    size_t n = 0;
    if (Z && rd(Z + 0x48, v, sizeof v) && vec_ok(v[0], v[1], kPenaltyStride, kMaxPenaltyRecords, n)) {
        bool ok = true;
        uint8_t chunk[kMaxPenaltyChunk * kPenaltyStride];
        uint64_t last = 0;
        for (size_t i = 0; i < n && ok; i += kMaxPenaltyChunk) {
            const size_t c = n - i < size_t(kMaxPenaltyChunk) ? n - i : size_t(kMaxPenaltyChunk);
            if (!rd(v[0] + i * kPenaltyStride, chunk, c * kPenaltyStride)) {
                ok = false;
                break;
            }
            for (size_t j = 0; j < c; ++j) {
                const uint8_t *r = chunk + j * kPenaltyStride;
                PenaltyRecord rec;
                rec.vehicle = r[0x08];
                rec.penalty = r[0x09];
                rec.infringement = r[0x0a];
                rec.other_vehicle = r[0x0b];
                rec.time_s = at<uint32_t>(r, 0x0c);
                rec.lap = at<uint32_t>(r, 0x10);
                rec.places = at<uint32_t>(r, 0x18);
                rec.points = at<uint32_t>(r, 0x20);
                rec.safety_points = at<uint32_t>(r, 0x2c);
                if (i + j < size_t(kLogRecords))
                    P.rec[i + j] = rec;
                if (rec.vehicle < kCars && rec.penalty == kPenaltyWarning) {
                    WarningCounts &w = P.warn[rec.vehicle];
                    ++w.total;
                    if (rec.infringement <= 0x1d && ((kTrackLimitsMask >> rec.infringement) & 1u))
                        ++w.track_limits;
                }
                if (i + j + 1 == n)
                    last = record_hash(r);
            }
        }
        if (ok) {
            P.log_ok = true;
            P.records = int(n);
            if (uint32_t(n) != pen_count_ || last != pen_last_) {
                pen_count_ = uint32_t(n);
                pen_last_ = last;
                ++P.log_seq;
            }
        } else {
            for (WarningCounts &w : P.warn)
                w = WarningCounts{};
        }
    }
    // MisconductManager (S1+0x410): drive-throughs [S1+0x568] (0x28-byte records, 4 slots, 0xff = empty) and
    // stop-gos [S1+0x578] (4-byte records, byte +3); a car past the end of a vector has 0 (the game's rule).
    const uintptr_t S1 = find(c_s1_, k_.session_component, now);
    s_.found_s1 = S1 != 0;
    uintptr_t obj[3];
    if (S1 && rd(S1 + 0x568, obj, sizeof obj) && obj[0] && obj[2] && !(obj[0] & 7) && !(obj[2] & 7)) {
        uintptr_t dv[2], sv[2];
        size_t dn = 0, sn = 0;
        uint8_t drec[kCars * 0x28];
        uint8_t srec[kCars * 4];
        if (rd(obj[0] + 0x68, dv, sizeof dv) && vec_ok(dv[0], dv[1], 0x28, 256, dn) &&
            rd(obj[2] + 0x68, sv, sizeof sv) && vec_ok(sv[0], sv[1], 4, 256, sn)) {
            const size_t dc = dn < size_t(kCars) ? dn : size_t(kCars), sc = sn < size_t(kCars) ? sn : size_t(kCars);
            if ((!dc || rd(dv[0], drec, dc * 0x28)) && (!sc || rd(sv[0], srec, sc * 4))) {
                P.mc_ok = true;
                for (int vid = 0; vid < kCars; ++vid) {
                    if (size_t(vid) < dc) {
                        const uint8_t *r = drec + vid * 0x28;
                        P.dt[vid] = uint8_t((r[0x08] != 0xff) + (r[0x10] != 0xff) + (r[0x18] != 0xff) + (r[0x20] != 0xff));
                    }
                    if (size_t(vid) < sc)
                        P.sg[vid] = srec[vid * 4 + 3];
                }
            }
        }
    }
    (void)f;
}

// ---------------------------------------------------------------- tyres

void Reader::read_tyre(uintptr_t V, TyreRead &t)
{
    uint8_t b[kTyreHi - kTyreLo];
    const auto F = [&](uintptr_t off) { return off - kTyreLo; };
    if (!V || (V & 7) || !rd(V + kTyreLo, b, sizeof b)) {
        t.state = 3;
        return;
    }
    const uint64_t version = at<uint64_t>(b, F(0x9bc0)), count = at<uint64_t>(b, F(0x9c48));
    const uint64_t built_for = at<uint64_t>(b, F(0x9c50)), built = at<uint64_t>(b, F(0x9c58));
    const uintptr_t sb = at<uintptr_t>(b, F(0x9c90)), se = at<uintptr_t>(b, F(0x9c98));
    if (!built || built_for != version) { // the game rebuilds first (0x142e9e6c0); the reader never calls it
        t.state = 2;
        return;
    }
    uint32_t id = 0;
    if (count == 0 || count > 5 || !sb || se < sb || se - sb < 0x78 || !get(se - 0x6c, id)) {
        t.state = 3;
        return;
    }
    const uint8_t *list = b + F(0x9bd0), *desc = nullptr;
    for (size_t i = 0; i < count && !desc; ++i)
        if (at<uint32_t>(list, i * 0x18) == id)
            desc = list + i * 0x18;
    const uint32_t fallback = id >= 3 ? 4 : 1; // 0x142d00ca2..0x142d00cad
    for (size_t i = 0; i < count && !desc; ++i)
        if (at<uint32_t>(list, i * 0x18) == fallback)
            desc = list + i * 0x18;
    if (!desc) {
        t.state = 3;
        return;
    }
    const uintptr_t actual = at<uintptr_t>(desc, 8), visual = at<uintptr_t>(desc, 0x10);
    uint8_t vr[0x54];
    if (!visual || !rd(visual, vr, sizeof vr)) {
        t.state = 3;
        return;
    }
    const int32_t c = at<int32_t>(vr, 0x50);
    uint8_t act = 0xff;
    if (c < -1 || c > 8 || (actual && !get(actual, act))) {
        t.state = 3;
        return;
    }
    t.state = 1;
    t.set_id = id;
    t.desc_id = at<uint32_t>(desc, 0);
    t.visual = vr[0];
    t.actual = act;
    t.compound = c;
    t.letter = tyre_letter(c);
}

void Reader::job_tyres(double now, const Frame &f, int half)
{
    const uintptr_t TS = find(c_tyres_, k_.tyres, now);
    s_.found_tyres = TS != 0;
    uintptr_t v[2];
    size_t n = 0;
    uintptr_t ptr[kMaxEntries];
    const bool table = TS && rd(TS + 0x110, v, sizeof v) && vec_ok(v[0], v[1], 8, kMaxEntries, n) &&
                       (!n || rd(v[0], ptr, n * 8));
    for (int vid = half; vid < kCars; vid += 2) {
        if (!racer(f, vid))
            continue;
        TyreRead &t = s_.tyre[vid];
        const char held = t.held;
        const double held_t = t.held_t;
        t = TyreRead{};
        t.t = now;
        t.held = held;
        t.held_t = held_t;
        if (!table || size_t(vid) >= n) {
            t.state = 3;
            continue;
        }
        read_tyre(ptr[vid], t);
        if (const char letter = checked_letter(t)) {
            t.held = letter;
            t.held_t = now;
        }
    }
}

// ---------------------------------------------------------------- flags (field-traces.md §7)

void Reader::job_flags(double now, const Frame &f)
{
    FlagRead &F = s_.flags;
    const uint32_t seq = F.seq;
    const bool sectors_ok = F.sectors_ok;
    const SectorTable sectors = F.sectors;
    F = FlagRead{};
    F.seq = seq + 1;
    F.t = now;
    F.sectors_ok = sectors_ok;
    F.sectors = sectors;
    // The session's sector table: one copy of the three globals, kept until the next reset; a failed or rejected
    // read is tried again at most once a second.
    if (!F.sectors_ok && k_.sector_table && (now - sector_try_ >= 1.0 || now < sector_try_)) {
        sector_try_ = now;
        uint8_t b[kSectorBlock];
        F.sectors_ok = rd(k_.sector_table, b, sizeof b) && sector_table_from(b, F.sectors);
    }
    if (F.sectors_ok && f.player_lap_m >= 0.f)
        F.player_sector = int8_t(sector_of(F.sectors, f.player_lap_m));

    // Zones: the bounds, one copy of the entries, one copy of [Z, Z+0x18) per zone, the start of each yellow zone.
    const uintptr_t MZ = find(c_zones_, k_.marshal_zones, now);
    s_.found_zones = MZ != 0;
    uintptr_t v[2];
    size_t n = 0;
    if (MZ && rd(MZ + 0x88, v, sizeof v) && vec_ok(v[0], v[1], kZoneStride, kMaxMarshalZones, n) &&
        (!n || rd(v[0], zbuf_, n * kZoneStride))) {
        bool ok = true;
        for (size_t i = 0; i < n; ++i) {
            const uintptr_t z = at<uintptr_t>(zbuf_, i * kZoneStride + 8);
            uint8_t zb[0x18];
            int32_t flag = -1;
            if (!z || (z & 7) || !rd(z, zb, sizeof zb) || (flag = at<int32_t>(zb, 0x14)) < zone_none || flag > zone_red) {
                ok = false;
                break;
            }
            F.flag[i] = int8_t(flag);
            if (flag != zone_yellow)
                continue;
            ++F.yellow;
            const uintptr_t def = at<uintptr_t>(zb, 0);
            float start = -1.f;
            int s = 0;
            if (F.sectors_ok && def && !(def & 3) && get(def + 0x10, start) && std::isfinite(start) && start >= 0.f &&
                start <= 1.f)
                s = sector_of(F.sectors, F.sectors.track_length * start);
            F.sector[i] = int8_t(s);
            if (s)
                F.ysec |= uint8_t(1u << (s - 1));
            else
                F.unmapped = true;
        }
        if (ok) {
            F.zones_ok = true;
            F.zones = int(n);
        } else { // one bad zone: the whole list is unavailable (nothing raised from a partial list)
            std::memset(F.flag, 0, sizeof F.flag);
            std::memset(F.sector, 0, sizeof F.sector);
            F.yellow = 0;
            F.ysec = 0;
            F.unmapped = false;
        }
    }

    // Red flag: one byte.
    const uintptr_t RF = find(c_red_, k_.red_flag, now);
    s_.found_red = RF != 0;
    uint8_t r = 0xff;
    if (RF && get(RF + 0x40, r) && r <= 2)
        F.red = int8_t(r);
}

// ---------------------------------------------------------------- game mode (Time Trial, ModeRead)

// The registry's game mode context (cached, as the badges' read), the mode object, its label pointer, then the label:
// at most two copies for the label. Any step that fails leaves the mode unread with the step's number.
void Reader::job_mode(double now)
{
    ModeRead &M = s_.mode;
    const uint32_t seq = M.seq;
    M = ModeRead{};
    M.seq = seq + 1;
    M.t = now;
    const uintptr_t GMC = find(c_mode_, k_.game_mode_context, now);
    uintptr_t mode = 0, label = 0;
    if (!GMC) {
        M.step = 1;
        return;
    }
    if (!get(GMC + badge::mode, mode) || !mode || (mode & 7)) {
        M.step = 2;
        return;
    }
    if (!get(mode + kModeLabel, label) || !label) {
        M.step = 3;
        return;
    }
    char b[kModeLabelMax];
    if (!read_cstr(label, b, sizeof b)) {
        M.step = 4;
        return;
    }
    size_t n = 0;
    for (; n < sizeof b && b[n]; ++n) {
        const char ch = b[n];
        if (!((ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') || ch == '_')) {
            M.step = 4;
            return;
        }
    }
    if (n == 0 || n == sizeof b) {
        M.step = 4;
        return;
    }
    std::memcpy(M.label, b, n + 1);
    M.ok = true;
    M.time_trial = std::strcmp(M.label, "time_trial") == 0;
}

} // namespace tower
