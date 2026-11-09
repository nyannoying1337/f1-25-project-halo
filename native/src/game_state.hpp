// The HUD's only view of the game: validated, normalised state read inside the F1 25 process.
//
// Nothing here comes from UDP telemetry, a socket, shared memory or another process. A provider reads
// the game's own objects (see game_state_f1_25.cpp) and fills a GameState once per frame. Every field
// group carries its own `ok` flag: false means "the game state could not be read or failed validation
// this frame", and the HUD must then show nothing for it rather than a made-up value.
//
// Field provenance (source object, offset, type, unit, range, evidence, confidence) is documented in
// docs/internal-state/fields.md. States the game is not known to expose (Active Aero engagement, Overtake
// Mode eligibility, the camera) are not invented here: the halo binds the game's own HUD view model for
// those (see tools/native/halo_native.py), or leaves them out.
#pragma once
#include <cstdint>

namespace halo::gs {

constexpr int kMaxCars = 32;

struct SessionState {
    bool active = false;        // the game's vehicle table holds at least one valid car
    uint32_t generation = 0;    // bumps whenever the player car object or the set of cars changes
    uint32_t cars = 0;          // valid cars in the vehicle table
    bool type_ok = false;
    uint32_t type = 0;          // 1..4 practice, 5..9 qualifying, 10..14 sprint shootout, 15..17 race
    bool track_ok = false;
    float track_length_m = 0;   // metres
    bool track_name_ok = false;
    char track_name[48]{};      // the game's internal name of the loaded track (NUL-terminated)

    bool race() const { return type_ok && type >= 15 && type <= 17; }
};

struct VehicleState {
    bool ok = false;            // the player's car was found and validated
    uint8_t id = 0;             // vehicle id (index into the game's vehicle table)
    bool ai_driving = false;    // the AI drives the player's car right now (e.g. pit entry auto-drive)
    bool speed_ok = false;
    float speed_mps = 0;        // |velocity|, m/s
    bool gear_ok = false;
    int gear = 0;               // -1 reverse, 0 neutral, 1..9
    bool accel_ok = false;
    float g_lat = 0, g_long = 0; // g
    bool steer_ok = false;
    float steer = 0;            // -1 full left .. +1 full right (normalised to the car's lock)
};

struct PowerUnitState {
    bool rpm_ok = false;
    float rpm = 0;              // engine speed, rev/min
    bool limiter_ok = false;
    float limiter_rpm = 0;      // rev limiter in force, rev/min
};

struct EnergyState {
    bool store_ok = false;
    float store_j = 0;          // energy in the battery, J
    bool capacity_ok = false;
    float capacity_j = 0;       // battery capacity, J (4 MJ)
    bool power_ok = false;
    float harvest_k_w = 0;      // MGU-K harvest power, W (>= 0)
    float harvest_h_w = 0;      // MGU-H harvest power, W (2026: no MGU-H, expect 0)
    float deploy_w = 0;         // MGU-K deploy power, W (>= 0)
    bool max_deploy_ok = false;
    float max_deploy_w = 0;     // the car's MGU-K deploy limit, W (2026: 350 kW)
    bool mode_ok = false;
    int mode = 0;               // ERS mode the driver selected: 0 None, 1 Medium, 2 Overtake, 3 Hotlap
    bool lap_ok = false;
    float harvested_lap_j = 0;  // MGU-K energy harvested this lap, J
    float deployed_lap_j = 0;   // energy deployed this lap, J
    float harvest_limit_lap_j = 0; // per-lap harvest limit in force, J
};

struct DriverInputState {
    bool ok = false;
    float throttle = 0;         // 0..1, as the car applies it (after assists)
    float brake = 0;            // 0..1
};

struct ProgressState {
    bool ok = false;
    float total_m = 0;          // distance covered in the session, m (the game's own running-order distance)
    float lap_m = 0;            // distance into the current lap, m (0 .. track length)
    int lap = 0;                // the game's lap counter for the car
};

// Not exposed by any verified in-process source yet: kept explicit so nothing pretends otherwise.
struct AeroState {
    bool known = false;         // Active Aero engagement comes from the game's HUD view model (is_xm_active)
};

struct CameraState {
    bool known = false;         // the active camera is not read; the HUD is placed by the game's OSD editor
};

// The field: road order by the game's own distance-covered counter (cars on track only), and the session
// classification the game's own UI shows (#session.cars.car<vid>.position).
struct FieldState {
    bool ok = false;
    int n = 0;
    uint8_t id[kMaxCars]{};     // vehicle ids in road order, leader first
    float total_m[kMaxCars]{};
    int player_rank = -1;       // index into id[] of the player's car
    // classification: pos[vehicle id] = 1..N, 0 = not read. classified: the player's position was read and no
    // two cars share one. Practice and qualifying: the session's order (L2: comparator not decoded); race:
    // race order; the formation lap's UI shows the grid instead; time trial: never updated by the game.
    bool classified = false;
    uint8_t pos[kMaxCars]{};
};

struct GameState {
    double time = 0;            // seconds, the HUD's own monotonic clock
    uint64_t frame = 0;
    bool compatible = false;    // the running game is the build this provider was verified on
    SessionState session;
    VehicleState vehicle;
    PowerUnitState power_unit;
    EnergyState energy;
    DriverInputState input;
    ProgressState progress;
    AeroState aero;
    CameraState camera;
    FieldState field;
};

class IGameStateProvider {
public:
    virtual ~IGameStateProvider() = default;
    // Short description for the log, e.g. "F1 25 d873a1c8 (in-process memory)".
    virtual const char *describe() const = 0;
    // The provider recognised the running game build and resolved what it needs.
    virtual bool compatible() const = 0;
    // Read the current frame into out. Never throws, never dereferences an unvalidated pointer.
    virtual void sample(double now, GameState &out) = 0;
};

}
