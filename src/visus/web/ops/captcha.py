"""Captchas de token — reCAPTCHA v2/v3/Enterprise, Cloudflare Turnstile e hCaptcha —
resolvidos por um serviço com a chave de quem automatiza.

Nenhum modelo de visão passa por esses captchas com segurança; um serviço de resolução
devolve o token que o widget daria a um humano. Os dois suportados falam a mesma API
(``createTask`` → ``getTaskResult``), então um cliente atende os dois:

* **CapSolver** (padrão) — o mais barato e rápido (IA): reCAPTCHA v2/v3/Enterprise e
  Turnstile. Não faz hCaptcha.
* **2Captcha** — mais caro, cobre também hCaptcha (com gente por trás quando precisa).

A chave vem do argumento ou de ``VISUS_CAPTCHA_KEY`` (o serviço, de
``VISUS_CAPTCHA_PROVIDER``); ela nunca vai para log, código gerado ou relatório. Sem
captcha na página, :func:`solve` só diz isso — o script gerado pode chamá-lo onde o
captcha às vezes aparece. A página inteira de desafio da Cloudflare ("Just a moment…")
não é um widget: num navegador de verdade ela some sozinha em segundos, e é o que
:func:`solve` espera; se não sumir, diz para clicar a caixa (ou pedir à pessoa).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from visus.web.errors import VisusWebError

__all__ = [
    "PROVIDERS",
    "CaptchaError",
    "CaptchaInfo",
    "balance",
    "detect",
    "request_token",
    "solve",
    "task_for",
]

PROVIDERS: dict[str, str] = {
    "capsolver": "https://api.capsolver.com",
    "2captcha": "https://api.2captcha.com",
}
DEFAULT_PROVIDER = "capsolver"
_NAMES = {"capsolver": "CapSolver", "2captcha": "2Captcha"}
_LABELS = {
    "recaptcha_v2": "reCAPTCHA v2",
    "recaptcha_v3": "reCAPTCHA v3",
    "turnstile": "Cloudflare Turnstile",
    "hcaptcha": "hCaptcha",
    "cloudflare_challenge": "Cloudflare challenge",
}


class CaptchaError(VisusWebError):
    """O captcha não pôde ser resolvido (sem chave, serviço recusou, tempo esgotado…)."""


@dataclass(frozen=True)
class CaptchaInfo:
    """O captcha achado na página: o tipo e o que o serviço precisa para resolvê-lo."""

    kind: str
    sitekey: str
    url: str
    enterprise: bool = False
    invisible: bool = False
    action: str | None = None
    cdata: str | None = None
    callback: str | None = None

    @property
    def label(self) -> str:
        return _LABELS.get(self.kind, self.kind) + (" Enterprise" if self.enterprise else "")


# Procura no documento: o desafio de página inteira da Cloudflare, o Turnstile, o
# hCaptcha, o reCAPTCHA v2 (elemento .g-recaptcha) e o v3 (api.js?render=<chave>) antes
# do iframe "anchor" — o v3 também cria um anchor invisível, que não é um v2.
_DETECT_JS = r"""(_) => {
  const q = (s) => document.querySelector(s);
  const frames = Array.from(document.querySelectorAll("iframe")).map((f) => f.src || "");
  const scripts = Array.from(document.scripts).map((s) => s.src || "");
  const param = (url, name) => {
    try { return new URL(url.replace("#", "?")).searchParams.get(name); } catch (e) { return null; }
  };
  const data = (el, key) => (el && el.getAttribute("data-" + key)) || null;
  if (window._cf_chl_opt || q("#challenge-form, #challenge-running, #challenge-stage")) {
    return { kind: "cloudflare_challenge", sitekey: "" };
  }
  let el = q(".cf-turnstile[data-sitekey]");
  if (el) {
    return { kind: "turnstile", sitekey: data(el, "sitekey"), action: data(el, "action"),
             cdata: data(el, "cdata"), callback: data(el, "callback") };
  }
  let src = frames.find((s) => s.includes("challenges.cloudflare.com"));
  if (src) {
    const m = src.match(/\/(0x[0-9A-Za-z_-]{10,})\//);
    if (m) return { kind: "turnstile", sitekey: m[1] };
  }
  el = q(".h-captcha[data-sitekey]");
  if (el) return { kind: "hcaptcha", sitekey: data(el, "sitekey"), callback: data(el, "callback") };
  src = frames.find((s) => s.includes("hcaptcha.com"));
  if (src && param(src, "sitekey")) return { kind: "hcaptcha", sitekey: param(src, "sitekey") };
  const enterprise = scripts.some((s) => s.includes("recaptcha/enterprise.js"))
    || frames.some((s) => s.includes("/recaptcha/enterprise/"));
  el = q(".g-recaptcha[data-sitekey]");
  if (el) {
    return { kind: "recaptcha_v2", sitekey: data(el, "sitekey"), enterprise,
             invisible: data(el, "size") === "invisible", callback: data(el, "callback"),
             action: data(el, "action") };
  }
  const v3 = scripts.find((s) => /recaptcha\/(api|enterprise)\.js/.test(s) && param(s, "render")
    && param(s, "render") !== "explicit");
  if (v3) return { kind: "recaptcha_v3", sitekey: param(v3, "render"), enterprise };
  src = frames.find((s) => /\/recaptcha\/(api2|enterprise)\/anchor/.test(s));
  if (src && param(src, "k")) {
    return { kind: "recaptcha_v2", sitekey: param(src, "k"), enterprise,
             invisible: param(src, "size") === "invisible" };
  }
  return null;
}"""

# Põe o token onde o site o lê: o campo escondido do widget, os getResponse/execute da
# biblioteca (o v3 e o v2 invisível pedem o token na hora do envio) e o callback da
# página — o do data-callback ou o registrado no render(), guardado em ___grecaptcha_cfg.
_INJECT_JS = r"""(a) => {
  const token = a.token, kind = a.kind;
  const set = (sel) => document.querySelectorAll(sel).forEach((e) => {
    e.value = token;
    e.innerHTML = token;
  });
  if (kind === "turnstile") set('[name="cf-turnstile-response"], [name="g-recaptcha-response"]');
  else if (kind === "hcaptcha") set('[name="h-captcha-response"], [name="g-recaptcha-response"]');
  else set('[name="g-recaptcha-response"], [id^="g-recaptcha-response"]');
  const lib = { recaptcha_v2: window.grecaptcha, recaptcha_v3: window.grecaptcha,
                turnstile: window.turnstile, hcaptcha: window.hcaptcha }[kind];
  for (const api of [lib, lib && lib.enterprise]) {
    if (!api) continue;
    try { api.getResponse = () => token; } catch (e) {}
    if (!kind.startsWith("recaptcha")) continue;
    try { api.execute = () => Promise.resolve(token); } catch (e) {}
  }
  let called = false;
  const fire = (fn) => {
    if (typeof fn === "string") fn = fn.split(".").reduce((o, k) => (o ? o[k] : undefined), window);
    if (typeof fn === "function") { fn(token); called = true; }
  };
  if (a.callback) fire(a.callback);
  if (!called && kind.startsWith("recaptcha") && window.___grecaptcha_cfg) {
    const seen = new Set();
    const walk = (o, depth) => {
      if (called || !o || typeof o !== "object" || depth > 5 || seen.has(o)) return;
      seen.add(o);
      for (const key of Object.keys(o)) {
        if (key === "callback") fire(o[key]); else walk(o[key], depth + 1);
        if (called) return;
      }
    };
    try { walk(window.___grecaptcha_cfg.clients, 0); } catch (e) {}
  }
  return called;
}"""


def detect(page: Any) -> CaptchaInfo | None:
    """O captcha da página, ou None. ``page`` é uma :class:`visus.web.Page`."""
    found = page.evaluate(_DETECT_JS, None)
    if not isinstance(found, dict) or not found.get("kind"):
        return None
    return CaptchaInfo(
        kind=str(found["kind"]),
        sitekey=str(found.get("sitekey") or ""),
        url=str(page.url),
        enterprise=bool(found.get("enterprise")),
        invisible=bool(found.get("invisible")),
        action=found.get("action") or None,
        cdata=found.get("cdata") or None,
        callback=found.get("callback") or None,
    )


def task_for(provider: str, info: CaptchaInfo) -> dict[str, Any]:
    """O ``task`` do ``createTask`` de cada serviço para este captcha."""
    base: dict[str, Any] = {"websiteURL": info.url, "websiteKey": info.sitekey}
    if provider == "capsolver":
        if info.kind == "recaptcha_v2":
            kind = (
                "ReCaptchaV2EnterpriseTaskProxyLess"
                if info.enterprise
                else "ReCaptchaV2TaskProxyLess"
            )
            extra = {} if info.enterprise else {"isInvisible": info.invisible}
            return {"type": kind, **base, **extra}
        if info.kind == "recaptcha_v3":
            kind = (
                "ReCaptchaV3EnterpriseTaskProxyLess"
                if info.enterprise
                else "ReCaptchaV3TaskProxyLess"
            )
            return {"type": kind, **base, **({"pageAction": info.action} if info.action else {})}
        if info.kind == "turnstile":
            metadata = {k: v for k, v in (("action", info.action), ("cdata", info.cdata)) if v}
            return {
                "type": "AntiTurnstileTaskProxyLess",
                **base,
                **({"metadata": metadata} if metadata else {}),
            }
        raise CaptchaError(f"CapSolver does not solve {info.label}: use 2Captcha for it")
    if provider == "2captcha":
        if info.kind == "recaptcha_v2":
            kind = (
                "RecaptchaV2EnterpriseTaskProxyless"
                if info.enterprise
                else "RecaptchaV2TaskProxyless"
            )
            return {"type": kind, **base, "isInvisible": info.invisible}
        if info.kind == "recaptcha_v3":
            task = {"type": "RecaptchaV3TaskProxyless", **base, "minScore": 0.7}
            if info.enterprise:
                task["isEnterprise"] = True
            return {**task, **({"pageAction": info.action} if info.action else {})}
        if info.kind == "turnstile":
            fields: dict[str, Any] = {
                k: v for k, v in (("action", info.action), ("data", info.cdata)) if v
            }
            return {"type": "TurnstileTaskProxyless", **base, **fields}
        if info.kind == "hcaptcha":
            return {"type": "HCaptchaTaskProxyless", **base}
    raise CaptchaError(f"unknown captcha service {provider!r} (use {' or '.join(PROVIDERS)})")


Post = Callable[[str, dict[str, Any]], dict[str, Any]]


def _post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 -- URL fixa do serviço
            return dict(json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        try:
            return dict(json.loads(exc.read().decode("utf-8")))
        except ValueError:
            raise CaptchaError(f"captcha service answered HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CaptchaError(f"could not reach the captcha service: {exc}") from exc


def _checked(provider: str, answer: dict[str, Any]) -> dict[str, Any]:
    if answer.get("errorId"):
        code = answer.get("errorCode") or ""
        text = answer.get("errorDescription") or code or "unknown error"
        raise CaptchaError(f"{_NAMES.get(provider, provider)}: {text}")
    return answer


def _provider(provider: str | None) -> str:
    name = (
        (provider or os.environ.get("VISUS_CAPTCHA_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    )
    if name not in PROVIDERS:
        raise CaptchaError(f"unknown captcha service {name!r} (use {' or '.join(PROVIDERS)})")
    return name


def request_token(
    provider: str,
    api_key: str,
    info: CaptchaInfo,
    *,
    timeout: float = 120.0,
    post: Post = _post,
    sleep: Callable[[float], Any] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Pede o token ao serviço e espera por ele (``createTask`` e ``getTaskResult``)."""
    base = PROVIDERS[provider]
    created = _checked(
        provider,
        post(f"{base}/createTask", {"clientKey": api_key, "task": task_for(provider, info)}),
    )
    task_id = created.get("taskId")
    solution = created.get("solution")  # o CapSolver às vezes já responde resolvido
    deadline = clock() + timeout
    while not solution:
        if not task_id:
            raise CaptchaError(f"{_NAMES[provider]} did not create the task")
        if clock() >= deadline:
            raise CaptchaError(
                f"{_NAMES[provider]} did not solve the {info.label} in {timeout:.0f}s"
            )
        sleep(3)
        result = _checked(
            provider, post(f"{base}/getTaskResult", {"clientKey": api_key, "taskId": task_id})
        )
        if result.get("status") == "ready":
            solution = result.get("solution") or {}
            break
    token = solution.get("gRecaptchaResponse") or solution.get("token")
    if not token:
        raise CaptchaError(f"{_NAMES[provider]} answered without a token")
    return str(token)


def balance(
    provider: str | None = None, api_key: str | None = None, *, post: Post = _post
) -> float:
    """O saldo da conta no serviço — também a forma de testar a chave."""
    name = _provider(provider)
    key = api_key or os.environ.get("VISUS_CAPTCHA_KEY") or ""
    if not key:
        raise CaptchaError("no captcha service key")
    answer = _checked(name, post(f"{PROVIDERS[name]}/getBalance", {"clientKey": key}))
    return float(answer.get("balance") or 0.0)


def _wait_challenge(page: Any, seconds: int, sleep: Callable[[float], Any]) -> bool:
    """A página de desafio da Cloudflare some sozinha num navegador de verdade."""
    for _ in range(seconds):
        sleep(1)
        info = detect(page)
        if info is None or info.kind != "cloudflare_challenge":
            return True
    return False


def solve(
    page: Any,
    *,
    provider: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
    post: Post = _post,
    sleep: Callable[[float], Any] = time.sleep,
) -> str:
    """Acha o captcha da página, resolve pelo serviço e aplica o token. Devolve o que fez."""
    info = detect(page)
    if info is None:
        return "no captcha on this page"
    if info.kind == "cloudflare_challenge":
        if _wait_challenge(page, 20, sleep):
            return "the Cloudflare check passed by itself"
        raise CaptchaError(
            "Cloudflare is still checking this browser: if the page shows a checkbox, "
            "click it (or ask the person to); it is not a widget a service can solve here"
        )
    if not info.sitekey:
        raise CaptchaError(f"found a {info.label} but not its site key")
    name = _provider(provider)
    key = api_key or os.environ.get("VISUS_CAPTCHA_KEY") or ""
    if not key:
        raise CaptchaError(
            f"found a {info.label}, but there is no captcha service key "
            "(VISUS_CAPTCHA_KEY) — solve it by hand in the browser, or add a key"
        )
    started = time.monotonic()
    token = request_token(name, key, info, timeout=timeout or 120.0, post=post, sleep=sleep)
    called = page.evaluate(
        _INJECT_JS, {"token": token, "kind": info.kind, "callback": info.callback}
    )
    spent = time.monotonic() - started
    applied = "token applied and the page's callback called" if called else "token applied"
    return f"solved the {info.label} with {_NAMES[name]} in {spent:.0f}s ({applied})"
