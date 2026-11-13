// Host tests for the broadcast cards' leaves (src/cards.hpp): each value's rule, fail-closed inputs, the pit3 node's
// write rule, refresh, budget and failed writes. Build and run: tests/run_tests.sh. Writes <out>/cards_leaves.txt.
#include "../src/cards.hpp"

#include <chrono>
#include <map>
#include <string>
#include <vector>

using namespace cards;

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

struct Rig {
    Cards c;
    tower::Snapshot s;
    In in;
    double t = 100.0;
    std::map<std::string, std::string> leaf; // the last value written per leaf ("0", "1" or the text)
    std::vector<std::string> log;            // every write, in order
    int writes = 0;
    bool fail = false;
    static bool sink(void *ctx, const char *path, bool is_text, bool value, const char *text)
    {
        Rig &r = *static_cast<Rig *>(ctx);
        ++r.writes;
        if (r.fail)
            return false;
        std::string k = std::string(path).substr(std::strlen("view_model_data.hud_cd_"));
        r.leaf[k] = is_text ? std::string(text) : std::string(value ? "1" : "0");
        r.log.push_back(k);
        return true;
    }
    Rig()
    {
        in.live = true;
        in.vid = 3;
        in.snap = &s;
    }
    // one frame; the reads are stamped fresh unless told otherwise
    int step(double dt = 1.0 / 60.0, int budget = 1000, bool stamp = true)
    {
        t += dt;
        if (stamp) {
            s.pitlaps.t = t;
            for (auto &ty : s.tyre)
                if (ty.state)
                    ty.t = t;
        }
        c.update(in, t);
        return c.flush(t, budget, sink, this);
    }
    void settle() { for (int i = 0; i < 30; ++i) step(); }
    bool on(const char *k) { return leaf.count(k) && leaf[k] == "1"; }
    int lit(int sector)
    {
        int n = 0;
        for (int j = 0; j < kSteps; ++j) {
            char b[12];
            std::snprintf(b, sizeof b, "s%dp%02d", sector, j);
            n += on(b);
        }
        return n;
    }
};

static void set_tyre(tower::TyreRead &t, uint8_t visual, int32_t compound, char letter)
{
    t.state = 1;
    t.visual = visual;
    t.compound = compound;
    t.letter = letter;
}

static void set_sectors(Rig &r, float a, float b, float c)
{
    r.s.flags.sectors_ok = true;
    r.s.flags.sectors.count = 3;
    r.s.flags.sectors.end_m[0] = a;
    r.s.flags.sectors.end_m[1] = b;
    r.s.flags.sectors.end_m[2] = c;
    r.s.flags.sectors.track_length = c;
}

static void test_names(const char *out)
{
    Cards c;
    CHECK(kLeaves == 12 + 48);
    std::map<std::string, int> seen;
    FILE *f = nullptr;
    if (out) {
        std::string p = std::string(out) + "/cards_leaves.txt";
        f = std::fopen(p.c_str(), "wb");
    }
    for (int i = 0; i < kLeaves; ++i) {
        CHECK(std::strncmp(c.path(i), "view_model_data.hud_cd_", 23) == 0);
        CHECK(++seen[c.path(i)] == 1);
        if (f)
            std::fprintf(f, "%s %s\n", c.path(i), c.is_text(i) ? "stri" : "bool");
    }
    if (f)
        std::fclose(f);
    CHECK(std::string(c.path(kBadge)) == "view_model_data.hud_cd_badge" && c.is_text(kBadge));
    CHECK(std::string(c.path(kPit3)) == "view_model_data.hud_cd_pit3" && c.is_text(kPit3));
    CHECK(std::string(c.path(kStep0 + 47)) == "view_model_data.hud_cd_s3p15" && !c.is_text(kStep0));
}

