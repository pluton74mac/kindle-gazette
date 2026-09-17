"""Theme resolution: directory lookup, template-override precedence, the loud
failure on an unknown KINDLE_GAZETTE_THEME — and a browser-tier pass that
renders the showcase edition through every installed theme."""
from io import BytesIO

import pytest
from PIL import Image

from kindle_gazette import config, renderers, server, store

import _util


def test_builtin_themes_are_available():
    themes = renderers.available_themes()
    assert "classic" in themes
    assert "noir" in themes


def test_unknown_theme_fails_loudly(monkeypatch):
    monkeypatch.setattr(config, "THEME", "no-such-theme")
    with pytest.raises(ValueError) as excinfo:
        renderers.theme_dir()
    # The error must name the bad theme and list what would have worked.
    assert "no-such-theme" in str(excinfo.value)
    assert "classic" in str(excinfo.value)


def test_base_context_carries_the_active_themes_css(monkeypatch):
    css_by_theme = {}
    for theme in ("classic", "noir"):
        monkeypatch.setattr(config, "THEME", theme)
        context = renderers._base_context("t", None)
        assert context["theme_css"] == (renderers.theme_dir() / "theme.css").read_text()
        css_by_theme[theme] = context["theme_css"]
    assert css_by_theme["classic"] != css_by_theme["noir"]


def test_theme_template_override_shadows_shared_template(tmp_path, monkeypatch):
    theme = tmp_path / "custom"
    theme.mkdir()
    (theme / "theme.css").write_text(":root {}")
    (theme / "home.html").write_text("OVERRIDDEN {{ title }}")
    monkeypatch.setattr(renderers, "_THEMES_DIR", tmp_path)
    monkeypatch.setattr(config, "THEME", "custom")

    env = renderers._env()
    assert env.get_template("home.html").render(title="x") == "OVERRIDDEN x"
    # Un-overridden templates still resolve from the shared templates dir.
    assert env.get_template("base.html") is not None


# ── browser tier: every theme renders the showcase edition ──

@pytest.mark.browser
@pytest.mark.parametrize("theme", renderers.available_themes())
def test_theme_renders_the_showcase_edition(theme, monkeypatch):
    """A theme is tokens + optional CSS + optional template overrides; an
    override that stops handling a figure kind (or a token a figure needs) shows
    up here as a failed render, not on the device."""
    monkeypatch.setattr(config, "THEME", theme)
    path = f"themetest/{theme.replace('-', '_')}"
    result = server.publish_edition(path, dict(_util.SHOWCASE_EDITION))
    assert result["success"] is True, result["error"]

    meta = store.get_view_meta(path)
    png = (config.DATA_DIR / "images" / f"{store.path_to_name(path)}.png").read_bytes()
    image = Image.open(BytesIO(png))
    assert image.size == (config.SCREEN_WIDTH, config.SCREEN_HEIGHT)
    assert image.mode == "L"
    assert {v for _count, v in image.getcolors(256)} <= {i * 17 for i in range(16)}

    assert any(t["action"] == "exit" for t in meta["taps"])

    # Whatever the theme does to the layout, the edition's links stay tappable —
    # including in a theme that ships its own article.html, which is a copy of
    # the shared template and has to be brought forward by hand.
    targets = {t["target"] for page in _pages(path) for t in page["taps"]
               if t["action"] == "navigate"}
    assert {"ops/fleet", "life/nutrition"} <= targets


def _pages(path):
    metas = []
    for i in range(1, 20):
        meta = store.get_view_meta(path if i == 1 else f"{path}/p{i}")
        if meta is None:
            break
        metas.append(meta)
    return metas
