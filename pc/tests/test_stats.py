from datetime import datetime

import pytest

from stashdisplay import stats
from stashdisplay.history import History

H = 3600


def line(start, count, step, v0, per_hour):
    return [(start + i * step, v0 + per_hour * i * step / H) for i in range(count)]


def test_rate_matches_a_steady_gain():
    pts = line(0, 13, 300, 100, 4.0)
    assert stats.rate_per_hour(pts, now=pts[-1][0]) == pytest.approx(4.0)


def test_rate_needs_enough_history():
    pts = line(0, 2, 300, 100, 4.0)
    assert stats.rate_per_hour(pts, now=pts[-1][0]) is None
    pts = line(0, 3, 60, 100, 4.0)  # 3 points but only 2 minutes
    assert stats.rate_per_hour(pts, now=pts[-1][0]) is None


def test_rate_only_uses_the_window():
    old = line(0, 12, 300, 0, 100.0)  # a huge gain long ago
    recent = line(10 * H, 13, 300, 500, 2.0)
    assert stats.rate_per_hour(old + recent, now=recent[-1][0]) == pytest.approx(2.0)


def test_session_gain_after_reset_starts_at_zero():
    pts = line(0, 10, 300, 100, 6.0)
    reset_at = pts[-1][0] + 10  # long press just after the last fetch
    assert stats.gain_since(pts, reset_at) == pytest.approx(0.0)
    pts.append((reset_at + 300, pts[-1][1] + 2))
    assert stats.gain_since(pts, reset_at) == pytest.approx(2.0)


def test_session_gain_ignores_a_stale_baseline():
    # PC was off for hours: the last point before the session is too old to use.
    pts = [(0, 100.0), (5 * H, 150.0), (5 * H + 300, 151.0)]
    assert stats.gain_since(pts, 5 * H - 5) == pytest.approx(1.0)


def test_session_without_points_yet():
    assert stats.gain_since([], 0) is None
    assert stats.gain_since([(0, 100.0)], 5 * H) == 0.0


def test_best_hour_skips_gaps():
    day = datetime(2026, 10, 27, 0, 0).astimezone().timestamp()
    pts = line(day + 9 * H, 13, 300, 100, 3.0)  # 9:00-10:00 at 3/h
    pts += [(day + 14 * H, 200.0)]  # big jump after a 4h gap: not one hour's gain
    pts += line(day + 14 * H + 300, 12, 300, 200.0 + 5.0 * 300 / H, 5.0)
    assert stats.best_hour(pts, day) == pytest.approx(5.0, abs=0.01)


def test_history_round_trip_and_league_start(tmp_path):
    h = History.load(tmp_path / "history.json")
    h.add(1000, 10.0, "Mercenaries")
    h.add(1300, 12.0, "Mercenaries")
    h.add(1200, 99.0, "Mercenaries")  # out of order: ignored
    h.start_session(1250)
    h.save()
    h2 = History.load(tmp_path / "history.json")
    assert h2.points == [(1000, 10.0), (1300, 12.0)]
    assert h2.session_start == 1250
    assert h2.league_starts == {"Mercenaries": (1000, 10.0)}


def test_an_unreadable_history_starts_again_and_keeps_the_file(tmp_path):
    path = tmp_path / "history.json"
    for broken in ('{"points": [[1, 2], [3', '{"points": [["soon", 2]]}', "[1, 2]"):
        path.write_text(broken, encoding="utf-8")
        h = History.load(path)
        assert h.points == [] and h.path == path
        assert (tmp_path / "history.broken.json").read_text(encoding="utf-8") == broken
    h.add(1000.0, 5.0, "Allflame")
    h.save()
    assert History.load(path).points == [(1000.0, 5.0)]
