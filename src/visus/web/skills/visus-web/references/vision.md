# Vision — OCR and image matching

```bash
pip install "visus-web[vision]"     # RapidOCR + OpenCV + Pillow + NumPy
```

Install it where the **daemon** runs — `read-text`, `solve-captcha` and
`find-image` all execute inside the daemon process (`session_server.py`'s
`_op_read_text` / `_op_solve_captcha` / `_op_find_image` import
`rapidocr_onnxruntime`, `cv2`, `numpy` and `PIL.Image` lazily, at call time).
Installing `[vision]` only where the CLI *client* runs does nothing — the
daemon is a separate process, possibly started before the extra was added.

```bash
visus read-text 4                          # OCR the element's screenshot
visus solve-captcha -s "#captcha"          # OCR a distorted text captcha
visus find-image button.png -c 0.85 --json # OpenCV template match over the page
visus find-image icon.png 4                # scope the search to field 4
```

`visus list-fields` no longer draws the numbered overlay unless you pass
`--highlight`, so the pixels stay clean by default. If you did opt in, run
`visus clear` before any of these — the highlight markers are real DOM nodes and
they show up in the image.

## Library entry points

```python
from visus.web.vision import read_text, solve_captcha, find_image, find_all_images, Match

read_text(page.screenshot())                                    # -> str
solve_captcha(page.screenshot(), preprocess=True)                # -> str
find_image(page.screenshot(), "logo.png", confidence=0.85)       # -> Match | None
find_all_images(page.screenshot(), "row.png", confidence=0.8)    # -> list[Match]

# Locator / page shortcuts (avoid the manual screenshot round-trip)
page.locator("#captcha").ocr_text()
page.solve_captcha(page.get_by_role("img", name="CAPTCHA"))
match = page.locator("#canvas").find_image("button.png", confidence=0.9)
```

`Match` carries `x, y, width, height, confidence` plus `center_x`/`center_y`
properties, so you can click the middle of a found template:

```python
if match:
    page.mouse.click(match.center_x, match.center_y)
```

`read_text`/`solve_captcha`/`find_image`/`find_all_images` all accept any
`ImageInput` — a file path, raw bytes, a `PIL.Image`, a `numpy` array, or a
base64 string — not just a live page screenshot.

If the extra is missing, the error surfaces as
`ModuleNotFoundError: No module named 'rapidocr_onnxruntime'` (from
`read-text`/`solve-captcha`) or `No module named 'cv2'` (from `find-image`) —
see [troubleshooting.md](troubleshooting.md).
