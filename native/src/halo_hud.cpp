// 2026 Halo HUD for Swofty Launcher (F1 25 with the 2026 Season Pack).
//
// The game draws the halo itself: the addon's archives build it into the stock 2026 dial scene
// (dial_om_xm.idf), so the game's OSD customisation moves and resizes it like any HUD element. The
// halo's template binds the game's own HUD view model for revs, battery, Active Aero, Overtake and the
// drivers' names; this DLL supplies the rest through view_model_data.hud_halo_* leaves.
//
// Every value comes from inside the game process: game_state_f1_25.cpp reads the game's own car,
// energy-recovery and progress objects (validated, read only). No UDP telemetry, no sockets, no other
// process. Everything runs on the flow thread (on_frame); swofty::hud::set queues the writes for it.
//
// The timing tower (Phase 2) runs after the halo in the same frame: tower_reader.cpp reads the game's results,
// timing, pit, safety-car, penalty and tyre systems; tower_model.cpp decides the rows; tower_leaves.cpp writes the
// view_model_data.hud_tt_* leaves (docs/timing-tower/leaves.md) with what is left of the frame's write budget.
#include <windows.h>

#include <swofty/events.hpp>
#include <swofty/hud.hpp>
#include <swofty/mixin.hpp>

#include "diag_log.hpp"
#include "game_state_f1_25.hpp"
#include "hud_model.hpp"
#include "leaves.hpp"
#include "tower_anim.hpp"
#include "tower_leaves.hpp"
#include "tower_model.hpp"
#include "tower_reader.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <memory>

SWOFTY_SETTING(bool, show_names, true);
SWOFTY_SETTING(bool, show_turns, true);
SWOFTY_SETTING(bool, g_meter, false);
SWOFTY_SETTING(bool, all_cars, true);
SWOFTY_SETTING(bool, validation_log, false);
// timing tower (swofty.json "tower*" options; read 4 times a second)
SWOFTY_SETTING(bool, tower_on, true);
SWOFTY_SETTING(std::string_view, tower_mode, "compact");
SWOFTY_SETTING(int, tower_rows, 5);
SWOFTY_SETTING(bool, tower_header, true);
SWOFTY_SETTING(bool, tower_tyres, true);
SWOFTY_SETTING(bool, tower_arrows, true);
SWOFTY_SETTING(bool, tower_gaps, true);
SWOFTY_SETTING(bool, tower_team_colours, true);
SWOFTY_SETTING(bool, tower_highlight, true);
SWOFTY_SETTING(std::string_view, tower_gap_mode, "interval");
SWOFTY_SETTING(int, tower_auto_s, 10);
SWOFTY_SETTING(bool, tower_animations, true);

namespace {

using namespace halo;

constexpr double kDiagPeriod = 1.0 / 30.0; // s between validation-log records
constexpr double kSummaryPeriod = 10.0;    // s between [halo-re] summary lines while live
constexpr double kTowerDiagPeriod = 0.1;   // s between tower log records
constexpr double kTowerSlowPeriod = 1.0;   // s between the tower log's tyre / penalty columns
constexpr double kTowerSettingsPeriod = 0.25; // s between reads of the tower's settings

struct App {
    bool init = false;
    std::unique_ptr<gs::F1_25Provider> provider;
    gs::GameState state;
    HudModel model;
    Leaves leaves;
    double wall = 0, last_diag = -1, last_summary = -100;
    // own CPU time per frame (QueryPerformanceCounter), accumulated between validation-log records
    double qpc_us = 0, cost_sum = 0, cost_max = 0;
    int cost_n = 0;
    // transitions worth a log line
    bool was_active = false, was_live = false;
    uint32_t last_generation = ~0u;
    uint32_t last_subject = ~0u;       // the car the halo follows, last logged
    bool was_watching = false;         // it was a car the spectator HUD watches
    std::string last_track, last_source;
    float last_shift = 0;
    // timing tower
    bool tower_reads = false;          // the provider is compatible: the reader has this build's keys
    tower::Reader treader;
    tower::Model tmodel;
    tower::Anim tanim;                 // the rows' motion packets (fixed arrays, about 8 KB)
    std::unique_ptr<tower::Publisher> tpub; // the leaf table (about 230 KB), built once
    tower::Settings tset;
    tower::Frame tframe;
    double last_tset = -100, last_tdiag = -100, last_tslow = -100;
    uint32_t last_pen_seq = 0;
    uint32_t player_generation = ~0u;  // the player's vehicle id is held within one generation
    int player = -1;
    bool was_tower_on = false;
    bool was_tower_trial = false;      // the Time Trial board was on
    uint32_t last_mode_seq = 0;        // the game mode read last looked at
    char last_mode[tower::kModeLabelMax + 8] = {}; // the game mode last logged: its label, or "?<step>"
    int last_hs = 0;                   // the tower header state last logged
    bool was_sectors_ok = false;       // the session's sector table was logged
    float t_read_us = 0, t_model_us = 0, t_pub_us = 0;
    int t_writes = 0, t_halo_writes = 0;
} g_app;

bool tower_copy(void *, uintptr_t addr, void *dst, size_t n)
{
    SIZE_T got = 0;
    return ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<LPCVOID>(addr), dst, n, &got) && got == n;
}

