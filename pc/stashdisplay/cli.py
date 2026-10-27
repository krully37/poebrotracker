"""Command line entry point.

    stashdisplay preview [--out DIR] [--scale N] [--seed N] [--offline]
        Render every page with demo data to PNG files (no screen, no WealthyExile needed).
        Downloads game icons and the Fontin font into the local cache the first time,
        unless --offline.
"""

import argparse
import sys
import time
from pathlib import Path

from . import pages as pagelib
from .assets import AssetCache
from .history import History
from .render import data as renderdata
from .render import fonts, renderer
from .render.data import ItemPrice
from .sources.demo import DemoSource


def demo_render_data(now: float, seed: int | None = None, assets: AssetCache | None = None) -> renderdata.RenderData:
    """About 6 hours of fake history, a session that started 2 hours ago, and fake poe.ninja prices."""
    source = DemoSource(seed=seed)
    source.sim_time = now
    history = History(path=None)
    snapshots = source.backfill(72)
    for snap in snapshots:
        history.add(snap.time, snap.total, snap.league)
    last = snapshots[-1]
    history.start_session(now - 2 * 3600 - 5 * 60)
    # Pretend the league started 9 days ago with a much smaller stash.
    history.league_starts[last.league] = (now - 9 * 86400, round(last.total * 0.22, 1))
    prices = {
        "Mirror of Kalandra": ItemPrice(chaos=round(last.div_price * 1180), div=1180.0, change=-3.0),
        "Mageblood": ItemPrice(chaos=round(last.div_price * 182), div=182.0, change=7.5),
        "Headhunter": ItemPrice(chaos=round(last.div_price * 34.5), div=34.5, change=-12.0),
    }
    return renderdata.build(
        history, last, now=now, synced_at=now - 130, item_prices=prices, icon=assets.icon if assets else None
    )


def cmd_preview(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    assets = AssetCache(offline=args.offline)
    fonts.register_fontin(assets.fontin())
    data = demo_render_data(time.time(), seed=args.seed, assets=assets)
    shown = pagelib.visible(pagelib.preset())
    images, labels = [], []
    for i, page in enumerate(shown):
        img = renderer.preview(page, data, i, len(shown))
        name = f"page{i + 1}-{page['id']}"
        img.save(out / f"{name}.png")
        renderer.overlay(page, data).save(out / f"{name}-overlay.png")
        if args.scale > 1:
            img.resize((img.width * args.scale, img.height * args.scale), resample=0).save(out / f"{name}@{args.scale}x.png")
        images.append(img)
        labels.append(f"{i + 1}. {page['name']}  ({page['template']})")
    sheet = renderer.contact_sheet(images, labels, scale=args.scale)
    sheet.save(out / "all-pages.png")
    print(f"Wrote {len(shown)} pages to {out.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stashdisplay")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preview", help="render all pages with demo data to PNG files")
    p.add_argument("--out", default="preview", help="output folder (default: ./preview)")
    p.add_argument("--scale", type=int, default=1, help="also write N-times enlarged copies")
    p.add_argument("--seed", type=int, default=7, help="demo data seed, for repeatable images")
    p.add_argument("--offline", action="store_true", help="only use icons and fonts already in the cache")
    p.set_defaults(func=cmd_preview)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
