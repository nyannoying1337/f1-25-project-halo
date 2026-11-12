// tower_leaves.hpp - the timing tower's view_model_data.hud_tt_* leaves (contract: docs/timing-tower/leaves.md).
//
// A fixed table built once (no allocation afterwards). Every frame publish() sets the wanted value of every leaf
// from the model's View; flush writes the changed ones within the frame's budget: global leaves first, then whole
// rows (a row's changed leaves go out in one frame, never half old and half new), then a few unchanged leaves
// round robin (every leaf is rewritten within about 2 s, because the game can rebuild its view model).
// v11: each row's motion packet (tower_anim.hpp) goes out after the row's data, in the same frame; with the
// Animations setting off nothing is written to those leaves, and every other leaf goes out as without animations.
// v12: a code starts by its own leaf going false -> true; it goes back to false kPulse later. No trigger, no
// rewrite of a true leaf, no refresh of anim leaves (a false never starts anything).
#pragma once

#include "tower_anim.hpp"
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
    kYsna, kLaps, kClock, kFlap, kGlobals // kLaps (docs/spectator-ui.md 10.4), kClock, kFlap:
                                          // each last, so no older global moves
};
// Row leaf ids, relative to the row's first leaf; car selection c00..c23 at kRowCar + vid.
enum RowLeaf : int {
    kRowOn, kRowVid, kRowPos, kRowP1, kRowUp, kRowDn, kRowGap, kRowGna, kRowTyre, kRowTS, kRowTM, kRowTH, kRowTI, kRowTW,
    kRowTna, kRowPit, kRowPen, kRowOut, kRowMe, kRowBadge, kRowBdg, kRowDet, kRowKo, kRowPb, kRowOb, kRowFl, kRowDup,
    kRowDdn, kRowCar,
    kRowLeaves = kRowCar + kCars // kRowKo after kRowDet, then kRowPb, kRowOb, kRowFl, then kRowDup, kRowDdn
};
constexpr size_t kLeafText = kBadgeTextMax; // text bytes per leaf with the NUL: the badge path is the longest
static_assert(kLeafText >= 64, "room for dbgtxt (63 characters)");
constexpr int kCarRowBase = kGlobals;                      // cVV_row, one per vehicle id
constexpr int kRowBase = kCarRowBase + kCars;              // first row leaf
constexpr int kLeaves = kRowBase + kRows * kRowLeaves;     // every leaf up to v10
// v12: per row the motion codes rNN_xu1 ... rNN_xrs (AnimCode's bits in order); after every older leaf, so
// no older leaf moves. Their names share no hash with any other view-model name (v11's rNN_st and rNN_u2 shared
// rNN_tS: one node)
constexpr int kAnimLeaves = kAnimCodes;
constexpr int kAnimBase = kLeaves;
// v13: the header's motion leaves, after every older leaf: the codes kin1 ... krs (HeadCode's bits in order,
// pulses as the rows' codes), the copies gh_chq ... gh_yel (one per card, Card order: held while the exit's copy
// shows) and the copy's yellow texts gh_ysec, gh_ysna (the texts the card showed as it went)
constexpr int kHeadBase = kAnimBase + kRows * kAnimLeaves;
constexpr int kHeadGhost = kHeadBase + kHeadCodes;
constexpr int kHeadYsec = kHeadGhost + (kCardKinds - 1);
constexpr int kHeadYsna = kHeadYsec + 1;
constexpr int kAllLeaves = kHeadYsna + 1;
constexpr double kPulse = 0.1; // s a started code stays true (and at least kPulseFrames frames)
constexpr int kPulseFrames = 2; // frames between a code's writes: true and false never share a core queue

