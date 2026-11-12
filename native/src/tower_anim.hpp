// tower_anim.hpp - the timing tower's motion: which rows slide when cars change
// places, which arrows ride in with them, which position numbers and lap time flashes fade in.
//
// Decided once per frame from the model's published view, after the model. Fixed arrays only (30 rows, 30 cars), no
// allocation, no memory reads; it changes nothing the model publishes. Each row holds a packet: the motion codes to
// start (docs/timing-tower/leaves.md v12) and a sequence number. The publisher starts each code of a new packet after
// the row's data in the same frame: its own leaf rNN_x.. goes from false to true, and back to false kPulse later
// (no trigger, no query; each code's decision fires on its own leaf). A row that slid gets a rest packet (rs
// alone) once its play is over. A slide never starts while the row's last slide may still be playing (kBusy): that
// row's new car snaps instead (the template's goToFraction during a play is not proven).
// The Animations setting off: no packet is ever made (a row still moving gets its rest packet first).
#pragma once

#include "tower_model.hpp"

#include <cstdint>

namespace tower {

constexpr double kPlay = 0.75;        // s a slide or arrow entry plays: the curve's period (seen in game: a play
                                      // lasts the curve's period whatever its span [game])
constexpr double kBusy = kPlay + 0.1; // s from a slide packet until the row may slide again
constexpr double kSlideRest = kBusy;  // s from a slide packet to its rest packet: only once the play is over
constexpr double kFadeRest = 0.3;     // s from a fade packet to its rest packet (the fade's curve takes 0.15 s)
constexpr double kSettle = 2.0;       // s without motion after a session or car-set change, or a replay jump
constexpr double kFlicker = 1.0;      // s: a car back on a position it left less than this ago snaps there
constexpr int kBulkCars = 4;          // more cars than this moving 2 or more rows in one frame: every row snaps
constexpr int kMaxSlide = 3;          // rows a slide spans at most
constexpr float kJumpMetres = 100.f;  // the followed car's lap distance moving more in one frame: a replay jump
constexpr float kWrapNear = 150.f, kWrapFar = 1500.f; // a lap wrap: from beyond kWrapFar to below kWrapNear

// A packet's codes, one bit per code leaf, in the leaves' order (rNN_xu1 ... rNN_xrs, leaves.md v12). rs never shares
// a packet with another code: a slide's own signals reset the row's other motions, a fade that falls on a due rest
// moves the rest later, and a snap's rest packet carries no fade.
enum AnimCode : uint16_t {
    kAnU1 = 1u << 0, kAnU2 = 1u << 1, kAnU3 = 1u << 2, // slide up 1-3 rows: the car gained places
    kAnD1 = 1u << 3, kAnD2 = 1u << 4, kAnD3 = 1u << 5, // slide down 1-3 rows: the car lost places
    kAnEu = 1u << 6, kAnEd = 1u << 7,                   // the ▲ / ▼ entry
    kAnNf = 1u << 8,                                    // the position number fades in
    kAnFf = 1u << 9,                                    // the lap time flash texts fade in
    kAnRs = 1u << 10,                                   // every motion of the row to rest
};
constexpr int kAnimCodes = 11; // code leaves per row (no trigger leaf)
constexpr uint16_t kAnSlide = kAnU1 | kAnU2 | kAnU3 | kAnD1 | kAnD2 | kAnD3;
constexpr uint16_t kAnFade = kAnNf | kAnFf;

struct AnimRow {
    uint16_t codes = kAnRs; // the packet the row's leaves hold; at rest kAnRs alone
    uint32_t seq = 0;       // bumps with every packet
};

// Why every row of a frame snapped (no slide, no arrow entry)
enum AnimSnap : uint8_t {
    kSnapNone = 0,
    kSnapOff,     // Animations off, the tower off or the Time Trial board
    kSnapFirst,   // the first frame the tower shows
    kSnapSession, // the session type or the car set changed (a settle starts)
    kSnapSettle,  // within the settle
    kSnapJump,    // the followed car's lap distance jumped (a replay jump or rewind; a settle starts)
    kSnapPlayer,  // the followed car changed (a spectator switch)
    kSnapWindow,  // the window moved (mode, rows, the compact window's start)
    kSnapBulk,    // more than kBulkCars cars moved 2 or more rows
    kSnapReasons
};

// Counts for the validation log (cumulative since load)
struct AnimStats {
    bool on = false;
    uint32_t slides = 0, entries = 0, nf = 0, ff = 0, rests = 0, snaps = 0, packets = 0;
    uint32_t busy = 0;      // new cars that snapped because their row's slide may still be playing
    uint32_t pair = 0;      // new cars that snapped with such a car (their slide would start on its row)
    uint16_t snap_bits = 0; // the snap reasons seen (1 << AnimSnap), cleared by the log
    int moving = 0;         // rows with a packet whose rest packet is still to come
    // the header's card motions: entries, exits (each with its copy), rest packets, cards changed at once on
    // a snap or within a motion (busy), motions cut by a snap
    uint32_t hd_in = 0, hd_out = 0, hd_rests = 0, hd_snaps = 0, hd_busy = 0, hd_cut = 0;
};

// for the validation log's apk column: why one row's new car snapped while the frame could move
enum RowSnap : uint8_t { kRowSnapEnter = 1, kRowSnapFar, kRowSnapBack, kRowSnapBusy, kRowSnapPair };

// A fixed ring of per-row log events (the publisher's started codes, the rows' own snaps), emptied by the log.
// what: AnimCode bits, or 0x8000 | RowSnap
struct RowEvent {
    float t;    // the model's clock (the log's t column)
    uint8_t row;
    uint16_t what;
};
constexpr uint16_t kEvSnap = 0x8000;
struct RowEvents {
    static constexpr int kMax = 64;
    RowEvent e[kMax];
    int n = 0;
    uint32_t dropped = 0;
    void add(double t, int row, uint16_t what)
    {
        if (n < kMax)
            e[n++] = RowEvent{float(t), uint8_t(row), what};
        else
            ++dropped;
    }
    void clear()
    {
        n = 0;
        dropped = 0;
    }
};

// The header's flag card. One card shows at a time, as the template nests them
// (chequered > red > SC > VSC > yellow, under the header setting). A card that appears where none showed slides in
// from under the header's bottom edge with the rows below it; a card that goes without another one taking its place
// leaves a copy that slides back up while the rows close the gap. One card for another changes at once.
enum Card : uint8_t { kCardNone = 0, kCardChq, kCardRed, kCardSc, kCardVsc, kCardYel, kCardKinds };
// the card's height class: 1 = 1 p (chequered), 2 = 2 p (red, SC, yellow), 3 = 2.5 p (VSC); 0 none
constexpr int card_size(Card c) { return c == kCardNone ? 0 : c == kCardChq ? 1 : c == kCardVsc ? 3 : 2; }
constexpr double kGhost = kBusy; // s the exit's copy holds: the play is over (kPlay) and the copy is out of sight

// A header packet's code, one bit per code leaf in the leaves' order (kin1 ... krs, leaves.md v13); one per packet
enum HeadCode : uint8_t {
    kHdIn1 = 1u << 0, kHdIn2 = 1u << 1, kHdIn3 = 1u << 2,    // the card slides in (by its height class)
    kHdOut1 = 1u << 3, kHdOut2 = 1u << 4, kHdOut3 = 1u << 5, // its copy slides out
    kHdRs = 1u << 6,                                         // the header's motion to rest
};
constexpr int kHeadCodes = 7;

struct AnimHead {
    uint8_t codes = kHdRs;  // the packet the header's code leaves hold; at rest kHdRs alone
    uint32_t seq = 0;       // bumps with every packet
    Card ghost = kCardNone; // the card whose copy shows (an exit), kCardNone none
    uint32_t gseq = 0;      // bumps when a copy starts (the publisher freezes the texts the card showed)
};

// Why the header's card changed without motion (or a motion was cut)
enum HeadWhy : uint8_t {
    kHwNone = 0,
    kHwOff,     // Animations off, the tower off or the Time Trial board
    kHwHdr,     // the Tower header setting off
    kHwFirst,   // the first frame the header shows (also after the setting or the tower comes back)
    kHwSession, // the session type or the car set changed
    kHwJump,    // a replay jump or rewind
    kHwSettle,  // within the settle after either
    kHwPlayer,  // the followed car changed (a spectator switch)
    kHwBusy,    // the header's last motion may still be playing
    kHwReasons
};

// A fixed ring of header log events (the hdk column), emptied by the log. kind: 'c' the card the written
// leaves show (card), 'k' a code started (code: its bit index), 'g' a copy shown (on) or hidden, '!' the card changed
// (or a motion was cut) without motion (why). frame: the halo's frame counter (the log's frame column)
struct HeadEvent {
    float t;
    uint32_t frame;
    char kind;
    uint8_t card, code, why;
    bool on;
};
struct HeadEvents {
    static constexpr int kMax = 16;
    HeadEvent e[kMax];
    int n = 0;
    uint32_t dropped = 0;
    void add(const HeadEvent &x)
    {
        if (n < kMax)
            e[n++] = x;
        else
            ++dropped;
    }
    void clear()
    {
        n = 0;
        dropped = 0;
    }
};

class Anim {
public:
    // after the model, every frame; now: the model's clock (s)
    void update(const View &v, const Frame &f, const Model &m, double now);
    // the header's packet and copy
    const AnimHead &head() const { return hd_; }
    int head_packets() const { return head_packets_; }        // header packets made this frame
    bool head_moving() const { return hd_rest_at_ > 0; }      // a header motion's rest packet is still to come
    uint32_t frame_no() const { return frame_no_; }           // the frame counter of the last update (the log's)
    const HeadEvents &head_events() const { return hev_; }    // the header's snaps since the log last took them
    void clear_head_events() { hev_.clear(); }
    const AnimRow &row(int r) const { return row_[r]; }
    bool on() const { return on_; }          // the setting: packets are made
    AnimSnap snap() const { return snap_; }  // why this frame's rows snapped (kSnapNone: they could move)
    int packets() const { return packets_; } // packets made this frame
    bool moving(int r) const { return rest_at_[r] > 0; }
    const AnimStats &stats() const { return st_; }
    void clear_snap_bits() { st_.snap_bits = 0; }
    bool busy(int r, double now) const { return now < busy_until_[r]; } // the row's slide may still play
    const RowEvents &events() const { return ev_; } // the rows' own snaps since the log last took them
    void clear_events() { ev_.clear(); }

private:
    void packet(int r, uint16_t codes, double now);
    void forget();
    void head_update(const View &v, AnimSnap snap, double now);
    void head_packet(uint8_t code, double now);

