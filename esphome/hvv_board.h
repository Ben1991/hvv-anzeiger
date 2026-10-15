#pragma once

#include "esphome.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <string>

namespace hvv {
struct Row {
  std::string line, destination, station, time, shape;
  int64_t departure = 0;
  int delay = 0;
  bool cancelled = false;
  uint32_t background = 0, foreground = 0xffffff;
};

class Board {
 public:
  bool accept(JsonObject root, uint32_t received) {
    if (!root["schema_version"].is<int>() || root["schema_version"].as<int>() != 1 ||
        !root["generated_at"].is<int64_t>() || !root["state"].is<const char *>() ||
        !root["valid_for_seconds"].is<int>() || !root["departures"].is<JsonArray>()) return false;
    const int64_t generated = root["generated_at"].as<int64_t>();
    const int ttl = root["valid_for_seconds"].as<int>();
    const std::string state = root["state"].as<std::string>();
    const std::string mode = root["time_mode"] | "";
    const std::string unit = root["minute_unit"] | "";
    const int64_t wall = clock_epoch_ ? clock_epoch_ +
        static_cast<uint32_t>(received - clock_tick_) / 1000 : 0;
    const bool previous_from_future = wall && generated_ > wall + 60;
    if (generated <= 0 || (wall && generated > wall + 60) ||
        (generated <= generated_ && !previous_from_future) || ttl < 0 || ttl > 86400 ||
        (state != "ok" && state != "stale" && state != "night" &&
         state != "expired" && state != "unavailable") ||
        (mode != "countdown" && mode != "departure_time") ||
        (unit != "min" && unit != "m" && unit != "none")) return false;
    auto rows = root["departures"].as<JsonArray>();
    if (rows.size() > 5) return false;
    std::array<Row, 5> next{};
    size_t count = 0;
    for (JsonObject item : rows) {
      if (!item["line"].is<const char *>() || !item["destination"].is<const char *>() ||
          !item["station"].is<const char *>() || !item["time"].is<const char *>() ||
          !item["departure_epoch"].is<int64_t>() || !item["cancelled"].is<bool>() ||
          !item["delay_seconds"].is<int>() || !item["background"].is<uint32_t>() ||
          !item["foreground"].is<uint32_t>() || !item["shape"].is<const char *>()) return false;
      Row &r = next[count++];
      r.line = item["line"].as<std::string>();
      r.destination = item["destination"].as<std::string>();
      r.station = item["station"].as<std::string>();
      r.time = item["time"].as<std::string>();
      r.shape = item["shape"].as<std::string>();
      if (r.line.size() > 48 || r.destination.size() > 256 || r.station.size() > 48 ||
          r.time.size() != 5) return false;
      r.departure = item["departure_epoch"].as<int64_t>();
      r.cancelled = item["cancelled"].as<bool>();
      r.delay = item["delay_seconds"].as<int>();
      r.background = item["background"].as<uint32_t>();
      r.foreground = item["foreground"].as<uint32_t>();
    }
    // Commit atomically only after validating every row. Duplicate/replayed
    // snapshots never refresh the lease, including after an HA reconnect.
    rows_ = std::move(next);
    count_ = count;
    state_ = state;
    mode_ = mode;
    unit_ = unit;
    generated_ = generated;
    ttl_ = ttl;
    received_ = received;
    return true;
  }

  void tick(uint32_t now, int64_t clock_epoch) {
    if (clock_epoch > 0) {
      clock_epoch_ = clock_epoch;
      clock_tick_ = now;
    }
  }

  int64_t age(uint32_t now) const {
    const int64_t elapsed = static_cast<uint32_t>(now - received_) / 1000;
    if (!clock_epoch_) return elapsed;
    const int64_t wall = clock_epoch_ + static_cast<uint32_t>(now - clock_tick_) / 1000;
    // A large future timestamp means the backend clock is untrustworthy.
    if (generated_ > wall + 60) return 86401;
    return std::max(elapsed, wall - generated_);
  }

  bool expired(uint32_t now) const { return !generated_ || age(now) >= ttl_; }
  bool night(uint32_t now) const { return state_ == "night" && !expired(now); }
  bool has_problem(uint32_t now) const {
    return !clock_epoch_ || expired(now) ||
           (state_ != "ok" && state_ != "night") ||
           static_cast<uint32_t>(now - received_) > 45000;
  }