static void test_fail_closed()
{
    Rig r; // nothing read at all
    r.settle();
    CHECK(r.leaf["badge"].empty() && !r.on("bdg") && !r.on("pfin"));
    for (const char *k : {"tS", "tM", "tH", "tI", "tW"})
        CHECK(r.leaf.count(k) && !r.on(k));
    CHECK(r.lit(1) + r.lit(2) + r.lit(3) == 0);
    // the pit state is unknown: the node is created once ("") and then left alone
    CHECK(r.leaf.count("pit3") && r.leaf["pit3"].empty());
    r.log.clear();
    for (int i = 0; i < 400; ++i)
        r.step();
    {
        int n3 = 0;
        for (auto &k : r.log)
            n3 += k == "pit3";
        CHECK(n3 == 0);
    }
    // not live (the tower's reader does not run), no car: everything off even with data in the snapshot
    Rig q;
    set_tyre(q.s.tyre[3], 16, 3, 'S');
    set_sectors(q, 1000, 2000, 3000);
    q.in.lap_m = 500;
    q.in.live = false;
    q.settle();
    CHECK(!q.on("tS") && q.lit(1) == 0);
    q.in.live = true;
    q.in.vid = -1;
    q.settle();
    CHECK(!q.on("tS") && q.lit(1) == 0);
    q.in.vid = 3;
    q.settle();
    CHECK(q.on("tS") && q.lit(1) == 8);
}

static void test_badge()
{
    Rig r;
    std::strcpy(r.s.badges.key[0], "mclaren");
    r.s.badges.keys = 1;
    r.s.badges.car[3].state = tower::kBadgeKey;
    r.s.badges.car[3].key = 0;
    r.settle();
    CHECK(r.on("bdg"));
    CHECK(r.leaf["badge"] == std::string(tower::kBadgePrefix) + "mclaren");
    // another car without a badge: off and empty
    r.in.vid = 4;
    r.settle();
    CHECK(!r.on("bdg") && r.leaf["badge"].empty());
    // a key index out of range is no badge
    r.in.vid = 3;
    r.s.badges.car[3].key = 5;
    r.settle();
    CHECK(!r.on("bdg") && r.leaf["badge"].empty());
}

static void test_tyre()
{
    Rig r;
    set_tyre(r.s.tyre[3], 17, 4, 'M');
    r.settle();
    CHECK(r.on("tM") && !r.on("tS") && !r.on("tH") && !r.on("tI") && !r.on("tW"));
    set_tyre(r.s.tyre[3], 8, 8, 'W');
    r.settle();
    CHECK(r.on("tW") && !r.on("tM"));
    // the visual id and the compound disagree: no letter
    set_tyre(r.s.tyre[3], 16, 4, 'S');
    r.settle();
    CHECK(!r.on("tS") && !r.on("tM") && !r.on("tW"));
    // a stale cache keeps the last checked letter for 1 s only
    r.s.tyre[3].state = 2;
    r.s.tyre[3].held = 'H';
    r.s.tyre[3].held_t = r.t;
    r.step();
    CHECK(r.on("tH"));
    for (int i = 0; i < 70; ++i)
        r.step();
    CHECK(!r.on("tH"));
    // a read that stopped (the reader no longer runs) is no tyre after kTyreAge
    set_tyre(r.s.tyre[3], 18, 5, 'H');
    r.settle();
    CHECK(r.on("tH"));
    for (int i = 0; i < 200; ++i)
        r.step(1.0 / 60.0, 1000, false);
    CHECK(!r.on("tH"));
}