    // the header
    AnimHead hd_;
    Card hd_card_ = kCardNone;    // the card the template showed last frame
    bool hd_have_prev_ = false;   // the header showed last frame (tower on, header and Animations settings on)
    double hd_rest_at_ = 0;       // when the header's rest packet is due; 0 at rest
    double hd_busy_until_ = -1e9; // until when the header's last motion may still be playing
    double hd_ghost_until_ = 0;   // when the copy goes
    int head_packets_ = 0;
    uint32_t frame_no_ = 0;
    HeadEvents hev_;

    AnimRow row_[kRows];
    double rest_at_[kRows] = {};     // when the row's rest packet is due; 0 at rest
    double busy_until_[kRows] = {};  // until when the row's last slide may still be playing
    bool nf_sent_[kRows] = {};       // the number fade went out for the row's current arrow
    int prev_vid_[kRows];            // the car each row showed last frame, -1 none
    int prev_row_[kCars];            // the row each car showed on last frame, -1 none
    double left_t_[kCars][kCars];    // when a car last left a classification index (shown rows only)
    uint8_t prev_fx_[kCars] = {};    // the model's flash per car last frame (0 none, 1 green, 2 purple)
    bool have_prev_ = false;         // the last frame showed the tower
    bool on_ = false;
    uint32_t session_ = ~0u, generation_ = ~0u;
    int player_ = -1;
    float lap_m_ = -1.f;
    int wmode_ = -1, wstart_ = -1, wrows_ = -1;
    double settle_until_ = -1e9;
    double last_now_ = -1;
    AnimSnap snap_ = kSnapNone;
    int packets_ = 0;
    AnimStats st_;
    RowEvents ev_;

public:
    Anim();
};

} // namespace tower
