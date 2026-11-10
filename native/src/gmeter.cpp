#include "gmeter.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>

namespace halo {
namespace {

constexpr float kDeg = 57.29577951308232f;

// the median of the first n (1..3) values; of two, their mean
float median(const float *a, int n)
{
    if (n <= 1)
        return a[0];
    if (n == 2)
        return 0.5f * (a[0] + a[1]);
    return std::max(std::min(a[0], a[1]), std::min(std::max(a[0], a[1]), a[2]));
}

bool same_bits(float a, float b)
{
    uint32_t x, y;
    std::memcpy(&x, &a, sizeof x);
    std::memcpy(&y, &b, sizeof y);
    return x == y;
}

} // namespace

void GMeter::reset()
{
    const bool on = v_.on;
    *this = GMeter{};
    v_.on = on;
}

void GMeter::update(bool on, bool ok, float g_lat, float g_long, float dt)
{
    dt = std::max(0.f, dt);
    if (!ok || !std::isfinite(g_lat) || !std::isfinite(g_long)) {
        reset(); // no value, no indicator; the next reading starts afresh
        v_.on = on;
        return;
    }
    v_.on = on;

    // 1. fresh records only: a paused game repeats the same pair bit for bit
    if (!have_last_ || !same_bits(g_lat, last_lat_) || !same_bits(g_long, last_lon_)) {
        have_last_ = true;
        last_lat_ = g_lat;
        last_lon_ = g_long;
        lat_[head_] = g_lat;
        lon_[head_] = g_long;
        head_ = (head_ + 1) % 3;
        n_ = std::min(n_ + 1, 3);
    }
    // 2. the median of the last 3 fresh records, per component
    const float m_lat = median(lat_, n_), m_lon = median(lon_, n_);
    // 3. ease each component
    if (!primed_) {
        primed_ = true;
        e_lat_ = m_lat;
        e_lon_ = m_lon;
    } else {
        const float k = std::exp(-dt / kTau);
        e_lat_ = m_lat + (e_lat_ - m_lat) * k;
        e_lon_ = m_lon + (e_lon_ - m_lon) * k;
    }
    // 4. magnitude and direction from the eased components
    const float m = std::hypot(e_lat_, e_lon_);
    float dir = std::atan2(e_lon_, e_lat_) * kDeg;
    if (dir < 0)
        dir += 360.f;
    if (dir >= 360.f)
        dir = 0;
    v_.ok = true;
    v_.g = m;
    v_.tenths = std::clamp(int(std::floor(m * 10.f + 0.5f)), 0, 99);
    v_.dir = dir;

    // indicator: whole 45-degree segments and the nearest axis (halo.js gView: JS rounding, halves round up)
    v_.indicator = m >= kOn;
    v_.wide = v_.indicator && (v_.wide ? m >= kNarrow : m >= kWide);
    v_.segs = 0;
    v_.axis = -1;
    if (v_.indicator) {
        const float s = dir / 45.f;
        const int k = v_.wide ? int(std::floor(s + 0.5f)) - 1 : int(std::floor(s));
        const int count = v_.wide ? 3 : 2;
        for (int i = 0; i < count; ++i)
            v_.segs |= uint8_t(1u << (((k + i) % 8 + 8) % 8));
        v_.axis = int(std::floor(dir / 90.f + 0.5f)) % 4;
    }
    v_.red_bar = v_.indicator && m >= kRedBar;

    // the digits' red flash: once per rise to 4.3, for 1.4 s
    flash_ = std::max(0.f, flash_ - dt);
    if (armed_ && v_.tenths >= kFlashTenths) {
        flash_ = kFlashS;
        armed_ = false;
    } else if (!armed_ && v_.tenths < kRearmTenths)
        armed_ = true;
    v_.red_digits = flash_ > 0;
}

}
