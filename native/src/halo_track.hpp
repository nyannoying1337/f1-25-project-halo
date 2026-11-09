// Turn numbers for any track.
// Stock tracks use the official F1 corner list (halo_corners.hpp), picked by the game's internal track name
// (or, without one, by a track length no other list is close to) and only when the length agrees.
// Every track also learns its centre line from the cars' world positions (5 m bins along the lap). Once
// the lap is covered, the learned line checks the official list (turn directions must agree) and snaps
// each official turn to the apex it finds nearby; tracks without a usable list (reverse layouts, new or
// modded tracks) get turns detected from the line's curvature, numbered from the start line.
#pragma once
#include <cstdint>
#include <vector>

namespace halo {

class Corners {
public:
    // name: the game's internal track name (may be empty); length_m: the game's track length.
    void reset(const char *name, float length_m);
    // Index into kTracks for this name/length, or -1 (no list, ambiguous length, reverse layout ...).
    static int official_for(const char *name, float length_m);
    int track() const { return track_; }
    float length() const { return length_; }

    // One position sample for a car on track (not in the pit lane). x, z: world horizontal plane.
    void feed(float lap_distance, float x, float z);
    // Evidence for which way round the world's horizontal axes are: the sign of the planar cross product
    // velocity x acceleration while the driver steers (steer < 0 = left).
    void vote(float cross, float steer);
    // +1 when a positive cross product (heading increasing in atan2(z, x)) is a left turn.
    int handedness() const;
    bool handedness_known() const;
    // Rebuild the learned line when the lap is covered. now: seconds, any monotonic clock.
    void update(double now);

    // The turn to show at this lap distance: ahead within 220 m, or just passed (15 m).
    bool current(float lap_distance, char *label, int cap, bool *right) const;
    const char *source() const;

    struct TurnInfo {
        float pos;
        const char *label;
        bool right;
    };
    std::vector<TurnInfo> list() const; // for tests and logs
    float shift() const { return shift_; } // metres the official list was moved to fit the line

private:
    struct Turn {
        float pos; // metres from the line
        char label[6];
        bool left;
    };
    void build();
    float turn_between(float from_m, float to_m) const; // summed heading change (radians)
    bool validate_official();
    void detect();

    int track_ = -1;
    float length_ = 0;
    int official_ = -1; // index into kTracks, or -1
    bool official_ok_ = true;
    int source_ = 0;    // 0 none, 1 official, 2 learned
    std::vector<Turn> turns_;

    // learned centre line
    int nb_ = 0;
    std::vector<double> sx_, sz_;
    std::vector<uint32_t> n_;
    std::vector<float> dth_; // smoothed heading change per bin (radians), at the end of each bin
    int built_ = 0;          // 0 not yet, 1 first build, 2 refined
    double first_ = -1;
    float votes_ = 0;
    int table_hand_ = 0;
    float shift_ = 0;
};

}
