// Host tests for the in-process game-state provider and the HUD model.
// Builds fake game objects with the F1 25 layouts in this process, points the provider at them, and checks
// decoding, validation, lifecycle handling (freed and recycled objects, AI takeover, session changes) and
// that nothing faults. Build and run: tests/run_tests.sh
#include "../src/game_state_f1_25.hpp"
#include "../src/halo_corners.hpp"
#include "../src/hud_model.hpp"
#include "../src/leaves.hpp"

#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

using namespace halo;

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
#define APPROX(a, b, eps) CHECK(std::fabs(double(a) - double(b)) <= (eps))

// vtables: static data inside this exe's image, like the game's. vt_car stands for vt_Car_SystemsContainer, the
// vptr of the container embedded at CarLive+0x380 (CarLive itself has no vtable).
static uintptr_t vt_car[4], vt_sys[4], vt_mgr[4], vt_world[4];

// Placement tags like the game's: string literals inside the image at any alignment. CarLive+0x0 holds the tag of
// the last Game_Place_Vehicle call: 0 at create, "VehicleProxyActor" (0x14560eb38, 8-aligned) while the pit-box
// actor holds the car in the garage, "PitLaneMovementManager::moveDownSpline" (0x14584366a, address & 7 == 2) once
// the pit lane releases it.
alignas(8) static const char kTagProxy[] = "VehicleProxyActor";
alignas(8) static const char kTagSplineBuf[] = "..PitLaneMovementManager::moveDownSpline";
static const char *const kTagSpline = kTagSplineBuf + 2;

// ---------------------------------------------------------------- fake game memory

struct Block {
    uint8_t *p;
    size_t n;
};
static std::vector<Block> g_blocks;

