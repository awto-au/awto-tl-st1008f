#!/usr/bin/env python3
"""Board-photo helpers for reading markings (docs/BOM.md).

- sheet DIR OUT: contact sheet of every JPEG in DIR, labelled thumbnails.
- crop IMG OUT X0 Y0 X1 Y1 [--scale S] [--rot DEG] [--enhance]: crop, rotate, upscale.
- downscale IMG OUT [--max PX] [--box X0 Y0 X1 Y1]: copy for docs/photos (EXIF dropped).
Coordinates are pixels of the EXIF-transposed image. Log: tmp/logs/photo_crop.log.
"""
import argparse
import logging
import pathlib
import sys

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp" / "logs" / "photo_crop.log"


def load(path):
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def sheet(args):
    files = sorted(p for p in pathlib.Path(args.dir).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    tw, cols = args.thumb, args.cols
    bh = int(tw * args.aspect)
    th = bh + 16
    rows = (len(files) + cols - 1) // cols
    out = Image.new("RGB", (cols * tw, rows * th), "white")
    d = ImageDraw.Draw(out)
    for i, f in enumerate(files):
        im = load(f)
        logging.info("%s %dx%d", f.name, *im.size)
        im.thumbnail((tw, bh))
        x, y = (i % cols) * tw, (i // cols) * th
        out.paste(im, (x, y + 16))
        d.text((x + 2, y + 2), f.name, fill="black")
    out.save(args.out, quality=85)
    logging.info("sheet %s: %d images", args.out, len(files))


def crop(args):
    im = load(args.img)
    c = im.crop((args.x0, args.y0, args.x1, args.y1))
    if args.rot:
        c = c.rotate(args.rot, expand=True, resample=Image.BICUBIC)
    if args.scale != 1:
        c = c.resize((int(c.width * args.scale), int(c.height * args.scale)), Image.LANCZOS)
    if args.enhance:
        c = ImageOps.autocontrast(c, cutoff=1)
        c = ImageEnhance.Sharpness(c).enhance(2.0)
    c.save(args.out, quality=92)
    logging.info("crop %s (%d,%d)-(%d,%d) -> %s %dx%d", args.img, args.x0, args.y0, args.x1, args.y1, args.out, *c.size)


def downscale(args):
    im = load(args.img)
    if args.box:
        im = im.crop(tuple(args.box))
    im.thumbnail((args.max, args.max), Image.LANCZOS)
    im.save(args.out, quality=args.quality, optimize=True)  # no exif= : metadata dropped
    size = pathlib.Path(args.out).stat().st_size
    logging.info("downscale %s -> %s %dx%d %d bytes", args.img, args.out, *im.size, size)
    if size > 1_000_000:
        logging.error("%s is %d bytes, over the 1 MB repo limit", args.out, size)
        sys.exit(1)


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(LOG), logging.StreamHandler()])
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("dir")
    s.add_argument("out")
    s.add_argument("--thumb", type=int, default=400)
    s.add_argument("--cols", type=int, default=5)
    s.add_argument("--aspect", type=float, default=0.75, help="cell height / width")
    s.set_defaults(fn=sheet)
    c = sub.add_parser("crop")
    c.add_argument("img")
    c.add_argument("out")
    for k in ("x0", "y0", "x1", "y1"):
        c.add_argument(k, type=int)
    c.add_argument("--scale", type=float, default=1.0)
    c.add_argument("--rot", type=float, default=0.0)
    c.add_argument("--enhance", action="store_true")
    c.set_defaults(fn=crop)
    d = sub.add_parser("downscale")
    d.add_argument("img")
    d.add_argument("out")
    d.add_argument("--max", type=int, default=1600)
    d.add_argument("--quality", type=int, default=82)
    d.add_argument("--box", type=int, nargs=4)
    d.set_defaults(fn=downscale)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
