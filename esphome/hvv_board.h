#pragma once

#include "esphome.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

namespace hvv {
struct Row {
  std::string line, destination, station, time, shape;
  int64_t departure = 0;
  int delay = 0;
  bool cancelled = false;
  uint32_t background = 0, foreground = 0xffffff;
};

// Fonts live in flash; the registry contains only pointers, never a framebuffer.
struct Fonts {
  std::array<esphome::font::Font *, 26> regular{}, bold{};
  esphome::font::Font *get(int size, bool strong,
                           esphome::font::Font *fallback) const {
    auto *font = (strong ? bold : regular)[size];
    return font ? font : fallback;
  }
};
inline Fonts board_fonts;

class Board {
 public:
  const std::string &state() const { return state_; }
  size_t departure_count() const { return count_; }
  const Row *departure(size_t index) const {
    return index < count_ ? &rows_[index] : nullptr;
  }

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
          r.time.size() != 5 || r.shape.size() > 16) return false;
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

  void tick(uint32_t now, int64_t clock_epoch, const char *local_clock = nullptr) {
    if (clock_epoch > 0) {
      clock_epoch_ = clock_epoch;
      clock_tick_ = now;
      if (local_clock) clock_label_ = local_clock;
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

  void format_time(const Row &row, uint32_t now, char *buffer, size_t size) const {
    if (size == 0) return;
    if (row.cancelled) {
      std::snprintf(buffer, size, "%s", "AUS");
      return;
    }
    if (mode_ == "departure_time") {
      std::snprintf(buffer, size, "%s", row.time.c_str());
      return;
    }
    const auto seconds = row.departure - (generated_ + age(now));
    const int minutes = static_cast<int>(std::max<int64_t>(0, (seconds + 59) / 60));
    if (minutes == 0) {
      std::snprintf(buffer, size, "%s", "sofort");
      return;
    }
    const bool show_unit = unit_ != "none";
    std::snprintf(buffer, size, "%d%s%s", minutes, show_unit ? " " : "",
                  show_unit ? unit_.c_str() : "");
  }

  void draw(esphome::display::Display &it, esphome::font::Font *font,
            esphome::font::Font *small, uint32_t now, bool enabled) const {
    using namespace esphome;
    const Color white(255, 255, 255), muted(185, 192, 199), red(213, 43, 47);
    it.fill(Color(9, 11, 13));
    if (!enabled || night(now)) { it.fill(Color::BLACK); return; }
    const int w = it.get_width(), h = it.get_height();
    auto face = [&](int size, bool bold = false) {
      return board_fonts.get(size, bold, size <= 12 ? small : font);
    };
    auto width = [](font::Font *f, const std::string &text) {
      int w, x, baseline, height;
      f->measure(text.c_str(), &w, &x, &baseline, &height);
      return w;
    };
    auto fit = [&](const std::string &text, int maximum, int size, int minimum,
                   bool bold = false) {
      while (size > minimum && width(face(size, bold), text) > maximum) --size;
      return size;
    };
    auto shorten = [&](std::string text, int maximum, font::Font *f) {
      if (width(f, text) <= maximum) return text;
      while (!text.empty()) {
        size_t end = text.size() - 1;
        while (end && (static_cast<unsigned char>(text[end]) & 0xc0) == 0x80) --end;
        text.resize(end);  // Remove an entire UTF-8 codepoint, never half an umlaut.
        if (width(f, text + "…") <= maximum) return text + "…";
      }
      return std::string("…");
    };
    it.filled_rectangle(0, 0, w, 42, Color(0, 60, 120));
    it.filled_rectangle(0, 38, std::min(w, 211), 5, Color(29, 117, 184));
    const int title_space = std::max(1, w - 30 - width(face(25, true), clock_label_));
    it.print(10, 8, face(fit("HVV  ABFAHRT", title_space, 19, 10, true), true),
             white, "HVV  ABFAHRT");
    it.print(w - 9, 5, face(25, true), white, display::TextAlign::TOP_RIGHT,
             clock_label_.c_str());
    if (!generated_ || !clock_epoch_ || expired(now)) {
      const char *text = !generated_ ? "Warte auf Abfahrtsdaten" :
          !clock_epoch_ ? "Warte auf Systemzeit" : "Letzter Stand zu alt";
      auto *f = face(fit(text, w - 16, 22, 16, true), true);
      it.print(w / 2, std::min(102, h - 30), f, muted,
               display::TextAlign::TOP_CENTER, text);
      return;
    }
    const int shown = std::min<int>(count_, std::min(5, (h - 42) / 39));
    for (int i = 0; i < shown; ++i) {
      const Row &r = rows_[i];
      const int y = 42 + i * 39;
      const Color bg((r.background >> 16) & 255, (r.background >> 8) & 255, r.background & 255);
      const Color fg((r.foreground >> 16) & 255, (r.foreground >> 8) & 255, r.foreground & 255);
      if (r.shape == "circle") {
        // True ellipse, including on drivers without a native ellipse primitive.
        for (int dy = 0; dy <= 27; ++dy) {
          const double v = (dy - 13.5) / 13.5;
          const int radius = static_cast<int>(29 * std::sqrt(std::max(0.0, 1 - v * v)));
          it.horizontal_line(38 - radius, y + 6 + dy, 2 * radius + 1, bg);
        }
      } else if (r.shape == "pointed") {
        it.filled_triangle(17, y + 6, 67, y + 6, 59, y + 33, bg);
        it.filled_triangle(17, y + 6, 59, y + 33, 9, y + 33, bg);
      } else if (r.shape == "rounded") {
        it.filled_rectangle(14, y + 6, 49, 28, bg);
        it.filled_rectangle(9, y + 11, 59, 18, bg);
        for (int x : {14, 62}) for (int yy : {y + 11, y + 28})
          it.filled_circle(x, yy, 5, bg);
      } else {
        it.filled_rectangle(9, y + 6, 59, 28, bg);
      }
      const int logo_size = fit(r.line, 48, r.line.size() <= 3 ? 18 : 15, 10, true);
      auto *logo = face(logo_size, true);
      const auto logo_text = shorten(r.line, 48, logo);
      // Font coordinates use the ascender as origin, just like Pillow's default.
      it.start_clipping(9, y + 6, 68, y + 34);
      it.print(38, y + 6 + (27 - logo_size * 3 / 4) / 2 - 2,
               logo, fg, display::TextAlign::TOP_CENTER, logo_text.c_str());
      it.end_clipping();
      const bool station = !r.station.empty();
      if (station) {
        const Color station_blue(0, 60, 120);
        it.filled_rectangle(78, y + 10, 13, 18, station_blue);
        it.filled_rectangle(75, y + 13, 19, 12, station_blue);
        for (int xx : {78, 90}) for (int yy : {y + 13, y + 24})
          it.filled_circle(xx, yy, 3, station_blue);
        auto *sf = face(10, true);
        const auto label = shorten(r.station, 16, sf);
        it.print(84, y + 14, sf, white, display::TextAlign::TOP_CENTER, label.c_str());
      }
      char time[16];
      format_time(r, now, time, sizeof(time));
      auto *tf = face(r.cancelled ? 18 : 17, true);
      const int x = station ? 99 : 76;
      const int available = std::max(1, std::min(station ? 143 : 164,
                                               w - 12 - width(tf, time) - x));
      auto *df = face(fit(r.destination, available, 18, 13));
      const auto destination = shorten(r.destination, available, df);
      it.start_clipping(x, y, std::max(x + 1, w - 8 - width(tf, time)), y + 37);
      it.print(x, y + 7, df, white, destination.c_str());
      it.end_clipping();
      it.print(w - 8, y + 5, tf, r.cancelled ? red : white,
               display::TextAlign::TOP_RIGHT, time);
      // departure_epoch/time already include the forecast; never add delay twice.
      if (mode_ == "countdown")
        it.print(w - 8, y + 25, face(10), muted,
                 display::TextAlign::TOP_RIGHT, r.time.c_str());
      it.horizontal_line(8, y + 38, w - 16, Color(72, 81, 90));
    }
    if (!shown) {
      const char *message = "Keine passenden Abfahrten";
      it.print(w / 2, std::min(102, h - 30), face(fit(message, w - 24, 22, 16, true), true),
               white, display::TextAlign::TOP_CENTER, message);
      if (h >= 160) it.print(42, 136, face(14), muted, "Nächster Versuch automatisch");
    }
    if (has_problem(now)) {
      it.filled_rectangle(0, h - 14, w, 14, red);
      const char *status = static_cast<uint32_t>(now - received_) > 45000 ?
          "Verbindung fehlt – letzter Stand" : "Veraltete Daten – letzter Stand";
      it.print(7, h - 14, face(fit(status, w - 14, 10, 8, true), true), white, status);
    }
  }

 private:
  std::array<Row, 5> rows_{};
  size_t count_ = 0;
  std::string state_, mode_, unit_, clock_label_ = "--:--";
  int64_t generated_ = 0, clock_epoch_ = 0;
  uint32_t received_ = 0, clock_tick_ = 0;
  int ttl_ = 0;
};
}  // namespace hvv

inline hvv::Board hvv_board;
