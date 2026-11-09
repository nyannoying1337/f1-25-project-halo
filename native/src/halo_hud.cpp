// Project Halo for Swofty Launcher (F1 25 with the 2026 Season Pack).
//
// The game draws the halo itself: the addon's archives build it into the stock 2026 dial scene
// (dial_om_xm.idf), so the game's OSD customisation moves and resizes it like any HUD element. The
// halo's template binds the game's own HUD view model for revs, battery, Active Aero, Overtake and the
// drivers' names; this DLL supplies the rest through view_model_data.hud_halo_* leaves.
//
// Every value comes from inside the game process: game_state_f1_25.cpp reads the game's own car,
// energy-recovery and progress objects (validated, read only). No UDP telemetry, no sockets, no other
// process. Everything runs on the flow thread (on_frame); swofty::hud::set queues the writes for it.
#include <windows.h>

#include <swofty/events.hpp>
#include <swofty/hud.hpp>
#include <swofty/mixin.hpp>

#include "diag_log.hpp"
#include "game_state_f1_25.hpp"
#include "hud_model.hpp"
#include "leaves.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <memory>

SWOFTY_SETTING(bool, show_names, true);
SWOFTY_SETTING(bool, show_turns, true);
SWOFTY_SETTING(bool, validation_log, false);

namespace {

using namespace halo;

constexpr double kDiagPeriod = 1.0 / 30.0; // s between validation-log records
constexpr double kSummaryPeriod = 10.0;    // s between [halo-re] summary lines while live

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
    std::string last_track, last_source;
} g_app;

void init(App &A)
{
    A.init = true;
    gs::F1_25Symbols sym;
    const char *missing = nullptr;
    const bool build = gs::f1_25_build_matches();
    const bool resolved = gs::f1_25_resolve(sym, &missing);
    A.provider = std::make_unique<gs::F1_25Provider>(sym, build && resolved);
    swofty::log("[halo-re] game state: %s (build %s, bindings %s%s%s, track name %s)", A.provider->describe(),
                build ? "d873a1c8 matches" : "differs", resolved ? "resolved" : "missing ", resolved ? "" : missing,
                "", sym.track_world ? "found" : "not found");
    if (!A.provider->compatible())
        swofty::log("[halo-re] in-process reads are off: the halo keeps the game's own speed, revs and battery and "
                    "shows nothing it cannot read");
    if (validation_log) {
        if (diag::start())
            swofty::log("[halo-re] validation log: %s", diag::path_utf8());
        else
            swofty::log("[halo-re] validation log: could not create the file under %%LOCALAPPDATA%%");
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
            swofty::log("[halo-re] player car: vehicle id %u (generation %u)", s.vehicle.id, s.session.generation);
    }
    if (v.live != A.was_live) {
        A.was_live = v.live;
        swofty::log("[halo-re] %s", v.live ? "live: the halo shows the game's state" : "not live: dynamic parts blank");
    }
    if (A.model.track_key() != A.last_track || A.model.turn_source() != A.last_source) {
        A.last_track = A.model.track_key();
        A.last_source = A.model.turn_source();
        swofty::log("[halo-re] turn numbers for '%s': %s", A.last_track.c_str(), A.last_source.c_str());
    }
    if (v.live && A.wall - A.last_summary >= kSummaryPeriod) {
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
    A.model.update(A.state, dt, HudConfig{bool(show_names), bool(show_turns)});
    publish(A.leaves, A.model.view(), A.wall);
    const double cost = qpc_now_us(A) - t0;
    A.cost_sum += cost;
    A.cost_max = std::max(A.cost_max, cost);
    ++A.cost_n;
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
        h.cost_mean_us = float(A.cost_sum / std::max(1, A.cost_n));
        h.cost_max_us = float(A.cost_max);
        h.cost_frames = A.cost_n;
        A.cost_sum = A.cost_max = 0;
        A.cost_n = 0;
        diag::record(A.state, A.provider->raw(), h);
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
