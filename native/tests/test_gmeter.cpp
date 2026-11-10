// Host tests for the G-force meter (src/gmeter.hpp): the filter, the indicator rules of docs/gmeter/design.md §4,
// the red flash, the HUD model's wiring and the leaves publish_gmeter() lights. Build and run: tests/run_tests.sh
#include "../src/gmeter.hpp"
#include "../src/hud_model.hpp"
#include "../src/leaves.hpp"

#include <cmath>
#include <cstdio>
#include <initializer_list>
#include <string>

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

constexpr float kDt = 1.f / 60.f;

// n frames of one reading; tiny alternating noise keeps every frame a fresh record, as when driving
static void hold(GMeter &m, float lat, float lon, int n, bool on = true)
{
    for (int i = 0; i < n; ++i) {
        const float e = (i & 1) ? 1e-4f : -1e-4f;
        m.update(on, true, lat + e, lon, kDt);
    }
}

static uint8_t bits(std::initializer_list<int> ks)
{
    uint8_t b = 0;
    for (int k : ks)
        b |= uint8_t(1u << k);
    return b;
}

static void test_unavailable()
{
    GMeter m;
    m.update(true, false, 3.f, 0.f, kDt);
    CHECK(m.view().on && !m.view().ok && !m.view().indicator && m.view().segs == 0 && m.view().axis == -1);
    CHECK(!m.view().red_bar && !m.view().red_digits);
    m.update(true, true, NAN, 0.f, kDt); // a non-finite read is no reading
    CHECK(!m.view().ok);
    hold(m, 3.f, 0.f, 30);
    CHECK(m.view().ok && m.view().indicator);
    m.update(true, false, 3.f, 0.f, kDt); // the reading drops out: no value, no indicator at once
    CHECK(!m.view().ok && !m.view().indicator && m.view().segs == 0);
    m.update(true, true, 1.5f, 0.f, kDt); // back: starts afresh at the new reading, no easing from the old one
    APPROX(m.view().g, 1.5, 1e-4);
}

static void test_value()
{
    GMeter m;
    m.update(true, true, 2.f, 0.f, kDt); // the first reading shows as it is (no rise from 0.0)
    CHECK(m.view().ok && m.view().tenths == 20);
    hold(m, 3.f, -4.f, 60); // 3-4-5
    APPROX(m.view().g, 5.0, 1e-3);
    CHECK(m.view().tenths == 50);
    hold(m, 0.044f, 0.f, 60);
    CHECK(m.view().tenths == 0);
    hold(m, 0.06f, 0.f, 60);
    CHECK(m.view().tenths == 1);
    hold(m, 12.f, 0.f, 60); // the game's range is +-12 g; the meter shows at most 9.9
    CHECK(m.view().tenths == 99);
    GMeter off;
    hold(off, 3.f, 0.f, 30, false); // the setting off: the model still runs, the leaves stay dark
    CHECK(!off.view().on && off.view().ok && off.view().tenths == 30);
}

static void test_filter()
{
    GMeter m;
    hold(m, 1.f, 0.f, 30);
    m.update(true, true, 8.2f, 0.f, kDt); // a one-record spike (fields.md: up to 8.2 g) is the median's outlier
    CHECK(m.view().tenths == 10);
    hold(m, 1.f, 0.f, 3);
    CHECK(m.view().tenths == 10);

    // a paused game repeats the record bit for bit: nothing new enters, the value holds
    GMeter p;
    hold(p, 2.f, 0.f, 30);
    p.update(true, true, 3.f, 0.f, kDt); // one fresh record of 3, then pause
    for (int i = 0; i < 600; ++i)
        p.update(true, true, 3.f, 0.f, kDt);
    CHECK(p.view().tenths == 20); // the median of (2, 2, 3) is 2: one record never moves it

    // a step: two fresh records move the median; then tau 0.05 s
    GMeter s;
    hold(s, 1.f, 0.f, 30);
    s.update(true, true, 3.f, 0.f, kDt);
    s.update(true, true, 3.0001f, 0.f, kDt); // median now 3: the ease starts
    const float g1 = s.view().g;
    CHECK(g1 > 1.2f && g1 < 1.8f);
    float t = kDt; // the step above already eased one frame
    while (s.view().g < 1.f + 2.f * 0.632f && t < 1.f) {
        s.update(true, true, 3.0001f, 0.f, kDt);
        t += kDt;
    }
    CHECK(t > 0.04f && t < 0.06f); // one time constant (0.05 s) from the median's step
}

