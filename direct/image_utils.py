"""Image preprocessing shared by training and evaluation.

mlx-vlm bypasses --image-resize-shape for models with native preprocessing
(qwen3_vl is one), so the flag cannot be relied on to bound vision-token count.
We downscale up front instead, which also guarantees training and eval see
pixel-identical inputs.

1280 is a compromise: small enough to keep a 4032x3024 photo under ~400 vision
tokens after Qwen's 28px patching and 2x2 merge, large enough that the digits on
a 料金 board stay legible -- OCR of those boards is the whole task.
"""

from pathlib import Path

from PIL import Image

MAX_SIDE = 1280

# These scripts live in direct/ but the image data sits at the project root, and
# the annotation JSONLs record paths relative to that root. Resolving against it
# explicitly keeps the scripts runnable from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def resolve(path):
    """Interpret a data path as project-root-relative unless it is absolute."""
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_resized(path, max_side=MAX_SIDE):
    """Open an image as RGB, downscaled so its longest side is at most max_side.

    Images already smaller than max_side are left alone -- upscaling adds no
    detail and only inflates the token count.
    """
    img = Image.open(path).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    return img