void read_tower_settings(App &A)
{
    tower::Settings &s = A.tset;
    s.enabled = tower_on;
    const std::string_view m = tower_mode;
    s.mode = m == "full" ? tower::Mode::full : m == "top" ? tower::Mode::top : tower::Mode::compact;
    s.rows = std::clamp(int(tower_rows), 3, tower::kRows);
    s.header = tower_header;
    s.tyres = tower_tyres;
    s.arrows = tower_arrows;
    s.gaps = tower_gaps;
    s.team_colours = tower_team_colours;
    s.highlight = tower_highlight;
    const std::string_view g = tower_gap_mode;
    s.gap_mode = g == "leader" ? tower::GapMode::leader : g == "auto" ? tower::GapMode::autoswitch : tower::GapMode::interval;
    s.auto_period = std::clamp(int(tower_auto_s), 5, 60);
    s.opacity = 100;      // no option: the HUD editor's own opacity applies to the element (contract §2)
    s.animation = tower_animations; // the Animations option (off: the static tower's leaves, no anim leaf written)
    s.debug = validation_log;
}

void init(App &A)
{
    A.init = true;
    gs::F1_25Symbols sym;
    const char *missing = nullptr;
    const bool build = gs::f1_25_build_matches();
    const bool resolved = gs::f1_25_resolve(sym, &missing);
    A.provider = std::make_unique<gs::F1_25Provider>(sym, build && resolved);
    A.tpub = std::make_unique<tower::Publisher>();
    if (A.provider->compatible()) {
        A.treader.configure(tower::Mem{tower_copy, nullptr},
                            tower::keys_from_image(uintptr_t(GetModuleHandleW(nullptr)), sym.game_manager));
        A.tower_reads = true;
    }
    read_tower_settings(A);
    A.last_tset = 0;
    swofty::log("[halo-re] game state: %s (build %s, bindings %s%s%s, track name %s)", A.provider->describe(),
                build ? "d873a1c8 matches" : "differs", resolved ? "resolved" : "missing ", resolved ? "" : missing,
                "", sym.track_world ? "found" : "not found");
    if (!A.provider->compatible())
        swofty::log("[halo-re] in-process reads are off: the halo keeps the game's own speed, revs and battery and "
                    "shows nothing it cannot read");
    if (validation_log) {
        if (diag::start())
            swofty::log("[halo-re] validation log: swofty/addons/nick.f1-2026-halo/%s in the game folder",
                        diag::path_utf8());
        else
            swofty::log("[halo-re] validation log: could not create the file in the addon's folder (the launcher's "
                        "storage is not available)");
    }
}

