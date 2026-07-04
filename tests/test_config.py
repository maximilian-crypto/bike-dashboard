from bikedash import config


def test_save_load_roundtrip_and_validation():
    config.save_config({
        "strava": {"client_id": "111", "client_secret": "sss"},
        "whoop": {"client_id": "www", "client_secret": "xxx"},
        "server": {"port": 8721},
        "ors": {"api_key": "orskey", "profile": "cycling-road"},
        "athlete": {"home_lat": 53.5, "home_lon": 9.4, "weekly_hours_target": 6},
    })
    raw = config.load_config_raw()
    assert config.provider_creds_ok(raw, "strava")
    assert config.provider_creds_ok(raw, "whoop")
    assert config.has_routing(raw)
    assert raw["ors"]["profile"] == "cycling-road"

    # validierender Loader akzeptiert gültige Werte
    cfg = config.load_config()
    assert cfg["server"]["port"] == 8721


def test_placeholder_creds_are_invalid():
    config.save_config({
        "strava": {"client_id": "DEINE_STRAVA_CLIENT_ID", "client_secret": "x"},
        "whoop": {"client_id": "w", "client_secret": "y"},
        "server": {"port": 8721},
        "ors": {"api_key": "", "profile": "cycling-regular"},
        "athlete": {"home_lat": 0.0, "home_lon": 0.0, "weekly_hours_target": 0},
    })
    raw = config.load_config_raw()
    assert not config.provider_creds_ok(raw, "strava")
    assert not config.has_routing(raw)
