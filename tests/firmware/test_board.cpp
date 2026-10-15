#include "../../esphome/hvv_board.h"
#include <fstream>
#include <iostream>

static bool contains(const esphome::display::Display &d, const std::string &s) {
  return std::find(d.texts.begin(), d.texts.end(), s) != d.texts.end();
}

int main(int argc, char **argv) {
  assert(argc == 2);
  std::ifstream input(argv[1]);
  JsonDocument source;
  assert(!deserializeJson(source, input));
  auto root = source.as<JsonObject>();
  const int64_t epoch = root["generated_at"].as<int64_t>();
  hvv::Board board;
  esphome::display::Display display;
  esphome::font::Font font;
  assert(board.expired(0));
  assert(board.accept(root, 0));
  board.draw(display, &font, &font, 0, true);
  assert(contains(display, "Warte auf Systemzeit"));
  board.tick(0, epoch);
  board.draw(display, &font, &font, 0, true);
  assert(contains(display, "sofort"));
  assert(contains(display, "AUS"));
  assert(!board.has_problem(0));
  for (const auto &size : {std::pair<int, int>{240, 135}, {320, 240}, {480, 320}}) {
    display.width = size.first;
    display.height = size.second;
    board.draw(display, &font, &font, 0, true);
    assert(contains(display, "sofort"));
    assert(contains(display, "AUS"));
  }
  assert(!board.accept(root, 40000));  // Replayed snapshot cannot renew lease.
  assert(board.has_problem(46000));
  assert(!board.expired(299000));
  assert(board.expired(300000));
  board.draw(display, &font, &font, 300000, true);
  assert(contains(display, "Letzter Stand zu alt"));
  assert(!contains(display, "AUS"));

  // A restart followed by HA's old attribute must not resurrect expired data.
  hvv::Board restarted;
  restarted.tick(0, epoch + 301);
  assert(restarted.accept(root, 0));
  assert(restarted.expired(0));

  // All countdown variants, absolute time, and cancellation priority.
  hvv::Row row;
  row.departure = epoch + 120;
  row.time = "12:02";
  for (const char *unit : {"min", "m", "none"}) {
    hvv::Board b;
    root["minute_unit"] = unit;
    assert(b.accept(root, 0));
    b.tick(0, epoch);
    assert(b.time_text(row, 0) == std::string("2") +
        (std::string(unit) == "none" ? "" : " " + std::string(unit)));
    assert(b.time_text(row, 120000) == "sofort");
  }
  root["time_mode"] = "departure_time";
  hvv::Board absolute;
  assert(absolute.accept(root, 0));
  assert(absolute.time_text(row, 0) == "12:02");
  row.cancelled = true;
  assert(absolute.time_text(row, 0) == "AUS");

  // Reject a partial update without replacing the last complete board.
  root["generated_at"] = epoch + 1;
  root["departures"][0]["line"] = 123;
  assert(!board.accept(root, 1));
  root["schema_version"] = 2;
  assert(!board.accept(root, 1));

  root["schema_version"] = 1;
  root["departures"][0]["line"] = "CHANGED";
  root["departures"][1]["line"] = 123;  // Last row fails after the first parsed.
  assert(!board.accept(root, 1));
  board.draw(display, &font, &font, 1, true);
  assert(!contains(display, "CHANGED"));
  assert(contains(display, "AUS"));

  root["schema_version"] = 1;
  root["state"] = "night";
  root["valid_for_seconds"] = 60;
  root["departures"].to<JsonArray>();
  hvv::Board night;
  assert(night.accept(root, 0));
  night.tick(0, epoch + 1);
  assert(night.night(0));
  night.draw(display, &font, &font, 0, true);
  assert(display.texts.empty());
  assert(!night.night(60000));
  night.draw(display, &font, &font, 60000, false);
  assert(display.texts.empty());

  // A future backend clock fails closed; millis rollover preserves the lease.
  hvv::Board future;
  future.tick(0, epoch - 100);
  assert(!future.accept(root, 0));
  assert(future.expired(0));
  hvv::Board initially_unsynced;
  assert(initially_unsynced.accept(root, 0));
  initially_unsynced.tick(0, epoch - 100);
  root["generated_at"] = epoch - 100;
  assert(initially_unsynced.accept(root, 0));
  root["generated_at"] = epoch + 1;
  hvv::Board rollover;
  assert(rollover.accept(root, UINT32_MAX - 10000));
  rollover.tick(UINT32_MAX - 10000, epoch + 1);
  assert(!rollover.expired(10000));
  assert(rollover.expired(60000));
  std::cout << "ESPHome board protocol, rendering and failure tests passed\n";
}
