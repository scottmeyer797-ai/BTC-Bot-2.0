import pytest

from bot.config import DEMO_BASE_URL, MODES, LiveEndpointRefused, assert_demo_url, load_config


@pytest.mark.parametrize("url", [
    "https://openapi.blofin.com",
    "https://openapi.blofin.com/",
    "http://demo-trading-openapi.blofin.com",
    "https://demo-trading-openapi.blofin.com.evil.example",
    "",
    None,
])
def test_demo_guard_refuses_anything_but_demo(url):
    with pytest.raises(LiveEndpointRefused):
        assert_demo_url(url)


def test_demo_guard_accepts_demo():
    assert assert_demo_url(DEMO_BASE_URL + "/") == DEMO_BASE_URL


def test_load_config_refuses_live_base_url(tmp_path):
    with pytest.raises(LiveEndpointRefused):
        load_config({"BLOFIN_BASE_URL": "https://openapi.blofin.com", "REPO_ROOT": str(tmp_path)})


def test_exchange_client_is_pinned_to_demo(tmp_path):
    from bot.exchange import BlofinDemo
    cfg = load_config({"REPO_ROOT": str(tmp_path)})
    client = BlofinDemo(cfg, private=False)
    assert client.ex.urls["api"]["rest"] == DEMO_BASE_URL
    client.ex.urls["api"]["rest"] = "https://openapi.blofin.com"
    with pytest.raises(LiveEndpointRefused):
        client._call("publicGetMarketInstruments", {"instType": "SWAP"})


def test_modes_and_kill_switch(tmp_path):
    cfg = load_config({"MODE": "funded", "REPO_ROOT": str(tmp_path)})
    assert cfg.mode is MODES["funded"] and cfg.account_size == 100000
    assert not cfg.kill_switch
    (tmp_path / "STOP").write_text("")
    assert cfg.kill_switch
    cfg2 = load_config({"BOT_ENABLED": "false", "REPO_ROOT": str(tmp_path / "x")})
    assert cfg2.kill_switch
    with pytest.raises(ValueError):
        load_config({"MODE": "yolo", "REPO_ROOT": str(tmp_path)})


def test_credentials_not_in_repr(tmp_path):
    cfg = load_config({"REPO_ROOT": str(tmp_path), "BLOFIN_API_KEY": "k-123", "BLOFIN_API_SECRET": "s-456",
                       "BLOFIN_PASSPHRASE": "p-789"})
    r = repr(cfg)
    assert "k-123" not in r and "s-456" not in r and "p-789" not in r