static void test_pit()
{
    Rig r;
    r.s.pitlaps.pit_ok = true;
    r.s.pitlaps.pit_have[3] = true;
    r.s.pitlaps.pit[3] = 0; // on track
    r.settle();
    CHECK(!r.on("pfin"));
    CHECK(r.leaf.count("pit3") && r.leaf["pit3"].empty()); // kept alive on track
    // into the pit lane: no final time, and the node is not written any more
    r.s.pitlaps.pit[3] = 4;
    r.step();
    r.log.clear();
    for (int i = 0; i < 400; ++i)
        r.step();
    CHECK(!r.on("pfin"));
    int n3 = 0;
    for (auto &k : r.log)
        n3 += k == "pit3";
    CHECK(n3 == 0);
    // out of the pit lane: pfin for kPitFinal seconds, still no write of the node
    r.s.pitlaps.pit[3] = 1;
    r.step();
    CHECK(r.on("pfin"));
    const double t0 = r.t;
    r.log.clear();
    while (r.t - t0 < kPitFinal - 0.1)
        r.step();
    CHECK(r.on("pfin"));
    n3 = 0;
    for (auto &k : r.log)
        n3 += k == "pit3";
    CHECK(n3 == 0);
    while (r.t - t0 < kPitFinal + 0.1)
        r.step();
    CHECK(!r.on("pfin"));
    // a session that starts with the car on track never shows a final time
    Rig q;
    q.s.pitlaps.pit_ok = true;
    q.s.pitlaps.pit_have[3] = true;
    q.s.pitlaps.pit[3] = 0;
    q.settle();
    CHECK(!q.on("pfin"));
    // a car switch in the pit lane and out again on the other car: nothing
    q.s.pitlaps.pit[3] = 5;
    q.settle();
    q.in.vid = 6;
    q.s.pitlaps.pit_have[6] = true;
    q.s.pitlaps.pit[6] = 0;
    q.settle();
    CHECK(!q.on("pfin"));
    // an unread state while in the pit lane, then on track: nothing (the exit was not seen)
    q.in.vid = 3;
    q.settle();
    q.s.pitlaps.pit_ok = false;
    q.settle();
    q.s.pitlaps.pit_ok = true;
    q.s.pitlaps.pit[3] = 0;
    q.settle();
    CHECK(!q.on("pfin"));
    // a pit state read that went stale is unknown
    q.s.pitlaps.pit[3] = 5;
    q.settle();
    for (int i = 0; i < 90; ++i)
        q.step(1.0 / 60.0, 1000, false);
    q.s.pitlaps.pit[3] = 0;
    q.step(1.0 / 60.0, 1000, false);
    CHECK(!q.on("pfin"));
}

static void test_steps()
{
    Rig r;
    set_sectors(r, 1600, 3200, 4800);
    r.in.lap_m = 0;
    r.settle();
    CHECK(r.lit(1) == 0 && r.lit(2) == 0 && r.lit(3) == 0);
    r.in.lap_m = 99.9f; // just under one step (100 m)
    r.settle();
    CHECK(r.lit(1) == 0);
    r.in.lap_m = 100.1f;
    r.settle();
    CHECK(r.lit(1) == 1 && r.on("s1p00") && !r.on("s1p01"));
    r.in.lap_m = 1599;
    r.settle();
    CHECK(r.lit(1) == 15);
    r.in.lap_m = 1600; // the sector's end belongs to it (the game's rule: end >= distance)
    r.settle();
    CHECK(r.lit(1) == 16 && r.lit(2) == 0);
    r.in.lap_m = 2400;
    r.settle();
    CHECK(r.lit(1) == 0 && r.lit(2) == 8 && r.lit(3) == 0);
    r.in.lap_m = 4799;
    r.settle();
    CHECK(r.lit(2) == 0 && r.lit(3) == 15);
    // past the last sector end, an unknown distance, a table without 3 sectors, no table: nothing
    r.in.lap_m = 4900;
    r.settle();
    CHECK(r.lit(1) + r.lit(2) + r.lit(3) == 0);
    r.in.lap_m = -1;
    r.settle();
    CHECK(r.lit(1) + r.lit(2) + r.lit(3) == 0);
    r.in.lap_m = 2400;
    r.s.flags.sectors.count = 2;
    r.settle();
    CHECK(r.lit(1) + r.lit(2) + r.lit(3) == 0);
    r.s.flags.sectors.count = 3;
    r.s.flags.sectors_ok = false;
    r.settle();
    CHECK(r.lit(1) + r.lit(2) + r.lit(3) == 0);
    // steps are lit from the left without a hole
    r.s.flags.sectors_ok = true;
    r.in.lap_m = 900;
    r.settle();
    for (int j = 0; j < kSteps; ++j) {
        char b[12];
        std::snprintf(b, sizeof b, "s1p%02d", j);
        CHECK(r.on(b) == (j < 9));
    }
}