  std::string time_text(const Row &row, uint32_t now) const {
    if (row.cancelled) return "AUS";
    if (mode_ == "departure_time") return row.time;
    const auto seconds = row.departure - (generated_ + age(now));
    const int minutes = static_cast<int>(std::max<int64_t>(0, (seconds + 59) / 60));
    if (minutes == 0) return "sofort";
    return std::to_string(minutes) + (unit_ == "none" ? "" : " " + unit_);
  }

  void draw(esphome::display::Display &it, esphome::font::Font *font,
            esphome::font::Font *small, uint32_t now, bool enabled) const {
    using namespace esphome;
    const Color white(255, 255, 255), muted(185, 192, 199), red(213, 43, 47);
    it.fill(Color::BLACK);
    if (!enabled || night(now)) return;
    const int w = it.get_width(), h = it.get_height();
    it.filled_rectangle(0, 0, w, 25, Color(0, 60, 120));
    it.print(5, 3, font, white, "HVV Abfahrten");
    if (!generated_ || !clock_epoch_ || expired(now)) {
      const char *text = !generated_ ? "Warte auf Abfahrtsdaten" :
          !clock_epoch_ ? "Warte auf Systemzeit" : "Letzter Stand zu alt";
      it.print(5, 40, font, muted, text);
      it.print(5, h - 18, small, muted, "Home Assistant / WLAN prüfen");
      return;
    }
    const int shown = std::min<int>(count_, std::min(5, (h - 47) / 36));
    const int row_height = shown > 0 ? (h - 47) / shown : 36;
    for (int i = 0; i < shown; ++i) {
      const Row &r = rows_[i];
      const int y = 28 + i * row_height;
      const Color bg((r.background >> 16) & 255, (r.background >> 8) & 255, r.background & 255);
      const Color fg((r.foreground >> 16) & 255, (r.foreground >> 8) & 255, r.foreground & 255);
      if (r.shape == "circle" || r.shape == "rounded") {
        it.filled_rectangle(16, y + 1, 28, 26, bg);
        it.filled_circle(16, y + 14, 13, bg);
        it.filled_circle(44, y + 14, 13, bg);
      } else if (r.shape == "pointed") {
        it.filled_rectangle(10, y + 1, 40, 26, bg);
        it.filled_triangle(3, y + 27, 10, y + 1, 10, y + 27, bg);
        it.filled_triangle(50, y + 1, 57, y + 1, 50, y + 27, bg);
      } else {
        it.filled_rectangle(3, y + 1, 54, 26, bg);
      }
      it.start_clipping(3, y, 57, y + 29);
      it.print(30, y + 4, font, fg, display::TextAlign::TOP_CENTER, r.line.c_str());
      it.end_clipping();
      it.start_clipping(62, y, w - 83, y + 20);
      it.print(62, y, font, white, r.destination.c_str());
      it.end_clipping();
      std::string detail = r.station.empty() ? r.time : r.station + "  " + r.time;
      if (r.delay) detail += "  " + std::string(r.delay > 0 ? "+" : "") +
          std::to_string(static_cast<int>(std::ceil(r.delay / 60.0))) + " min";
      it.start_clipping(62, y + 19, w - 83, y + 35);
      it.print(62, y + 19, small, muted, detail.c_str());
      it.end_clipping();
      it.print(w - 3, y + 3, font, r.cancelled ? red : white,
               display::TextAlign::TOP_RIGHT, time_text(r, now).c_str());
      it.horizontal_line(3, y + row_height - 2, w - 6, Color(48, 55, 62));
    }
    if (!shown) it.print(5, 40, font, muted, "Keine passenden Abfahrten");
    const char *status = static_cast<uint32_t>(now - received_) > 45000 ?
        "Verbindung fehlt – letzter Stand" : state_ == "stale" ?
        "Veraltete Daten – letzter Stand" : "Echtzeitprognose";
    it.print(5, h - 17, small, has_problem(now) ? red : muted, status);
  }

 private:
  std::array<Row, 5> rows_{};
  size_t count_ = 0;
  std::string state_, mode_, unit_;
  int64_t generated_ = 0, clock_epoch_ = 0;
  uint32_t received_ = 0, clock_tick_ = 0;
  int ttl_ = 0;
};
}  // namespace hvv

inline hvv::Board hvv_board;
