#include "../../esphome/hvv_board.h"
#include <fstream>
#include <iostream>
int main(int argc, char **argv) {
  assert(argc == 2);
  std::ifstream input(argv[1]);
  JsonDocument doc;
  assert(!deserializeJson(doc, input));
  std::array<esphome::font::Font, 52> fonts;
  for (int bold = 0; bold < 2; ++bold) for (int size = 8; size <= 25; ++size) {
    auto &f = fonts[bold * 26 + size];
    f.size = size; f.bold = bold;
    f.metrics = doc["metrics"][std::to_string(bold) + ":" + std::to_string(size)].as<JsonObject>();
    (bold ? hvv::board_fonts.bold : hvv::board_fonts.regular)[size] = &f;
  }
  hvv::Board board;
  const auto epoch = doc["payload"]["generated_at"].as<int64_t>();
  if (!doc["no_clock"].as<bool>()) board.tick(0, epoch, doc["clock"] | "12:08");
  if (!doc["no_data"].as<bool>()) assert(board.accept(doc["payload"].as<JsonObject>(), 0));
  esphome::display::Display display;
  board.draw(display, &fonts[18], &fonts[10], doc["elapsed"] | 0, !(doc["disabled"] | false));
  serializeJson(display.operations, std::cout);
}
