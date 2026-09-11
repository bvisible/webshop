#!/usr/bin/env python3
# //// Neoffice — added file (no upstream equivalent).
"""Compare two capture sets of the visual harness, page by page.

    python3 tests/e2e/visual/compare.py baseline after [--threshold 0.5]

For every page present in both sets: the share of pixels that differ, the
change in page height, and a diff image (visual/shots/<after>/diff/<page>.png)
where the moved pixels are drawn in red over a faded copy of the "after" capture.
Exit code 1 when any page moves more than the threshold, so a CI step can gate.

A page whose height changed is compared over the common area and reported
separately: a template that grew or shrank is news on its own.
"""

import argparse
import json
import os
import sys

from PIL import Image, ImageChops

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "shots")


def load(label):
	folder = os.path.join(SHOTS, label)
	if not os.path.isdir(folder):
		sys.exit(f"no capture set named {label!r} in {SHOTS}")
	return folder, {f[:-4] for f in os.listdir(folder) if f.endswith(".png")}


def compare_one(before_path, after_path, diff_path):
	before = Image.open(before_path).convert("RGB")
	after = Image.open(after_path).convert("RGB")
	height_delta = after.height - before.height
	width = min(before.width, after.width)
	height = min(before.height, after.height)
	before_c = before.crop((0, 0, width, height))
	after_c = after.crop((0, 0, width, height))
	diff = ImageChops.difference(before_c, after_c).convert("L")
	# anti-aliasing and font hinting move a few pixels by a few levels: ignore them
	mask = diff.point(lambda v: 255 if v > 24 else 0)
	changed = sum(1 for v in mask.getdata() if v)
	ratio = changed / float(width * height) if width and height else 0.0
	if changed:
		faded = Image.blend(after_c, Image.new("RGB", after_c.size, "white"), 0.6)
		red = Image.new("RGB", after_c.size, (220, 30, 30))
		faded.paste(red, mask=mask)
		os.makedirs(os.path.dirname(diff_path), exist_ok=True)
		faded.save(diff_path)
	return ratio, height_delta


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("before")
	parser.add_argument("after")
	parser.add_argument("--threshold", type=float, default=0.5, help="percent of pixels allowed to move")
	args = parser.parse_args()

	before_dir, before_pages = load(args.before)
	after_dir, after_pages = load(args.after)
	common = sorted(before_pages & after_pages)
	rows, moved = [], []
	for page in common:
		ratio, height_delta = compare_one(
			os.path.join(before_dir, page + ".png"),
			os.path.join(after_dir, page + ".png"),
			os.path.join(after_dir, "diff", page + ".png"),
		)
		percent = ratio * 100
		flag = "MOVED" if percent > args.threshold or abs(height_delta) > 4 else "same"
		if flag == "MOVED":
			moved.append(page)
		rows.append((page, percent, height_delta, flag))

	width = max((len(p) for p in common), default=10)
	print(f"{'page':{width}}  {'pixels':>8}  {'height':>8}  ")
	for page, percent, height_delta, flag in rows:
		print(f"{page:{width}}  {percent:7.2f}%  {height_delta:+7d}  {flag}")
	missing = sorted((before_pages | after_pages) - set(common))
	if missing:
		print("only on one side:", ", ".join(missing))
	report = {"before": args.before, "after": args.after, "threshold": args.threshold,
	          "pages": {p: {"pixels_percent": round(pc, 3), "height_delta": hd, "flag": f} for p, pc, hd, f in rows},
	          "moved": moved}
	with open(os.path.join(after_dir, "compare.json"), "w", encoding="utf-8") as fh:
		json.dump(report, fh, indent=1)
	print(f"\n{len(moved)} page(s) moved beyond {args.threshold}% — diffs in {os.path.join(after_dir, 'diff')}" if moved
	      else f"\nno page moved beyond {args.threshold}%")
	sys.exit(1 if moved else 0)


if __name__ == "__main__":
	main()
