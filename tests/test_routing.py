"""Routing-Tests mit gefälschter ORS-Antwort (kein Netzwerk)."""

from bikedash import routing


class _Resp:
    status_code = 200

    def __init__(self, dist_m):
        self._d = dist_m

    def raise_for_status(self):
        pass

    def json(self):
        return {"features": [{
            "geometry": {"coordinates": [[9.0, 53.0, 10.0], [9.01, 53.0, 12.0],
                                         [9.0, 53.01, 11.0], [9.0, 53.0, 10.0]]},
            "properties": {"summary": {"distance": self._d}, "ascent": 25.0},
        }]}


CFG = {"ors": {"api_key": "k", "profile": "cycling-regular"},
       "athlete": {"home_lat": 53.0, "home_lon": 9.0}}


def test_best_of_picks_closest(monkeypatch):
    # Nur seed 27 liefert eine brauchbare Länge, der Rest ist 3x zu lang.
    def fake_post(url, json, headers, timeout):
        seed = json["options"]["round_trip"]["seed"]
        req = json["options"]["round_trip"]["length"]
        return _Resp(req if seed == 27 else req * 3)

    monkeypatch.setattr(routing.requests, "post", fake_post)
    rt = routing.generate_loop(CFG, 30.0, seed=1)  # seeds 1,14,27,... -> 27 trifft
    assert abs(rt.distance_km - 30.0) / 30.0 < 0.15


def test_missing_config_raises():
    import pytest
    with pytest.raises(RuntimeError):
        routing.generate_loop({"ors": {"api_key": ""}, "athlete": {"home_lat": 0, "home_lon": 0}}, 30)


def test_wind_score_prefers_headwind_outbound():
    # Hinweg nach Osten, Rückweg nach Westen; Wind kommt aus Osten (90°).
    rt = routing.Route(
        lats=[53.0, 53.0, 53.0, 53.0, 53.0],
        lons=[9.00, 9.03, 9.06, 9.03, 9.00],
        distance_km=8.0, ascent_m=0.0,
        profile_dist_km=[0, 2, 4, 6, 8], profile_ele_m=[10, 10, 10, 10, 10], seed=1,
    )
    # Hinweg Ost = Gegenwind, Rückweg West = Rückenwind -> Score > 0
    assert routing.wind_score(rt, 90.0) > 0
    summ = routing.wind_summary(rt, 90.0, 20.0)
    assert summ["ok"] is True
    assert summ["first"] > summ["second"]