static uint8_t *alloc(size_t n)
{
    // page-backed so a block can be released for real (VirtualFree) to test freed objects
    auto *p = static_cast<uint8_t *>(VirtualAlloc(nullptr, n, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    std::memset(p, 0, n);
    g_blocks.push_back({p, n});
    return p;
}
template <class T> void put(uint8_t *base, size_t off, T v) { std::memcpy(base + off, &v, sizeof v); }
static void put_obf(uint8_t *base, size_t off, float f, uint32_t key)
{
    uint32_t bits;
    std::memcpy(&bits, &f, 4);
    put<uint32_t>(base, off, bits ^ key);
    put<uint64_t>(base, off + 8, key);
}

struct FakeCar {
    uint8_t *car, *engine, *gearbox, *chassis, *steering, *ers, *body, *state;
};

// A CarLive as Car_Chassis_Build leaves it: +0x0 (the placement tag) 0, +0x98 = the car's own +0xa0 (the teleport
// lock's CRITICAL_SECTION), +0x380 = the systems container's vptr.
static FakeCar make_car(uint8_t id, uint32_t is_ai, bool with_ers = true)
{
    FakeCar c{};
    c.car = alloc(0x600);
    put<uintptr_t>(c.car, 0, 0);
    put<uintptr_t>(c.car, 0x98, uintptr_t(c.car) + 0xa0);
    put<uintptr_t>(c.car, 0x380, uintptr_t(vt_car));
    put<uint8_t>(c.car, 0xe8, id);
    put<uint32_t>(c.car, 0x124, is_ai);
    auto sys = [&](size_t n, size_t slot) {
        uint8_t *s = alloc(n);
        put<uintptr_t>(s, 0, uintptr_t(vt_sys));
        put<uintptr_t>(s, 8, uintptr_t(c.car));
        put<uintptr_t>(c.car, slot, uintptr_t(s));
        return s;
    };
    c.engine = sys(0x2600, 0x530);
    c.gearbox = sys(0x700, 0x538);
    c.chassis = sys(0x400, 0x558);
    c.steering = sys(0x200, 0x560);
    c.ers = with_ers ? sys(0x1a80, 0x5a8) : nullptr;
    c.body = alloc(0x40);
    c.state = alloc(0x240);
    put<uintptr_t>(c.chassis, 0x340, uintptr_t(c.body));
    put<uintptr_t>(c.body, 0x18, uintptr_t(c.state));
    return c;
}

static void set_drive(FakeCar &c, float vx, float vz, uint32_t gear_index, float rate, float thr, float brk, uint8_t flags)
{
    put<float>(c.state, 0x220, vx);
    put<float>(c.state, 0x224, 0.f);
    put<float>(c.state, 0x228, vz);
    put<uint32_t>(c.gearbox, 0x680, gear_index);
    put<float>(c.engine, 0x2538, rate);
    put<float>(c.engine, 0x2528, 1371.8f);
    put<float>(c.car, 0x188, thr);
    put<float>(c.car, 0x190, brk);
    put<uint8_t>(c.car, 0x224, flags);
    put<float>(c.chassis, 0x320, 1.5f);
    put<float>(c.chassis, 0x324, -3.25f);
    put_obf(c.steering, 0x28, 0.34f, 0x9e3779b9u);
    put_obf(c.steering, 0xe8, -0.17f, 0x7f4a7c15u);
}

static void set_ers(FakeCar &c, float energy, float hk, float dp, int32_t mode)
{
    put<float>(c.ers, 0x28, 350e3f);
    put<float>(c.ers, 0x60, 4e6f);
    put<float>(c.ers, 0x19c8, 1.2e6f);
    put<float>(c.ers, 0x19d0, 2.5e6f);
    put<float>(c.ers, 0x19f0, energy);
    put<float>(c.ers, 0x19f4, 8.5e6f);
    put<float>(c.ers, 0x1a00, hk);
    put<float>(c.ers, 0x1a04, 0.f);
    put<float>(c.ers, 0x1a14, dp);
    put<int32_t>(c.ers, 0x1a68, mode);
}

struct FakeGame {
    uintptr_t table[32]{};
    uint32_t count = 0;
    uintptr_t manager = 0;
    float track_length = 4309.f;
    uint32_t session_type = 15;
    uintptr_t world = 0;
    uint8_t *mgr, *sys, *vec, *entries[32]{};
};

static void set_progress(FakeGame &g, uint8_t id, float total, uint16_t lap)
{
    uint8_t *e = g.entries[id];
    put<uint16_t>(e, 0x38, uint16_t(lap ^ 0x5a5a));
    put<uint64_t>(e, 0x40, 0x5a5a);
    // progress lap (+ delta 0): the lap the accumulated distance is counted from
    const int16_t plap = int16_t(std::floor(total / g.track_length));
    put<uint16_t>(e, 0x48, uint16_t(uint16_t(plap) ^ 0x3c3c));
    put<uint64_t>(e, 0x50, 0x3c3c);
    put<int16_t>(e, 0x58, 0);
    uint32_t bits;
    std::memcpy(&bits, &total, 4);
    put<uint32_t>(e, 0x98, bits ^ 0x13572468u);
    put<uint64_t>(e, 0xa0, 0x13572468u);
    // point 0's lap distance (+0x108 pair): not the total; garbage here must not matter
    put<uint32_t>(e, 0x108, 0x7fc00001u ^ 0x2222u);
    put<uint64_t>(e, 0x110, 0x2222u);
    // the link back to the car: [[entry+0x28]+0x58]
    uint8_t *veh = alloc(0x80);
    put<uintptr_t>(veh, 0x58, g.table[id]);
    put<uintptr_t>(e, 0x28, uintptr_t(veh));
}

static void make_world(FakeGame &g, int entries, const char *track = "brazil")
{
    g.mgr = alloc(0x400);
    put<uintptr_t>(g.mgr, 0, uintptr_t(vt_mgr));
    g.sys = alloc(0x100);
    put<uintptr_t>(g.sys, 0, uintptr_t(vt_mgr));
    put<uintptr_t>(g.mgr, 0x2d0, uintptr_t(g.sys));
    g.vec = alloc(8 * 32);
    for (int i = 0; i < entries; ++i) {
        g.entries[i] = alloc(0x200);
        put<uintptr_t>(g.vec, size_t(i) * 8, uintptr_t(g.entries[i]));
    }
    put<uintptr_t>(g.sys, 0x38, uintptr_t(g.vec));
    put<uintptr_t>(g.sys, 0x40, uintptr_t(g.vec) + size_t(entries) * 8);
    g.manager = uintptr_t(g.mgr);
    // track name chain [[[world]+0xd0]+0xe8]+0xa0
    uint8_t *w = alloc(0x100), *a = alloc(0x100), *t = alloc(0x100), *name = alloc(64);
    put<uintptr_t>(w, 0, uintptr_t(vt_world));
    put<uintptr_t>(w, 0xd0, uintptr_t(a));
    put<uintptr_t>(a, 0xe8, uintptr_t(t));
    put<uintptr_t>(t, 0xa0, uintptr_t(name));
    std::strcpy(reinterpret_cast<char *>(name), track);
    g.world = uintptr_t(w);
}

static gs::F1_25Symbols symbols(FakeGame &g)
{
    gs::F1_25Symbols s;
    s.vehicle_table = uintptr_t(g.table);
    s.vehicle_count = uintptr_t(&g.count);
    s.game_manager = uintptr_t(&g.manager);
    s.track_length = uintptr_t(&g.track_length);
    s.session_type = uintptr_t(&g.session_type);
    s.track_world = uintptr_t(&g.world);
    s.vt_car_systems = uintptr_t(vt_car);
    return s;
}

// ---------------------------------------------------------------- tests

static void test_decode()
{
    FakeGame g;
    make_world(g, 3);
    FakeCar a = make_car(0, 1), me = make_car(1, 0), b = make_car(2, 1);
    for (FakeCar *c : {&a, &me, &b})
        set_drive(*c, 30.f, 40.f, 6, 1100.f, 0.75f, 0.f, 0);
    set_ers(me, 2.0e6f, 120e3f, 0.f, 2);
    set_ers(a, 3.0e6f, 0.f, 0.f, 1);
    set_ers(b, 3.0e6f, 0.f, 0.f, 1);
    g.table[0] = uintptr_t(a.car);
    g.table[1] = uintptr_t(me.car);
    g.table[2] = uintptr_t(b.car);
    g.count = 3;
    set_progress(g, 0, 15000.f, 4);
    set_progress(g, 1, 14000.f, 4);
    set_progress(g, 2, 13000.f, 4);

    gs::F1_25Provider p(symbols(g), true);
    gs::GameState s;
    p.sample(1.0, s);
    CHECK(s.compatible && s.session.active);
    CHECK(s.session.cars == 3);
    CHECK(s.session.race() && s.session.track_ok && s.session.track_name_ok);
    CHECK(std::strcmp(s.session.track_name, "brazil") == 0);
    CHECK(s.vehicle.ok && s.vehicle.id == 1 && !s.vehicle.ai_driving);
    CHECK(s.vehicle.speed_ok);
    APPROX(s.vehicle.speed_mps, 50.0, 1e-3);
    CHECK(s.vehicle.gear_ok && s.vehicle.gear == 5);
    CHECK(s.power_unit.rpm_ok);
    APPROX(s.power_unit.rpm, 1100.0 * 60.0 / (2 * 3.14159265358979), 0.5);
    APPROX(s.power_unit.limiter_rpm, 1371.8 * 9.5492966, 0.5);
    CHECK(s.input.ok);
    APPROX(s.input.throttle, 0.75, 1e-6);
    APPROX(s.input.brake, 0.0, 1e-6);
    CHECK(s.vehicle.accel_ok);
    APPROX(s.vehicle.g_lat, 1.5, 1e-6);
    APPROX(s.vehicle.g_long, -3.25, 1e-6);
    CHECK(s.vehicle.steer_ok);
    APPROX(s.vehicle.steer, 0.5, 1e-4);
    CHECK(s.energy.store_ok && s.energy.power_ok && s.energy.mode_ok && s.energy.lap_ok);
    APPROX(s.energy.store_j, 2.0e6, 1);
    APPROX(s.energy.harvest_k_w, 120e3, 1);
    CHECK(s.energy.mode == 2);
    CHECK(s.energy.capacity_ok && s.energy.max_deploy_ok);
    CHECK(s.progress.ok && s.progress.lap == 4);
    APPROX(s.progress.lap_m, std::fmod(14000.0, 4309.0), 0.01);
    CHECK(s.field.ok && s.field.n == 3 && s.field.player_rank == 1);
    CHECK(s.field.id[0] == 0 && s.field.id[2] == 2);
    CHECK(p.raw().rejects == 0);
    CHECK(p.raw().progress_link && p.raw().humans == 1);

    // the HUD model: rival = car ahead in a race, boost from the ERS mode, turn from the official list
    HudModel m;
    m.update(s, 0.016, HudConfig{});
    const View &v = m.view();
    CHECK(v.live && v.speed_ok && v.kmh == 180 && v.mph == 112);
    CHECK(v.gear_ok && v.gear == 5);
    CHECK(v.boost);
    CHECK(v.rival_id == 0);
    CHECK(std::string(m.turn_source()) == "official");

    // reverse with the pedal-swap flag: throttle and brake trade places
    set_drive(me, -2.f, 0.f, 0, 300.f, 0.1f, 0.9f, 0x08);
    p.sample(1.1, s);
    CHECK(s.vehicle.gear == -1);
    APPROX(s.input.throttle, 0.9, 1e-6);
    APPROX(s.input.brake, 0.1, 1e-6);
    set_drive(me, -2.f, 0.f, 0, 300.f, 0.1f, 0.9f, 0x88); // both bits: no swap
    p.sample(1.2, s);
    APPROX(s.input.throttle, 0.1, 1e-6);

    // garbage values are rejected per field, the rest stays valid
    put<float>(me.engine, 0x2538, NAN);
    put<float>(me.car, 0x188, 7.f);
    p.sample(1.3, s);
    CHECK(!s.power_unit.rpm_ok && !s.input.ok && s.vehicle.gear_ok && s.vehicle.speed_ok);

    // a system that does not point back at the car is ignored
    set_drive(me, 30.f, 40.f, 6, 1100.f, 0.75f, 0.f, 0);
    put<uintptr_t>(me.engine, 8, uintptr_t(a.car));
    p.sample(1.4, s);
    CHECK(!s.power_unit.rpm_ok && s.vehicle.ok);
    put<uintptr_t>(me.engine, 8, uintptr_t(me.car));

    // a table slot whose car carries another id is rejected
    put<uint8_t>(b.car, 0xe8, 9);
    p.sample(1.5, s);
    CHECK(s.session.cars == 2 && p.raw().rejects == 1);
    put<uint8_t>(b.car, 0xe8, 2);

    // the AI takes the player's car for a moment: the same car stays the player's
    put<uint32_t>(me.car, 0x124, 1);
    const uint32_t gen = s.session.generation;
    p.sample(1.6, s);
    CHECK(s.vehicle.ok && s.vehicle.id == 1 && s.vehicle.ai_driving && s.session.generation == gen);
    put<uint32_t>(me.car, 0x124, 0);

    // a freed car object (pages released) is skipped without a fault
    VirtualFree(b.car, 0, MEM_RELEASE);
    p.sample(1.7, s);
    CHECK(s.session.cars == 2 && s.vehicle.ok);

    // the player's own car freed while still in the table: no fault, nothing reported for it
    VirtualFree(me.car, 0, MEM_RELEASE);
    p.sample(1.8, s);
    CHECK(!s.vehicle.ok && s.session.generation != gen);
    m.update(s, 0.016, HudConfig{});
    CHECK(!m.view().live && m.view().rival_id == -1 && m.view().turn.empty());

    // session over: the count drops to 0
    g.count = 0;
    p.sample(1.9, s);
    CHECK(!s.session.active && !s.vehicle.ok);

    // garbage count / null table entries
    g.count = 200;
    p.sample(2.0, s);
    CHECK(!s.session.active);
    g.count = 3;
    g.table[0] = g.table[1] = g.table[2] = 0;
    p.sample(2.1, s);
    CHECK(!s.session.active && p.raw().rejects == 3);
}

static void test_new_session()
{
    FakeGame g;
    make_world(g, 2);
    FakeCar a = make_car(0, 0), sc = make_car(1, 1, false); // player + a safety car (no ERS)
    set_drive(a, 0.f, 0.f, 1, 418.9f, 0.f, 0.f, 0);
    set_ers(a, 4e6f, 0.f, 0.f, 1);
    set_drive(sc, 10.f, 0.f, 3, 500.f, 0.3f, 0.f, 0);
    g.table[0] = uintptr_t(a.car);
    g.table[1] = uintptr_t(sc.car);
    g.count = 2;
    g.session_type = 2; // practice
    set_progress(g, 0, -120.f, 0); // on the grid, behind the line
    set_progress(g, 1, 300.f, 0);
    gs::F1_25Provider p(symbols(g), true);
    gs::GameState s;
    p.sample(0.5, s);
    CHECK(s.vehicle.ok && s.vehicle.speed_mps == 0.f && s.vehicle.gear == 0);
    APPROX(s.power_unit.rpm, 4000.2, 1.0);
    CHECK(!s.session.race());
    CHECK(s.field.n == 1); // the safety car has no ERS: not in the running order
    CHECK(s.progress.ok);
    APPROX(s.progress.lap_m, 4309.f - 120.f, 0.01);
    HudModel m;
    m.update(s, 0.016, HudConfig{});
    CHECK(m.view().live && m.view().rival_id == -1); // no rival outside races
    const uint32_t gen = s.session.generation;

    // restart: new car objects in the same slots
    FakeCar a2 = make_car(0, 0);
    set_drive(a2, 5.f, 0.f, 2, 600.f, 0.2f, 0.f, 0);
    set_ers(a2, 4e6f, 0.f, 0.f, 1);
    g.table[0] = uintptr_t(a2.car);
    p.sample(0.6, s);
    CHECK(s.vehicle.ok && s.session.generation != gen);

    // unsupported build: nothing is read at all
    gs::F1_25Provider off(symbols(g), false);
    off.sample(0.7, s);
    CHECK(!s.compatible && !s.session.active && !s.vehicle.ok);
}

static void test_progress()
{
    FakeGame g;
    make_world(g, 2);
    FakeCar lead = make_car(0, 1), me = make_car(1, 0);
    for (FakeCar *c : {&lead, &me}) {
        set_drive(*c, 80.f, 0.f, 7, 1100.f, 1.f, 0.f, 0);
        set_ers(*c, 3e6f, 0.f, 0.f, 1);
    }
    g.table[0] = uintptr_t(lead.car);
    g.table[1] = uintptr_t(me.car);
    g.count = 2;
    // the leader 11 m past the line, the player 9 m short of it: road order by the accumulated distance
    set_progress(g, 0, 4309.f + 11.f, 2);
    set_progress(g, 1, 4309.f - 9.f, 1);
    gs::F1_25Provider p(symbols(g), true);
    gs::GameState s;
    p.sample(1.0, s);
    CHECK(s.field.ok && s.field.id[0] == 0 && s.field.player_rank == 1);
    CHECK(s.progress.ok && p.raw().progress_link);
    APPROX(s.progress.lap_m, 4300.0, 0.01);
    // the player crosses the line: the lap distance wraps, the total keeps counting
    set_progress(g, 1, 4309.f + 1.f, 2);
    p.sample(1.1, s);
    APPROX(s.progress.lap_m, 1.0, 0.01);
    APPROX(s.progress.total_m, 4310.0, 0.01);
    // one change 0.1 s after the first: no distance reference yet (it needs >= 0.5 s, test_distance_reference)
    CHECK(p.raw().distance_window == 0 && p.raw().speed_from_distance == 0);
    // an entry linked to another car is logged; the link is not required until a drive confirms it
    uintptr_t veh = 0;
    std::memcpy(&veh, g.entries[1] + 0x28, sizeof veh);
    put<uintptr_t>(reinterpret_cast<uint8_t *>(veh), 0x58, uintptr_t(lead.car));
    p.sample(1.2, s);
    CHECK(!p.raw().progress_link && s.progress.ok);
}

// only the total, as the game's simulation step writes it (set_progress also rebuilds the entry)
static void set_total(FakeGame &g, uint8_t id, float total)
{
    uint32_t bits;
    std::memcpy(&bits, &total, 4);
    put<uint32_t>(g.entries[id], 0x98, bits ^ 0x13572468u);
}

// The progress total changes once per 60 Hz simulation step while the provider samples every rendered frame
// (~170 fps). Runs 4-6 logged the frame-to-frame difference: 0 on most frames, ~3x the speed on the rest.
static void test_distance_reference()
{
    FakeGame g;
    make_world(g, 2);
    FakeCar lead = make_car(0, 1), me = make_car(1, 0);
    for (FakeCar *c : {&lead, &me}) {
        set_drive(*c, 80.f, 0.f, 7, 1100.f, 1.f, 0.f, 0);
        set_ers(*c, 3e6f, 0.f, 0.f, 1);
    }
    g.table[0] = uintptr_t(lead.car);
    g.table[1] = uintptr_t(me.car);
    g.count = 2;
    set_progress(g, 0, 3000.f, 0);
    set_progress(g, 1, 1000.f, 0);
    gs::F1_25Provider p(symbols(g), true);
    gs::GameState s;
    double t = 10.0, next_step = 10.0;
    float total = 1000.f, speed = 80.f;
    bool steps_on = true;
    int k = 0, bad = 0;
    // frames 1/170 s +-30 %; the simulation steps (when on) at 60 Hz, each seen by the first frame after it
    auto run = [&](double seconds, int &with_ref, float &worst, float &peak) {
        with_ref = 0;
        worst = peak = 0;
        const double end = t + seconds;
        while (t < end) {
            t += (1.0 / 170) * (1.0 + 0.3 * double((k++ * 7919) % 11 - 5) / 5.0);
            for (; next_step <= t; next_step += 1.0 / 60)
                if (steps_on)
                    total += speed / 60.f;
            set_total(g, 1, total);
            p.sample(t, s);
            const gs::F1_25Raw &r = p.raw();
            peak = std::max(peak, std::fabs(r.speed_from_distance));
            if (r.distance_window > 0) {
                ++with_ref;
                worst = std::max(worst, std::fabs(r.speed_from_distance - speed));
                bad += !(r.distance_window >= 0.5f && r.distance_window < 0.56f);
            } else {
                bad += r.speed_from_distance != 0; // no window, no value
            }
        }
    };
    int n = 0;
    float worst = 0, peak = 0;
    run(0.45, n, worst, peak);
    CHECK(n == 0); // < 0.5 s of changes
    run(1.5, n, worst, peak);
    CHECK(n > 230); // every frame from 0.5 s on
    CHECK(worst < 0.025f * speed); // both ends are changes: at most one frame of timing error per end
    // paused (the total holds while frames go on): the reference goes away after 0.25 s ...
    steps_on = false;
    run(0.3, n, worst, peak);
    CHECK(n < 50 && p.raw().distance_window == 0);
    // ... and comes back 0.5 s after the steps resume, without the pause in it
    steps_on = true;
    speed = 50.f;
    run(0.45, n, worst, peak);
    CHECK(n == 0);
    run(1.0, n, worst, peak);
    CHECK(n > 140 && worst < 0.025f * speed);
    // a jump (car reset to the track, flashback) restarts the window instead of reading as speed
    total += 600.f;
    run(0.45, n, worst, peak);
    CHECK(n == 0 && peak < 0.025f * speed + speed);
    run(1.0, n, worst, peak);
    CHECK(n > 140 && worst < 0.025f * speed);
    CHECK(bad == 0);
}

static void test_player()
{
    FakeGame g;
    make_world(g, 3);
    FakeCar c[3] = {make_car(0, 0), make_car(1, 0), make_car(2, 0)}; // loading: no controller set, all read 0
    for (int i = 0; i < 3; ++i) {
        set_drive(c[i], 30.f, 40.f, 6, 1100.f, 0.75f, 0.f, 0);
        set_ers(c[i], 3e6f, 0.f, 0.f, 1);
        g.table[i] = uintptr_t(c[i].car);
        set_progress(g, uint8_t(i), 100.f * float(i), 0);
    }
    g.count = 3;
    gs::F1_25Provider p(symbols(g), true);
    gs::GameState s;
    p.sample(1.0, s);
    CHECK(!s.vehicle.ok && p.raw().humans == 3); // never guess: vehicle 0 is not taken
    // controllers set: one human
    put<uint32_t>(c[0].car, 0x124, 1);
    put<uint32_t>(c[2].car, 0x124, 1);
    p.sample(1.1, s);
    CHECK(s.vehicle.ok && s.vehicle.id == 1 && !s.vehicle.ai_driving);
    // AI handover (formation lap, pit lane): no car reads 0, the held car stays the player's
    put<uint32_t>(c[1].car, 0x124, 1);
    p.sample(1.2, s);
    CHECK(s.vehicle.ok && s.vehicle.id == 1 && s.vehicle.ai_driving);
    // a second human (split-screen): the held car stays the player's
    put<uint32_t>(c[1].car, 0x124, 0);
    put<uint32_t>(c[0].car, 0x124, 0);
    p.sample(1.3, s);
    CHECK(s.vehicle.ok && s.vehicle.id == 1 && !s.vehicle.ai_driving && p.raw().humans == 2);
    // a provider that holds no car in that state: no player
    gs::F1_25Provider fresh(symbols(g), true);
    fresh.sample(1.4, s);
    CHECK(!s.vehicle.ok);
}

// The component registry at [manager]+0x30 (16-byte {key, value} slots, then one info byte per slot) with the
// results system in one slot; the results entries hold each vehicle id's position, 0-based and XOR'd.
static uintptr_t results_key_static[1]; // the key is the address of a static, like the game's

struct FakeResults {
    uint8_t *reg, *slots, *info, *sys, *vec, *entry[32]{};
    int n_slots = 0, slot = -1;
};

static void place_results(FakeResults &r, int slot)
{
    if (r.slot >= 0) {
        put<uintptr_t>(r.slots, size_t(r.slot) * 16, 0);
        put<uintptr_t>(r.slots, size_t(r.slot) * 16 + 8, 0);
        r.info[r.slot] = 0;
    }
    r.slot = slot;
    if (slot < 0)
        return;
    put<uintptr_t>(r.slots, size_t(slot) * 16, uintptr_t(results_key_static));
    put<uintptr_t>(r.slots, size_t(slot) * 16 + 8, uintptr_t(r.sys));
    r.info[slot] = 0x81;
}

static FakeResults make_results(FakeGame &g, int n_slots, int slot, int cars)
{
    FakeResults r;
    r.n_slots = n_slots;
    r.reg = alloc(0x40);
    r.slots = alloc(size_t(n_slots) * 17);
    r.info = r.slots + size_t(n_slots) * 16;
    put<uintptr_t>(r.reg, 0x18, uintptr_t(r.slots));
    put<uintptr_t>(r.reg, 0x20, uintptr_t(r.info));
    put<uintptr_t>(g.mgr, 0x30, uintptr_t(r.reg));
    for (int i = 1; i < n_slots; i += 3) { // other systems in the registry
        put<uintptr_t>(r.slots, size_t(i) * 16, 0x1000u + uintptr_t(i) * 0x40);
        put<uintptr_t>(r.slots, size_t(i) * 16 + 8, uintptr_t(alloc(0x40)));
        r.info[i] = 0x80;
    }
    r.sys = alloc(0x200);
    r.vec = alloc(8 * 32);
    for (int i = 0; i < cars; ++i) {
        r.entry[i] = alloc(0x100);
        put<uint8_t>(r.entry[i], 0, uint8_t(i));
        put<uintptr_t>(r.vec, size_t(i) * 8, uintptr_t(r.entry[i]));
    }
    put<uintptr_t>(r.sys, 0x148, uintptr_t(r.vec));
    put<uintptr_t>(r.sys, 0x150, uintptr_t(r.vec) + size_t(cars) * 8);
    place_results(r, slot);
    return r;
}

static void set_pos(FakeResults &r, uint8_t vid, uint32_t pos)
{
    const uint32_t key = 0x2468ace0u ^ (uint32_t(vid) * 0x01000193u);
    put<uint32_t>(r.entry[vid], 0x48, (pos - 1) ^ key);
    put<uint32_t>(r.entry[vid], 0x50, key);
}

// The ControllerSystem: one controller set per vehicle; a HumanController at set+0x20 only for a car a local
// human drives. The provider reads it through a cached global.
static uintptr_t vt_ctrl_sys[4], vt_human_ctrl[4];

struct FakeControllers {
    uintptr_t global = 0;
    uint8_t *sys, *cv, *sets, *set[32]{}, *human[32]{};
};

static void set_human(FakeControllers &f, int i, bool on)
{
    if (on && !f.human[i]) {
        f.human[i] = alloc(0x20);
        put<uintptr_t>(f.human[i], 0, uintptr_t(vt_human_ctrl));
    }
    put<uintptr_t>(f.set[i], 0x20, on ? uintptr_t(f.human[i]) : 0);
}

static void make_controllers(FakeControllers &f, int n, int human)
{
    f.sys = alloc(0x400);
    put<uintptr_t>(f.sys, 0, uintptr_t(vt_ctrl_sys));
    put<uint8_t>(f.sys, 0x365, 1);
    f.cv = alloc(0x40);
    put<uint32_t>(f.cv, 0x28, 0x10000);
    put<uint32_t>(f.cv, 0x30, 0x10000 + uint32_t(n) * 8);
    put<uintptr_t>(f.sys, 0x90, uintptr_t(f.cv));
    f.sets = alloc(8 * 32);
    put<uintptr_t>(f.sys, 0x30, uintptr_t(f.sets));
    for (int i = 0; i < n; ++i) {
        f.set[i] = alloc(0x40);
        put<uint8_t>(f.set[i], 0x34, uint8_t(i));
        put<uintptr_t>(f.sets, size_t(i) * 8, uintptr_t(f.set[i]));
    }
    if (human >= 0)
        set_human(f, human, true);
    f.global = uintptr_t(f.sys);
}

static gs::F1_25Symbols with_controllers(gs::F1_25Symbols s, FakeControllers &f)
{
    s.controllers = uintptr_t(&f.global);
    s.vt_controllers = uintptr_t(vt_ctrl_sys);
    s.vt_human = uintptr_t(vt_human_ctrl);
    return s;
}

static void test_controllers()
{
    FakeGame g;
    make_world(g, 3);
    FakeCar c[3] = {make_car(0, 0), make_car(1, 0), make_car(2, 0)}; // loading: every car reads is_ai 0
    for (int i = 0; i < 3; ++i) {
        set_drive(c[i], 30.f, 40.f, 6, 1100.f, 0.75f, 0.f, 0);
        set_ers(c[i], 3e6f, 0.f, 0.f, 1);
        g.table[i] = uintptr_t(c[i].car);
        set_progress(g, uint8_t(i), 100.f * float(i), 0);
    }
    g.count = 3;
    FakeControllers f;
    make_controllers(f, 3, 2);
    gs::F1_25Provider p(with_controllers(symbols(g), f), true);
    gs::GameState s;

    // the game's own record names car 2 although the is_ai flags cannot tell
    p.sample(1.0, s);
    CHECK(s.vehicle.ok && s.vehicle.id == 2 && p.raw().ctrl_hits == 1 && p.raw().player_source == 2);
    CHECK(p.raw().isai_vid == -1 && p.raw().humans == 3);
    // AI takeover of car 2 (pit lane, formation lap): the HumanController stays, so does the player
    for (int i = 0; i < 3; ++i)
        put<uint32_t>(c[i].car, 0x124, 1);
    const uint32_t gen = s.session.generation;
    p.sample(1.1, s);
    CHECK(s.vehicle.ok && s.vehicle.id == 2 && s.vehicle.ai_driving && p.raw().player_source == 2);
    CHECK(s.session.generation == gen);
    // a set whose vehicle byte does not read back its index is not counted: the fallback keeps the held car
    put<uint8_t>(f.set[2], 0x34, 7);
    p.sample(1.2, s);
    CHECK(p.raw().ctrl_hits == 0 && s.vehicle.ok && s.vehicle.id == 2 && p.raw().player_source == 3);
    put<uint8_t>(f.set[2], 0x34, 2);
    // the sets destroyed (session end): the game names no local human; the fallback keeps the held car
    put<uint8_t>(f.sys, 0x365, 0);
    p.sample(1.3, s);
    CHECK(p.raw().ctrl_hits == 0 && s.vehicle.ok && p.raw().player_source == 3);
    put<uint8_t>(f.sys, 0x365, 1);
    // not the ControllerSystem (another object, another build): not readable
    put<uintptr_t>(f.sys, 0, uintptr_t(vt_mgr));
    p.sample(1.4, s);
    CHECK(p.raw().ctrl_hits == -1 && p.raw().player_source == 3);
    put<uintptr_t>(f.sys, 0, uintptr_t(vt_ctrl_sys));
    // a second local human (split-screen): one set of leaves cannot show two cars, so no player
    set_human(f, 0, true);
    p.sample(1.5, s);
    CHECK(p.raw().ctrl_hits == 2 && !s.vehicle.ok);
    // back to one: the player returns
    set_human(f, 0, false);
    p.sample(1.6, s);
    CHECK(s.vehicle.ok && s.vehicle.id == 2 && p.raw().player_source == 2);
    // the global cleared (no session): not readable
    f.global = 0;
    p.sample(1.7, s);
    CHECK(p.raw().ctrl_hits == -1);
}

static void test_classification()
{
    FakeGame g;
    make_world(g, 4);
    FakeCar c0 = make_car(0, 1), c1 = make_car(1, 1), me = make_car(2, 0), c3 = make_car(3, 1);
    FakeCar *all[] = {&c0, &c1, &me, &c3};
    for (int i = 0; i < 4; ++i) {
        set_drive(*all[i], 30.f, 40.f, 6, 1100.f, 0.75f, 0.f, 0);
        set_ers(*all[i], 3.0e6f, 0.f, 0.f, 1);
        g.table[i] = uintptr_t(all[i]->car);
        set_progress(g, uint8_t(i), 9000.f - 1000.f * float(i), 2); // road order 0, 1, 2, 3
    }
    g.count = 4;
    g.session_type = 2; // practice: the classification differs from the road order
    FakeResults r = make_results(g, 200, 137, 4);
    set_pos(r, 0, 3);
    set_pos(r, 1, 1);
    set_pos(r, 2, 2);
    set_pos(r, 3, 4);
    gs::F1_25Symbols sym = symbols(g);
    sym.results_key = uintptr_t(results_key_static);
    gs::F1_25Provider p(sym, true);
    gs::GameState s;
    HudModel m;
    auto rival = [&]() {
        m.update(s, 0.016, HudConfig{});
        return m.view().rival_id;
    };

    // practice: the car one place ahead in the classification, not on the road
    p.sample(1.0, s);
    CHECK(p.raw().results_found && s.field.classified);
    CHECK(s.field.pos[0] == 3 && s.field.pos[1] == 1 && s.field.pos[2] == 2 && s.field.pos[3] == 4);
    CHECK(rival() == 1);

    // P1 sees P2
    set_pos(r, 2, 1);
    set_pos(r, 1, 2);
    p.sample(1.1, s);
    CHECK(s.field.classified && s.field.pos[2] == 1 && rival() == 1);

    // two cars on one position: nothing reported, no rival outside races
    set_pos(r, 0, 2);
    p.sample(1.2, s);
    CHECK(!s.field.classified && s.field.pos[0] == 0 && rival() == -1);

    // race: the classification wins over the road order (road: car 1 ahead of the player; classified: car 3)
    set_pos(r, 0, 1);
    set_pos(r, 1, 4);
    set_pos(r, 2, 3);
    set_pos(r, 3, 2);
    g.session_type = 15;
    p.sample(1.3, s);
    CHECK(s.field.classified && s.session.race() && rival() == 3);

    // time trial: the game never updates positions there
    g.session_type = 18;
    p.sample(1.4, s);
    CHECK(s.field.classified && rival() == -1);
    g.session_type = 2;

    // an entry that does not read back its vehicle id is skipped: the player's target (P2) is unknown
    put<uint8_t>(r.entry[3], 0, 7);
    p.sample(1.5, s);
    CHECK(s.field.classified && s.field.pos[3] == 0 && rival() == -1);
    put<uint8_t>(r.entry[3], 0, 3);

    // a position outside 1..count is skipped
    set_pos(r, 3, 40);
    p.sample(1.6, s);
    CHECK(s.field.classified && s.field.pos[3] == 0);
    set_pos(r, 3, 2);

    // the results system leaves the registry: searched again at most once a second
    place_results(r, -1);
    p.sample(2.0, s); // cache miss, search (1 s since the last one): not found
    CHECK(!p.raw().results_found && !s.field.classified);
    place_results(r, 12);
    p.sample(2.5, s); // back, but the last search was 0.5 s ago
    CHECK(!p.raw().results_found && !s.field.classified);
    p.sample(3.1, s);
    CHECK(p.raw().results_found && s.field.classified && s.field.pos[3] == 2 && rival() == 3);

    // a registry pointer to garbage sizes is refused without a fault
    put<uintptr_t>(r.reg, 0x20, uintptr_t(r.slots) + 5);
    p.sample(3.2, s);
    CHECK(!p.raw().results_found && !s.field.classified && s.vehicle.ok);
    put<uintptr_t>(r.reg, 0x20, uintptr_t(r.info));

    // no key (another build's symbols): road order in races only, as before
    gs::F1_25Provider nokey(symbols(g), true);
    nokey.sample(4.0, s);
    CHECK(!s.field.classified && rival() == -1);
}

// F2 (2026-11-10 00:07 and 01:36 logs): no car has ERS, the safety car neither; it sits at the vehicle id after the
// field's and the results hold one entry per competitor. The halo showed no rival names (classified 0, rival -1)
// while every car without ERS was skipped. Competitors count by the results' entry count.
static void test_classification_no_ers()
{
    FakeGame g;
    make_world(g, 5);
    FakeCar c0 = make_car(0, 1, false), c1 = make_car(1, 1, false), me = make_car(2, 0, false),
            c3 = make_car(3, 1, false), sc = make_car(4, 1, false);
    FakeCar *all[] = {&c0, &c1, &me, &c3, &sc};
    for (int i = 0; i < 5; ++i) {
        set_drive(*all[i], 30.f, 40.f, 6, 1100.f, 0.75f, 0.f, 0);
        g.table[i] = uintptr_t(all[i]->car);
        set_progress(g, uint8_t(i), 9000.f - 1000.f * float(i), 2); // road order 0, 1, 2, 3
    }
    set_progress(g, 4, 9500.f, 2); // the safety car ahead of every car on the road
    g.count = 5;
    g.session_type = 2;
    FakeResults r = make_results(g, 200, 137, 4); // vids 0..3: not the safety car
    set_pos(r, 0, 3);
    set_pos(r, 1, 1);
    set_pos(r, 2, 2);
    set_pos(r, 3, 4);
    gs::F1_25Symbols sym = symbols(g);
    sym.results_key = uintptr_t(results_key_static);
    gs::F1_25Provider p(sym, true);
    gs::GameState s;
    HudModel m;
    auto rival = [&]() {
        m.update(s, 0.016, HudConfig{});
        return m.view().rival_id;
    };
    auto has = [&](uint8_t vid) {
        for (int i = 0; i < s.field.n; ++i)
            if (s.field.id[i] == vid)
                return true;
        return false;
    };

    // practice: classified like the F1 field; the safety car has no position
    p.sample(1.0, s);
    CHECK(s.vehicle.ok && s.vehicle.id == 2);
    CHECK(p.raw().results_found && s.field.classified);
    CHECK(s.field.pos[0] == 3 && s.field.pos[1] == 1 && s.field.pos[2] == 2 && s.field.pos[3] == 4 && s.field.pos[4] == 0);
    CHECK(rival() == 1);

    // the road order holds the four competitors, not the safety car ahead of them
    CHECK(s.field.ok && s.field.n == 4 && s.field.id[0] == 0 && s.field.player_rank == 2 && !has(4));

    // race: the classification names the car ahead (car 1 P1, the player P2)
    g.session_type = 15;
    p.sample(1.1, s);
    CHECK(s.session.race() && s.field.classified && rival() == 1);

    // race without the classification's position for the player: the car ahead on the road (car 1), never the
    // safety car
    set_pos(r, 2, 40);
    p.sample(1.2, s);
    CHECK(!s.field.classified && s.field.ok && s.field.n == 4 && !has(4) && rival() == 1);
    set_pos(r, 2, 2);

    // without the results system (another build's symbols) there is no competitor count: cars without ERS are
    // not counted, since one of them is the safety car. No road order, no rival.
    gs::F1_25Provider nokey(symbols(g), true);
    nokey.sample(2.0, s);
    CHECK(s.vehicle.ok && !s.field.classified && s.field.n == 0 && !s.field.ok && rival() == -1);
}

// An in-game log (2026-11-09, Bahrain practice, vehicle 13): 23 table slots, 22 cars in their garages and a safety car that
// was never placed. The pit-box actor's placement leaves an 8-aligned tag at CarLive+0x0, the pit lane's an
// unaligned one: the provider used to read +0x0 as a vtable and lost every car from its pit exit on (cars 22 -> 21
// -> 19, ControllerSystem still naming car 13, the halo blank). The car must stay the player's through the garage,
// the pit exit and the lap, with every DLL-driven part of the halo filled.
static void test_pit_exit()
{
    FakeGame g;
    g.track_length = 5409.f; // the game's Bahrain length in a practice log
    g.session_type = 2;      // practice
    make_world(g, 23, "bahrain");
    std::vector<FakeCar> c;
    for (int i = 0; i < 23; ++i) {
        const bool sc = i == 22; // the safety car: no ERS, never placed (+0x0 stays 0)
        c.push_back(make_car(uint8_t(i), 1, !sc));
        if (!sc) {
            set_ers(c.back(), 4e6f, 0.f, 0.f, 1);
            put<uintptr_t>(c.back().car, 0, uintptr_t(kTagProxy)); // held in the garage by the pit-box actor
        }
        set_drive(c.back(), 0.f, 0.f, 1, 410.5f, 0.f, 0.f, 0x80);
        g.table[i] = uintptr_t(c.back().car);
        set_progress(g, uint8_t(i), -5184.f, 0);
    }
    g.count = 23;
    FakeResults r = make_results(g, 300, 77, 23);
    for (int i = 0; i < 22; ++i)
        set_pos(r, uint8_t(i), uint32_t(i + 1));
    set_pos(r, 22, 1); // an entry under the safety car's id that collides with P1: not a competitor, not read
    FakeControllers f;
    make_controllers(f, 23, 13);
    gs::F1_25Symbols sym = with_controllers(symbols(g), f);
    sym.results_key = uintptr_t(results_key_static);
    gs::F1_25Provider p(sym, true);
    gs::GameState s;
    HudModel m;

    // in the garage: every slot is a car, the safety car included
    p.sample(60.8, s);
    CHECK(s.vehicle.ok && s.vehicle.id == 13 && p.raw().player_source == 2 && p.raw().ctrl_vid == 13);
    CHECK(s.session.cars == 23 && p.raw().rejects == 0 && p.raw().vcount == 23);
    CHECK(std::string(p.raw().slots) == std::string(22, '.') + "s");
    CHECK(p.raw().old_check == 1);
    CHECK(s.field.classified && s.field.pos[13] == 14 && s.field.pos[22] == 0 && s.field.n == 22);
    const uint32_t gen = s.session.generation;

    // the pit lane releases the car (unaligned tag at +0x0), the human drives off with Boost pressed, 114 m before
    // Bahrain's turn 1 (a right-hander at 0.1320 of the lap)
    put<uintptr_t>(c[13].car, 0, uintptr_t(kTagSpline));
    put<uint32_t>(c[13].car, 0x124, 0);
    set_drive(c[13], 0.f, 22.f, 3, 900.f, 0.8f, 0.f, 0x00);
    set_ers(c[13], 3.9e6f, 0.f, 120e3f, 2);
    set_progress(g, 13, 5409.f + 600.f, 1);
    for (int k = 0; k < 30; ++k) { // 0.5 s at 60 fps: 10 Hz scans and the per-frame re-read in between
        p.sample(66.0 + k / 60.0, s);
        m.update(s, 1 / 60.0, HudConfig{});
        CHECK(s.vehicle.ok && s.vehicle.id == 13);
    }
    CHECK(s.session.generation == gen && p.raw().player_source == 2 && s.session.cars == 23);
    CHECK(p.raw().old_check == 0); // what the old check rejected
    CHECK(std::string(p.raw().slots) == std::string(22, '.') + "s");
    {
        const View &v = m.view();
        CHECK(v.live && v.pedals_ok && v.throttle > 0.75f && v.brake == 0.f);
        CHECK(v.boost);
        CHECK(v.gear_ok && v.gear == 2);
        CHECK(v.energy_ok && v.deploy > 0.2f);
        CHECK(v.turn == "1" && v.turn_right);
        CHECK(v.rival_id == 12); // P14 sees P13
    }

    // two AI cars leave their garages too (an in-game log: 21 -> 19 cars): nothing changes
    put<uintptr_t>(c[4].car, 0, uintptr_t(kTagSpline));
    put<uintptr_t>(c[9].car, 0, uintptr_t(kTagProxy) + 3);
    p.sample(68.4, s);
    CHECK(s.session.cars == 23 && p.raw().rejects == 0 && s.session.generation == gen && s.vehicle.ok);

    // on to turn 2 (a left-hander 49 m ahead): the arrow flips; Boost released (mode back to Medium)
    set_progress(g, 13, 5409.f + 760.f, 1);
    set_ers(c[13], 3.8e6f, 0.f, 120e3f, 1);
    p.sample(68.5, s);
    m.update(s, 1 / 60.0, HudConfig{});
    CHECK(m.view().turn == "2" && !m.view().turn_right && !m.view().boost);
}

// The car's identity is the systems container's vptr and the teleport lock pointing into the car itself; +0x0 does
// not matter. A slot holding another object, a byte copy of a car at another address, a car under another id, a
// null or misaligned slot and a freed car are each rejected with their own status.
static void test_car_identity()
{
    FakeGame g;
    make_world(g, 4);
    FakeCar c[4] = {make_car(0, 1), make_car(1, 0), make_car(2, 1), make_car(3, 1)};
    for (int i = 0; i < 4; ++i) {
        set_drive(c[i], 30.f, 40.f, 6, 1100.f, 0.5f, 0.f, 0);
        set_ers(c[i], 3e6f, 0.f, 0.f, 1);
        g.table[i] = uintptr_t(c[i].car);
        set_progress(g, uint8_t(i), 1000.f - 100.f * float(i), 0);
    }
    g.count = 4;
    gs::F1_25Provider p(symbols(g), true);
    gs::GameState s;

    // any tag at +0x0: null (car 1, never placed), unaligned in the image, on the heap, aligned in the image
    put<uintptr_t>(c[0].car, 0, uintptr_t(kTagSpline));
    put<uintptr_t>(c[2].car, 0, uintptr_t(alloc(16)) + 3);
    put<uintptr_t>(c[3].car, 0, uintptr_t(kTagProxy));
    p.sample(1.0, s);
    CHECK(s.session.cars == 4 && p.raw().rejects == 0 && std::string(p.raw().slots) == "....");
    CHECK(s.vehicle.ok && s.vehicle.id == 1 && p.raw().old_check == 0 && p.raw().vcount == 4);

    // another object in a slot (another vptr at +0x380): not a car
    put<uintptr_t>(c[3].car, 0x380, uintptr_t(vt_sys));
    p.sample(1.1, s);
    CHECK(s.session.cars == 3 && p.raw().rejects == 1 && std::string(p.raw().slots) == "...t");
    put<uintptr_t>(c[3].car, 0x380, uintptr_t(vt_car));

    // a byte copy of a car at another address (a stale snapshot, recycled memory): its lock points into the original
    uint8_t *dup = alloc(0x600);
    std::memcpy(dup, c[3].car, 0x600);
    g.table[3] = uintptr_t(dup);
    p.sample(1.2, s);
    CHECK(s.session.cars == 3 && std::string(p.raw().slots) == "...t");
    g.table[3] = uintptr_t(c[3].car);

    // a car under another id, a null slot, a misaligned pointer, a freed car
    put<uint8_t>(c[2].car, 0xe8, 7);
    g.table[3] = 0;
    p.sample(1.3, s);
    CHECK(std::string(p.raw().slots) == "..in" && s.session.cars == 2 && s.vehicle.ok && p.raw().rejects == 2);
    put<uint8_t>(c[2].car, 0xe8, 2);
    g.table[3] = uintptr_t(c[3].car) + 4;
    p.sample(1.4, s);
    CHECK(std::string(p.raw().slots) == "...n");
    g.table[3] = uintptr_t(c[3].car);
    VirtualFree(c[3].car, 0, MEM_RELEASE);
    p.sample(1.5, s);
    CHECK(std::string(p.raw().slots) == "...u" && s.session.cars == 3 && s.vehicle.ok);

    // is_ai is a controller state, not an identity: a value the game never writes keeps the car, not as a human
    put<uint32_t>(c[0].car, 0x124, 2);
    p.sample(1.6, s);
    CHECK(s.session.cars == 3 && p.raw().humans == 1 && s.vehicle.ok && s.vehicle.id == 1);

    // no table: no slot status
    g.count = 0;
    p.sample(1.7, s);
    CHECK(p.raw().slots[0] == 0 && p.raw().vcount == 0 && p.raw().old_check == -1);

    // without the container vptr's address the provider stays off
    gs::F1_25Symbols none = symbols(g);
    none.vt_car_systems = 0;
    gs::F1_25Provider off(none, true);
    g.count = 3;
    off.sample(1.8, s);
    CHECK(!s.compatible && !s.vehicle.ok);
}

static void test_tracks()
{
    CHECK(Corners::official_for("brazil", 4309.f) >= 0);
    CHECK(Corners::official_for("Interlagos", 0.f) >= 0);
    CHECK(Corners::official_for("silverstone_reverse", 5891.f) == -1);
    CHECK(Corners::official_for("", 4309.f) == -1);        // Interlagos, Spielberg and Mexico are within 0.3 %
    CHECK(Corners::official_for("", 7004.f) >= 0);         // Spa: no other circuit near its length
    CHECK(Corners::official_for("brazil", 5200.f) == -1);  // name and length disagree: not the listed layout
    CHECK(Corners::official_for("abu_dhabi", 5281.f) >= 0);
}

// A Bahrain whose corners sit `offset` m after the official list (the game's lap distance starts apart from the
// official timing line: 33 m in the in-game logs): every listed turn a 50 m bend of its direction, 1/60 m at the apex.
static const TrackCorners &bahrain()
{
    for (const TrackCorners &t : kTracks)
        if (t.track == 3)
            return t;
    return kTracks[0];
}

static float bahrain_curvature(float d, float offset, bool mirror = false)
{
    const TrackCorners &T = bahrain();
    const float len = 5409.f;
    float k = 0;
    for (int i = 0; i < T.count; ++i) {
        const float x = std::fabs(std::remainder(d - (T.corners[i].frac * len + offset), len));
        if (x < 25.f)
            k += (T.corners[i].left != mirror ? 1.f : -1.f) / 60.f * (1.f - x / 25.f);
    }
    return k;
}

// One curvature sample every 1.5 m (90 m/s at 60 Hz) from `from` to `to` metres of driving.
static void drive(Corners &c, float from, float to, float offset, double &now, bool mirror = false)
{
    for (float d = from; d < to; d += 1.5f) {
        const float at = std::fmod(d, 5409.f);
        c.feed_curvature(at, bahrain_curvature(at, offset, mirror));
        c.update(now += 1 / 60.0);
    }
}

// The turn list learns where the game's corners are from the player's path curvature, and moves there.
static void test_learned_turns()
{
    const float len = 5409.f, offset = 33.f;
    const TrackCorners &T = bahrain();
    const float t1 = T.corners[0].frac * len, t5 = T.corners[4].frac * len;
    char label[8] = {};
    bool right = false;
    double now = 0;

    Corners c;
    c.reset("bahrain", len);
    CHECK(std::string(c.source()) == "official" && c.shift() == 0 && !c.handedness_known());
    // half a lap: nothing learned yet, the list as published (turn 2 from turn 1's listed apex on)
    drive(c, 0, 0.5f * len, offset, now);
    c.feed_curvature(t1, 0.5f); // a spin (tighter than a 5 m radius) teaches nothing
    CHECK(c.shift() == 0 && c.handedness() == 1 && c.handedness_known());
    CHECK(c.current(t1 + 2, label, sizeof label, &right) && std::string(label) == "2" && !right);
    // the lap covered: the whole list moves to the game's corners
    drive(c, 0.5f * len, 2.5f * len, offset, now);
    CHECK(std::string(c.source()) == "official");
    APPROX(c.shift(), offset, 5.0);
    CHECK(c.current(t1 + offset - 8, label, sizeof label, &right) && std::string(label) == "1" && right);
    CHECK(c.current(t1 + offset + 8, label, sizeof label, &right) && std::string(label) == "2" && !right);
    // turn 5, a left-hander (the table said right until 2026-11-09; the in-game logs turn left there)
    CHECK(c.current(t5 + offset - 50, label, sizeof label, &right) && std::string(label) == "5" && !right);

    // corners where the list says: nothing moves (under 12 m)
    Corners e;
    e.reset("bahrain", len);
    drive(e, 0, 2.5f * len, 0.f, now);
    CHECK(std::string(e.source()) == "official" && e.shift() == 0);

    // every bend the other way: the list does not fit, the turns come from the bends themselves
    Corners m;
    m.reset("bahrain", len);
    drive(m, 0, 2.5f * len, offset, now, true);
    CHECK(std::string(m.source()) == "learned" && m.shift() == 0);

    // a track that learns from positions ignores curvature (tools/mock feeds positions)
    Corners p;
    p.reset("bahrain", len);
    p.feed(10.f, 1.f, 2.f);
    p.feed_curvature(20.f, 0.01f);
    CHECK(!p.handedness_known());

    // the model feeds the list from the game state: frames that move the lap distance on, at speed, driven by
    // the player. A pause (the same lap distance, frame after frame) and the AI's drive teach nothing.
    gs::GameState s{};
    s.compatible = true;
    s.session.active = true;
    s.session.generation = 1;
    s.session.track_ok = true;
    s.session.track_length_m = len;
    s.session.track_name_ok = true;
    std::strcpy(s.session.track_name, "bahrain");
    s.vehicle.ok = s.vehicle.speed_ok = s.vehicle.accel_ok = true;
    s.vehicle.speed_mps = 60.f;
    s.progress.ok = true;
    auto lap = [&](HudModel &hm, float from, float to, bool ai) {
        s.vehicle.ai_driving = ai;
        for (float d = from; d < to; d += 1.f) {
            s.progress.lap_m = std::fmod(d, len);
            s.vehicle.g_lat = bahrain_curvature(s.progress.lap_m, offset) * 60.f * 60.f / 9.80665f;
            hm.update(s, 1 / 60.0, HudConfig{});
        }
    };
    HudModel hm;
    lap(hm, 0, 1000, false);
    s.vehicle.g_lat = -4.f; // paused in a corner: the frozen lateral g is not fed again and again
    for (int i = 0; i < 20000; ++i)
        hm.update(s, 1 / 60.0, HudConfig{});
    lap(hm, 1000, 2.5f * len, false);
    APPROX(hm.turn_shift(), offset, 5.0);
    s.progress.lap_m = t1 + offset + 8;
    hm.update(s, 1 / 60.0, HudConfig{});
    CHECK(hm.view().turn == "2" && !hm.view().turn_right);
    HudModel ai;
    lap(ai, 0, 2.5f * len, true);
    CHECK(ai.turn_shift() == 0);
    // a car the spectator HUD watches never teaches the list, even one a human drives (online): only the player's
    HudModel watched;
    s.vehicle.player = false;
    lap(watched, 0, 2.5f * len, false);
    CHECK(watched.turn_shift() == 0);
    s.vehicle.player = true;
}

// The spectator HUD (docs/spectator-ui.md §2; in game 2026-11-10 04:27, kizi.spectator-hud F8: the director followed
// all 22 cars). While the game's spectator HUD is up (the director in the registry, +0xd0 and +0xd1 set, +0xd6 a car
// of the table) the halo follows the watched car: every value, the progress, the rank and the rival are that car's;
// a value the game does not give for it is not shown (never the player's instead). The car set's generation (the
// tower's) stays over a switch; the subject generation bumps. Otherwise the player's car, as before.
static uintptr_t spectate_key_static[1]; // the key is the address of a static, like the game's

static uint8_t *add_director(FakeResults &r, int slot)
{
    uint8_t *d = alloc(0x100);
    put<uintptr_t>(r.slots, size_t(slot) * 16, uintptr_t(spectate_key_static));
    put<uintptr_t>(r.slots, size_t(slot) * 16 + 8, uintptr_t(d));
    r.info[slot] = 0x81;
    return d;
}

static void set_director(uint8_t *d, uint8_t ui, uint8_t active, uint8_t vid, uint32_t gap)
{
    put<uint8_t>(d, 0xd0, ui);
    put<uint8_t>(d, 0xd1, active);
    put<uint8_t>(d, 0xd6, vid);
    put<uint32_t>(d, 0xe4, gap);
}

static void test_spectate()
{
    FakeGame g;
    make_world(g, 5);
    // cars 0..3 competitors (the player drives car 2), car 4 the safety car (no ERS); each car its own values
    FakeCar c[5] = {make_car(0, 1), make_car(1, 1), make_car(2, 0), make_car(3, 1), make_car(4, 1, false)};
    for (int i = 0; i < 5; ++i) {
        set_drive(c[i], 0.f, 10.f * float(i + 1), uint32_t(i + 2), 500.f + 100.f * float(i), 0.1f * float(i + 1), 0.f, 0);
        if (i < 4)
            set_ers(c[i], 1e6f * float(i + 1), 0.f, 10e3f * float(i + 1), 1);
        g.table[i] = uintptr_t(c[i].car);
        set_progress(g, uint8_t(i), 9000.f - 1000.f * float(i), 2); // road order 0, 1, 2, 3
    }
    set_progress(g, 4, 9500.f, 2);
    g.count = 5;
    g.session_type = 15;
    FakeResults r = make_results(g, 200, 137, 4);
    for (int i = 0; i < 4; ++i)
        set_pos(r, uint8_t(i), uint32_t(i + 1)); // classified as on the road
    FakeControllers f;
    make_controllers(f, 5, 2);
    gs::F1_25Symbols sym = with_controllers(symbols(g), f);
    sym.results_key = uintptr_t(results_key_static);
    sym.spectate_key = uintptr_t(spectate_key_static);
    gs::F1_25Provider p(sym, true);
    gs::GameState s;
    HudModel m;
    HudConfig cfg;
    cfg.g_meter = true;
    auto upd = [&]() -> const View & {
        m.update(s, 1 / 60.0, cfg);
        return m.view();
    };
    auto player_values = [&]() {
        return s.vehicle.ok && s.vehicle.id == 2 && s.vehicle.player && std::fabs(s.vehicle.speed_mps - 30.f) < 1e-3f;
    };

    // no director in the registry: the player's car, as before
    p.sample(1.0, s);
    CHECK(player_values() && s.vehicle.player_id == 2);
    CHECK(!s.spectate.found && !s.spectate.read && !s.spectate.on && p.raw().spect_vid == -1);
    const uint32_t gen = s.session.generation, sub0 = s.session.subject;
    CHECK(upd().rival_id == 1 && m.view().gmeter.on);

    // the director appears and spectates car 1, but the spectator HUD is not up (+0xd0 0: the safety-car cinematic,
    // the winner sequence): still the player's car; spect_vid logs the director's car as before
    uint8_t *d = add_director(r, 150);
    set_director(d, 0, 1, 1, 1);
    p.sample(2.1, s); // over 1 s since the last registry search
    CHECK(s.spectate.found && s.spectate.read && s.spectate.ui == 0 && s.spectate.active == 1 && s.spectate.vehicle == 1);
    CHECK(!s.spectate.on && p.raw().spect_vid == 1 && player_values());
    CHECK(s.session.subject == sub0 && s.session.generation == gen);

    // the spectator HUD up, watching car 1: every value is car 1's; the car set's generation stays, the subject bumps
    set_director(d, 1, 1, 1, 2);
    p.sample(2.2, s);
    CHECK(s.spectate.on && s.spectate.gap == 2u && s.vehicle.ok && s.vehicle.id == 1 && !s.vehicle.player);
    CHECK(s.vehicle.player_id == 2 && s.session.generation == gen && s.session.subject != sub0);
    APPROX(s.vehicle.speed_mps, 20.f, 1e-3);
    CHECK(s.vehicle.gear_ok && s.vehicle.gear == 2);
    APPROX(s.power_unit.rpm, 600.f * 9.5492966f, 0.1);
    CHECK(s.input.ok);
    APPROX(s.input.throttle, 0.2f, 1e-5);
    CHECK(s.energy.store_ok && s.energy.power_ok);
    APPROX(s.energy.store_j, 2e6f, 1.0);
    APPROX(s.energy.deploy_w, 20e3f, 1.0);
    CHECK(s.vehicle.ai_driving); // the AI drives car 1
    CHECK(s.progress.ok && s.field.ok && s.field.player_rank == 1 && s.field.classified);
    APPROX(s.progress.total_m, 8000.f, 1e-2);
    {
        const View &v = upd(); // the rival: the car ahead of the watched car; the G-meter off while spectating
        CHECK(v.live && v.rival_id == 0 && v.kmh == 72 && v.gear == 2 && !v.gmeter.on);
        Leaves L;
        publish(L, v, 0.0);
        CHECK(L.wanted("rv00") && !L.wanted("rv01") && L.wanted("spd") && L.wanted("g2") && !L.wanted("gm"));
    }

    // between scans the watched car is re-read every frame: its new speed shows at once
    set_drive(c[1], 0.f, 25.f, 3, 600.f, 0.2f, 0.f, 0);
    p.sample(2.21, s);
    CHECK(!p.raw().scanned && s.spectate.on && s.vehicle.id == 1);
    APPROX(s.vehicle.speed_mps, 25.f, 1e-3);

    // F8: the next car (3); the subject bumps again, the car set does not; car 3 (P4) sees the player's car ahead
    const uint32_t sub1 = s.session.subject;
    set_director(d, 1, 1, 3, 2);
    p.sample(2.35, s);
    CHECK(s.spectate.on && s.vehicle.id == 3 && s.session.subject != sub1 && s.session.generation == gen);
    CHECK(upd().rival_id == 2);

    // a value the game does not give for the watched car is not shown, never the player's: car 3's gearbox fails its
    // check (back-pointer), the safety car has no ERS
    put<uintptr_t>(c[3].gearbox, 8, 0);
    p.sample(2.5, s);
    CHECK(s.vehicle.id == 3 && !s.vehicle.gear_ok && s.vehicle.speed_ok);
    {
        const View &v = upd();
        Leaves L;
        publish(L, v, 0.0);
        CHECK(!v.gear_ok);
        for (int i = 0; i <= 8; ++i)
            CHECK(!L.wanted("g" + std::to_string(i)));
    }
    put<uintptr_t>(c[3].gearbox, 8, uintptr_t(c[3].car));
    set_director(d, 1, 1, 4, 2);
    p.sample(2.6, s);
    CHECK(s.spectate.on && s.vehicle.id == 4 && !s.energy.store_ok && !s.energy.power_ok && s.field.player_rank == -1);
    {
        const View &v = upd();
        Leaves L;
        publish(L, v, 0.0);
        CHECK(v.live && !v.energy_ok && v.rival_id == -1 && !L.wanted("dp01") && !L.wanted("dp02"));
    }

    // spectating the player's own car: the player's values; the meter stays off while spectating
    set_director(d, 1, 1, 2, 1);
    p.sample(2.7, s);
    CHECK(s.spectate.on && player_values() && !upd().gmeter.on);

    // no car (0xff), a vehicle id past the table (7), a slot without a car: the player's car
    const uint8_t bad_ids[] = {0xff, 7};
    double t = 2.8;
    for (uint8_t bad : bad_ids) {
        set_director(d, 1, 1, bad, 1);
        p.sample(t, s);
        t += 0.1;
        CHECK(!s.spectate.on && player_values());
    }
    set_director(d, 1, 1, 3, 1);
    g.table[3] = 0;
    p.sample(t, s);
    t += 0.1;
    CHECK(!s.spectate.on && player_values() && s.session.generation == gen);
    g.table[3] = uintptr_t(c[3].car);
    p.sample(t, s);
    t += 0.1;
    CHECK(s.spectate.on && s.vehicle.id == 3);

    // the spectator HUD goes down (+0xd0 0) or the director stops (+0xd1 0): the player's car, the meter back on
    set_director(d, 0, 1, 3, 1);
    p.sample(t, s);
    t += 0.1;
    CHECK(!s.spectate.on && player_values() && upd().gmeter.on);
    set_director(d, 1, 1, 3, 1);
    p.sample(t, s);
    t += 0.1;
    CHECK(s.spectate.on && s.vehicle.id == 3);
    set_director(d, 1, 0, 3, 1);
    p.sample(t, s);
    t += 0.1;
    CHECK(!s.spectate.on && player_values() && p.raw().spect_vid == -1);
    // the director leaves the registry: the player's car
    set_director(d, 1, 1, 3, 1);
    p.sample(t, s);
    t += 0.1;
    CHECK(s.spectate.on && s.vehicle.id == 3);
    put<uintptr_t>(r.slots, size_t(150) * 16, 0);
    p.sample(t, s);
    CHECK(!s.spectate.found && !s.spectate.on && player_values() && s.session.generation == gen);

    // another build's symbols (no key): never spectates
    gs::F1_25Symbols nokey = sym;
    nokey.spectate_key = 0;
    gs::F1_25Provider q(nokey, true);
    q.sample(5.0, s);
    CHECK(!s.spectate.found && player_values());
}

static void test_levels()
{
    CHECK(stripe_level(0.f) == 0 && stripe_level(1.f) == kStripes && stripe_level(0.5f) == 5);
    CHECK(cap_level(2.f) == kCapLevels && cap_level(-1.f) == 0);
}

// The halo in 2025 and F2 cars (docs/halo-car-classes.md): the 2025 capsules show the same MGU-K power on a fixed
// 120 kW scale whatever limit the car reports (the 2026 capsules keep the car's own limit), and the setting all_cars
// reaches the template as leaf cls, also while the car is not read.
static void test_classes()
{
    gs::GameState s;
    s.compatible = true;
    s.session.active = true;
    s.vehicle.ok = true;
    s.energy.power_ok = true;
    s.energy.max_deploy_ok = true;
    s.energy.max_deploy_w = 126.3e3f;   // what the 2025 cars reported in the 2026-11-09 Montreal drives
    s.energy.deploy_w = 60e3f;
    HudModel m;
    for (int i = 0; i < 60; ++i) // 1 s at 60 fps: the 20 ms easing has settled
        m.update(s, 1 / 60.0, HudConfig{});
    {
        const View &v = m.view();
        APPROX(v.deploy, (60e3 - 2e3) / 126.3e3, 1e-4);
        APPROX(v.deploy25, (60e3 - 2e3) / 120e3, 1e-4);
        CHECK(v.recharge25 < 1e-6f && v.all_cars);
        Leaves L;
        publish(L, v, 0.0);
        CHECK(L.wanted("dp07") && L.wanted("dk08") && !L.wanted("dk07") && L.wanted("cls"));
        for (int i = 1; i <= kCapLevels; ++i)
            CHECK(!L.wanted("rk" + two(i)));
    }
    // full harvest (the logged 2025 peak, 119.985 kW): the 2025 recharge capsule is full, the 2026 one is not
    s.energy.deploy_w = 0;
    s.energy.harvest_k_w = 119.985e3f;
    for (int i = 0; i < 60; ++i)
        m.update(s, 1 / 60.0, HudConfig{true, true, false, false});
    {
        const View &v = m.view();
        CHECK(!v.all_cars);
        Leaves L;
        publish(L, v, 0.0);
        CHECK(L.wanted("rk16") && L.wanted("rc15") && !L.wanted("rc16") && !L.wanted("cls"));
        for (int i = 1; i <= kCapLevels; ++i)
            CHECK(!L.wanted("dk" + two(i)));
    }
    // power unreadable: no capsule; the car not read: still no capsule, the setting still published
    s.energy.power_ok = false;
    m.update(s, 1 / 60.0, HudConfig{});
    {
        Leaves L;
        publish(L, m.view(), 0.0);
        for (int i = 1; i <= kCapLevels; ++i)
            CHECK(!L.wanted("rk" + two(i)) && !L.wanted("dk" + two(i)));
        CHECK(L.wanted("cls"));
    }
    s.vehicle.ok = false;
    m.update(s, 1 / 60.0, HudConfig{true, true, false, false});
    {
        Leaves L;
        publish(L, m.view(), 0.0);
        CHECK(!m.view().live && !L.wanted("cls") && !L.wanted("rk16"));
    }
    m.update(s, 1 / 60.0, HudConfig{});
    {
        Leaves L;
        publish(L, m.view(), 0.0);
        CHECK(L.wanted("cls"));
    }
}

// The leaves publish() writes, for tools/native/check_leaves.py (template bindings must all be written).
static void test_leaf_names(const char *out_path)
{
    Leaves L;
    View v;
    v.live = true;
    publish(L, v, 0.0);
    const std::vector<std::string> p = L.paths();
    CHECK(p.size() == size_t(4 + 9 + 2 * kStripes + 2 * kCapLevels + 3 + 4 + kRivalSlots + 3 + 20 + kGSegments + 2 * kGAxes +
                             1 + 2 * kCapLevels));
    if (!out_path)
        return;
    FILE *f = std::fopen(out_path, "w");
    CHECK(f != nullptr);
    if (!f)
        return;
    for (const std::string &x : p)
        std::fprintf(f, "%s\n", x.c_str());
    std::fclose(f);
}

// Per-frame cost with a full 22-car field at 120 fps (not a pass/fail check: the numbers go into
// docs/qa/performance.md). Every provider read is a ReadProcessMemory call, as in game. publish() is timed
// separately: without swofty_core.dll every hud::set fails and is retried, which never happens in game.
static void bench_frame(bool watching = false)
{
    FakeGame g;
    make_world(g, 24);
    std::vector<FakeCar> cars;
    for (int i = 0; i < 22; ++i) {
        cars.push_back(make_car(uint8_t(i), i == 7 ? 0 : 1));
        set_drive(cars.back(), 30.f, 40.f, 6, 1100.f, 0.75f, 0.f, 0);
        set_ers(cars.back(), 2.0e6f, 120e3f, 0.f, 1);
        g.table[i] = uintptr_t(cars.back().car);
        set_progress(g, uint8_t(i), 15000.f - 100.f * i, 4);
    }
    g.count = 22;
    FakeResults r = make_results(g, 400, 291, 22); // the classification read is part of every scan
    for (int i = 0; i < 22; ++i)
        set_pos(r, uint8_t(i), uint32_t(i + 1));
    FakeControllers ctl; // the player from the ControllerSystem: one walk of 22 sets per scan
    make_controllers(ctl, 22, 7);
    gs::F1_25Symbols sym = with_controllers(symbols(g), ctl);
    sym.results_key = uintptr_t(results_key_static);
    // the spectator director in the registry (one copy per scan); watching: the spectator HUD up on car 12, so the
    // watched car's header is re-read every frame too
    sym.spectate_key = uintptr_t(spectate_key_static);
    set_director(add_director(r, 300), watching ? 1 : 0, watching ? 1 : 0, 12, 1);
    gs::F1_25Provider p(sym, true);
    gs::GameState s;
    HudModel m;
    Leaves L;
    LARGE_INTEGER f;
    QueryPerformanceFrequency(&f);
    const int n = 3000;
    double sum[3] = {}, worst[3] = {};
    int scans = 0;
    std::vector<double> scan_us, plain_us;
    for (int i = 0; i < n; ++i) {
        LARGE_INTEGER t[4];
        QueryPerformanceCounter(&t[0]);
        p.sample(i / 120.0, s);
        QueryPerformanceCounter(&t[1]);
        m.update(s, 1 / 120.0, HudConfig{});
        QueryPerformanceCounter(&t[2]);
        publish(L, m.view(), i / 120.0);
        QueryPerformanceCounter(&t[3]);
        scans += p.raw().scanned;
        (p.raw().scanned ? scan_us : plain_us).push_back(double(t[1].QuadPart - t[0].QuadPart) / double(f.QuadPart) * 1e6);
        for (int k = 0; k < 3; ++k) {
            const double d = double(t[k + 1].QuadPart - t[k].QuadPart) / double(f.QuadPart);
            sum[k] += d;
            worst[k] = std::max(worst[k], d);
        }
    }
    CHECK(s.vehicle.ok && s.field.n == 22 && s.field.classified && m.view().rival_id == (watching ? 11 : 6));
    CHECK(s.spectate.on == watching && s.vehicle.id == (watching ? 12 : 7));
    CHECK(scans >= n / 13 && scans <= n / 11 + 1); // 10 Hz at 120 fps: one frame in 12
    std::printf("bench%s (22 cars, 120 fps, %d frames, %d full scans): provider %.1f us mean / %.1f us worst, "
                "model %.2f us mean, publish %.1f us mean (test-only retries)\n",
                watching ? " spectating" : "", n, scans, sum[0] / n * 1e6, worst[0] * 1e6, sum[1] / n * 1e6,
                sum[2] / n * 1e6);
    auto pct = [](std::vector<double> v, double q) {
        std::sort(v.begin(), v.end());
        return v.empty() ? 0.0 : v[std::min(v.size() - 1, size_t(q * double(v.size())))];
    };
    std::printf("bench: provider on frames without a scan: median %.1f us, p99 %.1f us; scan frames: median %.1f us, "
                "p99 %.1f us\n",
                pct(plain_us, 0.5), pct(plain_us, 0.99), pct(scan_us, 0.5), pct(scan_us, 0.99));
}

int main(int argc, char **argv)
{
    test_decode();
    test_new_session();
    test_classification();
    test_classification_no_ers();
    test_controllers();
    test_progress();
    test_distance_reference();
    test_player();
    test_pit_exit();
    test_car_identity();
    test_tracks();
    test_learned_turns();
    test_spectate();
    test_levels();
    test_classes();
    test_leaf_names(argc > 1 ? argv[1] : nullptr);
    bench_frame();
    bench_frame(true);
    std::printf("%d passed, %d failed\n", g_pass, g_fail);
    return g_fail ? 1 : 0;
}
