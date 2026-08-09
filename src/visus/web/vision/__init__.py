"""visus.web.vision — optional OCR + image-matching plugin (requires [vision] extra)."""

from visus.web.vision.imaging import Match, find_all_images, find_image
from visus.web.vision.ocr import TextBox, find_text, read_text, read_text_boxes, solve_captcha

__all__ = [
    "Match",
    "TextBox",
    "find_all_images",
    "find_image",
    "find_text",
    "read_text",
    "read_text_boxes",
    "solve_captcha",
]
