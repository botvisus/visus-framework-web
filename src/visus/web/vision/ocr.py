"""Text OCR via RapidOCR (lazy singleton), with and without geometry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image

from visus.web.vision._images import ImageInput, _to_ndarray

_engine = None


@dataclass(frozen=True)
class TextBox:
    """One recognised text run and where it was rendered.

    Coordinates are pixels of the image that was read. Mirrors
    :class:`visus.web.vision.Match` so a caller can click either an image match
    or a text match with the same two properties.
    """

    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2


def _get_engine() -> object:
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine


def read_text_boxes(image: ImageInput) -> list[TextBox]:
    """Every recognised text run with its bounding box, in OCR order.

    The geometry is what makes rendered text a *target*: a canvas app, an
    embedded PDF or a widget with no accessibility tree exposes no role, no name
    and no stable selector, but it still paints words at coordinates.
    """
    arr = _to_ndarray(image)
    engine = _get_engine()
    result, _ = engine(arr)  # type: ignore[operator]
    if not result:
        return []
    boxes: list[TextBox] = []
    for line in result:
        quad, text, score = line[0], str(line[1]), float(line[2])
        xs = [float(point[0]) for point in quad]
        ys = [float(point[1]) for point in quad]
        x, y = int(min(xs)), int(min(ys))
        boxes.append(
            TextBox(
                text=text,
                x=x,
                y=y,
                width=int(max(xs)) - x,
                height=int(max(ys)) - y,
                confidence=score,
            )
        )
    return boxes


def find_text(image: ImageInput, needle: str, *, exact: bool = False) -> TextBox | None:
    """The highest-confidence text run matching *needle* (case-insensitive).

    Substring by default (``"ubmi"`` finds ``"SUBMIT"``), because OCR routinely
    merges or splits neighbouring words; pass ``exact=True`` to require the whole
    recognised run. Returns ``None`` when nothing matches.
    """
    want = needle.strip().casefold()
    matches = [
        box
        for box in read_text_boxes(image)
        if (box.text.strip().casefold() == want if exact else want in box.text.casefold())
    ]
    if not matches:
        return None
    return max(matches, key=lambda box: box.confidence)


def read_text(image: ImageInput) -> str:
    """Extract all text from an image (any format). Returns space-joined lines."""
    return " ".join(box.text for box in read_text_boxes(image))


def _preprocess(arr: npt.NDArray[Any]) -> npt.NDArray[Any]:
    img = Image.fromarray(arr).convert("L")
    img = img.resize((img.width * 2, img.height * 2))  # upscale helps small captchas
    return np.array(img.convert("RGB"))


def solve_captcha(image: ImageInput, *, preprocess: bool = True) -> str:
    """Read a (usually distorted) text captcha. Collapses whitespace."""
    arr = _to_ndarray(image)
    if preprocess:
        arr = _preprocess(arr)
    return "".join(read_text(arr).split())
