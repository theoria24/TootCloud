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
    """Composite Twemoji images onto a word-cloud image at placeholder positions.

    For each placeholder entry in *layout_* the corresponding Twemoji SVG is
    rendered and pasted onto *wc_image* at the position and orientation
    determined by wordcloud's layout algorithm.

    Position and orientation conventions
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    wordcloud stores ``position = (row, col)`` where ``row`` is the
    y-coordinate and ``col`` is the x-coordinate in pixels (before scaling).
    ``to_image()`` draws text at ``(col * scale, row * scale)`` in Pillow
    ``(x, y)`` notation, which is what we replicate here.

    ``orientation`` is ``None`` for horizontal text and
    ``PIL.Image.ROTATE_90`` for text rotated 90° counter-clockwise.

    Font metrics and sizing
    ~~~~~~~~~~~~~~~~~~~~~~~
    When *font_path* is provided the function loads the word-cloud font at each
    encountered font size and measures the actual glyph bounding box of the
    placeholder token via ``ImageFont.getbbox``.  Two adjustments are then
    applied:

    1. **y-offset correction** – the glyph does not start at the PIL drawing
       origin; it is shifted downward by ``bbox[1]`` pixels.  Without this
       correction the emoji is pasted above the actual text area, overlapping
       words placed just above by the layout engine.
    2. **height-based sizing** – the emoji is sized to the *visible* glyph
       height (``bbox[3] - bbox[1]``) rather than the raw *font_size*, so its
       dimensions match the text it replaces.

    When *font_path* is ``None`` (default) the legacy behaviour is preserved:
    ``size = font_size * wc_scale * font_size_scale``, ``y_offset = 0``.

    Parameters
    ----------
    wc_image:
        PIL Image produced by ``WordCloud.to_image()``.
    layout_:
        ``wc.layout_`` – list of
        ``((word, count), font_size, (row, col), orientation, color)``.
    placeholder_to_emoji:
        ``{placeholder_token: emoji_str}`` from :func:`build_placeholder_map`.
    assets_path:
        Directory containing Twemoji SVG files.
    font_size_scale:
        Multiplier applied to the emoji image size.
    wc_scale:
        ``wc.scale`` (default ``1``).  Applied to both position coordinates
        and font_size, matching the scaling used by ``WordCloud.to_image()``.
    font_path:
        Path to the TrueType font used by the word cloud.  When provided,
        actual glyph metrics are used for precise sizing and positioning of
        each emoji, preventing overlaps with adjacent words.

    Returns
    -------
    PIL Image (RGB)
        The word-cloud image with emoji composited in place of placeholders.
    """
    result = wc_image.convert("RGBA")

    # Cache font bbox measurements keyed by (scaled_font_size, word) to avoid
    # repeated font loads for the same size.
    _bbox_cache: Dict[Tuple[int, str], Optional[Tuple[int, int, int, int]]] = {}

    for (word, count), font_size, position, orientation, color in layout_:
        if not is_placeholder(word):
            continue

        emoji_str = placeholder_to_emoji.get(word)
        if emoji_str is None:
            continue

        scaled_font_size = max(1, int(font_size * wc_scale))

        # Determine emoji size and y-offset from actual font glyph metrics.
        y_offset = 0
        if font_path is not None:
            cache_key = (scaled_font_size, word)
            if cache_key not in _bbox_cache:
                try:
                    _font = ImageFont.truetype(font_path, scaled_font_size)
                    _bbox_cache[cache_key] = _font.getbbox(word)
                except Exception:
                    _bbox_cache[cache_key] = None
            bbox = _bbox_cache[cache_key]
            if bbox is not None:
                visible_height = max(1, bbox[3] - bbox[1])
                size = max(1, int(visible_height * font_size_scale))
                y_offset = bbox[1]
            else:
                size = max(1, int(scaled_font_size * font_size_scale))
        else:
            size = max(1, int(scaled_font_size * font_size_scale))

        emoji_img = render_twemoji(emoji_str, size, assets_path)
        if emoji_img is None:
            continue

        # position = (row, col) == (y_pixel, x_pixel) before scaling.
        # to_image() places text at (col * scale, row * scale) in Pillow (x, y).
        # y_offset shifts the emoji down to align with the actual glyph top.
        x_pixel = int(position[1] * wc_scale)
        y_pixel = int(position[0] * wc_scale) + y_offset

        if orientation is not None:
            # ROTATE_90 rotates the image 90° counter-clockwise to match how
            # wordcloud renders vertically-oriented words.
            emoji_img = emoji_img.rotate(90, expand=True)

        result.paste(emoji_img, (x_pixel, y_pixel), emoji_img)

    return result.convert("RGB")
