#include "diag_log.hpp"

#include <windows.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdarg>
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
constexpr size_t kTowerBatch = 512;            // tower records per buffer (10 Hz)

struct Record {
    gs::GameState s;
    gs::F1_25Raw raw;
    Shown shown;
};

std::mutex g_lock;
std::condition_variable g_wake;
std::vector<Record> g_fill, g_drain;
std::vector<TowerRec> g_tfill, g_tdrain;
std::atomic<bool> g_started{false};
std::atomic<uint64_t> g_dropped{0}, g_tdropped{0};
std::string g_path, g_tpath;
FILE *g_file = nullptr, *g_tfile = nullptr;
size_t g_bytes = 0, g_tbytes = 0;

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
    "vcount,slots,old_check,hud_turn_right,dist_win_s,turn_shift_m,"
    "hud_g_on,hud_g_tenths,hud_g_segs,hud_g_axis,hud_g_red_bar,hud_g_red_digits,"
    "spect_found,spect_ui,spect_gap\n";

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
        "%u,%s,%d,%d,%.3f,%.1f,"
        "%d,%d,%u,%d,%d,%d,"
        "%d,%d,%lld\n",
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
        unsigned(w.vcount), slots, int(w.old_check), h.turn_right, w.distance_window, h.turn_shift,
        int(h.g_on), h.g_tenths, unsigned(h.g_segs), h.g_axis, int(h.g_red_bar), int(h.g_red_digits),
        // the spectator director (docs/spectator-ui.md §2): found in the registry; +0xd0 and +0xe4 as read, -1 unread.
        // Whether the halo follows the watched car: spect_found, spect_ui != 0, spect_vid >= 0 and veh_id == spect_vid
        int(s.spectate.found), s.spectate.read ? int(s.spectate.ui) : -1,
        s.spectate.read ? (long long)s.spectate.gap : -1LL);
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

// ---------------------------------------------------------------- tower log

const char *kTowerHeader =
    "t,frame,generation,session,on,mode,rows,start,count,player,pidx,held,lead,hs,lap,lapna,"
    "cls_ok,cls_n,holes,dups,sorted,entries,pos,status,tpen,"
    "t_ok,t_entries,gl,gi,gain,"
    "pit_ok,pit,laps_ok,laps,"
    "sc,sc_extra,"
    "zones,red,psec,fseq,fshown,ysec,sectors,"
    "tyre,"
    "pen_ok,pen_n,pen_seq,pen_recs,mc_ok,dt,sg,warn,"
    "shown,found,read_us,model_us,publish_us,writes,halo_writes,copies,jobs,dropped,set,"
    "bdg,rbdg,bdgkeys,bdgvec,gmode,trial\n";

// A bounded appender: never writes past the buffer, keeps it NUL-terminated.
struct Out {
    char *b;
    size_t cap, n = 0;
    void add(const char *fmt, ...)
    {
        if (n + 1 >= cap)
            return;
        va_list a;
        va_start(a, fmt);
        const int k = std::vsnprintf(b + n, cap - n, fmt, a);
        va_end(a);
        if (k > 0)
            n = std::min(cap - 1, n + size_t(k));
    }
    void ch(char c)
    {
        if (n + 1 < cap) {
            b[n++] = c;
            b[n] = 0;
        }
    }
    void dash(int vid) { add(vid ? " -" : "-"); }
};

bool any_data(const TowerRec &r, int vid)
{
    const tower::Snapshot &s = r.snap;
    return s.cls.status[vid] != 0xff || s.cls.pos[vid] || s.timing.car[vid].have || s.pitlaps.pit_have[vid] ||
           s.pitlaps.lap_have[vid] || s.tyre[vid].state;
}

