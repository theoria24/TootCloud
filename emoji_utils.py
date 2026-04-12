"""Twemoji-based color emoji rendering utilities for TootCloud.

This module provides helpers to:
- Extract emoji tokens from text and count their frequencies.
- Map each emoji to a Twemoji SVG asset filename (codepoint sequence).
- Render SVG assets to RGBA PIL Images via cairosvg (cached).
- Composite rendered emoji onto a word-cloud PIL Image at the positions
  determined by wordcloud's layout algorithm.

Workflow summary
----------------
1. Extract emoji from raw text with :func:`extract_emoji_frequencies`.
2. Strip emoji from the text before passing it to MeCab with
   :func:`strip_emoji`.
3. Build placeholder ↔ emoji mappings with :func:`build_placeholder_map`
   and merge the placeholder frequencies into the word-frequency dict.
4. Generate the word cloud from the combined frequencies.
5. Make placeholder glyphs invisible by setting their colour to the
   background colour in ``wc.layout_``.
6. Call :func:`composite_emoji` to paste Twemoji images at the correct
   positions and orientations.
"""

import io
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import emoji as emoji_lib
from PIL import Image, ImageFont

# ---------------------------------------------------------------------------
# Default configuration values (can be overridden by callers)
# ---------------------------------------------------------------------------
TWEMOJI_ASSETS_PATH: Path = Path(__file__).parent / "assets" / "twemoji" / "svg"
FONT_SIZE_SCALE: float = 1.0   # font_size (px) → emoji image size (px)
MAX_EMOJI_COUNT: int = 50      # maximum distinct emoji included in the cloud

# Placeholder token format: "_e<index>" (e.g. "_e0", "_e12")
_PLACEHOLDER_PREFIX = "_e"
_PLACEHOLDER_RE = re.compile(r"^_e\d+$")


# ---------------------------------------------------------------------------
# Twemoji filename helpers
# ---------------------------------------------------------------------------

def emoji_to_twemoji_stem(emoji_str: str) -> str:
    """Return the Twemoji SVG filename stem for *emoji_str*.

    Twemoji names are the Unicode codepoints of the emoji joined by hyphens
    in lowercase hexadecimal, e.g. ``"1f602"`` or ``"1f1ef-1f1f5"``.

    Parameters
    ----------
    emoji_str:
        A single emoji character (may be a multi-codepoint sequence).

    Returns
    -------
    str
        Codepoint stem, e.g. ``"1f602"`` or ``"2764-fe0f"``.
    """
    return "-".join(format(ord(c), "x") for c in emoji_str)


def find_twemoji_svg(emoji_str: str, assets_path: Path) -> Optional[Path]:
    """Return the :class:`~pathlib.Path` to the Twemoji SVG for *emoji_str*.

    Two lookups are tried in order:

    1. Codepoints including any ``U+FE0F`` variation selector.
    2. Codepoints with ``U+FE0F`` stripped (fallback for emoji whose Twemoji
       asset omits the variation selector).

    Parameters
    ----------
    emoji_str:
        A single emoji string.
    assets_path:
        Directory that contains Twemoji SVG files.

    Returns
    -------
    Path or None
        The SVG file path, or ``None`` if no matching file is found.
    """
    stem_full = emoji_to_twemoji_stem(emoji_str)
    candidate_full = assets_path / f"{stem_full}.svg"
    if candidate_full.exists():
        return candidate_full

    # Fallback: drop variation selector U+FE0F
    stripped = "".join(c for c in emoji_str if ord(c) != 0xFE0F)
    if stripped != emoji_str:
        stem_stripped = emoji_to_twemoji_stem(stripped)
        candidate_stripped = assets_path / f"{stem_stripped}.svg"
        if candidate_stripped.exists():
            return candidate_stripped

    return None


# ---------------------------------------------------------------------------
# Render cache and SVG rendering
# ---------------------------------------------------------------------------

_render_cache: Dict[Tuple[str, int], Image.Image] = {}


