#include "diag_log.hpp"

#include <windows.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace halo::diag {
namespace {

constexpr size_t kMaxBytes = size_t(64) << 20; // per file; logging stops there
constexpr size_t kBatch = 4096;                // records per buffer

struct Record {
    gs::GameState s;
    gs::F1_25Raw raw;
    Shown shown;
};

std::mutex g_lock;
std::condition_variable g_wake;
std::vector<Record> g_fill, g_drain;
std::atomic<bool> g_started{false};
std::atomic<uint64_t> g_dropped{0};
std::string g_path;
FILE *g_file = nullptr;
size_t g_bytes = 0;

const char *kHeader =
    "t,frame,compatible,active,generation,cars,session_type,track_len_m,track_name,"
    "veh_ok,veh_id,ai_driving,is_ai,speed_ok,speed_kmh,speed_dist_kmh,vel_x,vel_y,vel_z,"
    "gear_ok,gear,gear_index,rpm_ok,rpm,limiter_ok,limiter_rpm,engine_rate,"
    "input_ok,throttle,brake,throttle_field,brake_field,input_flags,"
    "accel_ok,g_lat,g_long,steer_ok,steer,steer_angle,steer_lock,"
    "store_ok,store_mj,capacity_ok,capacity_mj,power_ok,harvest_k_kw,harvest_h_kw,deploy_kw,"
    "max_deploy_ok,max_deploy_kw,mode_ok,ers_mode,lap_ok,harvest_lap_mj,deploy_lap_mj,harvest_limit_mj,ers_flags,"
    "progress_ok,total_m,lap_m,lap,field_n,player_rank,rejects,results_found,classified,own_pos,cls,humans,progress_link,ctrl_hits,ctrl_vid,isai_vid,spect_vid,player_src,"
    "hud_live,hud_speed_ok,hud_kmh,hud_mph,hud_gear_ok,hud_gear,hud_pedals_ok,hud_th_lv,hud_br_lv,"
    "hud_energy_ok,hud_rc_lv,hud_dp_lv,hud_boost,hud_race,hud_turn,hud_rival_id,scan,cost_mean_us,cost_max_us,cost_frames,dropped,"
    "vcount,slots,old_check,hud_turn_right\n";

void write_record(const Record &r)
{
    const gs::GameState &s = r.s;
    const gs::F1_25Raw &w = r.raw;
    const Shown &h = r.shown;
    char name[sizeof s.session.track_name];
    size_t k = 0;
    for (const char *p = s.session.track_name; *p && k + 1 < sizeof name; ++p)
        name[k++] = (*p == ',' || *p == '"' || *p == '\n') ? '_' : *p;
    name[k] = 0;
    // the classification by vehicle id: "p" + two hex digits per car up to the last one read, "-" for none
    char cls[2 + 2 * gs::kMaxCars] = "-";
    int last = -1;
    for (int i = 0; i < gs::kMaxCars; ++i)
        if (s.field.pos[i])
            last = i;
    if (last >= 0) {
        cls[0] = 'p';
        for (int i = 0; i <= last; ++i)
            std::snprintf(cls + 1 + 2 * i, 3, "%02x", unsigned(s.field.pos[i]));
    }
    const int own_pos = s.vehicle.ok && s.vehicle.id < gs::kMaxCars ? s.field.pos[s.vehicle.id] : 0;
    // the vehicle table's slot status from the last scan (gs::SlotStatus), "-" without a table
    char slots[sizeof w.slots] = "-";
    for (size_t i = 0; i + 1 < sizeof w.slots && w.slots[i]; ++i) {
        slots[i] = std::strchr(".snuti", w.slots[i]) ? w.slots[i] : '?';
        slots[i + 1] = 0;
    }
    char line[2048];
    int n = std::snprintf(
        line, sizeof line,
        "%.4f,%llu,%d,%d,%u,%u,%u,%.2f,%s,"
        "%d,%u,%d,%u,%d,%.3f,%.3f,%.3f,%.3f,%.3f,"
        "%d,%d,%u,%d,%.1f,%d,%.1f,%.3f,"
        "%d,%.4f,%.4f,%.4f,%.4f,%u,"
        "%d,%.4f,%.4f,%d,%.4f,%.5f,%.5f,"
        "%d,%.5f,%d,%.4f,%d,%.3f,%.3f,%.3f,"
        "%d,%.2f,%d,%d,%d,%.5f,%.5f,%.5f,%02x%02x%02x%02x,"
        "%d,%.3f,%.3f,%d,%d,%d,%u,%d,%d,%d,%s,%d,%d,%d,%d,%d,%d,%d,"
        "%d,%d,%d,%d,%d,%d,%d,%d,%d,"
        "%d,%d,%d,%d,%d,%s,%d,%d,%.1f,%.1f,%d,%llu,"
        "%u,%s,%d,%d\n",
        s.time, (unsigned long long)s.frame, s.compatible, s.session.active, s.session.generation, s.session.cars,
        s.session.type_ok ? s.session.type : 9999u, s.session.track_ok ? s.session.track_length_m : -1.f, name,
        s.vehicle.ok, s.vehicle.id, s.vehicle.ai_driving, w.is_ai, s.vehicle.speed_ok, s.vehicle.speed_mps * 3.6f,
        w.speed_from_distance * 3.6f, w.vel[0], w.vel[1], w.vel[2],
        s.vehicle.gear_ok, s.vehicle.gear, w.gear_index, s.power_unit.rpm_ok, s.power_unit.rpm, s.power_unit.limiter_ok,
        s.power_unit.limiter_rpm, w.engine_rate,
        s.input.ok, s.input.throttle, s.input.brake, w.throttle_field, w.brake_field, unsigned(w.input_flags),
        s.vehicle.accel_ok, s.vehicle.g_lat, s.vehicle.g_long, s.vehicle.steer_ok, s.vehicle.steer, w.steer_angle,
        w.steer_lock,
        s.energy.store_ok, s.energy.store_j / 1e6f, s.energy.capacity_ok, s.energy.capacity_j / 1e6f, s.energy.power_ok,
        s.energy.harvest_k_w / 1e3f, s.energy.harvest_h_w / 1e3f, s.energy.deploy_w / 1e3f,
        s.energy.max_deploy_ok, s.energy.max_deploy_w / 1e3f, s.energy.mode_ok, s.energy.mode, s.energy.lap_ok,
        s.energy.harvested_lap_j / 1e6f, s.energy.deployed_lap_j / 1e6f, s.energy.harvest_limit_lap_j / 1e6f,
        w.ers_flags[0], w.ers_flags[1], w.ers_flags[2], w.ers_flags[3],
        s.progress.ok, s.progress.total_m, s.progress.lap_m, s.progress.lap, s.field.n, s.field.player_rank, w.rejects,
        w.results_found, s.field.classified, own_pos, cls, int(w.humans), w.progress_link, int(w.ctrl_hits),
        int(w.ctrl_vid), int(w.isai_vid), int(w.spect_vid), int(w.player_source),
        h.live, h.speed_ok, h.kmh, h.mph, h.gear_ok, h.gear, h.pedals_ok, h.th_lv, h.br_lv,
        h.energy_ok, h.rc_lv, h.dp_lv, h.boost, h.race, h.turn[0] ? h.turn : "-", h.rival_id, w.scanned,
        h.cost_mean_us, h.cost_max_us, h.cost_frames, (unsigned long long)g_dropped.load(),
        unsigned(w.vcount), slots, int(w.old_check), h.turn_right);
    if (n <= 0 || !g_file)
        return;
    if (g_bytes + size_t(n) > kMaxBytes) {
        std::fputs("# size limit reached: logging stopped\n", g_file);
        std::fclose(g_file);
        g_file = nullptr;
        return;
    }
    std::fwrite(line, 1, size_t(n), g_file);
    g_bytes += size_t(n);
}

void writer()
{
    for (;;) {
        {
            std::unique_lock<std::mutex> lk(g_lock);
            g_wake.wait_for(lk, std::chrono::milliseconds(500));
            g_drain.swap(g_fill);
        }
        for (const Record &r : g_drain)
            write_record(r);
        g_drain.clear();
        if (g_file)
            std::fflush(g_file);
    }
}

std::wstring widen(const std::string &s)
{
    std::wstring w(s.size() + 1, L'\0');
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, w.data(), int(w.size()));
    w.resize(n > 0 ? size_t(n - 1) : 0);
    return w;
}

} // namespace

