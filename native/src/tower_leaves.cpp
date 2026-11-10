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
                                          "ysna"};
const LeafType kGlobalType[kGlobals] = {
    LeafType::boolean, LeafType::boolean, LeafType::boolean,
    LeafType::boolean, LeafType::text,    LeafType::int32,   LeafType::boolean, LeafType::boolean,
    LeafType::boolean, LeafType::int32,   LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::boolean,
    LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::int32,   LeafType::boolean,
    LeafType::boolean, LeafType::boolean, LeafType::text,    LeafType::text,    LeafType::boolean, LeafType::int32,
    LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::text,
    LeafType::boolean};
const char *const kRowKey[kRowCar] = {"on", "vid", "pos", "p1",  "up",  "dn",  "gap", "gna",   "tyre", "tS", "tM",
                                      "tH", "tI",  "tW",  "tna", "pit", "pen", "out", "me", "badge", "bdg"};
const LeafType kRowType[kRowCar] = {LeafType::boolean, LeafType::int32,   LeafType::text,    LeafType::boolean,
                                    LeafType::boolean, LeafType::boolean, LeafType::text,    LeafType::boolean,
                                    LeafType::text,    LeafType::boolean, LeafType::boolean, LeafType::boolean,
                                    LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::boolean,
                                    LeafType::boolean, LeafType::boolean, LeafType::boolean, LeafType::text,
                                    LeafType::boolean};

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
    }
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

void Publisher::want_badge(int id, const char *key)
{
    Leaf &l = leaf_[id];
    if (!key || !badge_text(key, l.want_t, sizeof l.want_t))
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
    for (const Leaf &l : leaf_)
        n += l.dirty;
    return n;
}

int Publisher::publish(const View &v, double, int budget)
{
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
        want_badge(b + kRowBadge, shown && w.bdg ? w.badge : nullptr);
        want(b + kRowBdg, leaf_[b + kRowBadge].want_t[0] != 0);
    }

    // 1. global and per-car leaves
    int writes = 0;
    for (int id = 0; id < kRowBase && writes < budget; ++id)
        if (leaf_[id].dirty) {
            write(id);
            ++writes;
        }
    // 2. whole rows, top to bottom; a row that does not fit waits for the next frame (unless nothing else was
    //    written this frame, so a row larger than a whole budget still goes out)
    for (int r = 0; r < kRows && writes < budget; ++r) {
        const int b = row_leaf(r, 0);
        int d = 0;
        for (int k = 0; k < kRowLeaves; ++k)
            d += leaf_[b + k].dirty;
        if (!d)
            continue;
        if (d > budget - writes && writes > 0)
            break;
        for (int k = 0; k < kRowLeaves && writes < budget; ++k)
            if (leaf_[b + k].dirty) {
                write(b + k);
                ++writes;
            }
    }
    // 3. refresh: rewrite unchanged leaves round robin
    for (int k = 0; k < kRefreshPerFrame && writes < budget; ++k) {
        const int id = refresh_;
        refresh_ = (refresh_ + 1) % kLeaves;
        if (leaf_[id].dirty || !leaf_[id].sent)
            continue;
        write(id);
        ++writes;
    }
    return writes;
}

} // namespace tower
