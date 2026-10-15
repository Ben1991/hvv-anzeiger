"""Check package YAML and render HA templates for relevant failure states.

This checks syntax and template behavior, not a running Home Assistant instance.
"""

from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!secret", lambda loader, node: loader.construct_scalar(node))


def main():
    package = yaml.load(
        (ROOT / "home-assistant/hvv.yaml").read_text(encoding="utf-8"),
        Loader=Loader,  # noqa: S506 -- SafeLoader subclass, tags are strings
    )
    dashboard = yaml.safe_load(
        (ROOT / "home-assistant/dashboard.yaml").read_text(encoding="utf-8")
    )
    rest = package["sensor"][0]
    if not rest["verify_ssl"] or rest["authentication"] != "basic":
        raise ValueError("REST transport must retain TLS and authentication")
    row = {
        "line": "U3",
        "destination": "Barmbek",
        "station": "W",
        "time": "12:00",
        "display_time": "sofort",
    }
    for state in ("ok", "stale", "expired", "unavailable", "unknown", "night"):
        for rows in ([], [row]):
            env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701
            env.globals.update(states=lambda _: state, state_attr=lambda *_: rows)
            next_sensor = package["template"][0]["sensor"][0]
            available = env.from_string(next_sensor["availability"]).render().strip()
            expected = state in {"ok", "stale"} and bool(rows)
            if available != str(expected):
                raise ValueError(f"Unexpected next departure availability: {state}")
            for template in (
                next_sensor["state"],
                *next_sensor["attributes"].values(),
                package["template"][1]["binary_sensor"][0]["state"],
            ):
                env.from_string(template).render()
            rendered = env.from_string(dashboard["content"]).render()
            if (
                state in {"expired", "unavailable", "unknown", "night"}
                and "Barmbek" in rendered
            ):
                raise ValueError("Dashboard displays unavailable data")
    print("Home Assistant YAML and templates passed (12 scenarios)")


if __name__ == "__main__":
    main()