class Publisher {
public:
    Publisher();
    void set_sink(const LeafSink &s) { sink_ = s; }
    // Set every leaf from the view, then write within `budget` writes. Returns the writes made. anim: the rows'
    // motion packets; null or off: no anim leaf is written (the static tower's writes exactly)
    int publish(const View &v, double now, int budget, const Anim *anim = nullptr);
    // the codes started (written true) since the log last took them, by row
    const RowEvents &events() const { return ev_; }
    void clear_events() { ev_.clear(); }
    // the header's writes since the log last took them (the card the written leaves show, codes started,
    // copies shown and hidden), each with the frame it went out in
    const HeadEvents &head_events() const { return hev_; }
    void clear_head_events() { hev_.clear(); }
    // (tests) the header code still waiting to start; the card the written leaves show
    uint8_t head_pending() const { return hpend_; }
    Card sent_card() const;

    int count() const { return kAllLeaves; }
    const char *path(int id) const { return leaf_[id].path; }
    LeafType type(int id) const { return leaf_[id].type; }
    // what the template would read now (tests): the last value written for the leaf, and whether one was
    bool sent(int id) const { return leaf_[id].sent; }
    int32_t sent_int(int id) const { return leaf_[id].sent_i; }
    const char *sent_text(int id) const { return leaf_[id].sent_t; }
    int dirty() const; // leaves whose wanted value has not been written yet (anim leaves: while they are written)
    static int row_leaf(int row, int leaf) { return kRowBase + row * kRowLeaves + leaf; }
    // a row's anim leaf, k = an AnimCode's bit index
    static int anim_leaf(int row, int k) { return kAnimBase + row * kAnimLeaves + k; }
    // the header's code leaf, k = a HeadCode's bit index; a card's copy leaf
    static int head_leaf(int k) { return kHeadBase + k; }
    static int ghost_leaf(Card c) { return kHeadGhost + int(c) - 1; }
    // (tests) the codes of the row's newest packet still waiting to start
    uint16_t pending(int row) const { return pend_[row]; }

private:
    struct Leaf {
        char path[40];
        LeafType type = LeafType::boolean;
        bool sent = false;      // a value was written (sent_*) since the table was built
        bool dirty = true;      // the wanted value differs from the written one
        bool hold = false;      // not written while true (clock: the template's formatter owns it while timed)
        int32_t want_i = 0, sent_i = 0;
        char want_t[kLeafText] = {}, sent_t[kLeafText] = {};
    };
    void want(int id, bool v) { want_int(id, v ? 1 : 0); }
    void want_int(int id, int32_t v);
    void want_text(int id, const char *s);
    // the text kBadgePrefix + key, or "" when key is null or not a key badge_text accepts
    // render = true: kRenderBadgePrefix + key (a render badge)
    void want_badge(int id, const char *key, bool render = false);
    bool write(int id);
    bool anim_writable(int id) const { return leaf_[id].dirty && (anim_on_ || leaf_[id].sent); }

    Leaf leaf_[kAllLeaves];
    LeafSink sink_;
    int refresh_ = 0;
    int last_error_ = 0;
    // the packet each row's anim leaves were last set from; the setting at the last publish
    uint32_t aseq_[kRows] = {};
    bool anim_on_ = false;
    // per row the codes still to start; per code leaf when it last went true (time, frame) and false (frame)
    uint16_t pend_[kRows] = {};
    double on_t_[kRows * kAnimLeaves] = {};
    uint32_t on_f_[kRows * kAnimLeaves] = {}, off_f_[kRows * kAnimLeaves] = {};
    uint32_t frame_ = 0; // publish() calls
    RowEvents ev_;
    // the header's packet (as the rows': the code waiting to start, when each code leaf last went true and
    // false), the copy whose texts were frozen, the card last logged
    void head_write(double now, uint32_t frame_no);
    void head_card(double now, uint32_t frame_no);
    uint32_t hseq_ = 0, hgseq_ = 0;
    uint8_t hpend_ = 0;
    double hon_t_[kHeadCodes] = {};
    uint32_t hon_f_[kHeadCodes] = {}, hoff_f_[kHeadCodes] = {};
    Card hlogged_ = kCardNone;
    HeadEvents hev_;
};

} // namespace tower
