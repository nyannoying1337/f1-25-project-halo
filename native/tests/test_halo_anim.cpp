// Host tests for the halo's animations (src/halo_anim.hpp): each trigger, the snap rules, the
// pulse rules, the rests, and the Animations option off (no leaf is written). Build and run: tests/run_tests.sh
#include "../src/halo_anim.hpp"

#include <chrono>
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

constexpr double kDt = 1.0 / 60.0;

struct Write {
    int frame;
    double t;
    std::string key; // the leaf's name after hud_halo_
    bool value;
};

// One driven dial: the animation layer, its clock and every leaf write it made.
struct Rig {
    HaloAnim a;
    AnimIn in;
    double t = 0;
    int frame = 0;
    std::vector<Write> log;
    bool fail_sink = false;

    Rig()
    {
        in.enabled = true;
        in.live = true;
        in.subject = 7;
        in.gear_ok = true;
        in.gear = 3;
        in.rival_id = 4;
        in.rev_ok = true;
        in.rpm = 8000;
        in.limiter_rpm = 12000;
        in.lap_ok = true;
        in.lap_m = 500;
        in.track_m = 5000;
    }
    static bool sink(void *ctx, const char *path, bool v)
    {
        Rig &r = *static_cast<Rig *>(ctx);
        if (r.fail_sink)
            return false;
        const char *k = std::strstr(path, "hud_halo_");
        r.log.push_back({r.frame, r.t, k ? k + 9 : path, v});
        return true;
    }
    void step(int n = 1, double dt = kDt)
    {
        for (int i = 0; i < n; ++i) {
            t += dt;
            ++frame;
            in.lap_m += float(60.0 * dt); // 60 m/s
            if (in.lap_m > 5000.f)
                in.lap_m -= 5000.f;
            a.update(in, t);
            a.flush(t, kAnimWrites, sink, this);
        }
    }
    void run(double seconds) { step(int(seconds / kDt + 0.5)); }
    int count(const std::string &key, bool value, size_t from = 0) const
    {
        int n = 0;
        for (size_t i = from; i < log.size(); ++i)
            n += log[i].key == key && log[i].value == value;
        return n;
    }
    const Write *last(const std::string &key) const
    {
        for (size_t i = log.size(); i-- > 0;)
            if (log[i].key == key)
                return &log[i];
        return nullptr;
    }
    // past the first settle: the gate is on
    void settle() { run(kAnimSettle + 0.1); }
};

// The pulse rules over a whole log: per leaf the first write is false (the leaf's creation), then true and false
// alternate; a false comes at least kAnimPulse seconds and kAnimPulseFrames frames after its true; a true at least
// kAnimPulseFrames frames after the last false; nothing is true at the end.
static void check_pulses(const Rig &r)
{
    for (int i = kAnHeld; i < kAnLeaves; ++i) {
        const std::string key = std::strstr(r.a.path(i), "hud_halo_") + 9;
        bool on = false;
        const Write *prev = nullptr;
        bool ok = true;
        for (const Write &w : r.log) {
            if (w.key != key)
                continue;
            if (!prev && w.value)
                ok = false; // a true before the leaf was created
            if (prev && w.value == on)
                ok = false; // the same value twice in a row
            if (prev && !w.value && (w.t - prev->t < kAnimPulse - 1e-9 || w.frame - prev->frame < kAnimPulseFrames))
                ok = false;
            if (prev && w.value && w.frame - prev->frame < kAnimPulseFrames)
                ok = false;
            on = w.value;
            prev = &w;
        }
        CHECK(ok);
        CHECK(!on);
    }
}

static void test_names()
{
    HaloAnim a;
    CHECK(HaloAnim::count() == 2 + kAnimSlots + 1 + kAnimGears + 3);
    CHECK(std::string(a.path(kAnXan)) == "view_model_data.hud_halo_xan");
    CHECK(std::string(a.path(kAnGhost + 23)) == "view_model_data.hud_halo_gv23");
    CHECK(std::string(a.path(kAnXg + 8)) == "view_model_data.hud_halo_xg8");
    CHECK(std::string(a.path(kAnXrr)) == "view_model_data.hud_halo_xrr");
    for (int i = 0; i < HaloAnim::count(); ++i)
        for (int j = i + 1; j < HaloAnim::count(); ++j)
            CHECK(std::strcmp(a.path(i), a.path(j)) != 0);
}