void write_tower(const TowerRec &r)
{
    using namespace tower;
    if (!g_tfile)
        return;
    static char line[16384];
    Out o{line, sizeof line};
    line[0] = 0;
    const Snapshot &s = r.snap;
    const tower::View &v = r.view;
    const Classification &c = s.cls;
    int last = -1; // per-car columns hold one token per vehicle id, 0..the last id with any data
    for (int vid = 0; vid < kCars; ++vid)
        if (any_data(r, vid))
            last = vid;
    o.add("%.4f,%llu,%u,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%s,%d,", r.t, (unsigned long long)r.frame, r.generation,
          r.session_ok ? int(r.session) : -1, v.on, int(v.set.mode), v.rows, v.start, v.count, r.player, v.player_index,
          v.held, v.lead, v.hs, v.lap[0] ? v.lap : "-", v.lapna);
    o.add("%d,%d,%d,%d,%d,%d,", c.ok, c.n, c.holes, c.dups, int(c.sorted), c.entries);
    for (int vid = 0; vid <= last; ++vid) // positions by vehicle id
        c.pos[vid] ? o.add(vid ? " %d" : "%d", c.pos[vid]) : o.dash(vid);
    o.ch(',');
    for (int vid = 0; vid <= last; ++vid) // result status digits
        o.ch(c.status[vid] <= 7 ? char('0' + c.status[vid]) : '-');
    o.ch(',');
    for (int vid = 0; vid <= last; ++vid) // time-penalty totals, s
        c.tpen_ok[vid] ? o.add(vid ? " %g" : "%g", double(c.tpen_s[vid])) : o.dash(vid);
    o.ch(',');
    const Timing &tm = s.timing;
    o.add("%d,%d,", tm.ok, tm.entries);
    for (int k = 0; k < 2; ++k) { // gl, gi: ms and the game's valid flag (v valid, x not); "-" no entry
        for (int vid = 0; vid <= last; ++vid) {
            const GapRec &g = tm.car[vid];
            if (vid)
                o.ch(' ');
            if (!g.have)
                o.ch('-');
            else
                o.add("%lld%c", (long long)(k ? g.ahead_ms : g.leader_ms), (k ? g.ahead_valid : g.leader_valid) ? 'v' : 'x');
        }
        o.ch(',');
    }
    for (int vid = 0; vid <= last; ++vid) { // the game's own gained / lost bytes (T +0x88 / +0x89)
        const GapRec &g = tm.car[vid];
        if (g.have)
            o.add(vid ? " %u%u" : "%u%u", unsigned(g.gained > 9 ? 9 : g.gained), unsigned(g.lost > 9 ? 9 : g.lost));
        else
            o.dash(vid);
    }
    o.ch(',');
    const PitLaps &pl = s.pitlaps;
    o.add("%d,", pl.pit_ok);
    for (int vid = 0; vid <= last; ++vid) // pit state, one hex digit per car
        o.ch(pl.pit_have[vid] ? "0123456789abcdef"[pl.pit[vid] & 15] : '-');
    o.add(",%d,", pl.laps_ok);
    for (int vid = 0; vid <= last; ++vid)
        pl.lap_have[vid] ? o.add(vid ? " %d" : "%d", int(pl.lap[vid])) : o.dash(vid);
    o.add(",%d,%u,", int(s.sc.state), unsigned(s.sc.extra));
    // flags: zones in list order, one char each: the flag digit 0 1 2 4, a yellow zone as its sector letter
    // (A = sector 1, B = 2, ...) or '?' without one; '.' an empty list, '-' unreadable. Then the red flag byte
    // (-1 unread), the player's sector (0 unknown), the flags read count, what the view showed (r red, y yellow,
    // n yellow without sector, '-' none), its sector text and, in the 1 Hz records, the session's sector table.
    const FlagRead &fl = s.flags;
    if (!fl.zones_ok)
        o.ch('-');
    else if (!fl.zones)
        o.ch('.');
    for (int i = 0; fl.zones_ok && i < fl.zones && i < int(kMaxMarshalZones); ++i)
        o.ch(fl.flag[i] == zone_yellow ? (fl.sector[i] > 0 ? char('A' + fl.sector[i] - 1) : '?') : char('0' + fl.flag[i]));
    o.add(",%d,%d,%u,", int(fl.red), int(fl.player_sector), fl.seq);
    if (v.red)
        o.ch('r');
    if (v.yel)
        o.ch('y');
    if (v.ysna)
        o.ch('n');
    if (!v.red && !v.yel)
        o.ch('-');
    o.ch(',');
    if (v.ysec[0])
        for (const char *q = v.ysec; *q; ++q)
            o.ch(*q == ' ' ? '_' : *q);
    else
        o.ch('-');
    o.ch(',');
    if (r.slow && fl.sectors_ok) { // sector ends / track length, m
        for (int i = 0; i < fl.sectors.count && i < kMaxSectors; ++i)
            o.add(i ? "/%.1f" : "%.1f", double(fl.sectors.end_m[i]));
        o.add("@%.1f", double(fl.sectors.track_length));
    } else
        o.ch('-');
    o.ch(',');
    if (r.slow) { // tyres: state.set.desc.visual.actual.enum.letter for state 1, else the state alone
        for (int vid = 0; vid <= last; ++vid) {
            const TyreRead &t = s.tyre[vid];
            if (vid)
                o.ch(' ');
            if (t.state == 1)
                o.add("1.%u.%u.%u.%u.%d.%c", t.set_id, t.desc_id, unsigned(t.visual), unsigned(t.actual), int(t.compound),
                      t.letter ? t.letter : '_');
            else
                o.add("%u", unsigned(t.state));
        }
    } else
        o.ch('-');
    const Penalties &p = s.pen;
    o.add(",%d,%d,%u,", p.log_ok, p.records, p.log_seq);
    if (r.pen_changed && p.log_ok) { // vehicle:type:infringement:time:lap:other, ';' between records
        const int n = p.records < kLogRecords ? p.records : kLogRecords;
        for (int i = 0; i < n; ++i) {
            const PenaltyRecord &q = p.rec[i];
            o.add(i ? ";%u:%u:%u:%u:%u:%u" : "%u:%u:%u:%u:%u:%u", unsigned(q.vehicle), unsigned(q.penalty),
                  unsigned(q.infringement), q.time_s, q.lap, unsigned(q.other_vehicle));
        }
        if (!n)
            o.ch('0');
    } else
        o.ch('-');
    o.add(",%d,", p.mc_ok);
    if (r.slow) {
        for (int vid = 0; vid <= last; ++vid)
            o.ch(p.mc_ok ? char('0' + (p.dt[vid] > 9 ? 9 : p.dt[vid])) : '-');
        o.ch(',');
        for (int vid = 0; vid <= last; ++vid)
            o.ch(p.mc_ok ? char('0' + (p.sg[vid] > 9 ? 9 : p.sg[vid])) : '-');
        o.ch(',');
        for (int vid = 0; vid <= last; ++vid)
            p.log_ok ? o.add(vid ? " %d/%d" : "%d/%d", p.warn[vid].total, p.warn[vid].track_limits) : o.dash(vid);
    } else
        o.add("-,-,-");
    o.ch(',');
    // what the tower showed, per visible row: vid:pos:kind:gap:tyre:flags
    for (int k = 0; k < v.rows && k < kRows; ++k) {
        const tower::RowView &w = v.row[k];
        char gap[16];
        size_t g = 0;
        for (const char *q = w.gap; *q && g + 1 < sizeof gap; ++q)
            gap[g++] = *q == ' ' ? '_' : *q;
        gap[g] = 0;
        o.add(k ? " %d:%d:%u:%s:%c:" : "%d:%d:%u:%s:%c:", w.vid, w.pos, unsigned(w.shown), g ? gap : "-",
              w.tyre ? w.tyre : '-');
        const bool on[] = {w.up, w.dn, w.pit, w.pen, w.out, w.me, w.gna, w.tna, w.tyre_held, w.p1};
        for (size_t i = 0; i < sizeof on; ++i)
            if (on[i])
                o.ch("udpnomgth1"[i]);
    }
    if (v.rows <= 0)
        o.ch('-');
    o.add(",%c%c%c%c%c%c%c%c%c%c", s.found_results ? 'R' : '.', s.found_timing ? 'T' : '.', s.found_pit ? 'P' : '.',
          s.found_sc ? 'S' : '.', s.found_log ? 'Z' : '.', s.found_s1 ? '1' : '.', s.found_tyres ? 'Y' : '.',
          s.found_progress ? 'G' : '.', s.found_zones ? 'M' : '.', s.found_red ? 'F' : '.');
    o.add(",%.1f,%.1f,%.1f,%d,%d,%d,%u,%llu", double(r.read_us), double(r.model_us), double(r.publish_us), r.writes,
          r.halo_writes, r.copies, r.jobs, (unsigned long long)g_tdropped.load());
    // the display settings the model used: header, tyres, arrows, gaps, team colours, highlight ('-' off)
    const Settings &st = v.set;
    o.add(",%c%c%c%c%c%c,", st.header ? 'h' : '-', st.tyres ? 't' : '-', st.arrows ? 'a' : '-', st.gaps ? 'g' : '-',
          st.team_colours ? 'c' : '-', st.highlight ? 'm' : '-');
    // team badges (field-traces.md §10). bdg, one char per car: the key's letter ('a' = the first key of the car
    // set), '?' the game builds another path (My Team / render badge), '1'..'9' the step a failed read stopped at,
    // '.' not read yet. rbdg, one char per shown row: the row's key letter, '-' none. bdgkeys: letter=key for every
    // key of the car set (',', '"', ' ', '%' and '=' as %XX), in the 1 Hz records and whenever a car's result changed
    // ('.' none yet), else '-'.
    const Badges &bd = s.badges;
    for (int vid = 0; vid <= last; ++vid) {
        const BadgeRead &b = bd.car[vid];
        o.ch(b.state == kBadgeKey && b.key >= 0 && b.key < 26 ? char('a' + b.key)
             : b.state == kBadgeOther                         ? '?'
             : b.state == kBadgeFailed                        ? char('0' + (b.step <= 9 ? b.step : 9))
                                                              : '.');
    }
    o.ch(',');
    for (int k = 0; k < v.rows && k < kRows; ++k)
        o.ch(v.row[k].bdg && v.row[k].bkey >= 0 && v.row[k].bkey < 26 ? char('a' + v.row[k].bkey) : '-');
    if (v.rows <= 0)
        o.ch('-');
    o.ch(',');
    static uint32_t listed_seq = ~0u, listed_gen = ~0u;
    if (r.slow || bd.seq != listed_seq || r.generation != listed_gen) {
        listed_seq = bd.seq;
        listed_gen = r.generation;
        for (int k = 0; k < bd.keys && k < 26; ++k) {
            o.add(k ? " %c=" : "%c=", char('a' + k));
            for (const char *q = bd.key[k]; *q && q < bd.key[k] + kBadgeKeyMax; ++q)
                std::strchr(",\" %=", *q) ? o.add("%%%02X", unsigned((unsigned char)*q)) : o.ch(*q);
        }
        if (bd.keys <= 0)
            o.ch('.');
    } else
        o.ch('-');
    // bdgvec: the game's entrant vector at the last badge run: its record count, '-' no run reached it in this car
    // set, 'u' its bounds unreadable, 's' not sane (or over kMaxEntrants records), 'c' a chunk of records unreadable
    o.ch(',');
    if (bd.entrants >= 0)
        o.add("%d", int(bd.entrants));
    else
        o.ch(bd.entrants == kEntrantsUnreadable    ? 'u'
             : bd.entrants == kEntrantsNotSane    ? 's'
             : bd.entrants == kEntrantsCopyFailed ? 'c'
                                                  : '-');
    // gmode: the game mode label of the last read ("time_trial", "grand_prix_23", "none"), '-' never
    // read, '?N' the read stopped at step N (ModeRead); trial: the Time Trial board is on
    const ModeRead &md = s.mode;
    o.ch(',');
    if (md.ok)
        o.add("%s", md.label);
    else if (md.seq)
        o.add("?%d", int(md.step));
    else
        o.ch('-');
    o.add(",%d", int(v.trial));
    o.ch('\n');
    if (g_tbytes + o.n > kMaxBytes) {
        std::fputs("# size limit reached: logging stopped\n", g_tfile);
        std::fclose(g_tfile);
        g_tfile = nullptr;
        return;
    }
    std::fwrite(line, 1, o.n, g_tfile);
    g_tbytes += o.n;
}

