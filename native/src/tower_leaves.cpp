// tower_leaves.cpp - the hud_tt_* publisher. Contract: docs/timing-tower/leaves.md.
#include "tower_leaves.hpp"

#include <swofty/hud.hpp>
#include <swofty/mixin.hpp>

#include <cstdio>
#include <cstring>

namespace tower {
namespace {

constexpr const char *kPrefix = "view_model_data.hud_tt_";

const char *const kGlobalKey[kGlobals] = {"on",  "trial", "show",    "dbg",  "dbgtxt", "mode",  "full",  "compact",
                                          "top", "rows",  "trunc",   "hdr",  "tyres",  "arrows", "ints", "teamcol",
                                          "hl",  "anim",  "bg",      "lead", "race",   "timed", "sess",  "lap",
                                          "lapna", "hs",  "sc",      "vsc",  "chq",    "red",   "yel",   "ysec",
                                          "ysna", "laps", "clock", "flap"};
const LeafType kGlobalType[kGlobals] = {
    LeafType::boolean, LeafType::boolean, LeafType::boolean,
    LeafType::boolean, LeafType::text,    LeafType::int32,   LeafType::boolean, LeafType::boolean,
    LeafType::boolean, LeafType::int32,   LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::boolean,
    LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::int32,   LeafType::boolean,
    LeafType::boolean, LeafType::boolean, LeafType::text,    LeafType::text,    LeafType::boolean, LeafType::int32,
    LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::text,
    LeafType::boolean, LeafType::boolean, LeafType::text,    LeafType::boolean};
const char *const kRowKey[kRowCar] = {"on", "vid", "pos", "p1",  "up",  "dn",  "gap", "gna",   "tyre", "tS", "tM",
                                      "tH", "tI",  "tW",  "tna", "pit", "pen", "out", "me", "badge", "bdg",
                                      "det", "ko", "pb", "ob", "fl", "dup", "ddn"};
const LeafType kRowType[kRowCar] = {LeafType::boolean, LeafType::int32,   LeafType::text,    LeafType::boolean,
                                    LeafType::boolean, LeafType::boolean, LeafType::text,    LeafType::boolean,
                                    LeafType::text,    LeafType::boolean, LeafType::boolean, LeafType::boolean,
                                    LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::boolean,
                                    LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::text,
                                    LeafType::boolean, LeafType::text, LeafType::boolean, LeafType::boolean,
                                    LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::boolean};
// v12: the motion codes in AnimCode's bit order (all bool). v11's "u1" ... "rs" and the trigger "st" are
// gone: djb2("..._st") = djb2("..._u2") = djb2("..._tS"), so the three were one view-model node
// 3). The build checks that no name of the contract shares a hash with any other view-model name
const char *const kAnimKey[kAnimLeaves] = {"xu1", "xu2", "xu3", "xd1", "xd2", "xd3", "xeu", "xed", "xnf", "xff", "xrs"};
// v13: the header's leaves in id order: the codes (HeadCode's bits), the copies (Card order), the copy's texts
constexpr int kHeadLeaves = kAllLeaves - kHeadBase;
const char *const kHeadKey[kHeadLeaves] = {"kin1",   "kin2",   "kin3",  "kout1", "kout2",  "kout3",   "krs",
                                           "gh_chq", "gh_red", "gh_sc", "gh_vsc", "gh_yel", "gh_ysec", "gh_ysna"};
// the header's state leaves (one write unit with the header's motion leaves while the animations run)
constexpr bool head_state(int id) { return id >= kHs && id <= kYsna; }
static_assert(kYsna - kHs == 7 && kYsec == kYsna - 1, "the header state leaves are kHs ... kYsna");

int core_set(void *, const char *path, LeafType type, const void *value)
{
    const SwoftyHud *t = swofty::hud::detail::table();
    if (!t)
        return SWOFTY_ASSET_UNAVAILABLE;
    const uint32_t kind = type == LeafType::text ? SWOFTY_HUD_TEXT : type == LeafType::int32 ? SWOFTY_HUD_INT : SWOFTY_HUD_BOOL;
    return t->set(path, kind, value);
}

} // namespace

LeafSink core_sink()
{
    LeafSink s;
    s.set = core_set;
    return s;
}

Publisher::Publisher()
{
    static_assert(sizeof kGlobalKey / sizeof kGlobalKey[0] == kGlobals, "one key per global leaf");
    for (int i = 0; i < kGlobals; ++i) {
        std::snprintf(leaf_[i].path, sizeof leaf_[i].path, "%s%s", kPrefix, kGlobalKey[i]);
        leaf_[i].type = kGlobalType[i];
    }
    for (int vid = 0; vid < kCars; ++vid) {
        Leaf &l = leaf_[kCarRowBase + vid];
        std::snprintf(l.path, sizeof l.path, "%sc%02d_row", kPrefix, vid);
        l.type = LeafType::int32;
        l.want_i = -1;
    }
    for (int r = 0; r < kRows; ++r) {
        for (int k = 0; k < kRowCar; ++k) {
            Leaf &l = leaf_[row_leaf(r, k)];
            std::snprintf(l.path, sizeof l.path, "%sr%02d_%s", kPrefix, r, kRowKey[k]);
            l.type = kRowType[k];
        }
        leaf_[row_leaf(r, kRowVid)].want_i = -1;
        for (int vid = 0; vid < kCars; ++vid) {
            Leaf &l = leaf_[row_leaf(r, kRowCar + vid)];
            std::snprintf(l.path, sizeof l.path, "%sr%02d_c%02d", kPrefix, r, vid);
            l.type = LeafType::boolean;
        }
        // the row's anim leaves at rest: every code false (a code starts by going true)
        for (int k = 0; k < kAnimLeaves; ++k) {
            Leaf &l = leaf_[anim_leaf(r, k)];
            std::snprintf(l.path, sizeof l.path, "%sr%02d_%s", kPrefix, r, kAnimKey[k]);
            l.type = LeafType::boolean;
            l.want_i = 0;
        }
    }
    static_assert(sizeof kAnimKey / sizeof kAnimKey[0] == kAnimLeaves, "one key per anim leaf");
    // the header's leaves at rest: every code false, no copy, no text
    for (int k = 0; k < kHeadLeaves; ++k) {
        Leaf &l = leaf_[kHeadBase + k];
        std::snprintf(l.path, sizeof l.path, "%s%s", kPrefix, kHeadKey[k]);
        l.type = kHeadBase + k == kHeadYsec ? LeafType::text : LeafType::boolean;
        l.want_i = 0;
    }
    static_assert(sizeof kHeadKey / sizeof kHeadKey[0] == kHeadLeaves && kHeadLeaves == kHeadCodes + 7,
                  "one key per header leaf");
    static_assert(kHdRs == 1u << (kHeadCodes - 1), "krs is the last header code");
    static_assert(kAnimCodes == 11 && kAnRs == 1u << (kAnimCodes - 1), "rs is the last code");
    sink_ = core_sink();
}

void Publisher::want_int(int id, int32_t v)
{
    Leaf &l = leaf_[id];
    l.want_i = v;
    l.dirty = !l.sent || l.sent_i != v;
}

void Publisher::want_text(int id, const char *s)
{
    Leaf &l = leaf_[id];
    size_t n = 0;
    for (; s && n + 1 < sizeof l.want_t && s[n]; ++n)
        l.want_t[n] = s[n];
    l.want_t[n] = 0;
    l.dirty = !l.sent || std::strcmp(l.sent_t, l.want_t) != 0;
}

void Publisher::want_badge(int id, const char *key, bool render)
{
    Leaf &l = leaf_[id];
    if (!key || !badge_text(key, l.want_t, sizeof l.want_t, render))
        l.want_t[0] = 0;
    l.dirty = !l.sent || std::strcmp(l.sent_t, l.want_t) != 0;
}

bool Publisher::write(int id)
{
    Leaf &l = leaf_[id];
    int32_t v = l.want_i;
    const int r = sink_.set ? sink_.set(sink_.ctx, l.path, l.type, l.type == LeafType::text ? (const void *)l.want_t : &v)
                            : SWOFTY_ASSET_UNAVAILABLE;
    if (r != SWOFTY_ASSET_OK) {
        if (r != last_error_) {
            last_error_ = r;
            swofty::log("[halo] tower leaf %s: write failed (%d)", l.path, r);
        }
        return false;
    }
    l.sent = true;
    l.dirty = false;
    l.sent_i = l.want_i;
    std::memcpy(l.sent_t, l.want_t, sizeof l.sent_t);
    return true;
}

int Publisher::dirty() const
{
    int n = 0;
    for (int id = 0; id < kLeaves; ++id)
        n += leaf_[id].dirty && !leaf_[id].hold;
    for (int id = kAnimBase; id < kAllLeaves; ++id)
        n += anim_writable(id);
    return n;
}

// log the card the written leaves show when it changed (the hdk column: its frame next to its code's)
void Publisher::head_card(double now, uint32_t frame_no)
{
    const Card c = sent_card();
    if (c != hlogged_) {
        hlogged_ = c;
        hev_.add(HeadEvent{float(now), frame_no, 'c', uint8_t(c), 0, 0, c != kCardNone});
    }
}

Card Publisher::sent_card() const
{
    auto on = [&](int id) { return leaf_[id].sent && leaf_[id].sent_i == 1; };
    if (!on(kOn) || !on(kHdr))
        return kCardNone;
    return on(kChq) ? kCardChq : on(kRed) ? kCardRed : on(kSc) ? kCardSc : on(kVsc) ? kCardVsc : on(kYel) ? kCardYel
                                                                                                    : kCardNone;
}

// the header's write unit, in one frame: the state leaves, the copy's texts, the copies, then the code. So the
// card's new state and its motion (or its copy) go out together, the copy's texts before the copy shows
void Publisher::head_write(double now, uint32_t frame_no)
{
    for (int id = kHs; id <= kYsna; ++id)
        if (leaf_[id].dirty)
            write(id);
    head_card(now, frame_no);
    for (int id : {kHeadYsec, kHeadYsna})
        if (anim_writable(id))
            write(id);
    for (int c = kCardChq; c < kCardKinds; ++c) {
        // logged when the copy shows or goes (not the first false of each copy leaf)
        const int id = ghost_leaf(Card(c));
        const bool was = leaf_[id].sent && leaf_[id].sent_i == 1;
        if (anim_writable(id) && write(id) && was != (leaf_[id].sent_i == 1))
            hev_.add(HeadEvent{float(now), frame_no, 'g', uint8_t(c), 0, 0, !was});
    }
    for (int k = 0; k < kHeadCodes; ++k) {
        const int id = head_leaf(k);
        if (!anim_writable(id) || !write(id))
            continue;
        if (leaf_[id].sent_i == 1) {
            hon_t_[k] = now;
            hon_f_[k] = frame_;
            hpend_ = 0;
            hev_.add(HeadEvent{float(now), frame_no, 'k', 0, uint8_t(k), 0, true});
        } else {
            hoff_f_[k] = frame_;
        }
    }
}

int Publisher::publish(const View &v, double now, int budget, const Anim *anim)
{
    ++frame_;
    const Settings &s = v.set;
    const bool on = v.on;
    want(kOn, on);
    want(kTrial, v.trial);
    want(kShow, v.show);
    want(kDbg, s.debug);
    want_text(kDbgTxt, s.debug ? v.dbg : "");
    want_int(kMode, int32_t(s.mode));
    want(kFull, s.mode == Mode::full);
    want(kCompact, s.mode == Mode::compact);
    want(kTop, s.mode == Mode::top);
    want_int(kRowsN, on ? v.rows : 0);
    want(kTrunc, on && v.trunc);
    want(kHdr, s.header);
    want(kTyres, s.tyres);
    want(kArrows, s.arrows);
    want(kInts, s.gaps);
    want(kTeamCol, s.team_colours);
    want(kHl, s.highlight);
    want(kAnim, s.animation);
    want_int(kBg, s.opacity);
    want(kLead, v.lead);
    want(kRace, on && v.race);
    want(kTimed, on && v.timed);
    want_text(kSess, on ? v.sess : "");
    want_text(kLap, on && v.race ? v.lap : "");
    want(kLapNa, on && v.race && v.lapna);
    want_int(kHs, on ? v.hs : 0);
    want(kSc, on && v.sc);
    want(kVsc, on && v.vsc);
    want(kChq, on && v.chq);
    want(kRed, on && v.red);
    want(kYel, on && v.yel);
    want_text(kYsec, on && v.yel ? v.ysec : "");
    want(kYsna, on && v.yel && v.ysna);
    want(kLaps, on && v.laps);
    want(kFlap, on && v.flap); // every lap time of the column at the template's lap time size
    // the header clock's node: the template's copy of the game's own clock formatter writes it while the
    // header is timed; the DLL only keeps it existing ("") at other times and never writes it while timed
    want_text(kClock, "");
    leaf_[kClock].hold = on && v.timed;
    for (int vid = 0; vid < kCars; ++vid)
        want_int(kCarRowBase + vid, on ? v.car_row[vid] : -1);
    char pos[8];
    for (int r = 0; r < kRows; ++r) {
        const RowView &w = v.row[r];
        const bool shown = on && w.on;
        const int b = row_leaf(r, 0);
        want(b + kRowOn, shown);
        want_int(b + kRowVid, shown ? w.vid : -1);
        for (int vid = 0; vid < kCars; ++vid)
            want(b + kRowCar + vid, shown && w.vid == vid);
        if (shown)
            std::snprintf(pos, sizeof pos, "%d", w.pos);
        want_text(b + kRowPos, shown ? pos : "");
        want(b + kRowP1, shown && w.p1);
        want(b + kRowUp, shown && w.up);
        want(b + kRowDn, shown && w.dn);
        want_text(b + kRowGap, shown ? w.gap : "");
        want(b + kRowGna, shown && w.gna);
        const char letter[2] = {shown ? w.tyre : char(0), 0};
        want_text(b + kRowTyre, letter);
        want(b + kRowTS, letter[0] == 'S');
        want(b + kRowTM, letter[0] == 'M');
        want(b + kRowTH, letter[0] == 'H');
        want(b + kRowTI, letter[0] == 'I');
        want(b + kRowTW, letter[0] == 'W');
        want(b + kRowTna, shown && w.tna);
        want(b + kRowPit, shown && w.pit);
        want(b + kRowPen, shown && w.pen);
        want(b + kRowOut, shown && w.out);
        want(b + kRowMe, shown && w.me);
        // the team badge whatever teamcol says (the template hides the logo when it is off)
        want_badge(b + kRowBadge, shown && w.bdg ? w.badge : nullptr, w.brender);
        want(b + kRowBdg, leaf_[b + kRowBadge].want_t[0] != 0);
        want_text(b + kRowDet, shown ? w.det : ""); // the spectator's Detail cell text (docs/spectator-ui.md 10.4)
        want(b + kRowKo, shown && w.ko);             // the knockout hatch
        want(b + kRowPb, shown && w.pb);             // the lap time flash, green
        want(b + kRowOb, shown && w.ob);             // the lap time flash, purple
        want(b + kRowFl, shown && w.fl);             // the race's fastest lap mark
        want(b + kRowDup, shown && w.dup);           // Detail Position Change: places gained
        want(b + kRowDdn, shown && w.ddn);           // Detail Position Change: places lost
    }
    // the rows' motion packets. A new packet's codes wait to start (pend_): a rest drops whatever still waits
    // (it is stale), a slide drops a waiting rest or slide (the newest wins) and keeps waiting fades, fades drop a
    // waiting rest (the Anim sends a new one after them). A code starts when its leaf goes false -> true: only from a
    // false written at least kPulseFrames frames before; it goes back to false kPulse (and kPulseFrames frames) later.
    // So every start is a change the template sees, a true is never written twice, and no false ever starts
    // anything (the decisions have no '0' event). Off: no anim leaf is ever written, except to finish what is
    // already out (a pulse's false, a moving row's rest packet)
    anim_on_ = anim && anim->on();
    if (anim)
        for (int r = 0; r < kRows; ++r) {
            const AnimRow &a = anim->row(r);
            if (a.seq == aseq_[r])
                continue;
            aseq_[r] = a.seq;
            const uint16_t c = a.codes;
            if (c & kAnRs)
                pend_[r] = kAnRs;
            else if (c & kAnSlide)
                pend_[r] = uint16_t((pend_[r] & kAnFade) | c);
            else
                pend_[r] = uint16_t((pend_[r] & ~kAnRs) | c);
        }
    for (int r = 0; r < kRows; ++r)
        for (int k = 0; k < kAnimLeaves; ++k) {
            const int id = anim_leaf(r, k), j = r * kAnimLeaves + k;
            const Leaf &l = leaf_[id];
            if (l.sent && l.sent_i == 1)
                want_int(id, now - on_t_[j] >= kPulse && frame_ - on_f_[j] >= uint32_t(kPulseFrames) ? 0 : 1);
            else
                want_int(id, ((pend_[r] >> k) & 1u) && l.sent && frame_ - off_f_[j] >= uint32_t(kPulseFrames) ? 1 : 0);
        }

    // the header's packet, as a row's (one code a packet: the newest replaces one still waiting). A new copy
    // freezes the yellow texts the template shows now: the last written ysec / ysna, before this frame's writes (the
    // flag's sectors may clear in the very frame the card goes). The copies follow the Anim's
    const uint32_t frame_no = anim ? anim->frame_no() : 0;
    if (anim) {
        const AnimHead &h = anim->head();
        if (h.seq != hseq_) {
            hseq_ = h.seq;
            hpend_ = h.codes;
        }
        if (h.gseq != hgseq_) {
            hgseq_ = h.gseq;
            want_text(kHeadYsec, leaf_[kYsec].sent ? leaf_[kYsec].sent_t : "");
            want(kHeadYsna, leaf_[kYsna].sent && leaf_[kYsna].sent_i == 1);
        }
        for (int c = kCardChq; c < kCardKinds; ++c)
            want(ghost_leaf(Card(c)), h.ghost == c);
    }
    for (int k = 0; k < kHeadCodes; ++k) {
        const int id = head_leaf(k);
        const Leaf &l = leaf_[id];
        if (l.sent && l.sent_i == 1)
            want_int(id, now - hon_t_[k] >= kPulse && frame_ - hon_f_[k] >= uint32_t(kPulseFrames) ? 0 : 1);
        else
            want_int(id, ((hpend_ >> k) & 1u) && l.sent && frame_ - hoff_f_[k] >= uint32_t(kPulseFrames) ? 1 : 0);
    }

    // 1. global and per-car leaves. While the header's motion leaves are live (the Animations setting on, or
    //    one of them still to finish), the header's state leaves and motion leaves go out as one unit first, whole or
    //    not at all this frame; otherwise every global in id order, as before
    int writes = 0;
    bool head_live = anim_on_;
    for (int id = kHeadBase; id < kAllLeaves && !head_live; ++id)
        head_live = anim_writable(id);
    if (head_live) {
        int d = 0;
        for (int id = kHs; id <= kYsna; ++id)
            d += leaf_[id].dirty;
        for (int id = kHeadBase; id < kAllLeaves; ++id)
            d += anim_writable(id);
        if (d && d <= budget) {
            head_write(now, frame_no);
            writes += d;
        }
    }
    for (int id = 0; id < kRowBase && writes < budget; ++id)
        if (leaf_[id].dirty && !leaf_[id].hold && !(head_live && head_state(id))) {
            write(id);
            ++writes;
        }
    // the card the written leaves show, when it changed (the unit logs it before its code)
    if (anim)
        head_card(now, frame_no);
    // 2. whole rows, top to bottom; a row that does not fit waits for the next frame (unless nothing else was
    //    written this frame, so a row larger than a whole budget still goes out). A row's anim leaves are part
    //    of the row and go out last, so a motion starts with the row's new data already in
    for (int r = 0; r < kRows && writes < budget; ++r) {
        const int b = row_leaf(r, 0);
        int d = 0;
        for (int k = 0; k < kRowLeaves; ++k)
            d += leaf_[b + k].dirty;
        for (int k = 0; k < kAnimLeaves; ++k)
            d += anim_writable(anim_leaf(r, k));
        if (!d)
            continue;
        if (d > budget - writes && writes > 0)
            break;
        for (int k = 0; k < kRowLeaves && writes < budget; ++k)
            if (leaf_[b + k].dirty) {
                write(b + k);
                ++writes;
            }
        uint16_t started = 0;
        for (int k = 0; k < kAnimLeaves && writes < budget; ++k) {
            const int id = anim_leaf(r, k), j = r * kAnimLeaves + k;
            if (!anim_writable(id))
                continue;
            ++writes;
            if (!write(id))
                continue;
            if (leaf_[id].sent_i == 1) {
                on_t_[j] = now;
                on_f_[j] = frame_;
                pend_[r] = uint16_t(pend_[r] & ~(1u << k));
                started = uint16_t(started | (1u << k));
            } else {
                off_f_[j] = frame_;
            }
        }
        if (started)
            ev_.add(now, r, started);
    }
    // 3. refresh: rewrite unchanged leaves round robin
    for (int k = 0; k < kRefreshPerFrame && writes < budget; ++k) {
        const int id = refresh_;
        refresh_ = (refresh_ + 1) % kLeaves;
        if (leaf_[id].dirty || !leaf_[id].sent || leaf_[id].hold)
            continue;
        write(id);
        ++writes;
    }
    // no refresh of anim leaves (an earlier build rewrote rest values; a false never starts anything, and a lost false
    // is written again by the next pulse)
    return writes;
}

} // namespace tower
