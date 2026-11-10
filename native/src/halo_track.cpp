#include "halo_track.hpp"

#include "halo_corners.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <iterator>
#include <string>

namespace halo {
namespace {

constexpr float kBin = 5.f;           // metres per centre-line bin
constexpr float kPi = 3.14159265358979f;
constexpr float kDeg = kPi / 180.f;
constexpr float kAhead = 220.f;       // show a turn from this far before it ...
constexpr float kBehind = 15.f;       // ... until this far after it
// Turn detection, tuned on the 24 stock circuits' traces (tools: mock_track): turning tighter than a
// 350 m radius, at least 15 degrees in one direction, gaps up to 30 m merged. Finds 317 of the 403
// official turns (the misses are mostly flat-out kinks) with 18 extra.
#ifndef HALO_CURV_R
#define HALO_CURV_R 350.f
#endif
#ifndef HALO_MIN_DEG
#define HALO_MIN_DEG 15
#endif
#ifndef HALO_GAP
#define HALO_GAP 6
#endif
constexpr float kCurv = kBin / HALO_CURV_R; // heading change per bin at that radius
constexpr int kVotesKnown = 30;
constexpr float kMaxCurvature = 0.2f;       // 1/m: a 5 m radius; tighter is a spin, not the track

float wrap_pi(float a)
{
    while (a > kPi)
        a -= 2 * kPi;
    while (a < -kPi)
        a += 2 * kPi;
    return a;
}

float wrap_len(float d, float len) { return std::fmod(std::fmod(d, len) + len, len); }

// Words that identify each listed circuit in the game's internal track names (matched as whole words).
struct Alias {
    int track;
    const char *words[4];
};
constexpr Alias kAliases[] = {
    {0, {"melbourne", "australia", "albert"}}, {2, {"shanghai", "china"}}, {3, {"sakhir", "bahrain"}},
    {4, {"catalunya", "barcelona", "spain"}}, {5, {"monaco", "montecarlo"}}, {6, {"montreal", "canada"}},
    {7, {"silverstone", "britain", "greatbritain"}}, {9, {"hungaroring", "hungary", "budapest"}},
    {10, {"spa", "belgium", "francorchamps"}}, {11, {"monza", "italy"}}, {12, {"singapore", "marinabay"}},
    {13, {"suzuka", "japan"}}, {14, {"abudhabi", "yas", "yasmarina"}}, {15, {"austin", "texas", "cota"}},
    {16, {"interlagos", "brazil", "saopaulo"}}, {17, {"spielberg", "austria", "redbullring"}},
    {19, {"mexico", "mexicocity"}}, {20, {"baku", "azerbaijan"}}, {26, {"zandvoort", "netherlands"}},
    {27, {"imola", "emilia", "emiliaromagna"}}, {29, {"jeddah", "saudi", "saudiarabia"}}, {30, {"miami"}},
    {31, {"vegas", "lasvegas"}}, {32, {"losail", "qatar"}},
};

int index_of(int track)
{
    for (int i = 0; i < int(std::size(kTracks)); ++i)
        if (kTracks[i].track == track)
            return i;
    return -1;
}

} // namespace

int Corners::official_for(const char *name, float len)
{
    // whole words of the lower-cased name; pairs of neighbours too ("abu_dhabi" -> "abudhabi")
    std::vector<std::string> words;
    std::string w;
    for (const char *p = name ? name : ""; ; ++p) {
        const char c = *p;
        if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9'))
            w += c;
        else if (c >= 'A' && c <= 'Z')
            w += char(c - 'A' + 'a');
        else {
            if (!w.empty())
                words.push_back(w);
            w.clear();
            if (!c)
                break;
        }
    }
    const size_t single = words.size();
    for (size_t i = 0; i + 1 < single; ++i)
        words.push_back(words[i] + words[i + 1]);
    for (const std::string &x : words)
        if (x == "reverse" || x == "rev" || x == "short")
            return -1; // reverse and short layouts: the official list does not apply
    int by_name = -1;
    for (const Alias &a : kAliases)
        for (const char *alias : a.words)
            if (alias && std::find(words.begin(), words.end(), std::string(alias)) != words.end())
                by_name = index_of(a.track);
    if (by_name >= 0)
        return len <= 0 || std::fabs(len - kTracks[by_name].length_m) <= 0.03f * kTracks[by_name].length_m ? by_name : -1;
    // no usable name: a length within 1.5 % of exactly one listed circuit and 0.5 % clear of every other one
    int best = -1, near = 0;
    for (int i = 0; i < int(std::size(kTracks)); ++i) {
        const float d = std::fabs(len - kTracks[i].length_m) / kTracks[i].length_m;
        if (d <= 0.015f) {
            ++near;
            best = i;
        } else if (d <= 0.02f)
            ++near;
    }
    return near == 1 ? best : -1;
}

void Corners::reset(const char *name, float length_m)
{
    *this = Corners{};
    length_ = length_m;
    official_ = official_for(name, length_m);
    track_ = official_ >= 0 ? kTracks[official_].track : -1;
    if (official_ >= 0 && length_ <= 0)
        length_ = kTracks[official_].length_m;
    if (length_ > 200) {
        nb_ = int(std::ceil(length_ / kBin));
        sx_.assign(nb_, 0);
        sz_.assign(nb_, 0);
        sk_.assign(nb_, 0);
        n_.assign(nb_, 0);
    }
    if (official_ >= 0) {
        const TrackCorners &T = kTracks[official_];
        for (int i = 0; i < T.count; ++i) {
            const Corner &c = T.corners[i];
            Turn t{};
            t.pos = c.frac * length_;
            if (c.letter)
                std::snprintf(t.label, sizeof t.label, "%d%c", c.number, c.letter);
            else
                std::snprintf(t.label, sizeof t.label, "%d", c.number);
            t.left = c.left;
            turns_.push_back(t);
        }
        source_ = 1;
    }
}

void Corners::feed(float d, float x, float z)
{
    if (nb_ <= 0 || absolute_ || !std::isfinite(d) || !std::isfinite(x) || !std::isfinite(z))
        return;
    int b = std::min(nb_ - 1, int(wrap_len(d, length_) / kBin));
    if (n_[b] >= 4000)
        return;
    sx_[b] += x;
    sz_[b] += z;
    count(b);
}

void Corners::feed_curvature(float d, float k)
{
    if (nb_ <= 0 || !std::isfinite(d) || !std::isfinite(k) || std::fabs(k) > kMaxCurvature)
        return;
    if (!absolute_) {
        if (covered_)
            return; // this track learns from positions
        absolute_ = true;
    }
    int b = std::min(nb_ - 1, int(wrap_len(d, length_) / kBin));
    if (n_[b] >= 4000)
        return;
    sk_[b] += k;
    count(b);
}

void Corners::count(int b)
{
    covered_ += n_[b] == 0;
    solid_ += n_[b] == 3;
    ++n_[b];
}

void Corners::vote(float cross, float steer)
{
    votes_ = std::clamp(votes_ + (cross > 0 ? 1.f : -1.f) * (steer < 0 ? 1.f : -1.f), -400.f, 400.f);
}

bool Corners::handedness_known() const { return absolute_ || std::fabs(votes_) >= kVotesKnown || table_hand_; }

int Corners::handedness() const
{
    if (absolute_)
        return 1; // curvature: + is left
    if (std::fabs(votes_) >= kVotesKnown)
        return votes_ > 0 ? 1 : -1;
    return table_hand_ ? table_hand_ : 1;
}

void Corners::update(double now)
{
    if (nb_ <= 0 || built_ >= 2)
        return;
    if (covered_ && first_ < 0)
        first_ = now;
    float cov = float(covered_) / nb_;
    if (built_ == 0 && (cov >= 0.97f || (cov >= 0.9f && now - first_ > 120))) {
        build();
        built_ = 1;
    } else if (built_ == 1 && solid_ >= 0.95f * nb_) {
        build();
        built_ = 2;
    }
}

void Corners::build()
{
    const int N = nb_;
    std::vector<float> x(N), z(N);
    std::vector<int> known;
    for (int i = 0; i < N; ++i)
        if (n_[i]) {
            x[i] = float((absolute_ ? sk_[i] : sx_[i]) / n_[i]); // curvature: the bin's mean, in x
            z[i] = absolute_ ? 0.f : float(sz_[i] / n_[i]);
            known.push_back(i);
        }
    if (known.size() < 8)
        return;
    // gaps: straight line between the nearest covered bins either side
    for (size_t k = 0; k < known.size(); ++k) {
        int a = known[k], b = known[(k + 1) % known.size()];
        int gap = (b - a + N) % N;
        for (int j = 1; j < gap; ++j) {
            int i = (a + j) % N;
            float t = float(j) / gap;
            x[i] = x[a] + (x[b] - x[a]) * t;
            z[i] = z[a] + (z[b] - z[a]) * t;
        }
    }
    auto smooth = [N](std::vector<float> &v, int r) {
        std::vector<float> o(N);
        for (int i = 0; i < N; ++i) {
            float s = 0;
            for (int j = -r; j <= r; ++j)
                s += v[((i + j) % N + N) % N];
            o[i] = s / (2 * r + 1);
        }
        v.swap(o);
    };
    dth_.assign(N, 0);
    if (absolute_) {
        // the heading change from one bin centre to the next (at the end of each bin, like the position line's)
        for (int i = 0; i < N; ++i)
            dth_[i] = 0.5f * (x[i] + x[(i + 1) % N]) * kBin;
    } else {
        for (int pass = 0; pass < 2; ++pass) {
            smooth(x, 3);
            smooth(z, 3);
        }
        std::vector<float> h(N);
        for (int i = 0; i < N; ++i) {
            int p = (i - 1 + N) % N, q = (i + 1) % N;
            h[i] = std::atan2(z[q] - z[p], x[q] - x[p]);
        }
        for (int i = 0; i < N; ++i)
            dth_[i] = wrap_pi(h[(i + 1) % N] - h[i]);
    }
    smooth(dth_, 2);

    if (official_ >= 0 && official_ok_) {
        official_ok_ = validate_official();
        if (official_ok_)
            return;
    }
    detect();
    source_ = turns_.empty() ? 0 : 2;
}

float Corners::turn_between(float a, float b) const
{
    int i0 = int(std::floor(a / kBin)), i1 = int(std::floor(b / kBin));
    float s = 0;
    for (int i = i0; i <= i1; ++i)
        s += dth_[((i % nb_) + nb_) % nb_];
    return s;
}

// Median distance from each listed turn to the strongest bend of its direction within 60 m (hand: +1 when a
// heading increase is a left turn); 0 when fewer than 5 turns find one.
float Corners::apex_offset(int hand) const
{
    const int reach = int(60 / kBin);
    std::vector<float> deltas;
    for (const Turn &t : turns_) {
        float want = t.left ? float(hand) : float(-hand), best_v = kCurv;
        int centre = int(t.pos / kBin) - 1, best = 0;
        bool found = false;
        for (int j = -reach; j <= reach; ++j) {
            int i = ((centre + j) % nb_ + nb_) % nb_;
            if (want * dth_[i] > best_v) {
                best_v = want * dth_[i];
                best = j;
                found = true;
            }
        }
        if (found)
            deltas.push_back(best * kBin);
    }
    if (deltas.size() < 5)
        return 0;
    std::nth_element(deltas.begin(), deltas.begin() + deltas.size() / 2, deltas.end());
    return deltas[deltas.size() / 2];
}

// The official list fits this track if most turn directions agree with the learned line (under one
// handedness, or the measured one). Then the whole list shifts by the median distance from each turn to
// the strongest apex of its direction within 60 m, when that is 12 m or more: it absorbs a timing line
// that sits apart from the game's, without moving single turns onto a neighbour's apex. Bends learned from
// curvature know left from right, so there the shift comes first and the directions are judged where the
// turns really are (at Bahrain, 33 m on: a +-25 m window around a listed turn would sit on the exit of the
// turn before).
bool Corners::validate_official()
{
    const TrackCorners &T = kTracks[official_];
    for (int i = 0; i < T.count && i < int(turns_.size()); ++i)
        turns_[i].pos = T.corners[i].frac * length_;
    const float pre = absolute_ ? apex_offset(1) : 0.f;
    int counted = 0, match_a = 0; // a: heading increase = left
    for (const Turn &t : turns_) {
        const float p = t.pos + pre;
        float turn = turn_between(p - 25, p + 25);
        if (std::fabs(turn) < 6 * kDeg)
            turn = turn_between(p - 60, p + 60);
        if (std::fabs(turn) < 3 * kDeg)
            continue;
        ++counted;
        match_a += (turn > 0) == t.left;
    }
    shift_ = 0;
    if (counted < 4)
        return true; // nothing to judge by: keep the list
    float ra = float(match_a) / counted, rb = 1 - ra;
    int voted = absolute_ ? 1 : std::fabs(votes_) >= kVotesKnown ? (votes_ > 0 ? 1 : -1) : 0;
    float r = voted > 0 ? ra : voted < 0 ? rb : std::max(ra, rb);
    if (r < 0.7f)
        return false;
    if (!voted && std::max(ra, rb) >= 0.85f)
        table_hand_ = ra >= rb ? 1 : -1;

    const int hand = voted ? voted : (ra >= rb ? 1 : -1);
    const float shift = absolute_ ? pre : apex_offset(hand);
    if (std::fabs(shift) >= 12) {
        for (Turn &t : turns_)
            t.pos = wrap_len(t.pos + shift, length_);
        shift_ = shift;
    }
    return true;
}

// Turns from the learned line: runs of bins turning tighter than a 400 m radius, same direction, with
// gaps under 30 m merged; a run counts when it turns at least 20 degrees. Numbered from the line.
void Corners::detect()
{
    turns_.clear();
    const int N = nb_;
    int start = -1;
    for (int i = 0; i < N && start < 0; ++i)
        if (std::fabs(dth_[i]) <= kCurv)
            start = i;
    if (start < 0)
        return;
    struct Run {
        int sign = 0, s = 0, e = 0;
        float sum = 0, w = 0, wpos = 0;
    };
    std::vector<Run> runs;
    Run cur;
    for (int k = 1; k <= N; ++k) {
        int i = start + k;
        float v = dth_[i % N];
        int sg = v > kCurv ? 1 : v < -kCurv ? -1 : 0;
        if (!sg)
            continue;
        if (cur.sign == sg && i - cur.e <= HALO_GAP) {
            for (int j = cur.e + 1; j <= i; ++j) {
                float vj = dth_[j % N], wj = std::max(0.f, sg * vj);
                cur.sum += vj;
                cur.w += wj;
                cur.wpos += wj * j;
            }
            cur.e = i;
        } else {
            if (cur.sign)
                runs.push_back(cur);
            cur = Run{sg, i, i, v, std::fabs(v), std::fabs(v) * i};
        }
    }
    if (cur.sign)
        runs.push_back(cur);
    for (const Run &r : runs) {
        if (std::fabs(r.sum) < HALO_MIN_DEG * kDeg || r.w <= 0)
            continue;
        Turn t{};
        t.pos = wrap_len((r.wpos / r.w + 1) * kBin, length_);
        t.left = r.sign > 0; // relative: resolved with handedness() when shown
        turns_.push_back(t);
    }
    std::sort(turns_.begin(), turns_.end(), [](const Turn &a, const Turn &b) { return a.pos < b.pos; });
    for (size_t i = 0; i < turns_.size(); ++i)
        std::snprintf(turns_[i].label, sizeof turns_[i].label, "%d", int(i + 1));
}

bool Corners::current(float lap_distance, char *label, int cap, bool *right) const
{
    if (turns_.empty() || length_ <= 0 || !std::isfinite(lap_distance))
        return false;
    float d = wrap_len(lap_distance, length_);
    const Turn *ahead = nullptr, *behind = nullptr;
    float best_a = 1e9f, best_b = 1e9f;
    for (const Turn &t : turns_) {
        float a = wrap_len(t.pos - d, length_), b = wrap_len(d - t.pos, length_);
        if (a < best_a) {
            best_a = a;
            ahead = &t;
        }
        if (b < best_b) {
            best_b = b;
            behind = &t;
        }
    }
    const Turn *t = best_a <= kAhead ? ahead : best_b <= kBehind ? behind : nullptr;
    if (!t)
        return false;
    std::snprintf(label, cap, "%s", t->label);
    bool left = source_ == 2 ? (t->left ? handedness() > 0 : handedness() < 0) : t->left;
    *right = !left;
    return true;
}

const char *Corners::source() const { return source_ == 1 ? "official" : source_ == 2 ? "learned" : "none"; }

std::vector<Corners::TurnInfo> Corners::list() const
{
    std::vector<TurnInfo> v;
    for (const Turn &t : turns_) {
        bool left = source_ == 2 ? (t.left ? handedness() > 0 : handedness() < 0) : t.left;
        v.push_back({t.pos, t.label, !left});
    }
    return v;
}

}