static void test_gate_and_settle()
{
    Rig r;
    r.step();
    CHECK(!r.a.gate()); // the first read frame starts a settle
    // with the option on every leaf is created once, as false, at most kAnimWrites a frame
    CHECK(int(r.log.size()) == kAnimWrites);
    r.step(HaloAnim::count() / kAnimWrites);
    CHECK(int(r.log.size()) == HaloAnim::count());
    for (const Write &w : r.log)
        CHECK(!w.value);
    for (int i = 0; i < HaloAnim::count(); ++i)
        CHECK(r.a.written(i));
    r.step(30);
    CHECK(int(r.log.size()) == HaloAnim::count()); // and not again
    r.in.gear = 4; // a change inside the settle: no pop
    r.run(1.0);
    CHECK(r.count("xg4", true) == 0);
    r.run(kAnimSettle);
    CHECK(r.a.gate());
    CHECK(r.count("xan", true) == 1);
    // the followed car changes (a spectator switch, a restart): the gate goes off for 2 s, changes show at once
    r.in.subject = 8;
    r.in.gear = 6;
    r.in.rival_id = 9;
    r.step();
    CHECK(!r.a.gate());
    CHECK(r.last("xan") && !r.last("xan")->value);
    r.run(1.0);
    CHECK(r.count("xg6", true) == 0 && r.count("xrv", true) == 0);
    r.run(1.2);
    CHECK(r.a.gate());
    // the car is lost and read again: a settle again
    r.in.live = false;
    r.step(3);
    CHECK(!r.a.gate());
    r.in.live = true;
    r.step();
    CHECK(!r.a.gate());
    r.run(kAnimSettle + 0.1);
    CHECK(r.a.gate());
    check_pulses(r);
}

static void test_gear()
{
    Rig r;
    r.settle();
    const size_t mark = r.log.size();
    r.in.gear = 4;
    r.step();
    CHECK(r.count("xg4", true, mark) == 1); // the pop starts in the frame of the change
    CHECK(r.log.back().key == "xg4" && r.log.back().value);
    r.run(0.2);
    CHECK(r.count("xg4", false, mark) == 1); // the pulse is over
    CHECK(r.count("xgr", true, mark) == 0);  // the rest waits for the play
    r.run(0.7);
    CHECK(r.count("xgr", true, mark) == 1);  // 0.85 s after the pop
    const Write *rest = r.last("xg4");
    CHECK(rest != nullptr);
    // a fast run through the gears: each digit pops once, one rest after the last
    const size_t m2 = r.log.size();
    for (int g : {5, 6, 7, 8}) {
        r.in.gear = g;
        r.run(0.12);
    }
    CHECK(r.count("xg5", true, m2) == 1 && r.count("xg6", true, m2) == 1 && r.count("xg7", true, m2) == 1 &&
          r.count("xg8", true, m2) == 1);
    CHECK(r.count("xgr", true, m2) == 0);
    r.run(1.0);
    CHECK(r.count("xgr", true, m2) == 1);
    // back to a digit whose play may still run: no second pop (busy), the digit just shows
    const size_t m3 = r.log.size();
    r.in.gear = 7;
    r.step();
    r.in.gear = 8;
    r.run(0.2);
    r.in.gear = 7;
    r.run(0.2);
    CHECK(r.count("xg7", true, m3) == 1 && r.count("xg8", true, m3) == 1);
    CHECK(r.a.stats().pops_busy == 1);
    // reverse and an unread gear: nothing
    const size_t m4 = r.log.size();
    r.run(1.5);
    r.in.gear = -1;
    r.run(0.3);
    r.in.gear_ok = false;
    r.run(0.3);
    r.in.gear_ok = true;
    r.in.gear = 2; // from an unread gear: no pop
    r.run(0.3);
    int pops = 0;
    for (size_t i = m4; i < r.log.size(); ++i)
        pops += r.log[i].key.rfind("xg", 0) == 0 && r.log[i].key != "xgr" && r.log[i].value;
    CHECK(pops == 0);
    r.in.gear = 3;
    r.step();
    CHECK(r.count("xg3", true, m4) == 1);
    r.run(2.0);
    check_pulses(r);
}

