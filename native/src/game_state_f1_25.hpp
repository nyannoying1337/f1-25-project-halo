// F1 25 (Steam build sha256 d873a1c8…, PE timestamp 1789118616) in-process game-state provider.
#pragma once
#include "game_state.hpp"

#include <cstdint>
#include <memory>

namespace halo::gs {

// Addresses of the game globals the provider reads. In the game they come from Swofty's signature-resolved
// bindings (swofty::api->resolve); the host tests point them at fake objects.
struct F1_25Symbols {
    uintptr_t vehicle_table = 0; // g_Sess_VehicleTable: void *[], indexed by vehicle id
    uintptr_t vehicle_count = 0; // g_Sess_VehicleCount: u32
    uintptr_t game_manager = 0;  // g_Game_Manager: void *
    uintptr_t track_length = 0;  // g_Game_TrackLength: float, metres
    uintptr_t session_type = 0;  // g_Sess_TyreRulesSessionType: u32
    uintptr_t track_world = 0;   // unnamed singleton (0x146ce72b8 in this build): [[[it]+0xd0]+0xe8]+0xa0 = track name; optional
    uintptr_t results_key = 0;   // the results system's key in the component registry: the address of a static
                                 // (0x14607f1a0 in this build); optional: without it the rival comes from road order
    // Who drives which car (addresses inside this build's image). Optional: without them the player car comes
    // from the cars' is_ai flags.
    uintptr_t controllers = 0;    // qword global holding the ControllerSystem (0x146096578)
    uintptr_t vt_controllers = 0; // vt_Sess_ControllerSystem (0x1458824a0)
    uintptr_t vt_human = 0;       // vt_Sess_HumanController (0x145882170)
    uintptr_t spectate_key = 0;   // the spectate component's registry key (0x146080ca8); logged only
    // vt_Car_SystemsContainer (0x145c040c8): the vptr of the component container embedded at CarLive+0x380, the
    // car's type identity (CarLive itself has no vtable). Required.
    uintptr_t vt_car_systems = 0;
};

// Table slot status, one character per slot of the vehicle table (validation log column "slots").
enum SlotStatus : char {
    kSlotCar = '.',        // a CarLive with an ERS system (a competitor)
    kSlotNoErs = 's',      // a CarLive without ERS (the safety car)
    kSlotNull = 'n',       // null or misaligned pointer
    kSlotUnreadable = 'u', // the car's header could not be copied
    kSlotType = 't',       // not a CarLive: the container vptr or the lock self-pointer does not match
    kSlotId = 'i',         // a CarLive whose vehicle id does not read back as its slot index
};

// Raw values behind the normalised state, for the diagnostics log only (never shown by the HUD).
struct F1_25Raw {
    uint32_t is_ai = 0;
    uint8_t input_flags = 0;   // CarLive+0x224
    uint32_t gear_index = 0;   // GearBox+0x680
    float throttle_field = 0;  // CarLive+0x188 before the reverse swap
    float brake_field = 0;     // CarLive+0x190 before the reverse swap
    float engine_rate = 0;     // rad/s
    float vel[3]{};            // m/s, world
    float steer_angle = 0, steer_lock = 0; // rad
    uint8_t ers_flags[4]{};    // CarErs+0x1a60..+0x1a63 (meaning unconfirmed)
    float speed_from_distance = 0; // m/s, d(total distance)/dt over the last sample, 0 when unknown
    uint32_t rejects = 0;      // cars rejected by validation in this frame's scan (+1: the player's car failed
                               // re-validation after the reads)
    uint8_t humans = 0;        // cars read as human-driven (is_ai == 0) this frame
    bool progress_link = false; // the player's progress entry links back to the car ([[entry+0x28]+0x58])
    bool results_found = false; // the results system is known (found in the component registry, re-checked each scan)
    int8_t ctrl_hits = -1;     // cars with a local HumanController (ControllerSystem, last scan); -1 not readable
    int8_t ctrl_vid = -1;      // that car when exactly one
    int8_t isai_vid = -1;      // the car the is_ai rule picks (cross-check and fallback)
    int8_t spect_vid = -1;     // the car the game spectates (logged only), -1 none
    uint8_t player_source = 0; // 0 none, 2 ControllerSystem, 3 is_ai rule
    bool scanned = false;      // this frame re-read the whole car table (on a change, else at 10 Hz)
    uint8_t vcount = 0;        // g_Sess_VehicleCount as read this frame (0 when unreadable; > 32 is rejected)
    char slots[kMaxCars + 1]{}; // SlotStatus per table slot from the last scan, NUL-terminated ("" without a table)
    // The check the provider used before 2026-11-09 on the player's car: CarLive+0x0 (the last placement request's
    // tag string, not a vtable) 8-byte aligned and inside the image. 1 pass, 0 fail, -1 no player. Logged only.
    int8_t old_check = -1;
};

class F1_25Provider : public IGameStateProvider {
public:
    struct Impl;
    explicit F1_25Provider(const F1_25Symbols &symbols, bool build_ok);
    ~F1_25Provider() override;
    const char *describe() const override;
    bool compatible() const override;
    void sample(double now, GameState &out) override;
    const F1_25Raw &raw() const;

private:
    std::unique_ptr<Impl> impl_;
};

// The running exe is the build the offsets were verified on (PE timestamp and image size).
bool f1_25_build_matches();
// Resolve the symbols through Swofty's bindings. On failure *missing names the first one that did not resolve.
bool f1_25_resolve(F1_25Symbols &out, const char **missing);

}
