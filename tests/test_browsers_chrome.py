from visus.web.backends.browsers import chrome


def test_options_headless_adds_flag(tmp_path):
    opts = chrome.build_options(
        headless=True, download_dir=str(tmp_path), user_data_dir=str(tmp_path / "p")
    )
    args = opts.arguments
    assert "--headless=new" in args
    assert any(a.startswith("--user-data-dir=") for a in args)


def test_options_headed_omits_headless(tmp_path):
    opts = chrome.build_options(
        headless=False, download_dir=str(tmp_path), user_data_dir=str(tmp_path / "p")
    )
    assert "--headless=new" not in opts.arguments


def test_service_factory_returns_service():
    svc = chrome.build_service()
    assert hasattr(svc, "path")


def test_no_container_o_chrome_sai_do_proprio_sandbox(tmp_path, monkeypatch):
    """Num container Linux o seccomp barra o sandbox do Chrome: --no-sandbox e o
    /dev/shm pequeno contornado. Fora dele, nada muda."""
    monkeypatch.setenv("VISUS_CHROME_NO_SANDBOX", "1")
    opts = chrome.build_options(
        headless=False, download_dir=str(tmp_path), user_data_dir=str(tmp_path / "p")
    )
    assert "--no-sandbox" in opts.arguments and "--disable-dev-shm-usage" in opts.arguments
    monkeypatch.setenv("VISUS_CHROME_NO_SANDBOX", "0")
    opts = chrome.build_options(
        headless=False, download_dir=str(tmp_path), user_data_dir=str(tmp_path / "p")
    )
    assert "--no-sandbox" not in opts.arguments


def test_fora_de_container_nao_desliga_o_sandbox(tmp_path, monkeypatch):
    monkeypatch.delenv("VISUS_CHROME_NO_SANDBOX", raising=False)
    monkeypatch.setattr(chrome.sys, "platform", "win32")
    assert chrome.in_container() is False


def test_http_continua_http_sem_https_first(tmp_path):
    """Intranet de empresa é http:// puro: o Chrome não pode tentar https antes (lento) nem
    barrar/avisar 'site não seguro' (a navegação ficava na Nova guia, sem erro nenhum)."""
    opts = chrome.build_options(
        headless=False, download_dir=str(tmp_path), user_data_dir=str(tmp_path / "p")
    )
    disabled = [a for a in opts.arguments if a.startswith("--disable-features=")]
    assert len(disabled) == 1  # o Chrome só respeita UM --disable-features
    features = disabled[0].split("=", 1)[1].split(",")
    assert {"HttpsUpgrades", "HttpsFirstBalancedModeAutoEnable"} <= set(features)
    assert opts.experimental_options["prefs"]["https_only_mode_enabled"] is False