static void test_boost()
{
    Rig r;
    r.settle();
    const size_t mark = r.log.size();
    r.in.boost = true;
    r.step();
    CHECK(r.count("xbo", true, mark) == 1); // the streak starts in the frame Boost turns on
    r.run(0.5);
    r.in.boost = false;
    r.run(0.1);
    r.in.boost = true; // again inside the play: busy, no second streak yet
    r.step();
    CHECK(r.count("xbo", true, mark) == 1);
    CHECK(r.a.stats().boosts_busy == 1);
    // Boost stays on: the streak repeats one second after the last one started, and every second after that
    r.run(0.3);
    CHECK(r.count("xbo", true, mark) == 1);
    r.run(0.2);
    CHECK(r.count("xbo", true, mark) == 2);
    r.run(3.0);
    CHECK(r.count("xbo", true, mark) == 5);
    CHECK(r.a.stats().boost_repeats == 4);
    // the starts are kAnimRepeat apart
    double last = -1;
    bool even = true;
    int seen = 0;
    for (size_t i = mark; i < r.log.size(); ++i)
        if (r.log[i].key == "xbo" && r.log[i].value) {
            if (seen++ >= 2 && std::fabs(r.log[i].t - last - kAnimRepeat) > 1.5 * kDt)
                even = false;
            last = r.log[i].t;
        }
    CHECK(even);
    // Boost off: no more streaks
    r.in.boost = false;
    r.run(3.0);
    CHECK(r.count("xbo", true, mark) == 5);
    // no repeat during a settle; it picks up again after it while Boost is still on
    r.in.boost = true;
    r.step();
    CHECK(r.count("xbo", true, mark) == 6);
    r.in.subject = 31;
    r.step();
    const size_t m2 = r.log.size();
    r.run(kAnimSettle - 0.1);
    CHECK(r.count("xbo", true, m2) == 0);
    r.run(0.3);
    CHECK(r.count("xbo", true, m2) == 1);
    // the streak has no rest pulse: only starts and their falses were written for it
    r.in.boost = false;
    r.run(1.0);
    CHECK(r.count("xbo", false, mark) == r.count("xbo", true, mark));
    check_pulses(r);
}

static void test_rival()
{
    Rig r;
    r.settle();
    const size_t mark = r.log.size();
    r.in.rival_id = 11;
    r.step();
    CHECK(r.count("xrv", true, mark) == 1);
    CHECK(r.count("gv04", true, mark) == 1); // the car that was ahead rolls out as its copy
    r.run(0.5);
    CHECK(r.count("gv04", false, mark) == 0);
    r.run(0.2);
    CHECK(r.count("gv04", false, mark) == 1); // the copy hides after 0.6 s
    r.run(0.3);
    CHECK(r.count("xrr", true, mark) == 1);
    // a second change inside the play: at once (no pulse, no copy)
    const size_t m2 = r.log.size();
    r.in.rival_id = 2;
    r.step();
    r.run(0.3);
    r.in.rival_id = 3;
    r.step();
    CHECK(r.count("xrv", true, m2) == 1);
    CHECK(r.count("gv11", true, m2) == 1 && r.count("gv02", true, m2) == 0);
    CHECK(r.a.stats().rolls_at_once == 1);
    r.run(1.5);
    // no rival to a rival and back: at once
    const size_t m3 = r.log.size();
    r.in.rival_id = -1;
    r.run(1.0);
    r.in.rival_id = 5;
    r.run(1.0);
    CHECK(r.count("xrv", true, m3) == 0);
    // a slot the dial does not have: no copy, the roll still plays
    r.in.rival_id = 30;
    r.run(1.0);
    r.in.rival_id = 6;
    r.step();
    int copies = 0;
    for (size_t i = m3; i < r.log.size(); ++i)
        copies += r.log[i].key.rfind("gv", 0) == 0 && r.log[i].value;
    CHECK(copies == 1); // gv05, when 5 gave way to 30
    r.run(2.0);
    check_pulses(r);
}

