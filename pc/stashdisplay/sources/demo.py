"""Fake but plausible data, so the screen can be built without WealthyExile.

Each fetch advances a simulated clock by `step` seconds, so the sparkline and the
divines/hour fill up in seconds instead of hours.
"""

import random
import time

from .base import Item, Snapshot, Tab

# (name, tab, quantity, value per unit in divines)
_STOCK = [
    ("Divine Orb", "Currency", 120, 1.0),
    ("Mirror Shard", "Currency", 3, 9.5),
    ("Chaos Orb", "Currency", 4200, 1 / 215),
    ("Exalted Orb", "Currency", 310, 0.07),
    ("Orb of Conflict", "Currency", 9, 0.9),
    ("Awakened Empower Support", "Gems", 1, 24.0),
    ("Valdo's Puzzle Box", "Maps", 6, 1.6),
    ("The Apothecary", "Cards", 2, 6.8),
    ("Divine Vessel", "Fragments", 38, 0.06),
    ("Ambush Scarab of Containment", "Scarabs", 44, 0.1),
    ("Fracturing Orb", "Currency", 11, 0.55),
    ("Eldritch Chaos Orb", "Currency", 70, 0.02),
]


class DemoSource:
    def __init__(self, step: float = 300, seed: int | None = None):
        self.step = step
        self.rng = random.Random(seed)
        self.sim_time = time.time()
        # Per-item multiplier that drifts up over time: the stash "grows".
        self.qty = {name: q for name, _, q, _ in _STOCK}

    def backfill(self, points: int) -> list[Snapshot]:
        """Snapshots for the last `points` steps, so the screen starts with a full sparkline."""
        self.sim_time -= points * self.step
        return [self.fetch() for _ in range(points)]

    def fetch(self) -> Snapshot:
        self.sim_time += self.step
        rng = self.rng
        # Roughly +4 to +6 div/h on average, with noise, the odd big drop and the odd purchase.
        for name, _, base_q, unit in _STOCK:
            if unit < 1:
                self.qty[name] += max(0, round(rng.gauss(base_q * 0.001, base_q * 0.002)))
        if rng.random() < 0.25:
            self.qty["Divine Orb"] += 1
        if rng.random() < 0.015:
            self.qty["Divine Orb"] += rng.randint(3, 8)
        if rng.random() < 0.02:
            self.qty["Divine Orb"] = max(0, self.qty["Divine Orb"] - rng.randint(2, 6))

        items = [
            Item(name, self.qty[name], round(self.qty[name] * unit * rng.uniform(0.98, 1.02), 3), tab)
            for name, tab, _, unit in _STOCK
        ]
        tabs: dict[str, float] = {}
        for it in items:
            tabs[it.tab] = tabs.get(it.tab, 0) + it.value
        return Snapshot(
            total=round(sum(it.value for it in items), 2),
            time=self.sim_time,
            items=items,
            tabs=[Tab(n, round(v, 2)) for n, v in tabs.items()],
            div_price=round(rng.uniform(205, 225), 1),
            league="Demo",
        )
