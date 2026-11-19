#pragma once

#include "esphome.h"
#include <mbedtls/base64.h>
#include <mbedtls/md.h>
#include <algorithm>
#include <cctype>
#include <ctime>
#include <string>
#include <utility>
#include <vector>

namespace hvv {

struct DepartureCandidate {
  std::string line;
  std::string destination;
  std::string station;
  std::string time;
  int64_t departure_epoch;
  bool cancelled;
  int delay_seconds;
};

inline std::string departure_text(size_t index, uint32_t now) {
  if (hvv_board.expired(now)) return "";
  const Row *row = hvv_board.departure(index);
  if (!row) return "";
  std::string value = row->line + " → " + row->destination + " · " + row->time;
  if (!row->station.empty()) value += " · " + row->station;
  if (row->cancelled) value += " · AUSFALL";
  if (row->delay != 0) {
    value += " · ";
    if (row->delay > 0) value += "+";
    value += std::to_string(row->delay / 60) + " min";
  }
  return value;
}

inline std::string geofox_request_body(const std::string &stations_json,
                                       int64_t epoch) {
  JsonDocument stations_doc;
  if (deserializeJson(stations_doc, stations_json) || !stations_doc.is<JsonArray>())
    return "";
  JsonArray stations = stations_doc.as<JsonArray>();
  if (stations.size() == 0 || stations.size() > 4) return "";

  const time_t timestamp = static_cast<time_t>(epoch);
  struct tm local_time {};
  localtime_r(&timestamp, &local_time);
  char date[11], clock[6];
  strftime(date, sizeof(date), "%d.%m.%Y", &local_time);
  strftime(clock, sizeof(clock), "%H:%M", &local_time);

  JsonDocument request_doc;
  JsonObject request = request_doc.to<JsonObject>();
  request["version"] = 63;
  request["language"] = "de";
  request["time"]["date"] = date;
  request["time"]["time"] = clock;
  request["maxList"] = 30;
  request["maxTimeOffset"] = 90;
  request["useRealtime"] = true;
  auto make_station = [](JsonObject target, JsonObjectConst source) {
    target["name"] = source["name"] | "";
    target["city"] = source["city"] | "Hamburg";
    target["id"] = source["id"] | "";
    target["type"] = "STATION";
  };
  if (stations.size() == 1) {
    make_station(request["station"].to<JsonObject>(), stations[0].as<JsonObjectConst>());
  } else {
    JsonArray output = request["stations"].to<JsonArray>();
    for (JsonObject station : stations) {
      JsonObject item = output.add<JsonObject>();
      make_station(item, station);
    }
  }
  std::string body;
  serializeJson(request_doc, body);
  return body;
}

inline std::string geofox_signature(const std::string &body,
                                   const std::string &password) {
  const auto *info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA1);
  if (!info) return "";
  unsigned char digest[20];
  if (mbedtls_md_hmac(info,
                      reinterpret_cast<const unsigned char *>(password.data()),
                      password.size(),
                      reinterpret_cast<const unsigned char *>(body.data()),
                      body.size(), digest) != 0) return "";
  unsigned char encoded[32];
  size_t encoded_size = 0;
  if (mbedtls_base64_encode(encoded, sizeof(encoded), &encoded_size, digest,
                            sizeof(digest)) != 0) return "";
  return std::string(reinterpret_cast<char *>(encoded), encoded_size);
}

inline std::string normalize_station_text(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return value;
}

inline bool route_selected(JsonArrayConst stations, const std::string &station_id,
                           const std::string &line,
                           const std::string &destination,
                           std::string &label) {
  const std::string normalized_line = normalize_station_text(line);
  const std::string normalized_destination = normalize_station_text(destination);
  for (JsonObjectConst station : stations) {
    if (!station_id.empty() && station["id"].as<std::string>() != station_id)
      continue;
    JsonArrayConst routes = station["routes"].as<JsonArrayConst>();
    if (routes.isNull() || routes.size() == 0) {
      label = station["label"] | "";
      return true;
    }
    for (JsonObjectConst route : routes) {
      if (normalize_station_text(route["line"].as<std::string>()) != normalized_line)
        continue;
      const std::string wanted = normalize_station_text(
          route["destination"] | "");
      if (wanted.empty() || normalized_destination.find(wanted) != std::string::npos ||
          wanted.find(normalized_destination) != std::string::npos) {
        label = station["label"] | "";
        return true;
      }
    }
  }
  return false;
}

inline bool make_display_snapshot(const std::string &response_body,
                                  const std::string &stations_json,
                                  int64_t request_epoch,
                                  int64_t generated_at,
                                  std::string &snapshot) {
  JsonDocument stations_doc, response_doc, output_doc;
  if (deserializeJson(stations_doc, stations_json) ||
      !stations_doc.is<JsonArray>() ||
      deserializeJson(response_doc, response_body) ||
      response_doc["returnCode"] != "OK") return false;
  JsonArrayConst stations = stations_doc.as<JsonArrayConst>();
  JsonArray raw = response_doc["departures"].as<JsonArray>();
  std::vector<DepartureCandidate> candidates;
  candidates.reserve(raw.size());
  JsonObject root = output_doc.to<JsonObject>();
  root["schema_version"] = 1;
  root["generated_at"] = generated_at;
  root["state"] = "ok";
  root["valid_for_seconds"] = 300;
  root["time_mode"] = "countdown";
  root["minute_unit"] = "min";
  JsonArray departures = root["departures"].to<JsonArray>();
  for (JsonObject item : raw) {
    JsonObject line_data = item["line"].as<JsonObject>();
    JsonObject stop = item["station"].as<JsonObject>();
    if (line_data.isNull()) continue;
    const std::string line = line_data["name"] | "";
    const std::string destination = line_data["direction"] | "";
    std::string station_id = stop["id"] | "";
    if (station_id.empty() && stations.size() == 1)
      station_id = stations[0]["id"] | "";
    int offset = 0, delay = 0;
    if (line.empty() || destination.empty() || item["timeOffset"].isNull()) continue;
    offset = item["timeOffset"].as<int>();
    delay = item["delay"] | 0;
    std::string label;
    if (!route_selected(stations, station_id, line, destination, label)) continue;
    const int64_t departure_epoch = request_epoch + offset * 60 + delay;
    const time_t departure_time = static_cast<time_t>(departure_epoch);
    struct tm local_departure {};
    localtime_r(&departure_time, &local_departure);
    char clock[6];
    strftime(clock, sizeof(clock), "%H:%M", &local_departure);
    candidates.push_back({line, destination, label, clock, departure_epoch,
                          item["cancelled"] | false, delay});
  }
  std::stable_sort(candidates.begin(), candidates.end(),
                   [](const DepartureCandidate &left,
                      const DepartureCandidate &right) {
                     return left.departure_epoch < right.departure_epoch;
                   });
  for (const auto &candidate : candidates) {
    if (departures.size() >= 5) break;
    JsonObject row = departures.add<JsonObject>();
    row["line"] = candidate.line;
    row["destination"] = candidate.destination;
    row["station"] = candidate.station;
    row["time"] = candidate.time;
    row["departure_epoch"] = candidate.departure_epoch;
    row["cancelled"] = candidate.cancelled;
    row["delay_seconds"] = candidate.delay_seconds;
    row["background"] = 0x005A9C;
    row["foreground"] = 0xFFFFFF;
    row["shape"] = "rectangle";
  }
  std::string encoded;
  serializeJson(output_doc, encoded);
  if (encoded.size() > 8192) return false;
  snapshot = std::move(encoded);
  return true;
}

}  // namespace hvv