static void test_rev_line()
{
    Rig r;
    r.settle();
    const size_t mark = r.log.size();
    r.in.rpm = 11300; // 94.2 %: below the on threshold
    r.step();
    CHECK(r.count("xrl", true, mark) == 0);
    r.in.rpm = 11450; // 95.4 %
    r.step();
    CHECK(r.count("xrl", true, mark) == 1);
    r.in.rpm = 11250; // 93.75 %: stays on (off below 93 %)
    r.step(5);
    CHECK(r.count("xrl", false, mark) == 0);
    r.in.rpm = 11100; // 92.5 %
    r.step();
    CHECK(r.count("xrl", false, mark) == 1);
    r.in.rpm = 11900;
    r.step();
    r.in.rev_ok = false; // the limiter or the revs are not read: off
    r.step();
    CHECK(r.last("xrl") && !r.last("xrl")->value);
    r.in.rev_ok = true;
    r.in.limiter_rpm = 0;
    r.step(3);
    CHECK(!r.last("xrl")->value);
}

static void test_jump()
{
    Rig r;
    r.in.lap_m = 4800;
    r.settle();
    // crossing the line is not a jump
    CHECK(r.in.lap_m > 4900.f);
    r.run(2.0);
    CHECK(r.in.lap_m < 100.f);
    CHECK(r.a.gate());
    CHECK(r.a.stats().settles == 1);
    // a rewind: 300 m back in one frame
    r.in.lap_m -= 300.f;
    r.in.gear = 5;
    r.step();
    CHECK(!r.a.gate());
    CHECK(r.count("xg5", true) == 0);
    r.run(kAnimSettle + 0.1);
    CHECK(r.a.gate());
    // a replay jump forward
    r.in.lap_m += 800.f;
    r.step();
    CHECK(!r.a.gate());
    r.run(kAnimSettle + 0.1);
    CHECK(r.a.gate());
    // a flashback from the middle of the lap to the start line is a jump, not the line being crossed
    r.in.lap_m = 2600.f;
    r.run(kAnimSettle + 0.2); // (the move to 2600 m was a jump too)
    CHECK(r.a.gate());
    r.in.lap_m = 40.f;
    r.in.gear = 2;
    r.step();
    CHECK(!r.a.gate());
    CHECK(r.count("xg2", true) == 0);
    r.run(kAnimSettle + 0.1);
    CHECK(r.a.gate());
    // a jump hidden behind one frame without a lap distance is still seen
    const uint32_t before = r.a.stats().settles;
    r.in.lap_ok = false;
    r.step();
    r.in.lap_ok = true;
    r.in.lap_m += 900.f;
    r.step();
    CHECK(!r.a.gate() && r.a.stats().settles == before + 1);
    r.run(kAnimSettle + 0.1);
    // with the lap's length unknown: from beyond 1500 m to the first 150 m counts as the line
    Rig u;
    u.in.track_m = 0;
    u.in.lap_m = 4800;
    u.settle();
    u.run(2.0);
    CHECK(u.in.lap_m < 100.f && u.a.gate() && u.a.stats().settles == 1);
    check_pulses(r);
}

static void test_cut()
{
    // a settle while motions are in flight: starts not yet written are dropped, the copy hides, every null gets its rest
    Rig r;
    r.settle();
    const size_t mark = r.log.size();
    r.in.gear = 4;
    r.in.boost = true;
    r.in.rival_id = 12;
    r.step();
    CHECK(r.count("xg4", true, mark) == 1 && r.count("xbo", true, mark) == 1 && r.count("xrv", true, mark) == 1);
    r.run(0.2);
    r.in.subject = 9;
    r.step();
    CHECK(r.count("xgr", true, mark) == 1 && r.count("xrr", true, mark) == 1);
    CHECK(r.count("gv04", false, mark) == 1);
    CHECK(r.last("xan") && !r.last("xan")->value);
    r.run(3.0);
    CHECK(r.count("xgr", true, mark) == 1 && r.count("xrr", true, mark) == 1);
    check_pulses(r);
}

