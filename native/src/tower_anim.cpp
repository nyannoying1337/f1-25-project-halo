// tower_anim.cpp - the timing tower's motion.
#include "tower_anim.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>

namespace tower {

Anim::Anim()
{
    for (auto &row : left_t_)
        for (double &t : row)
            t = -1e9;
    forget();
}

// nothing of the last frame counts any more: the next frame the tower shows snaps
void Anim::forget()
{
    have_prev_ = false;
    for (int &vid : prev_vid_)
        vid = -1;
    for (int &r : prev_row_)
        r = -1;
    for (bool &b : nf_sent_)
        b = false;
}

void Anim::packet(int r, uint16_t codes, double now)
{
    AnimRow &a = row_[r];
    a.codes = codes;
    ++a.seq;
    ++packets_;
    ++st_.packets;
    if (codes & kAnSlide) {
        rest_at_[r] = now + kSlideRest;
        busy_until_[r] = now + kBusy;
        ++st_.slides;
    } else if (codes & kAnFade) {
        // a fade alone leaves a slide in flight running: its rest comes when both are done
        rest_at_[r] = (codes & kAnRs) || rest_at_[r] <= 0 ? now + kFadeRest : std::max(rest_at_[r], now + kFadeRest);
    } else {
        rest_at_[r] = 0; // the rest packet
    }
    st_.entries += (codes & (kAnEu | kAnEd)) != 0;
    st_.nf += (codes & kAnNf) != 0;
    st_.ff += (codes & kAnFf) != 0;
    st_.rests += (codes & kAnRs) != 0;
}

// the card the template shows (tt_cards: chequered, else red / SC / VSC, else yellow under none of them),
// behind the tower and the header setting
static Card shown_card(const View &v)
{
    if (!v.on || !v.set.header)
        return kCardNone;
    return v.chq ? kCardChq : v.red ? kCardRed : v.sc ? kCardSc : v.vsc ? kCardVsc : v.yel ? kCardYel : kCardNone;
}

void Anim::head_packet(uint8_t code, double now)
{
    hd_.codes = code;
    ++hd_.seq;
    ++head_packets_;
    if (code & kHdRs) {
        hd_rest_at_ = 0;
        ++st_.hd_rests;
    } else {
        hd_rest_at_ = now + kSlideRest;
        hd_busy_until_ = now + kBusy;
        st_.hd_in += (code & (kHdIn1 | kHdIn2 | kHdIn3)) != 0;
        st_.hd_out += (code & (kHdOut1 | kHdOut2 | kHdOut3)) != 0;
    }
}

// After the rows: the rows' snap reasons hold for the header too (except the rows' own
// window and bulk). A card change slides only from no card (in) or to no card (out); on a snap frame, within the
// last motion's play (busy), or one card for another, the new state shows at once. A snap frame cuts a motion in
// flight (rest packet, copy gone); so does the Animations setting going off (the packet that finishes it is the only
// one made while off).
void Anim::head_update(const View &v, AnimSnap snap, double now)
{
    head_packets_ = 0;
    const Card card = shown_card(v);
    HeadWhy why = kHwNone;
    if (snap == kSnapOff)
        why = kHwOff;
    else if (!v.set.header)
        why = kHwHdr;
    else if (snap == kSnapFirst || !hd_have_prev_)
        why = kHwFirst;
    else if (snap == kSnapSession)
        why = kHwSession;
    else if (snap == kSnapJump)
        why = kHwJump;
    else if (snap == kSnapSettle)
        why = kHwSettle;
    else if (snap == kSnapPlayer)
        why = kHwPlayer;
    const bool moving = hd_rest_at_ > 0;
    auto note = [&](HeadWhy w) {
        hev_.add(HeadEvent{float(now), frame_no_, '!', uint8_t(card), 0, uint8_t(w), false});
    };
    if (card != hd_card_) {
        const Card was = hd_card_;
        if (why == kHwNone && now < hd_busy_until_)
            why = kHwBusy;
        if (why != kHwNone) {
            // at once: a motion in flight goes to rest, its copy goes (logged unless the setting or the tower is
            // off with nothing in flight)
            const bool cut = moving || hd_.ghost != kCardNone;
            if (moving)
                head_packet(kHdRs, now);
            hd_.ghost = kCardNone;
            if (why != kHwOff || cut) {
                ++st_.hd_snaps;
                st_.hd_busy += why == kHwBusy;
                note(why);
            }
        } else if (was == kCardNone) {
            head_packet(uint8_t(kHdIn1 << (card_size(card) - 1)), now);
        } else if (card == kCardNone) {
            head_packet(uint8_t(kHdOut1 << (card_size(was) - 1)), now);
            hd_.ghost = was;
            ++hd_.gseq;
            hd_ghost_until_ = now + kGhost;
        }
        // one card for another, no motion in flight: at once, nothing to send
    } else if (why != kHwNone && (moving || hd_.ghost != kCardNone)) {
        // a snap frame (or the setting off) cuts the motion in flight
        if (moving)
            head_packet(kHdRs, now);
        hd_.ghost = kCardNone;
        ++st_.hd_cut;
        note(why);
    }
    // the end of a motion: the copy goes, then (in the same frame at the latest) the rest packet
    if (hd_.ghost != kCardNone && now >= hd_ghost_until_)
        hd_.ghost = kCardNone;
    if (!head_packets_ && hd_rest_at_ > 0 && now >= hd_rest_at_)
        head_packet(kHdRs, now);
    hd_card_ = card;
    hd_have_prev_ = why != kHwOff && why != kHwHdr;
}

void Anim::update(const View &v, const Frame &f, const Model &m, double now)
{
    packets_ = 0;
    frame_no_ = f.frame_no;
    // the last frame's length: the number fade is armed when the arrow ends within the next two such frames (one
    // frame early at a steady frame rate, and still in time when the next frame comes up to twice as late)
    const double dt = last_now_ >= 0 && now > last_now_ ? std::clamp(now - last_now_, 1.0 / 240, 0.1) : 1.0 / 60;
    last_now_ = now;
    on_ = v.set.animation;
    st_.on = on_;
    const uint32_t session = f.session_ok ? f.session : ~0u;
    const bool set_changed = session != session_ || f.generation != generation_;
    session_ = session;
    generation_ = f.generation;
    if (set_changed)
        settle_until_ = now + kSettle;
    // a replay jump or rewind: the followed car's lap distance moves more than kJumpMetres in one frame, other than
    // across the line
    bool jump = false;
    if (have_prev_ && f.player >= 0 && f.player == player_ && lap_m_ >= 0 && f.player_lap_m >= 0) {
        const bool wrap = f.player_lap_m < kWrapNear && lap_m_ > kWrapFar;
        jump = std::fabs(f.player_lap_m - lap_m_) > kJumpMetres && !wrap;
    }
    if (jump)
        settle_until_ = now + kSettle;

    AnimSnap snap = kSnapNone;
    bool hard = false; // no fade either: nothing of the frame is a change the player saw happen
    if (!on_ || !v.on) {
        snap = kSnapOff;
        hard = true;
    } else if (!have_prev_) {
        snap = kSnapFirst;
        hard = true;
    } else if (set_changed) {
        snap = kSnapSession;
        hard = true;
    } else if (jump) {
        snap = kSnapJump;
        hard = true;
    } else if (now < settle_until_) {
        snap = kSnapSettle;
        hard = true;
    } else if (f.player != player_) {
        snap = kSnapPlayer;
    } else if (int(v.set.mode) != wmode_ || v.start != wstart_ || v.rows != wrows_) {
        snap = kSnapWindow;
    } else {
        int far = 0; // cars moving 2 or more rows
        for (int k = 0; k < v.rows && k < kRows; ++k) {
            const int c = v.row[k].vid;
            far += v.row[k].on && c >= 0 && c < kCars && prev_row_[c] >= 0 && std::abs(prev_row_[c] - k) >= 2;
        }
        if (far > kBulkCars)
            snap = kSnapBulk;
    }

    const bool shown = snap != kSnapOff;
    // per row: the car shown, its motion codes, the row its slide starts from (-1: no slide) and why its new car
    // snapped (0: it did not); fixed arrays, filled every frame
    int car[kRows], from[kRows];
    uint16_t code[kRows];
    uint8_t why[kRows];
    for (int k = 0; k < kRows; ++k) {
        const RowView &w = v.row[k];
        const int c = shown && w.on && w.vid >= 0 && w.vid < kCars ? w.vid : -1;
        car[k] = c;
        from[k] = -1;
        code[k] = 0;
        why[k] = 0;
        if (c < 0 || snap != kSnapNone)
            continue;
        if (c == prev_vid_[k]) {
            // the number fades back in as the arrow ends: armed up to two frames early (frame times vary; the 18:44
            // log replayed at 60 fps between its 10 Hz records missed some at one frame), once per arrow
            if ((w.up || w.dn) && !nf_sent_[k] && m.arrow(c, now + 2 * dt) == 0) {
                code[k] |= kAnNf;
                nf_sent_[k] = true;
            }
            continue;
        }
        const int o = prev_row_[c], idx = v.start + k;
        const bool back = idx >= 0 && idx < kCars && left_t_[c][idx] > now - kFlicker;
        const bool far = o >= 0 && std::abs(o - k) > kMaxSlide;
        if (o < 0 || far || back || busy(k, now)) {
            // the car enters the window, moves too far, comes back to a position it just left, or its row's
            // last slide may still be playing: it snaps
            why[k] = o < 0 ? kRowSnapEnter : far ? kRowSnapFar : back ? kRowSnapBack : kRowSnapBusy;
            continue;
        }
        // d > 0: the car gained d places; its content starts d rows lower and slides up
        const int d = o - k;
        code[k] |= d > 0 ? uint16_t(kAnU1 << (d - 1)) : uint16_t(kAnD1 << (-d - 1));
        // the arrow eases in from the side the row comes from, when that side is a row of the window
        if (d > 0 && w.up && o != v.rows - 1)
            code[k] |= kAnEu;
        if (d < 0 && w.dn && o != 0)
            code[k] |= kAnEd;
        from[k] = o;
    }
    // the pair rule: a slide that would start on a row whose new car snapped because that row may still be
    // sliding (busy), or by this rule, snaps too, so the cars of one move switch together (no car gliding out of a
    // row that switched at once, over the car now on it). Enter, far and back snaps keep the slides around them (the
    // cars a jump passes still slide). Each pass turns at least one slide into a snap: at most kRows passes.
    for (bool again = true; again;) {
        again = false;
        for (int k = 0; k < kRows; ++k)
            if (from[k] >= 0 && (why[from[k]] == kRowSnapBusy || why[from[k]] == kRowSnapPair)) {
                code[k] = uint16_t(code[k] & ~(kAnSlide | kAnEu | kAnEd));
                from[k] = -1;
                why[k] = kRowSnapPair;
                again = true;
            }
    }
    for (int k = 0; k < kRows; ++k) {
        const RowView &w = v.row[k];
        const int c = car[k];
        uint16_t codes = code[k];
        // a row in motion goes to rest on a snap, and when its rest packet is due
        bool rest = moving(k) && (snap != kSnapNone || now >= rest_at_[k]);
        const bool snapped = why[k] != 0; // this row's new car snapped while the frame could move
        if (snapped) {
            rest = rest || moving(k);
            st_.busy += why[k] == kRowSnapBusy;
            st_.pair += why[k] == kRowSnapPair;
            ev_.add(now, k, uint16_t(kEvSnap | why[k]));
        }
        // the lap time flash fades in when the car's flash starts (by vehicle id: a flashing car pushed down a row
        // keeps its flash without a second fade)
        if (c >= 0 && !hard && (w.pb || w.ob) && v.fx[c] != 0 && v.fx[c] != prev_fx_[c])
            codes |= kAnFf;
        // rs never shares a packet (each code's decision fires on its own, in no proven order). A slide's own
        // signals reset the row's other motions and fades; a snap's rest goes alone (a fade with it is dropped: the
        // flash shows at once); a fade that falls on a due rest goes first, and its packet moves the rest later
        if (codes & kAnSlide)
            rest = false;
        else if (rest && (snap != kSnapNone || snapped))
            codes = 0;
        else if (codes)
            rest = false;
        if (rest || codes)
            packet(k, rest ? uint16_t(kAnRs) : codes, now);
        if (c != prev_vid_[k] || !(w.up || w.dn))
            nf_sent_[k] = false;
    }

    // the header's card
    head_update(v, snap, now);

    // what this frame showed, for the next one
    if (shown) {
        // a car that held a position last frame and holds another one now (or is gone) left it: by classification
        // index, so the window moving with the player leaves nothing
        for (int k = 0; k < kRows; ++k) {
            const int pc = prev_vid_[k], pidx = wstart_ + k;
            if (pc < 0 || pidx < 0 || pidx >= kCars)
                continue;
            const int nr = v.car_row[pc];
            if (!(nr >= 0 && v.start + nr == pidx))
                left_t_[pc][pidx] = now;
        }
        for (int k = 0; k < kRows; ++k)
            prev_vid_[k] = v.row[k].on && v.row[k].vid >= 0 && v.row[k].vid < kCars ? v.row[k].vid : -1;
        for (int vid = 0; vid < kCars; ++vid)
            prev_row_[vid] = v.car_row[vid] >= 0 && v.car_row[vid] < kRows ? v.car_row[vid] : -1;
        wmode_ = int(v.set.mode);
        wstart_ = v.start;
        wrows_ = v.rows;
        have_prev_ = true;
    } else {
        forget();
    }
    std::memcpy(prev_fx_, v.fx, sizeof prev_fx_);
    player_ = f.player;
    lap_m_ = f.player_lap_m;
    snap_ = snap;
    if (snap != kSnapNone) {
        st_.snap_bits = uint16_t(st_.snap_bits | (1u << snap));
        st_.snaps += snap != kSnapOff && snap != kSnapSettle;
    }
    int n = 0;
    for (int k = 0; k < kRows; ++k)
        n += moving(k);
    st_.moving = n;
}

} // namespace tower
