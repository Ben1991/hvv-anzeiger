// Drawing adapter for native protocol tests and recorded firmware renders.
#pragma once
#include <ArduinoJson.h>
#include <cassert>
#include <string>
#include <vector>

namespace esphome {
struct Color {
  int r, g, b;
  Color(int r = 0, int g = 0, int b = 0) : r(r), g(g), b(b) {}
  static const Color BLACK;
};
inline const Color Color::BLACK{};
namespace font {
struct Font {
  int size = 16;
  bool bold = false;
  JsonObject metrics;
  void measure(const char *text, int *width, int *x, int *baseline, int *height) {
    *x = 0; *baseline = size; *height = size;
    *width = 0;
    // UTF-8 codepoints, with actual font advances supplied by the visual runner.
    for (const char *p = text; *p;) {
      const char *start = p++;
      while (*p && (static_cast<unsigned char>(*p) & 0xc0) == 0x80) ++p;
      const std::string glyph(start, p - start);
      *width += metrics.isNull() ? size / 2 : metrics[glyph].as<int>();
    }
  }
};
}
namespace display {
enum class TextAlign { TOP_CENTER, TOP_RIGHT };
struct Display {
  std::vector<std::string> texts;
  JsonDocument operations;
  int width = 320, height = 240;
  int get_width() const { return width; }
  int get_height() const { return height; }
  JsonObject op(const char *kind, Color c) {
    auto o = operations.as<JsonArray>().add<JsonObject>();
    o["kind"] = kind;
    o["color"].add(c.r); o["color"].add(c.g); o["color"].add(c.b);
    return o;
  }
  void fill(Color c) {
    texts.clear(); operations.to<JsonArray>();
    auto o = op("fill", c); (void)o;
  }
  void filled_rectangle(int x, int y, int w, int h, Color c) {
    auto o = op("rectangle", c); o["x"] = x; o["y"] = y; o["w"] = w; o["h"] = h;
  }
  void filled_triangle(int x, int y, int x2, int y2, int x3, int y3, Color c) {
    auto o = op("triangle", c);
    for (int v : {x, y, x2, y2, x3, y3}) o["points"].add(v);
  }
  void filled_circle(int x, int y, int radius, Color c) {
    auto o = op("circle", c); o["x"] = x; o["y"] = y; o["radius"] = radius;
  }
  void horizontal_line(int x, int y, int w, Color c) { filled_rectangle(x, y, w, 1, c); }
  void start_clipping(int left, int top, int right, int bottom) {
    assert(right > left && bottom > top);
    auto o = op("clip", {});
    for (int v : {left, top, right, bottom}) o["box"].add(v);
  }
  void end_clipping() { op("unclip", {}); }
  void print(int x, int y, font::Font *f, Color c, const char *s) {
    texts.emplace_back(s);
    auto o = op("text", c); o["x"] = x; o["y"] = y;
    o["size"] = f->size; o["bold"] = f->bold; o["text"] = s;
  }
  void print(int x, int y, font::Font *f, Color c, TextAlign align, const char *s) {
    int width, offset, baseline, height;
    f->measure(s, &width, &offset, &baseline, &height);
    print(x - (align == TextAlign::TOP_CENTER ? width / 2 : width), y, f, c, s);
  }
};
}
}
