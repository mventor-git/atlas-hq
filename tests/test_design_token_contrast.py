"""Automated contrast verification for the §39 web UI design tokens.

`contract.md` §39.1 makes the §39.2 token table the source of truth, so this
test parses that table instead of restating its values. §39.5 requires every
token pair in both themes to be verified by an automated run rather than by
eye, permits exactly three named exceptions, and requires a pair §39.3 forbids
to be reported as forbidden rather than as a pass. There is no UI yet (§39.7):
this is the check, not a frontend.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONTRACT = Path(__file__).parents[1] / "contract.md"
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
TABLE_ROW = re.compile(r"^\|\s*`(?P<token>[a-zA-Z][a-zA-Z.]*)`\s*\|")

#: W3C WCAG 2.1 SC 1.4.3 (text) and SC 1.4.11 (non-text), per §39.5.
TEXT_MINIMUM = 4.5
NON_TEXT_MINIMUM = 3.0

LIGHT, DARK = 0, 1
THEMES = ("light", "dark")

#: ``None`` as the background means the token's own fill: every ``state.*`` cell
#: is an ink and a fill that §39.2 says are never separated.
TEXT_PAIRS = (
    ("fg.default", "bg.canvas"),
    ("fg.default", "bg.surface"),
    ("onAccent.default", "accent.default"),
    ("state.success", None),
    ("state.warning", None),
    ("state.danger", None),
    ("state.info", None),
)
NON_TEXT_PAIRS = (
    ("border.control", "bg.canvas"),
    ("border.control", "bg.surface"),
    ("focus.ring", "bg.canvas"),
    ("focus.ring", "bg.surface"),
    ("focus.ring.onAccent", "accent.default"),
    ("state.success.indicator", None),
)
#: §39.3 forbids this pair in the dark theme, so it is checked as forbidden.
FORBIDDEN = (("focus.ring", "accent.default"),)
#: The only other pairs allowed to sit below 3:1: decorative dividers.
DECORATIVE = (("border.divider", "bg.canvas"), ("border.divider", "bg.surface"))


def _token_table() -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """The §39.2 table: token name -> (light values, dark values)."""
    lines = CONTRACT.read_text(encoding="utf-8").splitlines()
    table: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    for line in lines[lines.index("## 39.2 TOKEN TABLE") + 1 :]:
        if line.startswith("## "):
            break
        match = TABLE_ROW.match(line)
        if match is None:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        table[match["token"]] = (tuple(HEX.findall(cells[1])), tuple(HEX.findall(cells[2])))
    return table


TOKENS = _token_table()


def _values(token: str, theme: int) -> tuple[str, ...]:
    return TOKENS[token][theme]


def _pair(foreground: str, background: str | None, theme: int) -> tuple[str, str]:
    values = _values(foreground, theme)
    ink = values[0]
    fill = values[1] if background is None else _values(background, theme)[0]
    return ink, fill


def _luminance(hex_value: str) -> float:
    channels = [int(hex_value[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _ratio(foreground: str, background: str) -> float:
    first, second = _luminance(foreground), _luminance(background)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


def _measured(foreground: str, background: str | None, theme: int) -> float:
    ink, fill = _pair(foreground, background, theme)
    return _ratio(ink, fill)


CHECKS = [(theme, *pair, TEXT_MINIMUM) for theme in (LIGHT, DARK) for pair in TEXT_PAIRS] + [
    (theme, *pair, NON_TEXT_MINIMUM) for theme in (LIGHT, DARK) for pair in NON_TEXT_PAIRS
]


def test_both_themes_use_the_same_token_names_with_a_decided_value() -> None:
    """§39.2/§39.5: one role, one name, no UNRESOLVED cell, no ``fg.muted`` hex."""
    assert "fg.muted" not in TOKENS, "fg.muted is derived, not a table cell"
    for token, (light, dark) in TOKENS.items():
        assert light and dark, f"{token} has no value in one theme"
        assert len(light) == len(dark) in (1, 2), f"{token} is not a pair in both themes"
    assert len(TOKENS) == 14, sorted(TOKENS)


@pytest.mark.parametrize(("theme", "foreground", "background", "minimum"), CHECKS)
def test_every_pair_meets_its_wcag_minimum(
    theme: int,
    foreground: str,
    background: str | None,
    minimum: float,
) -> None:
    assert _measured(foreground, background, theme) >= minimum, (
        f"{THEMES[theme]} {foreground} on {background or 'its own fill'}"
    )


def test_every_token_in_the_table_is_checked_by_this_run() -> None:
    """A pair measured against one background only is not checked (§39.5)."""
    pairs = TEXT_PAIRS + NON_TEXT_PAIRS + DECORATIVE + FORBIDDEN
    checked = {pair[0] for pair in pairs}
    checked.update(pair[1] for pair in pairs if pair[1])

    assert set(TOKENS) - checked == set()


@pytest.mark.parametrize("theme", (LIGHT, DARK))
def test_both_divider_values_stay_decorative_below_the_non_text_minimum(theme: int) -> None:
    """The named §39.5 exception survives only while it stays decorative."""
    for foreground, background in DECORATIVE:
        assert _measured(foreground, background, theme) < NON_TEXT_MINIMUM


@pytest.mark.parametrize("theme", (LIGHT, DARK))
def test_the_success_indicator_clears_non_text_and_still_fails_as_text(theme: int) -> None:
    """The one size/role exemption: 3:1 as an indicator, never 4.5:1 as text."""
    measured = _measured("state.success.indicator", None, theme)

    assert NON_TEXT_MINIMUM <= measured < TEXT_MINIMUM


@pytest.mark.parametrize("theme", (LIGHT, DARK))
def test_the_forbidden_focus_pair_is_reported_as_forbidden(theme: int) -> None:
    """§39.3/§39.5: the dark pair fails, so the token carve-out is load-bearing."""
    measured = _measured(*FORBIDDEN[0], theme)

    if theme is DARK:
        assert measured < NON_TEXT_MINIMUM
    else:
        assert measured >= NON_TEXT_MINIMUM


def test_the_accent_fill_that_fails_three_to_one_is_a_fill_not_a_boundary() -> None:
    """§39.5: the 2.71:1 light accent is not a fourth exception."""
    assert _measured("accent.default", "bg.canvas", LIGHT) < NON_TEXT_MINIMUM
    assert _measured("focus.ring.onAccent", "accent.default", LIGHT) >= NON_TEXT_MINIMUM
    assert _measured("onAccent.default", "accent.default", LIGHT) >= TEXT_MINIMUM