static void test_off()
{
    // Animations off from the start: not one leaf is written, whatever happens
    Rig r;
    r.in.enabled = false;
    r.run(3.0);
    r.in.gear = 5;
    r.in.boost = true;
    r.in.rival_id = 9;
    r.in.rpm = 11900;
    r.run(1.0);
    r.in.subject = 3;
    r.in.gear = 6;
    r.run(3.0);
    CHECK(r.log.empty());
    for (int i = 0; i < HaloAnim::count(); ++i)
        CHECK(!r.a.written(i));
    CHECK(!r.a.gate());

    // switched off in the middle of motions: the held leaves go false once, each moving null gets one rest, then
    // nothing more is written
    Rig q;
    q.settle();
    q.in.rpm = 11900;
    q.in.gear = 4;
    q.in.rival_id = 12;
    q.step();
    q.run(0.2);
    const size_t mark = q.log.size();
    q.in.enabled = false;
    q.step();
    q.run(1.0);
    CHECK(q.count("xan", false, mark) == 1 && q.count("xrl", false, mark) == 1 && q.count("gv04", false, mark) == 1);
    CHECK(q.count("xgr", true, mark) == 1 && q.count("xrr", true, mark) == 1);
    const size_t quiet = q.log.size();
    q.in.gear = 6;
    q.in.boost = true;
    q.in.rival_id = 2;
    q.run(6.0);
    CHECK(q.log.size() == quiet);
    for (int i = 0; i < HaloAnim::count(); ++i)
        CHECK(!q.a.sent(i));
    check_pulses(q);
    // on again: a settle first, then motions
    q.in.enabled = true;
    q.step();
    CHECK(!q.a.gate());
    q.run(kAnimSettle + 0.1);
    CHECK(q.a.gate());
    q.in.gear = 7;
    q.step();
    CHECK(q.count("xg7", true, quiet) == 1);
}

static void test_refresh_and_failures()
{
    // held leaves are rewritten every 2 s (the game can rebuild its view model); pulses never are
    Rig r;
    r.settle();
    r.in.gear = 4;
    r.step();
    r.run(1.5);
    const size_t mark = r.log.size();
    r.run(6.1);
    CHECK(r.count("xan", true, mark) == 3);
    CHECK(r.count("xrl", false, mark) == 3 && r.count("gv07", false, mark) == 3); // every held leaf, also while false
    int pulses = 0;
    for (size_t i = mark; i < r.log.size(); ++i)
        pulses += r.log[i].key[0] == 'x' && r.log[i].key != "xan" && r.log[i].key != "xrl";
    CHECK(pulses == 0);
    // a start in a refresh frame is not held up: the pop goes out in the frame of the shift
    r.run(1.9 - 6.1 + 2.0 * 3 + 0.0);
    const size_t m2 = r.log.size();
    int worst = 0;
    for (int g = 5; g <= 8; ++g) {
        r.run(1.0);
        const int f0 = r.frame + 1;
        r.in.gear = g;
        r.step();
        const std::string key = "xg" + std::to_string(g);
        CHECK(r.last(key) && r.last(key)->value && r.last(key)->frame == f0);
        worst = r.last(key) ? r.last(key)->frame - f0 : 99;
    }
    CHECK(worst == 0);
    (void)m2;
    // a failed write is tried again and the pulse keeps its rules
    Rig f;
    f.settle();
    f.fail_sink = true;
    f.in.gear = 5;
    f.step(3);
    CHECK(f.count("xg5", true) == 0);
    f.fail_sink = false;
    f.step();
    CHECK(f.count("xg5", true) == 1);
    f.run(2.0);
    check_pulses(f);
}

