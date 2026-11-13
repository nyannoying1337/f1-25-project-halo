// Host tests for src/elements.hpp: what the DLL runs for every combination of the six element switches.
// Build and run: tests/run_tests.sh.
#include "../src/elements.hpp"

#include <cstdio>

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

using el::Elements;
using el::Needs;

static Elements none() { return Elements{false, false, false, false, false, false}; }

int main()
{
    // all off: nothing runs
    {
        const Needs n = el::needs(none());
        CHECK(!n.any());
        CHECK(!n.sample && !n.halo && !n.reader && !n.tower_model && !n.tower_publish && !n.cards);
    }
    // all on: everything runs
    {
        const Needs n = el::needs(Elements{});
        CHECK(n.sample && n.halo && n.reader && n.tower_model && n.tower_publish && n.cards);
    }
    // each element alone
    {
        Elements e = none();
        e.halo = true;
        const Needs n = el::needs(e);
        CHECK(n.sample && n.halo);
        CHECK(!n.reader && !n.tower_model && !n.tower_publish && !n.cards); // the halo never reads the classification
    }
    {
        Elements e = none();
        e.tower = true;
        const Needs n = el::needs(e);
        CHECK(n.sample && n.reader && n.tower_model && n.tower_publish);
        CHECK(!n.halo && !n.cards);
    }
    {
        Elements e = none();
        e.banner = true;
        CHECK(!el::needs(e).any()); // scenes only
    }
    {
        Elements e = none();
        e.pit_banner = true;
        CHECK(!el::needs(e).any()); // scenes only
        e.banner = true;
        CHECK(!el::needs(e).any());
    }
    {
        // the pit card alone: logo, tyre and final time come from the reader; no tower model, no tower leaves
        Elements e = none();
        e.pit_card = true;
        const Needs n = el::needs(e);
        CHECK(n.sample && n.reader && n.cards);
        CHECK(!n.halo && !n.tower_model && !n.tower_publish);
    }
    {
        // the lap card alone: the sector bar from the reader, the time's colour from the tower model's flash; the
        // tower itself stays off
        Elements e = none();
        e.lap_card = true;
        const Needs n = el::needs(e);
        CHECK(n.sample && n.reader && n.tower_model && n.cards);
        CHECK(!n.halo && !n.tower_publish);
    }
    // every combination: the invariants
    for (int m = 0; m < 64; ++m) {
        Elements e;
        e.halo = m & 1;
        e.tower = m & 2;
        e.banner = m & 4;
        e.pit_card = m & 8;
        e.lap_card = m & 16;
        e.pit_banner = m & 32;
        const Needs n = el::needs(e);
        CHECK(n.halo == e.halo);                                  // the halo runs live exactly with its own switch
        CHECK(n.tower_publish == e.tower);                        // the tower shows exactly with its own switch
        CHECK(n.cards == (e.pit_card || e.lap_card));             // the cards need no tower switch
        CHECK(n.reader == (e.tower || e.pit_card || e.lap_card)); // the reader runs for any element that uses it
        CHECK(n.tower_model == (e.tower || e.lap_card));
        CHECK(n.sample == (e.halo || e.tower || e.pit_card || e.lap_card));
        CHECK(!n.reader || n.sample);                             // a read never runs without the sample it builds on
        CHECK(!n.tower_model || n.reader);
        CHECK(!n.tower_publish || n.tower_model);
        // the scene-only elements change nothing
        Elements f = e;
        f.banner = !e.banner;
        f.pit_banner = !e.pit_banner;
        const Needs k = el::needs(f);
        CHECK(k.sample == n.sample && k.halo == n.halo && k.reader == n.reader && k.tower_model == n.tower_model &&
              k.tower_publish == n.tower_publish && k.cards == n.cards);
    }
    // the highlights clip latch
    {
        el::ClipLatch c;
        CHECK(!c.update(true, false, 1, false));  // racing
        CHECK(!c.update(true, false, 1, true));   // AI drives before the finish (pit entry, formation): no clip
        CHECK(!c.update(true, true, 1, true));    // finished: the final state itself is not a clip
        CHECK(c.update(true, false, 1, true));    // a replayed moment after the finish: a clip
        CHECK(c.update(true, false, 1, true));
        CHECK(!c.update(true, true, 1, true));    // back at the final state between clips
        CHECK(c.update(true, false, 1, true));    // the next clip
        CHECK(!c.update(true, false, 1, false));  // the player drives: a restarted race ends it
        CHECK(!c.update(true, false, 1, true));   // and AI driving alone does not bring it back
        CHECK(!c.update(true, true, 1, true));
        CHECK(c.update(true, false, 1, true));
        CHECK(!c.update(true, false, 2, true));   // a new car set: forgotten
        c.update(true, true, 2, true);
        CHECK(!c.update(false, false, 2, true));  // the tower off: no clip, and the latch goes
        CHECK(!c.update(true, false, 2, true));
    }
    std::printf("elements: %d passed, %d failed\n", g_pass, g_fail);
    return g_fail ? 1 : 0;
}
