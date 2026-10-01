"""The UI kit (ui/): served by the local app server by name only, and written to its accessibility and
safety rules."""
import re
from pathlib import Path

from tests.test_api_contracts import app, call  # noqa: F401  (the real web server fixture)

UI = Path(__file__).resolve().parent.parent / "ui"


def get(base, path):
    from urllib.request import urlopen

    try:
        with urlopen(base + path, timeout=30) as r:
            return r.status, r.headers, r.read().decode("utf-8")
    except Exception as error:
        return error.code, error.headers, ""


def test_the_kit_is_served_by_name_only(app):  # noqa: F811
    base, _ = app
    for name, kind in (("tokens.css", "text/css"), ("rabbit.js", "text/javascript"), ("gallery.html", "text/html"),
                       ("gallery.js", "text/javascript")):
        status, headers, body = get(base, f"/ui/{name}")
        assert status == 200 and headers["Content-Type"].startswith(kind) and body
        assert "script-src 'self'" in headers["Content-Security-Policy"]
    for bad in ("/ui/../rabbitsoft/web.py", "/ui/%2e%2e/VERSION", "/ui/", "/ui/missing.js"):
        assert get(base, bad)[0] == 404


def test_components_never_put_text_in_as_html():
    source = (UI / "rabbit.js").read_text(encoding="utf-8")
    assert "textContent" in source
    # innerHTML only ever receives the fixed component markup, built inside shadow().
    assert len(re.findall(r"\.innerHTML\s*=", source)) == 1 and "fixed markup only" in source
    assert "insertAdjacentHTML" not in source and "outerHTML" not in source


def test_accessibility_rules_are_built_in():
    source = (UI / "rabbit.js").read_text(encoding="utf-8")
    tokens = (UI / "tokens.css").read_text(encoding="utf-8")
    assert 'role="log"' in source and 'aria-live="polite"' in source            # the chat is read out
    assert 'role="alertdialog"' in source and ".no\").focus()" in source        # "No" is focused first
    assert "Esc = No" in source and "STATES" in source and '"Problem"' in source  # status has words, not just colour
    for rule in ("--rabbit-touch", "data-text=\"big\"", "data-contrast=\"high\"", "prefers-reduced-motion",
                 ":focus-visible"):
        assert rule in tokens
    for name in ("rabbit-button", "rabbit-card", "rabbit-status", "rabbit-choices", "rabbit-dialog", "rabbit-chat"):
        assert f'"{name}"' in source