static void test_budget()
{
    // more changes than one frame may write: the rest waits for the next frame, nothing is lost
    Rig r;
    r.settle();
    r.in.gear = 4;
    r.in.boost = true;
    r.in.rival_id = 12;
    r.in.rpm = 11900;
    r.t += kDt;
    ++r.frame;
    r.a.update(r.in, r.t);
    const size_t mark = r.log.size();
    CHECK(r.a.flush(r.t, 2, Rig::sink, &r) == 2);
    CHECK(r.log.size() == mark + 2);
    r.run(2.0);
    CHECK(r.count("xg4", true, mark) == 1 && r.count("xbo", true, mark) >= 2 && r.count("xrv", true, mark) == 1 &&
          r.count("xrl", true, mark) >= 1 && r.count("gv04", true, mark) == 1); // Boost stays on: a streak every second
    check_pulses(r);
}

// A long mixed drive at uneven frame times: the pulse rules hold and everything ends at rest.
static void test_soak()
{
    Rig r;
    uint32_t seed = 12345;
    auto rnd = [&seed]() {
        seed = seed * 1664525u + 1013904223u;
        return seed >> 8;
    };
    for (int i = 0; i < 60000; ++i) {
        const uint32_t x = rnd() % 1000;
        if (x < 30)
            r.in.gear = int(rnd() % 10) - 1;
        else if (x < 40)
            r.in.boost = !r.in.boost;
        else if (x < 46)
            r.in.rival_id = int(rnd() % 26) - 1;
        else if (x < 48)
            r.in.subject += 1;
        else if (x < 50)
            r.in.live = !r.in.live;
        else if (x < 51)
            r.in.enabled = !r.in.enabled;
        else if (x < 53)
            r.in.lap_m = float(rnd() % 5000);
        r.in.rpm = 6000.f + float(rnd() % 6000);
        r.step(1, (rnd() % 4 == 0) ? 1.0 / 30.0 : (rnd() % 7 == 0) ? 0.2 : 1.0 / 144.0);
    }
    r.in.enabled = true;
    r.in.live = true;
    r.run(5.0);
    check_pulses(r);
    for (int i = kAnGhost; i < kAnGhost + kAnimSlots; ++i)
        CHECK(!r.a.sent(i));
    CHECK(r.a.stats().pops > 100 && r.a.stats().rolls > 10 && r.a.stats().boosts > 10 && r.a.stats().settles > 50);
    // a rest follows the last start of each kind
    CHECK(r.a.started(kAnXgr) > 0 && r.a.started(kAnXrr) > 0);
}

// Cost per frame of update + flush with a sink that only counts (not a pass / fail check).
static void bench()
{
    static int sunk = 0;
    const auto sink = [](void *, const char *, bool) {
        ++sunk;
        return true;
    };
    for (int mode = 0; mode < 3; ++mode) {
        HaloAnim a;
        AnimIn in;
        in.enabled = mode != 0;
        in.live = true;
        in.gear_ok = true;
        in.rev_ok = true;
        in.limiter_rpm = 12000;
        in.lap_ok = true;
        const int n = 2000000;
        double t = 0;
        const auto t0 = std::chrono::steady_clock::now();
        for (int i = 0; i < n; ++i) {
            t += 1.0 / 120.0;
            in.lap_m = float(i % 5000);
            in.rpm = 7000.f + float(i % 5000);
            if (mode == 2 && i % 40 == 0) { // a shift every third of a second, a new rival and Boost now and then
                in.gear = 1 + (i / 40) % 8;
                if (i % 400 == 0)
                    in.rival_id = (i / 400) % 20;
                in.boost = (i / 200) % 2;
            }
            a.update(in, t);
            a.flush(t, kAnimWrites, sink, nullptr);
        }
        const double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count() / n;
        std::printf("halo anim bench (%s): %.4f us per frame\n",
                    mode == 0 ? "Animations off" : mode == 1 ? "on, steady driving" : "on, shifting 3 times a second", us);
    }
    (void)sunk;
}

int main()
{
    test_names();
    test_gate_and_settle();
    test_gear();
    test_boost();
    test_rival();
    test_rev_line();
    test_jump();
    test_cut();
    test_off();
    test_refresh_and_failures();
    test_budget();
    test_soak();
    bench();
    std::printf("halo anim: %d passed, %d failed\n", g_pass, g_fail);
    return g_fail ? 1 : 0;
}
