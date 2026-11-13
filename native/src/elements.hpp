// elements.hpp - the addon's elements and what each one makes the DLL do (0.2.2).
//
// Every element has its own switch (swofty.json): the halo dial, the timing tower, the Race Control banner, the pit
// lane timer card, the lap time card, the pit speed colour. No element needs another element's switch: a piece of
// work runs while any element that uses it is on, and stops when none does.
//
//   sample         the game-state sample (speed, gear, lap distance, session, the followed car): the halo shows it,
//                  the tower and both cards need the session and the followed car from it
//   halo           the halo's model, leaves and animations run live (off: the blank state is published, no read)
//   reader         the classification reader (order, gaps, tyres, pit states, lap times): the tower's rows, the pit
//                  card's logo, tyre and final time, the lap card's sector bar and flash
//   tower_model    the tower's model: its rows, and the lap time flash the lap card colours its time with
//   tower_publish  the tower's leaves and animations show the model (off: the off state is published)
//   cards          the cards' leaves are live (off: blank)
//
// The Race Control banner and the pit speed colour are scenes only: they need nothing from the DLL.
// Header-only and free of game or Windows headers: tests/test_elements.cpp runs the whole matrix on the host.
#pragma once

namespace el {

struct Elements {
    bool halo = true;       // Halo dial
    bool tower = true;      // Timing tower
    bool banner = true;     // Race Control banner
    bool pit_card = true;   // Pit lane timer
    bool lap_card = true;   // Lap time card
    bool pit_banner = true; // Pit speed colour (inside the Race Control banner)
};

struct Needs {
    bool sample = false;
    bool halo = false;
    bool reader = false;
    bool tower_model = false;
    bool tower_publish = false;
    bool cards = false;
    constexpr bool any() const { return sample || halo || reader || tower_model || tower_publish || cards; }
};

constexpr Needs needs(const Elements &e)
{
    const bool cards = e.pit_card || e.lap_card;
    Needs n;
    n.sample = e.halo || e.tower || cards;
    n.halo = e.halo;
    n.reader = e.tower || cards;
    n.tower_model = e.tower || e.lap_card;
    n.tower_publish = e.tower;
    n.cards = cards;
    return n;
}

// a highlights clip. After a race the game replays moments of it (the results screen's View highlights, and
// a replay opened there): the classification and the laps are then the moment's, the gaps stay the final ones
// (seen in a validation log: the race start replayed with lap 1 and the grid order, the gap column
// still the finish's). A clip: the leader was classified finished in this car set, is not now, and the followed
// car is AI-driven (after the finish the game drives it; a restarted race with the player driving ends the latch).
struct ClipLatch {
    bool finished = false;
    unsigned generation = ~0u;
    // on: the tower's model is on; chq: its leader is classified finished; ai: the followed car is AI-driven
    constexpr bool update(bool on, bool chq, unsigned gen, bool ai)
    {
        if (gen != generation || !on) {
            generation = gen;
            finished = false;
        }
        if (!on)
            return false;
        if (chq)
            finished = true;
        else if (finished && !ai)
            finished = false; // the player drives again: a restarted race, not a replayed moment
        return finished && !chq;
    }
};

} // namespace el