def render_twemoji(
    emoji_str: str,
    size: int,
    assets_path: Path = TWEMOJI_ASSETS_PATH,
) -> Optional[Image.Image]:
    """Render a Twemoji SVG to a square RGBA PIL :class:`~PIL.Image.Image`.

    Results are cached by ``(emoji_str, size)`` so repeated calls for the
    same emoji at the same size are free.

    Parameters
    ----------
    emoji_str:
        A single emoji string.
    size:
        Desired side length of the output image in pixels.
    assets_path:
        Directory containing Twemoji SVG files.

    Returns
    -------
    PIL Image (RGBA) or None
        The rendered emoji image, or ``None`` if the SVG asset is not found.
    """
    cache_key = (emoji_str, size)
    cached = _render_cache.get(cache_key)
    if cached is not None:
        return cached

    svg_path = find_twemoji_svg(emoji_str, assets_path)
    if svg_path is None:
        return None

    import cairosvg  # deferred import – cairosvg is optional at module load

    png_bytes = cairosvg.svg2png(
        url=str(svg_path), output_width=size, output_height=size
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    _render_cache[cache_key] = img
    return img


# ---------------------------------------------------------------------------
# Emoji extraction helpers
# ---------------------------------------------------------------------------

def extract_emoji_frequencies(text: str) -> Dict[str, int]:
    """Count occurrences of each Unicode emoji in *text*.

    Parameters
    ----------
    text:
        Raw input text (may contain HTML-decoded Unicode).

    Returns
    -------
    dict
        ``{emoji_str: count}`` mapping.
    """
    freqs: Dict[str, int] = {}
    for item in emoji_lib.emoji_list(text):
        e = item["emoji"]
        freqs[e] = freqs.get(e, 0) + 1
    return freqs


def strip_emoji(text: str) -> str:
    """Remove all Unicode emoji from *text*.

    Use this to clean text before passing it to MeCab, which does not handle
    emoji gracefully.

    Parameters
    ----------
    text:
        Input text that may contain emoji.

    Returns
    -------
    str
        Text with all emoji replaced by empty string.
    """
    return emoji_lib.replace_emoji(text, replace="")


# ---------------------------------------------------------------------------
# Placeholder helpers
# ---------------------------------------------------------------------------

def make_placeholder(index: int) -> str:
    """Return a unique placeholder token for the emoji at position *index*.

    Placeholders are short ASCII strings of the form ``_e<N>`` (e.g. ``_e0``,
    ``_e12``).  They are used as word-cloud tokens so that wordcloud's layout
    engine reserves space for each emoji.

    Parameters
    ----------
    index:
        Zero-based position of the emoji in the sorted-by-frequency list.
    """
    return f"{_PLACEHOLDER_PREFIX}{index}"


def is_placeholder(word: str) -> bool:
    """Return ``True`` if *word* is an emoji placeholder token."""
    return bool(_PLACEHOLDER_RE.match(word))


def build_emoji_wordmap(
    emoji_freqs: Dict[str, int],
    max_count: int = MAX_EMOJI_COUNT,
) -> Tuple[Dict[str, str], Dict[str, int]]:
    """Build an identity emoji-word mapping for direct emoji rendering in word clouds.

    Unlike :func:`build_placeholder_map`, this function uses the emoji
    characters themselves as the word-cloud tokens instead of opaque ``_eN``
    placeholders.  Wordcloud renders each emoji with the configured font
    (monochrome), giving collision detection based on the actual glyph shape.
    Color Twemoji images are then composited on top at exactly those positions.

    Kazesawa (the default font) renders every emoji glyph as a square whose
    side length is approximately ``font_size * 0.73``.
    This square bbox is what wordcloud's layout engine reserves,
    so replacing it with a same-sized Twemoji avoids any overlap with adjacent
    words.

    Parameters
    ----------
    emoji_freqs:
        ``{emoji_str: count}`` as returned by :func:`extract_emoji_frequencies`.
    max_count:
        Maximum number of distinct emoji to include.

    Returns
    -------
    emoji_map : dict
        ``{emoji_str: emoji_str}`` — identity mapping.  The same emoji string
        is both the wordcloud token and the Twemoji lookup key.
    emoji_word_freqs : dict
        ``{emoji_str: count}`` trimmed to the top *max_count* entries by
        frequency — ready to merge into word frequencies for
        ``WordCloud.generate_from_frequencies()``.
    """
    sorted_emoji = sorted(
        emoji_freqs.items(), key=lambda kv: kv[1], reverse=True
    )[:max_count]

    emoji_map: Dict[str, str] = {e: e for e, _ in sorted_emoji}
    emoji_word_freqs: Dict[str, int] = dict(sorted_emoji)
    return emoji_map, emoji_word_freqs


def build_placeholder_map(
    emoji_freqs: Dict[str, int],
    max_count: int = MAX_EMOJI_COUNT,
) -> Tuple[Dict[str, str], Dict[str, int]]:
    """Build bidirectional placeholder ↔ emoji mappings from frequency data.

    Emoji are sorted by descending frequency and the top *max_count* are
    assigned placeholder tokens.

    Parameters
    ----------
    emoji_freqs:
        ``{emoji_str: count}`` as returned by :func:`extract_emoji_frequencies`.
    max_count:
        Maximum number of distinct emoji to include.

    Returns
    -------
    placeholder_to_emoji : dict
        ``{placeholder_token: emoji_str}``
    placeholder_freqs : dict
        ``{placeholder_token: count}`` – ready to merge into word frequencies
        and pass to ``WordCloud.generate_from_frequencies()``.
    """
    sorted_emoji = sorted(
        emoji_freqs.items(), key=lambda kv: kv[1], reverse=True
    )[:max_count]

    placeholder_to_emoji: Dict[str, str] = {}
    placeholder_freqs: Dict[str, int] = {}
    for i, (emoji_str, freq) in enumerate(sorted_emoji):
        ph = make_placeholder(i)
        placeholder_to_emoji[ph] = emoji_str
        placeholder_freqs[ph] = freq

    return placeholder_to_emoji, placeholder_freqs


# ---------------------------------------------------------------------------
# Compositing
# ---------------------------------------------------------------------------

def composite_emoji(
    wc_image: Image.Image,
    layout_: List,
    placeholder_to_emoji: Dict[str, str],
    assets_path: Path = TWEMOJI_ASSETS_PATH,
    font_size_scale: float = FONT_SIZE_SCALE,
    wc_scale: float = 1.0,
    font_path: Optional[str] = None,
) -> Image.Image:
    """Composite Twemoji images onto a word-cloud image at emoji token positions.

    For each entry in *layout_* that is present as a key in
    *placeholder_to_emoji* the corresponding Twemoji SVG is rendered and pasted
    onto *wc_image* at the position and orientation determined by wordcloud's
    layout algorithm.

    Position and orientation conventions
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    wordcloud stores ``position = (row, col)`` where ``row`` is the
    y-coordinate and ``col`` is the x-coordinate in pixels (before scaling).
    ``to_image()`` draws text at ``(col * scale, row * scale)`` in Pillow
    ``(x, y)`` notation, which is what we replicate here.

    ``orientation`` is ``None`` for horizontal text and
    ``PIL.Image.ROTATE_90`` for text rotated 90° counter-clockwise.

    Sizing and position rationale
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Wordcloud's collision detection uses
    ``draw.textbbox((0, 0), word, font=font, anchor="lt")`` to determine the
    reserved area height (*lt_h*).  However, the actual drawing in
    ``generate_from_frequencies`` and ``to_image()`` both call ``draw.text``
    with the **default Pillow anchor** ``"la"`` (left-ascender), which places
    each glyph ``font.getbbox(word)[1]`` pixels (*la_y0*) **below** the stored
    anchor point.  This creates an anchor–glyph mismatch:

    - Collision box occupies ``[row, row + lt_h]`` (from ``textbbox("lt")``).
    - Actual glyph pixels occupy ``[row + la_y0, row + la_y0 + la_h]``
      (drawn with anchor ``"la"``; ``la_h == lt_h``).

    Words placed in the gap ``[row, row + la_y0]`` — where the collision box
    exists but no monochrome pixels do — can fit without triggering an
    occupancy conflict.  Their glyphs then extend into ``[row + la_y0, ...]``,
    which is exactly where the Twemoji must go.  Pasting without a y-offset
    (at ``y = row``) therefore causes large, systematic visual overlaps between
    the Twemoji and adjacent words.

    The fix is to apply ``y_offset = la_y0`` so the Twemoji is pasted at
    ``(col * scale, row * scale + la_y0 * scale)``, aligning it with the
    monochrome glyph and eliminating those major overlaps.

    The Twemoji is sized to ``la_h = lt_h = getbbox()[3] - getbbox()[1]``,
    the visible glyph height (identical to ``textbbox("lt")[3]`` and
    ``getmask().size[1]`` in practice).

    When *font_path* is ``None`` the size falls back to
    ``font_size * wc_scale * font_size_scale`` and no y-offset is applied.

    Parameters
    ----------
    wc_image:
        PIL Image produced by ``WordCloud.to_image()``.
    layout_:
        ``wc.layout_`` — list of
        ``((word, count), font_size, (row, col), orientation, color)``.
    placeholder_to_emoji:
        ``{word_token: emoji_str}`` mapping.  Can be the identity dict
        ``{emoji_str: emoji_str}`` returned by :func:`build_emoji_wordmap`
        (recommended) or the old-style ``{_eN: emoji_str}`` dict from
        :func:`build_placeholder_map`.  Only words present as keys are
        composited; all others are skipped.
    assets_path:
        Directory containing Twemoji SVG files.
    font_size_scale:
        Multiplier applied to the emoji image size.
    wc_scale:
        ``wc.scale`` (default ``1``).  Applied to both position coordinates
        and font_size, matching the scaling used by ``WordCloud.to_image()``.
    font_path:
        Path to the TrueType font used by the word cloud.  When provided,
        ``font.getbbox(word)`` is used to derive both the emoji size
        (``la_h = getbbox()[3] - getbbox()[1]``, identical to ``getmask().size[1]``)
        and the vertical offset (*la_y0* = ``getbbox()[1]``) for correct
        glyph alignment.

    Returns
    -------
    PIL Image (RGB)
        The word-cloud image with emoji composited in place of their tokens.
    """
    result = wc_image.convert("RGBA")

    # Cache glyph metrics keyed by (scaled_font_size, word).
    # Value is (mask_h, la_y0) or None on failure.
    _bbox_cache: Dict[Tuple[int, str], Optional[Tuple[int, int]]] = {}

    for (word, count), font_size, position, orientation, color in layout_:
        if word not in placeholder_to_emoji:
            continue

        emoji_str = placeholder_to_emoji[word]

        scaled_font_size = max(1, int(font_size * wc_scale))

        # la_y0: vertical offset from the recorded anchor point to the top of
        # the visible glyph.  Applied to y_pixel below so the Twemoji lands
        # on the actual drawn glyph (see positioning rationale in the
        # docstring).
        la_y0 = 0
        if font_path is not None:
            cache_key = (scaled_font_size, word)
            if cache_key not in _bbox_cache:
                try:
                    _font = ImageFont.truetype(font_path, scaled_font_size)
                    bb = _font.getbbox(word)
                    # getbbox uses the default "la" anchor:
                    # (left, la_y0, right, la_y0 + la_h).  la_h == mask_h.
                    _bbox_cache[cache_key] = (bb[3] - bb[1], bb[1])
                except Exception:
                    _bbox_cache[cache_key] = None
            cached = _bbox_cache[cache_key]
            if cached is not None:
                mask_h, la_y0 = cached
                size = max(1, int(mask_h * font_size_scale))
            else:
                size = max(1, int(scaled_font_size * font_size_scale))
        else:
            size = max(1, int(scaled_font_size * font_size_scale))

        emoji_img = render_twemoji(emoji_str, size, assets_path)
        if emoji_img is None:
            continue

        # position = (row, col) == (y_pixel, x_pixel) before scaling.
        # wordcloud records the "la" (left-ascender) anchor point as the
        # word position in layout_, and both generate_from_frequencies and
        # to_image() draw glyphs with the default "la" anchor.  This places
        # every glyph la_y0 pixels *below* the stored row value.  We must
        # shift the Twemoji by the same amount so it aligns with the
        # monochrome glyph rather than the raw anchor point.
        x_pixel = int(position[1] * wc_scale)
        y_pixel = int(position[0] * wc_scale) + int(la_y0 * wc_scale)

        if orientation is not None:
            # ROTATE_90 rotates the image 90° counter-clockwise to match how
            # wordcloud renders vertically-oriented words.
            emoji_img = emoji_img.rotate(90, expand=True)

        result.paste(emoji_img, (x_pixel, y_pixel), emoji_img)

    return result.convert("RGB")