bool start()
{
    bool expected = false;
    if (!g_started.compare_exchange_strong(expected, true))
        return g_file != nullptr;
    char base[MAX_PATH];
    DWORD n = GetEnvironmentVariableA("LOCALAPPDATA", base, sizeof base);
    if (!n || n >= sizeof base)
        return false;
    std::string dir = std::string(base) + "\\nick.f1-2026-halo";
    CreateDirectoryW(widen(dir).c_str(), nullptr);
    dir += "\\diag";
    CreateDirectoryW(widen(dir).c_str(), nullptr);
    std::time_t t = std::time(nullptr);
    std::tm tm{};
    localtime_s(&tm, &t);
    char stamp[32];
    std::strftime(stamp, sizeof stamp, "%Y%m%d_%H%M%S", &tm);
    g_path = dir + "\\halo_" + stamp + ".csv";
    g_file = _wfopen(widen(g_path).c_str(), L"wb");
    if (!g_file)
        return false;
    g_bytes = std::fwrite(kHeader, 1, std::strlen(kHeader), g_file);
    g_fill.reserve(kBatch);
    g_drain.reserve(kBatch);
    std::thread(writer).detach();
    return true;
}

void record(const gs::GameState &s, const gs::F1_25Raw &raw, const Shown &shown)
{
    if (!g_file)
        return;
    std::unique_lock<std::mutex> lk(g_lock, std::try_to_lock);
    if (!lk.owns_lock() || g_fill.size() >= kBatch) {
        g_dropped.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    g_fill.push_back(Record{s, raw, shown});
}

const char *path_utf8() { return g_path.c_str(); }

}