void writer()
{
    for (;;) {
        {
            std::unique_lock<std::mutex> lk(g_lock);
            g_wake.wait_for(lk, std::chrono::milliseconds(500));
            g_drain.swap(g_fill);
            g_tdrain.swap(g_tfill);
        }
        for (const Record &r : g_drain)
            write_record(r);
        g_drain.clear();
        if (g_file)
            std::fflush(g_file);
        for (const TowerRec &r : g_tdrain)
            write_tower(r);
        g_tdrain.clear();
        if (g_tfile)
            std::fflush(g_tfile);
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
    // the timing tower's companion log, same stamp (tools/ingame/analyze_diag.py reads both)
    g_tpath = dir + "\\tower_" + stamp + ".csv";
    g_tfile = _wfopen(widen(g_tpath).c_str(), L"wb");
    if (g_tfile) {
        g_tbytes = std::fwrite(kTowerHeader, 1, std::strlen(kTowerHeader), g_tfile);
        g_tfill.reserve(kTowerBatch);
        g_tdrain.reserve(kTowerBatch);
    }
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

void record_tower(const TowerRec &r)
{
    if (!g_tfile)
        return;
    std::unique_lock<std::mutex> lk(g_lock, std::try_to_lock);
    if (!lk.owns_lock() || g_tfill.size() >= kTowerBatch) {
        g_tdropped.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    g_tfill.push_back(r);
}

const char *path_utf8() { return g_path.c_str(); }

}
