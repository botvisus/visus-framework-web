"""E2E: um site http:// abre como http://, sem o Chrome forçar https nem barrar.

Sem desligar o HTTPS-First, o `goto` do Chrome 157 voltava SEM erro com a aba ainda na
Nova guia (ou na página de aviso) — o passo seguinte quebrava. Depende de internet:

    set VISUS_E2E_INTERNET=1
    uv run --all-extras pytest tests/test_http_site_e2e.py --no-cov -n 0
"""

from __future__ import annotations

import pytest

from visus.web import launch

pytestmark = [pytest.mark.browser, pytest.mark.internet, pytest.mark.timeout(120)]

HTTP_ONLY = "http://http.badssl.com/"


def test_site_http_abre_como_http() -> None:
    with launch("chrome", headless=True) as browser:
        page = browser.new_page()
        page.goto(HTTP_ONLY)
        assert page.url == HTTP_ONLY
        assert page.title() == "http.badssl.com"
