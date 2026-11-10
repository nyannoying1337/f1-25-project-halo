// tower_leaves.hpp - the timing tower's view_model_data.hud_tt_* leaves (contract: docs/timing-tower/leaves.md).
//
// A fixed table built once (no allocation afterwards). Every frame publish() sets the wanted value of every leaf
// from the model's View; flush writes the changed ones within the frame's budget: global leaves first, then whole
// rows (a row's changed leaves go out in one frame, never half old and half new), then a few unchanged leaves
// round robin (every leaf is rewritten within about 2 s, because the game can rebuild its view model).
#pragma once

#include "tower_model.hpp"

#include <cstdint>

namespace tower {

enum class LeafType : uint8_t { boolean, text, int32 };

// Where writes go: the core's HUD table in the game; a recorder in the host tests. Returns 0 when queued.
struct LeafSink {
    int (*set)(void *ctx, const char *path, LeafType type, const void *value) = nullptr;
    void *ctx = nullptr;
};
LeafSink core_sink(); // swofty::hud's table (a sink that fails when the core has none)

constexpr int kFrameBudget = 56;  // writes per frame for the halo and the tower together (the core queue holds 64)
constexpr int kRefreshPerFrame = 8;

// Global leaf ids, in table order (on, trial and show first: they go out in one frame).
enum Global : int {
    kOn, kTrial, kShow, kDbg, kDbgTxt, kMode, kFull, kCompact, kTop, kRowsN, kTrunc, kHdr, kTyres, kArrows, kInts,
    kTeamCol, kHl, kAnim, kBg, kLead, kRace, kTimed, kSess, kLap, kLapNa, kHs, kSc, kVsc, kChq, kRed, kYel, kYsec,
    kYsna, kGlobals
};
// Row leaf ids, relative to the row's first leaf; car selection c00..c23 at kRowCar + vid.
enum RowLeaf : int {
    kRowOn, kRowVid, kRowPos, kRowP1, kRowUp, kRowDn, kRowGap, kRowGna, kRowTyre, kRowTS, kRowTM, kRowTH, kRowTI, kRowTW,
    kRowTna, kRowPit, kRowPen, kRowOut, kRowMe, kRowBadge, kRowBdg, kRowCar, kRowLeaves = kRowCar + kCars
};
constexpr size_t kLeafText = kBadgeTextMax; // text bytes per leaf with the NUL: the badge path is the longest
static_assert(kLeafText >= 64, "room for dbgtxt (63 characters)");
constexpr int kCarRowBase = kGlobals;                      // cVV_row, one per vehicle id
constexpr int kRowBase = kCarRowBase + kCars;              // first row leaf
constexpr int kLeaves = kRowBase + kRows * kRowLeaves;     // every leaf

class Publisher {
public:
    Publisher();
    void set_sink(const LeafSink &s) { sink_ = s; }
    // Set every leaf from the view, then write within `budget` writes. Returns the writes made.
    int publish(const View &v, double now, int budget);

    int count() const { return kLeaves; }
    const char *path(int id) const { return leaf_[id].path; }
    LeafType type(int id) const { return leaf_[id].type; }
    // what the template would read now (tests): the last value written for the leaf, and whether one was
    bool sent(int id) const { return leaf_[id].sent; }
    int32_t sent_int(int id) const { return leaf_[id].sent_i; }
    const char *sent_text(int id) const { return leaf_[id].sent_t; }
    int dirty() const; // leaves whose wanted value has not been written yet
    static int row_leaf(int row, int leaf) { return kRowBase + row * kRowLeaves + leaf; }

private:
    struct Leaf {
        char path[40];
        LeafType type = LeafType::boolean;
        bool sent = false;      // a value was written (sent_*) since the table was built
        bool dirty = true;      // the wanted value differs from the written one
        int32_t want_i = 0, sent_i = 0;
        char want_t[kLeafText] = {}, sent_t[kLeafText] = {};
    };
    void want(int id, bool v) { want_int(id, v ? 1 : 0); }
    void want_int(int id, int32_t v);
    void want_text(int id, const char *s);
    // the text kBadgePrefix + key, or "" when key is null or not a key badge_text accepts
    void want_badge(int id, const char *key);
    bool write(int id);

    Leaf leaf_[kLeaves];
    LeafSink sink_;
    int refresh_ = 0;
    int last_error_ = 0;
};

} // namespace tower