void log_transitions(App &A)
{
    const gs::GameState &s = A.state;
    const View &v = A.model.view();
    if (s.session.active != A.was_active) {
        A.was_active = s.session.active;
        swofty::log("[halo-re] session %s: %u cars, type %u, track %.0f m %s", s.session.active ? "on" : "off",
                    s.session.cars, s.session.type, s.session.track_length_m, s.session.track_name_ok ? s.session.track_name : "(no name)");
    }
    if (s.session.generation != A.last_generation) {
        A.last_generation = s.session.generation;
        if (s.vehicle.ok)
            swofty::log("[halo-re] player car: vehicle id %u (generation %u)", s.vehicle.player_id, s.session.generation);
    }
    if (s.session.subject != A.last_subject && s.vehicle.ok) {
        A.last_subject = s.session.subject;
        if (!s.vehicle.player || A.was_watching)
            swofty::log("[halo-re] the halo follows %s: vehicle id %u (spectator HUD %s)",
                        s.vehicle.player ? "the player's car" : "the watched car", s.vehicle.id,
                        s.spectate.on ? "up" : "down");
        A.was_watching = !s.vehicle.player;
    }
    if (v.live != A.was_live) {
        A.was_live = v.live;
        swofty::log("[halo-re] %s", v.live ? "live: the halo shows the game's state" : "not live: dynamic parts blank");
    }
    if (A.model.track_key() != A.last_track || A.model.turn_source() != A.last_source ||
        A.model.turn_shift() != A.last_shift) {
        A.last_track = A.model.track_key();
        A.last_source = A.model.turn_source();
        A.last_shift = A.model.turn_shift();
        swofty::log("[halo-re] turn numbers for '%s': %s, moved %+.0f m to the game's corners", A.last_track.c_str(),
                    A.last_source.c_str(), A.last_shift);
    }
    const tower::View &tv = A.tmodel.view();
    if (tv.on != A.was_tower_on) {
        A.was_tower_on = tv.on;
        swofty::log("[halo-re] timing tower %s (%s)", tv.on ? "on" : "off", tv.dbg);
    }
    if (tv.trial != A.was_tower_trial) {
        A.was_tower_trial = tv.trial;
        swofty::log("[halo-re] timing tower: Time Trial board %s", tv.trial ? "on" : "off");
    }
    // the game mode label, when it changes (read at 4 Hz while the tower setting is on)
    const tower::ModeRead &md = A.treader.snapshot().mode;
    if (md.seq != A.last_mode_seq) {
        A.last_mode_seq = md.seq;
        char now_mode[sizeof A.last_mode];
        if (md.ok)
            std::snprintf(now_mode, sizeof now_mode, "%s", md.label);
        else
            std::snprintf(now_mode, sizeof now_mode, "?%d", int(md.step));
        if (std::strcmp(now_mode, A.last_mode) != 0) {
            std::memcpy(A.last_mode, now_mode, sizeof A.last_mode);
            if (md.ok)
                swofty::log("[halo-re] tower: game mode '%s'%s", md.label, md.time_trial ? " (Time Trial)" : "");
            else
                swofty::log("[halo-re] tower: game mode not read (step %d)", int(md.step));
        }
    }
    const tower::FlagRead &fl = A.treader.snapshot().flags;
    if (fl.sectors_ok != A.was_sectors_ok) {
        A.was_sectors_ok = fl.sectors_ok;
        if (fl.sectors_ok) {
            char ends[96] = {};
            size_t k = 0;
            for (int i = 0; i < fl.sectors.count && i < tower::kMaxSectors && k < sizeof ends - 16; ++i)
                k += size_t(std::snprintf(ends + k, sizeof ends - k, i ? " / %.0f" : "%.0f", double(fl.sectors.end_m[i])));
            swofty::log("[halo-re] tower: sector table: %d sectors ending at %s m, track %.0f m", fl.sectors.count, ends,
                        double(fl.sectors.track_length));
        }
    }
    if (tv.hs != A.last_hs) {
        A.last_hs = tv.hs;
        static const char *const kName[] = {"normal", "safety car", "virtual safety car", "red flag", "chequered flag",
                                            "yellow flag"};
        swofty::log("[halo-re] tower header: %s (SC byte %d, red flag byte %d, yellow zones %d, sector '%s'%s)",
                    tv.hs >= 0 && tv.hs <= 5 ? kName[tv.hs] : "?", int(A.treader.snapshot().sc.state), int(fl.red),
                    fl.zones_ok ? fl.yellow : -1, tv.ysec, tv.ysna ? ", unmapped" : "");
    }
    if (v.live && A.wall - A.last_summary >= kSummaryPeriod) {
        if (tv.on)
            swofty::log("[halo-re] tower: %d cars, rows %d from %d, %s, read %.1f us model %.1f us leaves %.1f us (%d writes)",
                        tv.count, tv.rows, tv.start, tv.dbg, A.t_read_us, A.t_model_us, A.t_pub_us, A.t_writes);
        A.last_summary = A.wall;
        const gs::F1_25Raw &r = A.provider->raw();
        swofty::log("[halo-re] %s%.0f km/h (dist %.0f) gear %d rpm %.0f thr %.2f brk %.2f | E %.2f MJ hk %.0f kW dp %.0f "
                    "kW mode %d flags %02x%02x%02x%02x | lap %d %.0f m rank %d/%d",
                    s.vehicle.speed_ok ? "" : "speed? ", s.vehicle.speed_mps * 3.6f, r.speed_from_distance * 3.6f,
                    s.vehicle.gear, s.power_unit.rpm, s.input.throttle, s.input.brake, s.energy.store_j / 1e6f,
                    s.energy.harvest_k_w / 1e3f, s.energy.deploy_w / 1e3f, s.energy.mode, r.ers_flags[0],
                    r.ers_flags[1], r.ers_flags[2], r.ers_flags[3], s.progress.lap, s.progress.lap_m,
                    s.field.player_rank + 1, s.field.n);
    }
}

