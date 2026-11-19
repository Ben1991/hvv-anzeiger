#include "../../esphome/hvv_board.h"
#include "../../esphome/hvv_geofox.h"
#include <cassert>
#include <string>

int main() {
  const std::string stations =
      R"json([{"name":"Station","city":"Hamburg","id":"stop:1","label":"S","routes":[]}])json";
  const std::string response = R"json({"returnCode":"OK","departures":[
    {"line":{"name":"L1","direction":"Destination"},"timeOffset":1,"delay":0},
    {"line":{"name":"L2","direction":"Destination"},"timeOffset":3,"delay":-60},
    {"line":{"name":"L3","direction":"Destination"},"timeOffset":2,"delay":0},
    {"line":{"name":"L4","direction":"Destination"},"timeOffset":10,"delay":-480},
    {"line":{"name":"L5","direction":"Destination"},"timeOffset":5,"delay":0},
    {"line":{"name":"L6","direction":"Destination"},"timeOffset":1,"delay":600}
  ]})json";

  const int64_t request_epoch = 1799999940;
  const int64_t response_epoch = request_epoch + 45;
  std::string snapshot;
  assert(hvv::make_display_snapshot(response, stations, request_epoch,
                                    response_epoch, snapshot));
  JsonDocument parsed;
  assert(!deserializeJson(parsed, snapshot));
  JsonArray rows = parsed["departures"].as<JsonArray>();
  assert(rows.size() == 5);
  const std::string expected_lines[] = {"L1", "L2", "L3", "L4", "L5"};
  const int64_t expected_epochs[] = {
      request_epoch + 60, request_epoch + 120, request_epoch + 120,
      request_epoch + 120, request_epoch + 300};
  for (size_t index = 0; index < rows.size(); ++index) {
    assert(rows[index]["line"].as<std::string>() == expected_lines[index]);
    assert(rows[index]["station"].as<std::string>() == "S");
    assert(rows[index]["departure_epoch"].as<int64_t>() == expected_epochs[index]);
  }
  assert(parsed["generated_at"].as<int64_t>() == response_epoch);

  const std::string multi_stations = R"json([
    {"name":"Weistritzstraße","id":"Master:82039","label":"W","routes":[
      {"line":"186","destination":"S Othmarschen"}]},
    {"name":"Recknitzstraße","id":"Master:82015","label":"R","routes":[
      {"line":"21","destination":"U Niendorf Nord"}]}
  ])json";
  const std::string stationless_response = R"json({"returnCode":"OK","departures":[
    {"line":{"name":"186","direction":"S Othmarschen"},"timeOffset":5},
    {"line":{"name":"21","direction":"U Niendorf Nord"},"timeOffset":3},
    {"line":{"name":"22","direction":"U Kellinghusenstraße"},"timeOffset":1}
  ]})json";
  assert(hvv::make_display_snapshot(stationless_response, multi_stations,
                                    request_epoch, response_epoch, snapshot));
  assert(!deserializeJson(parsed, snapshot));
  JsonArray matched_rows = parsed["departures"].as<JsonArray>();
  assert(matched_rows.size() == 2);
  assert(matched_rows[0]["line"].as<std::string>() == "21");
  assert(matched_rows[0]["station"].as<std::string>() == "R");
  assert(matched_rows[1]["line"].as<std::string>() == "186");
  assert(matched_rows[1]["station"].as<std::string>() == "W");
  assert(hvv_board.accept(parsed.as<JsonObject>(), 1000));
  assert(!hvv::departure_text(0, 1000).empty());
  assert(hvv::departure_text(0, 302000).empty());
}
