// The optional G-force meter (setting "g_meter", off by default; docs/gmeter/design.md): the car's horizontal g in
// the halo's centre, in place of the speed, with an indicator drawn toward the force the driver feels.
//
// Input: the game's own chassis acceleration (game_state.hpp: VehicleState g_lat / g_long in g; lat + = the car
// accelerates toward its left, long + = speeding up). It holds no gravity and no vertical axis. Nothing is
// estimated: without a validated reading the meter shows no value and no indicator.
//
// Filter (design §3): only fresh records count (the pair changed; a paused game holds both bit for bit). The median
// of the last 3 fresh records, per component, removes single-record spikes; then each component eases with
// tau 0.05 s. Magnitude and direction come from the eased components.
//
// Indicator (design §4): direction = atan2(g_long, g_lat) on screen (0 right, 90 down, 180 left, 270 up). Shown
// from 0.3 g: the 2 cyan 45-degree segments nearest the direction, or 3 centred on it from 2.0 g until the value
// drops below 1.0 g. A white bar on the nearest axis, and a red bar outside it from 2.3 g. The digits flash red for
// 1.4 s when the shown value first reads 4.3 or more; the flash re-arms once the shown value is below 4.0.
#pragma once
#include <cstdint>

namespace halo {

struct GView {
    bool on = false;          // the setting: the meter replaces the speed centre
    bool ok = false;          // a value is shown (the car's g was read)
    float g = 0;              // magnitude, g (filtered)
    int tenths = 0;           // the value as shown: 0..99 = "0.0".."9.9"
    float dir = 0;            // felt-force direction, degrees in [0, 360): 0 right, 90 down, 180 left, 270 up
    bool indicator = false;   // segments and bars shown (g >= 0.3)
    bool wide = false;        // 3 segments instead of 2
    uint8_t segs = 0;         // bit k: segment k (centred on k * 45 degrees) lit
    int axis = -1;            // the bars' axis: 0 right, 1 down, 2 left, 3 up; -1 without the indicator
    bool red_bar = false;     // the red bar outside the white one (g >= 2.3)
    bool red_digits = false;  // the 4.3 g flash is running
};

class GMeter {
public:
    static constexpr float kOn = 0.3f;        // g: indicator shown from here
    static constexpr float kWide = 2.0f;      // g: 3 segments from here ...
    static constexpr float kNarrow = 1.0f;    // g: ... until the value drops below this
    static constexpr float kRedBar = 2.3f;    // g: red bar
    static constexpr int kFlashTenths = 43;   // shown value 4.3: the digits flash red
    static constexpr int kRearmTenths = 40;   // shown value below 4.0: the next 4.3 flashes again
    static constexpr float kFlashS = 1.4f;    // s
    static constexpr float kTau = 0.05f;      // s, per component

    // on: the setting; ok: the car's g was read and validated this frame; dt: seconds since the previous call
    void update(bool on, bool ok, float g_lat, float g_long, float dt);
    // a new session or another car: nothing carries over
    void reset();
    const GView &view() const { return v_; }

private:
    GView v_;
    float lat_[3]{}, lon_[3]{};  // the last 3 fresh records
    int n_ = 0, head_ = 0;
    bool have_last_ = false;     // last_* hold the previous record
    float last_lat_ = 0, last_lon_ = 0;
    bool primed_ = false;        // the eased components start at the first median, not at 0
    float e_lat_ = 0, e_lon_ = 0;
    float flash_ = 0;            // seconds of red left
    bool armed_ = true;
};

}
