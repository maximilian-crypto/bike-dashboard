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


# --- Env-Overlay: robust gegen kopierte Anfuehrungszeichen -----------------

def test_env_value_cleaning():
    assert config._clean_env_value('  170 ') == "170"
    assert config._clean_env_value('"2027-03-01"') == "2027-03-01"
    assert config._clean_env_value("'170'") == "170"
    assert config._clean_env_value("170") == "170"
    # Kein Kahlschlag bei Anfuehrungszeichen mitten im Wert.
    assert config._clean_env_value('ab"cd') == 'ab"cd'


def test_quoted_env_secrets_still_apply(monkeypatch):
    """TOML-Zeile versehentlich in ein GitHub-Secret kopiert: darf nicht still
    auf den Vorgabewert zurueckfallen."""
    monkeypatch.setenv("ATHLETE_FTP", '"170"')
    monkeypatch.setenv("ATHLETE_SEASON_START", '"2027-03-01"')
    assert config.ftp_from_config() == 170

    from bikedash import season
    assert season.season_start_from_config().isoformat() == "2027-03-01"


def test_blank_env_var_does_not_override(monkeypatch):
    monkeypatch.setenv("ATHLETE_FTP", "   ")
    assert config.ftp_from_config() is None


def test_intervals_env_overlay(monkeypatch):
    """Zwift-Zustellung: beide Werte müssen aus den Actions-Secrets ankommen."""
    monkeypatch.setenv("INTERVALS_API_KEY", '"abc123"')
    monkeypatch.setenv("INTERVALS_ATHLETE_ID", "i12345")
    cfg: dict = {}
    config._overlay_env(cfg)
    assert cfg["intervals"] == {"api_key": "abc123", "athlete_id": "i12345"}