static void test_indicator()
{
    GMeter m;
    hold(m, 0.29f, 0.f, 60);
    CHECK(m.view().tenths == 3 && !m.view().indicator && m.view().segs == 0 && m.view().axis == -1);
    hold(m, 0.31f, 0.f, 60);
    CHECK(m.view().indicator && m.view().axis == 0);

    // left-hand corner (the car accelerates toward its left, g_lat > 0): the indicator on the right
    GMeter l;
    hold(l, 1.2f, 0.f, 60);
    CHECK(l.view().indicator && !l.view().wide && l.view().axis == 0 && l.view().segs == bits({0, 1}));
    // right-hand corner: left
    GMeter r;
    hold(r, -1.2f, 0.f, 60);
    CHECK(r.view().axis == 2 && r.view().segs == bits({4, 5}));
    // braking (g_long < 0): up; wide from 2.0 g, centred on the segment that holds the direction
    GMeter b;
    hold(b, 0.f, -3.8f, 60);
    CHECK(b.view().wide && b.view().axis == 3 && b.view().segs == bits({5, 6, 7}) && b.view().red_bar);
    // speeding up: down (a little right of straight down, off the segment boundary at 90 degrees)
    GMeter a;
    hold(a, -0.1f, 0.8f, 60);
    CHECK(a.view().axis == 1 && a.view().segs == bits({2, 3}) && !a.view().red_bar);
    // the pairs and triples of halo.js gView (docs/gmeter/design.md: the Node checks)
    struct Case { float g, dir; bool wide; uint8_t segs; int axis; };
    const Case cases[] = {
        {0.4f, -22.f, false, bits({7, 0}), 0},  {0.8f, 30.f, false, bits({0, 1}), 0},
        {4.5f, 4.f, true, bits({7, 0, 1}), 0},  {2.2f, 180.f, true, bits({3, 4, 5}), 2},
        {3.8f, -90.f, true, bits({5, 6, 7}), 3}, {1.5f, 134.f, false, bits({2, 3}), 1},
        {1.5f, 136.f, false, bits({3, 4}), 2},
    };
    for (const Case &c : cases) {
        GMeter x;
        const float d = c.dir * 3.14159265f / 180.f;
        hold(x, c.g * std::cos(d), c.g * std::sin(d), 60);
        CHECK(x.view().wide == c.wide && x.view().segs == c.segs && x.view().axis == c.axis);
        if (x.view().segs != c.segs)
            std::printf("  case g %.1f dir %.0f: segs %02x axis %d\n", c.g, c.dir, x.view().segs, x.view().axis);
    }
}

static void test_hysteresis()
{
    GMeter m;
    hold(m, 1.9f, 0.f, 60);
    CHECK(!m.view().wide);
    hold(m, 2.1f, 0.f, 60);
    CHECK(m.view().wide && m.view().segs == bits({7, 0, 1}));
    hold(m, 1.1f, 0.f, 60); // wide until the value drops below 1.0 g
    CHECK(m.view().wide);
    hold(m, 0.9f, 0.f, 60);
    CHECK(!m.view().wide && m.view().segs == bits({0, 1}));
    hold(m, 1.9f, 0.f, 60); // and narrow again until 2.0 g
    CHECK(!m.view().wide);
    // the red bar: one threshold, 2.3 g
    hold(m, 2.25f, 0.f, 60);
    CHECK(!m.view().red_bar);
    hold(m, 2.35f, 0.f, 60);
    CHECK(m.view().red_bar);
}