// a standing start. The grid slot lies in sector 1 (the first drives' logs: 116 m into a 4,323.5 m lap with
// sector ends at 1,204.0 / 2,934.9 / 4,323.5 m, lap counter 0), so the bar shows from the grid on and grows on lap 1
static void test_standing_start()
{
    Rig r;
    set_sectors(r, 1204.0f, 2934.9f, 4323.5f);
    r.in.lap_m = 116;
    r.settle();
    CHECK(r.c.sector() == 1 && r.lit(1) == 1 && r.lit(2) == 0 && r.lit(3) == 0);
    r.in.lap_m = 674;
    r.settle();
    CHECK(r.lit(1) == 8);
    r.in.lap_m = 1203;
    r.settle();
    CHECK(r.lit(1) == 15);
    r.in.lap_m = 1414; // the lap card's capture: 25 s into lap 1
    r.settle();
    CHECK(r.c.sector() == 2 && r.c.steps() == 1 && r.lit(1) == 0 && r.lit(2) == 1 && r.on("s2p00"));
    CHECK(r.c.failed() == 0 && r.c.written() > 0);
    // what the log says about the sector the bar left: sector 1 reached 15 steps, each written at least once
    CHECK(r.c.left_peak() == 15 && r.c.left_on() >= 15);
    // before the car is read (the lights-out frame of another session): nothing
    r.in.lap_m = -1;
    r.settle();
    CHECK(r.c.sector() == 0 && r.lit(1) + r.lit(2) + r.lit(3) == 0);
}

// the lap time's result colour, and sector 1's steps held back after the line
static void test_lap_colour()
{
    Rig r;
    r.s.laps.ok = true;
    r.settle();
    CHECK(!r.on("lcol") && !r.on("lpb") && !r.on("lob"));
    // a first best lap: nothing to compare with, white
    r.s.laps.read[3] = true;
    r.s.laps.best_ok[3] = true;
    r.s.laps.best_ms[3] = 80000;
    r.settle();
    CHECK(!r.on("lcol"));
    // the same best read again: nothing
    r.settle();
    CHECK(!r.on("lcol"));
    // it falls: green for kLapColour seconds
    r.s.laps.best_ms[3] = 79500;
    r.step();
    CHECK(r.on("lcol") && r.on("lpb") && !r.on("lob"));
    const double t0 = r.t;
    while (r.t - t0 < kLapColour - 0.1)
        r.step();
    CHECK(r.on("lpb"));
    while (r.t - t0 < kLapColour + 0.1)
        r.step();
    CHECK(!r.on("lcol") && !r.on("lpb"));
    // it falls and the game names this car the fastest: purple
    r.s.laps.fastest_ok = true;
    r.s.laps.fastest = 3;
    r.s.laps.best_ms[3] = 79000;
    r.step();
    CHECK(r.on("lcol") && r.on("lob") && !r.on("lpb"));
    // a slower lap never colours; another car's best neither
    for (int i = 0; i < 300; ++i)
        r.step();
    r.s.laps.best_ok[4] = true;
    r.s.laps.best_ms[4] = 70000;
    r.settle();
    CHECK(!r.on("lcol"));
    // the best unread (a new session): the next value is a first one again
    r.s.laps.best_ok[3] = false;
    r.s.laps.read[3] = false;
    r.settle();
    r.s.laps.read[3] = true;
    r.s.laps.best_ok[3] = true;
    r.s.laps.best_ms[3] = 60000;
    r.settle();
    CHECK(!r.on("lcol"));
    // a car switch: no colour from the other car's lower time
    r.in.vid = 4;
    r.s.laps.read[4] = true;
    r.settle();
    CHECK(!r.on("lcol"));
    // timed sessions: the tower model's flash starts it (1 green, 2 purple), once per flash
    Rig q;
    q.in.flash = 1;
    q.step();
    CHECK(q.on("lpb"));
    for (int i = 0; i < 60 * 4; ++i)
        q.step();
    CHECK(!q.on("lcol")); // the flash still set: no second start
    q.in.flash = 0;
    q.settle();
    q.in.flash = 2;
    q.step();
    CHECK(q.on("lob") && !q.on("lpb"));
    // not live: nothing
    Rig n;
    n.in.live = false;
    n.in.flash = 1;
    n.settle();
    CHECK(!n.on("lcol"));
}