double qpc_now_us(App &A)
{
    LARGE_INTEGER t;
    if (A.qpc_us == 0) {
        LARGE_INTEGER f;
        QueryPerformanceFrequency(&f);
        A.qpc_us = 1e6 / double(f.QuadPart);
    }
    QueryPerformanceCounter(&t);
    return double(t.QuadPart) * A.qpc_us;
}

void frame(double dt, void *)
{
    App &A = g_app;
    A.wall += dt;
    if (!A.init)
        init(A);
    const double t0 = qpc_now_us(A);
    A.provider->sample(A.wall, A.state);
    A.model.update(A.state, dt, HudConfig{bool(show_names), bool(show_turns), bool(g_meter), bool(all_cars)});
    const int halo_writes = publish(A.leaves, A.model.view(), A.wall);
    const double t1 = qpc_now_us(A);
    const double cost = t1 - t0;
    A.cost_sum += cost;
    A.cost_max = std::max(A.cost_max, cost);
    ++A.cost_n;

    // timing tower: after the halo, with what is left of the frame's write budget
    if (A.wall - A.last_tset >= kTowerSettingsPeriod || A.wall < A.last_tset) {
        A.last_tset = A.wall;
        read_tower_settings(A);
    }
    tower::Frame &f = A.tframe;
    const gs::GameState &st = A.state;
    // the tower's highlighted row: the car the halo follows (the player's, or the spectator's watched car). The car
    // set (f.generation) stays over a spectator switch, so the tower keeps its arrows, badges and held reads.
    if (st.session.subject != A.player_generation) {
        A.player_generation = st.session.subject;
        A.player = -1;
    }
    if (st.vehicle.ok)
        A.player = st.vehicle.id; // held over a frame whose re-validation failed (same car)
    f.session_ok = st.session.type_ok;
    f.session = st.session.type;
    f.generation = st.session.generation;
    static_assert(sizeof(tower::Frame::slots) == sizeof(gs::F1_25Raw::slots), "one slot status per table slot");
    std::memcpy(f.slots, A.provider->raw().slots, sizeof f.slots);
    f.slots[sizeof f.slots - 1] = 0;
    f.player = A.player;
    f.player_lap_m = st.progress.ok ? st.progress.lap_m : -1.f;
    // the spectator menu's Gap and Detail while the halo and the tower follow the watched car (10.4)
    f.spect = st.spectate.on;
    f.spect_gap = st.spectate.gap;
    f.spect_detail = st.spectate.detail;
    f.frame_no = uint32_t(st.frame); // the hdk events' frame (the logs' frame column)
    if (A.tower_reads && A.tset.enabled)
        A.treader.update(A.wall, f);
    const double t2 = qpc_now_us(A);
    A.tmodel.update(A.treader.snapshot(), f, A.tset, A.wall);
    A.tanim.update(A.tmodel.view(), f, A.tmodel, A.wall); // after the model, from what it publishes
    const double t3 = qpc_now_us(A);
    A.t_writes = A.tpub->publish(A.tmodel.view(), A.wall, std::max(0, tower::kFrameBudget - halo_writes), &A.tanim);
    const double t4 = qpc_now_us(A);
    A.t_read_us = float(t2 - t1);
    A.t_model_us = float(t3 - t2);
    A.t_pub_us = float(t4 - t3);
    A.t_halo_writes = halo_writes;
    log_transitions(A);

    if (validation_log && A.wall - A.last_diag >= kDiagPeriod) {
        A.last_diag = A.wall;
        const View &v = A.model.view();
        diag::Shown h{};
        h.live = v.live;
        h.speed_ok = v.speed_ok;
        h.gear_ok = v.gear_ok;
        h.pedals_ok = v.pedals_ok;
        h.energy_ok = v.energy_ok;
        h.boost = v.boost;
        h.race = v.race;
        h.kmh = v.kmh;
        h.mph = v.mph;
        h.gear = v.gear;
        h.th_lv = v.pedals_ok ? stripe_level(v.throttle) : 0;
        h.br_lv = v.pedals_ok ? stripe_level(v.brake) : 0;
        h.rc_lv = v.energy_ok ? cap_level(v.recharge) : 0;
        h.dp_lv = v.energy_ok ? cap_level(v.deploy) : 0;
        h.rival_id = v.rival_id;
        std::strncpy(h.turn, v.turn.c_str(), sizeof h.turn - 1);
        h.turn_right = v.live && !v.turn.empty() ? int(v.turn_right) : -1; // as publish() lights tl / tr
        h.turn_shift = A.model.turn_shift();
        const GView &gm = v.gmeter; // as publish_gmeter() lights it
        const bool g_shown = gm.on && v.live && gm.ok;
        h.g_on = gm.on;
        h.g_tenths = g_shown ? gm.tenths : -1;
        h.g_segs = g_shown && gm.indicator ? gm.segs : 0;
        h.g_axis = g_shown && gm.indicator ? gm.axis : -1;
        h.g_red_bar = g_shown && gm.red_bar;
        h.g_red_digits = g_shown && gm.red_digits;
        h.cost_mean_us = float(A.cost_sum / std::max(1, A.cost_n));
        h.cost_max_us = float(A.cost_max);
        h.cost_frames = A.cost_n;
        A.cost_sum = A.cost_max = 0;
        A.cost_n = 0;
        diag::record(A.state, A.provider->raw(), h);
    }
    if (validation_log && A.wall - A.last_tdiag >= kTowerDiagPeriod) {
        A.last_tdiag = A.wall;
        static diag::TowerRec rec; // about 9 KB: built in place, copied into the writer's buffer
        const tower::Snapshot &snap = A.treader.snapshot();
        rec.t = A.wall;
        rec.frame = A.state.frame;
        rec.generation = f.generation;
        rec.session = f.session;
        rec.session_ok = f.session_ok;
        rec.player = f.player;
        rec.snap = snap;
        rec.view = A.tmodel.view();
        rec.slow = A.wall - A.last_tslow >= kTowerSlowPeriod;
        if (rec.slow)
            A.last_tslow = A.wall;
        rec.pen_changed = snap.pen.log_seq != A.last_pen_seq;
        A.last_pen_seq = snap.pen.log_seq;
        rec.read_us = A.t_read_us;
        rec.model_us = A.t_model_us;
        rec.publish_us = A.t_pub_us;
        rec.writes = A.t_writes;
        rec.halo_writes = A.t_halo_writes;
        rec.copies = A.treader.copies();
        rec.jobs = A.treader.ran();
        rec.anim = A.tanim.stats();
        A.tanim.clear_snap_bits();
        rec.started = A.tpub->events(); // the apk column
        rec.rowsnaps = A.tanim.events();
        rec.hdpub = A.tpub->head_events(); // the hdk column
        rec.hdanim = A.tanim.head_events();
        A.tpub->clear_events();
        A.tanim.clear_events();
        A.tpub->clear_head_events();
        A.tanim.clear_head_events();
        diag::record_tower(rec);
    }
    if (!validation_log) {
        A.tpub->clear_events();
        A.tanim.clear_events();
        A.tpub->clear_head_events();
        A.tanim.clear_head_events();
    }
}

} // namespace

SWOFTY_ON_LOAD
{
    swofty::events::Result r = swofty::events::on_frame(frame);
    swofty::log("[halo] loaded (native HUD, in-process game state, no telemetry): frame %s, hud %s",
                swofty::events::name(r), swofty::hud::available() ? "available" : "unavailable");
}

SWOFTY_ADDON()
