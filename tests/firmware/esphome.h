// Test double for drawing calls only. JSON parsing uses the real ArduinoJson.
#pragma once
#include <ArduinoJson.h>
#include <cassert>
#include <string>
#include <vector>

namespace esphome {
struct Color {
  Color(int = 0, int = 0, int = 0) {}
  static const Color BLACK;
};
inline const Color Color::BLACK{};
namespace font { struct Font {}; }
namespace display {
enum class TextAlign { TOP_CENTER, TOP_RIGHT };
struct Display {
  std::vector<std::string> texts;
  int width = 320, height = 240;
  int get_width() const { return width; }
  int get_height() const { return height; }
  void fill(Color) { texts.clear(); }
  void filled_rectangle(int, int, int, int, Color) {}
  void filled_triangle(int, int, int, int, int, int, Color) {}
  void filled_circle(int, int, int, Color) {}
  void horizontal_line(int, int, int, Color) {}
  void start_clipping(int left, int top, int right, int bottom) {
    assert(right > left && bottom > top);
  }
  void end_clipping() {}
  void print(int, int, font::Font *, Color, const char *s) { texts.emplace_back(s); }
  void print(int, int, font::Font *, Color, TextAlign, const char *s) { texts.emplace_back(s); }
};
}
}