static void test_flash()
{
    GMeter m;
    hold(m, 3.f, 0.f, 60);
    CHECK(!m.view().red_digits);
    hold(m, 4.4f, 0.f, 20); // the eased value reads 4.3 at frame 8: the flash starts there
    CHECK(m.view().tenths == 44 && m.view().red_digits);
    hold(m, 4.4f, 0.f, 60); // 1.2 s after the start: still red
    CHECK(m.view().red_digits);
    hold(m, 4.4f, 0.f, 18); // 1.5 s: white, although the value stays above 4.3
    CHECK(!m.view().red_digits);
    hold(m, 4.1f, 0.f, 60); // not below 4.0: no new flash on the way back up
    hold(m, 4.5f, 0.f, 60);
    CHECK(!m.view().red_digits);
    hold(m, 3.9f, 0.f, 60); // below 4.0: re-armed
    hold(m, 4.3f, 0.f, 30);
    CHECK(m.view().tenths == 43 && m.view().red_digits);
}

static void test_model_and_leaves()
{
    gs::GameState s;
    s.compatible = true;
    s.session.active = true;
    s.vehicle.ok = true;
    s.vehicle.accel_ok = true;
    s.vehicle.g_lat = 4.5f;   // a fast left-hander
    s.vehicle.g_long = 0.f;
    HudModel model;
    HudConfig cfg;
    cfg.show_turns = false;
    for (int i = 0; i < 30; ++i) {
        s.vehicle.g_lat = (i & 1) ? 4.5f : 4.5001f;
        s.time = i * kDt;
        model.update(s, kDt, cfg);
    }
    CHECK(!model.view().gmeter.on && model.view().gmeter.ok); // default off
    Leaves L;
    publish(L, model.view(), 0.0);
    CHECK(!L.wanted("gm") && !L.wanted("gok") && !L.wanted("gu4") && !L.wanted("gs0"));

    cfg.g_meter = true;
    model.update(s, kDt, cfg);
    const View &v = model.view();
    CHECK(v.live && v.gmeter.on && v.gmeter.ok && v.gmeter.tenths == 45);
    publish(L, v, 0.0);
    CHECK(L.wanted("gm") && L.wanted("gok") && L.wanted("gu4") && L.wanted("gt5") && !L.wanted("gu5") && !L.wanted("gt4"));
    CHECK(L.wanted("gs7") && L.wanted("gs0") && L.wanted("gs1") && !L.wanted("gs2") && !L.wanted("gs6"));
    CHECK(L.wanted("gw0") && L.wanted("gr0") && !L.wanted("gw2") && !L.wanted("gr2"));
    int lit = 0;
    for (int d = 0; d <= 9; ++d)
        lit += L.wanted("gu" + std::to_string(d)) + L.wanted("gt" + std::to_string(d));
    CHECK(lit == 2); // one digit per place

    // no validated g: the meter stays (gm) with the dimmed label (no gok): no digit, segment or bar
    s.vehicle.accel_ok = false;
    model.update(s, kDt, cfg);
    publish(L, model.view(), 0.0);
    CHECK(L.wanted("gm") && !L.wanted("gok") && !L.wanted("gred") && !L.wanted("gu4") && !L.wanted("gs0") && !L.wanted("gw0"));
    // no player car (menus, spectating): the same
    s.vehicle.accel_ok = true;
    s.vehicle.ok = false;
    model.update(s, kDt, cfg);
    CHECK(!model.view().live && model.view().gmeter.on && !model.view().gmeter.ok);
    publish(L, model.view(), 0.0);
    CHECK(L.wanted("gm") && !L.wanted("gok") && !L.wanted("gt5"));
    // a new session: nothing carries over (the provider bumps the subject generation with the car set's)
    s.vehicle.ok = true;
    s.session.generation++;
    s.session.subject++;
    s.vehicle.g_lat = 0.5f;
    model.update(s, kDt, cfg);
    CHECK(model.view().gmeter.tenths == 5 && !model.view().gmeter.red_digits);
}

int main()
{
    test_unavailable();
    test_value();
    test_filter();
    test_indicator();
    test_hysteresis();
    test_flash();
    test_model_and_leaves();
    std::printf("gmeter: %d passed, %d failed\n", g_pass, g_fail);
    return g_fail ? 1 : 0;
}