static void test_line_hold()
{
    Rig r;
    set_sectors(r, 1204.0f, 2934.9f, 4323.5f);
    r.in.lap_m = 4300;
    r.settle();
    CHECK(r.lit(3) == 15);
    // across the line: sector 1's steps wait kLineHold, then show the car's real place
    r.in.lap_m = 80;
    r.step();
    const double t0 = r.t;
    r.settle();
    CHECK(r.c.sector() == 1 && r.lit(1) == 0 && r.lit(3) == 0);
    r.in.lap_m = 400;
    while (r.t - t0 < kLineHold - 0.2)
        r.step();
    CHECK(r.lit(1) == 0);
    while (r.t - t0 < kLineHold + 0.5)
        r.step();
    CHECK(r.lit(1) == 5);
    // a standing start is no crossing: the steps show at once (test_standing_start); a small step back neither
    r.in.lap_m = 380;
    r.settle();
    CHECK(r.lit(1) == 5);
}

static void test_writes()
{
    Rig r;
    set_tyre(r.s.tyre[3], 16, 3, 'S');
    set_sectors(r, 1600, 3200, 4800);
    r.in.lap_m = 2400;
    r.settle();
    // nothing changes: nothing is written until the refresh, then every leaf once (pit3 not: the pit state is unread)
    r.writes = 0;
    int quiet = 0, total = 0;
    for (int i = 0; i < 60 * 4; ++i) {
        const int n = r.step();
        total += n;
        quiet += n == 0;
    }
    CHECK(quiet >= 60 * 4 - 4);
    CHECK(total == 2 * (kLeaves - 1));
    // a budget: never more per frame, and everything still gets out
    Rig b;
    set_sectors(b, 1600, 3200, 4800);
    b.in.lap_m = 1599;
    int mx = 0;
    for (int i = 0; i < 60; ++i)
        mx = std::max(mx, b.step(1.0 / 60.0, kCardWrites));
    CHECK(mx <= kCardWrites);
    CHECK(b.lit(1) == 15);
    // failed writes are tried again
    Rig f;
    set_tyre(f.s.tyre[3], 16, 3, 'S');
    f.fail = true;
    f.settle();
    CHECK(f.leaf.empty());
    f.fail = false;
    f.settle();
    CHECK(f.on("tS"));
}

static void bench()
{
    Rig r;
    set_tyre(r.s.tyre[3], 16, 3, 'S');
    set_sectors(r, 1600, 3200, 4800);
    const int n = 600000;
    const auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < n; ++i) {
        r.in.lap_m = float(i % 4800);
        r.t += 1.0 / 60.0;
        r.s.pitlaps.t = r.t;
        r.s.tyre[3].t = r.t;
        r.c.update(r.in, r.t);
        r.c.flush(r.t, kCardWrites, Rig::sink, &r);
        if (r.log.size() > 4096)
            r.log.clear();
    }
    const double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count() / n;
    std::printf("cards bench: %.4f us per frame (update + flush, the sink's bookkeeping included)\n", us);
}

int main(int argc, char **argv)
{
    test_names(argc > 1 ? argv[1] : nullptr);
    test_fail_closed();
    test_badge();
    test_tyre();
    test_pit();
    test_steps();
    test_standing_start();
    test_lap_colour();
    test_line_hold();
    test_writes();
    bench();
    std::printf("cards: %d passed, %d failed\n", g_pass, g_fail);
    return g_fail ? 1 : 0;
}
