"""Record what the Python app does, so tests/parity.test.js can check the JS port does the same.

Run after changing the Python learning logic:  python mobile/tools/make_fixtures.py
"""
import hashlib
import json
import random
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from answers import check  # noqa: E402
from display_options import (AUTOPLAY_CONTENT, DIRECTIONS, autoplay_steps, card_sides,  # noqa: E402
                             clean_langs)
from learning_log import classify, last_n_days, streaks, summarize  # noqa: E402
from phrase_filters import FILTERS, SORTS, select  # noqa: E402
from phrase_loader import load_all  # noqa: E402
from progress import Progress  # noqa: E402
from srs import RATINGS, CardState, format_interval, next_interval, review  # noqa: E402
from study import StudySession, statistics, todays_phrases  # noqa: E402
from trainer import card_status, filter_phrases  # noqa: E402

OUT = ROOT / "mobile" / "tests" / "fixtures.json"
START = date(2026, 3, 25)  # crosses a daylight-saving change and a month end


def srs_cases(rng: random.Random) -> list:
    cases = []
    for _ in range(300):
        state, today, steps = CardState(), START, []
        for _ in range(14):
            rating = rng.choice(RATINGS)
            preview = [next_interval(state, r) for r in RATINGS]
            state = review(state, rating, today)
            steps.append([rating, today.isoformat(), preview, state.to_dict()])
            today += timedelta(days=rng.choice([0, 1, state.interval, state.interval + 3]))
        cases.append(steps)
    return cases


def typo(rng: random.Random, text: str) -> str:
    if len(text) < 3:
        return text + "x"
    i = rng.randrange(len(text))
    return rng.choice([text[:i] + text[i + 1:], text[:i] + "q" + text[i:], text[:i] + "e" + text[i + 1:]])


def check_cases(rng: random.Random, phrases) -> list:
    cases = []
    for p in rng.sample(phrases, 250):
        ascii_german = p.german.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        for typed, expected in (
            (p.english, p.english), (p.german, p.german), (ascii_german, p.german),
            (typo(rng, p.german), p.german), (typo(rng, typo(rng, p.english)), p.english),
            (p.english.removeprefix("to "), p.english), (p.german.upper(), p.german),
            (p.german.split()[0], p.german), ("", p.german), ("???", p.english),
            (p.examples[0][0], p.german), (p.examples[0][0] * 4, p.examples[1][0] * 4),  # autojunk
        ):
            cases.append([typed, expected, *check(typed, expected)])
    return cases


LANG_CHOICES = [["de"], ["en"], ["zh"], ["de", "en"], ["zh", "de"], ["de", "en", "zh"], [], ["fr"], None]


def display_cases(rng: random.Random, phrases) -> dict:
    sample = [p for p in phrases if not p.examples][:2] + rng.sample(phrases, 6)
    return {
        "card_sides": [[d, list(card_sides(d))] for d in [*DIRECTIONS, "en_zh", None]],
        "clean_langs": [[langs, clean_langs(langs)] for langs in LANG_CHOICES],
        "autoplay_steps": [[p.id, content, langs, autoplay_steps(p, content, langs)]
                           for p in sample for content in [*AUTOPLAY_CONTENT, "bogus"]
                           for langs in LANG_CHOICES],
    }


def session_days(rng: random.Random, phrases, path: Path) -> tuple[list, Progress]:
    progress = Progress(path)
    progress.save = lambda: None  # saved once at the end; rapid file replaces fail on Windows
    progress.settings.update(new_per_day=12, daily_goal=25)
    pool = filter_phrases(phrases, "B1", "ALL")
    days = []
    for n in range(45):
        today = START + timedelta(days=n)
        if rng.random() < 0.15:  # a missed day
            continue
        session = StudySession(pool, progress, today)
        ops, start_queue = [], [p.id for p in session.queue]
        for _ in range(rng.randint(5, 70)):
            roll = rng.random()
            if roll < 0.06:
                op = ["undo", session.undo()]
            elif roll < 0.12:
                op = ["skip", session.skip()]
            elif roll < 0.15:
                count = rng.choice([3, 10])
                op = ["add_new", count, session.add_new(count)]
            elif session.current is None:
                break
            else:
                rating = rng.choices(RATINGS, weights=[3, 2, 5, 2])[0]
                seconds = round(rng.uniform(0, 90), 3)
                session.rate(rating, seconds)
                op = ["rate", rating, seconds]
            ops.append([*op, [p.id for p in session.queue], session.remaining()])
        days.append({
            "today": today.isoformat(), "start_queue": start_queue, "ops": ops,
            "todays": [p.id for p in todays_phrases(pool, progress, today)],
            "stats": statistics(phrases, progress, today),
            "status": {p.id: card_status(progress, p, today) for p in pool[:200:7]},
        })
    return days, progress


def main() -> None:
    rng = random.Random(1234)
    phrases = load_all()
    with tempfile.TemporaryDirectory() as tmp:
        days, progress = session_days(rng, phrases, Path(tmp) / "progress.json")
        Progress.save(progress)
        saved = json.loads((Path(tmp) / "progress.json").read_text(encoding="utf-8"))
    end = START + timedelta(days=45)
    summaries = summarize(progress.log)
    progress.starred = {p.id for p in rng.sample(phrases[:300], 25)}
    selections = []
    for kind in FILTERS:
        for sort in SORTS:
            for query in ("", "machen", "STRASSE", "der", "zu"):
                ids = [p.id for p in select(phrases, progress, kind, query, sort, today=end)]
                digest = hashlib.sha1(",".join(ids).encode()).hexdigest()
                selections.append([kind, sort, query, len(ids), ids[:20], digest])
    fixtures = {
        "start": START.isoformat(), "end": end.isoformat(),
        "settings": {"new_per_day": 12, "daily_goal": 25},
        "srs": srs_cases(rng),
        "format_interval": [[d, format_interval(d)] for d in [*range(0, 40), 45, 59, 60, 61, 89, 90,
                                                              100, 300, 364, 365, 400, 547, 548, 1000, 3650]],
        "check": check_cases(rng, phrases),
        "display": display_cases(random.Random(99), phrases),  # own seed: the other cases stay as they were
        "days": days,
        "progress": saved,
        "starred": sorted(progress.starred),
        "select": selections,
        "classify": [[(START + timedelta(days=i)).isoformat(),
                      classify(START + timedelta(days=i), summaries, 25, end)] for i in range(-3, 50)],
        "streaks": [[(START + timedelta(days=i)).isoformat(),
                     list(streaks(summaries, START + timedelta(days=i)))] for i in range(0, 50, 2)],
        "last_n_days": [[s.day.isoformat(), s.total, s.recalled, s.forgotten, s.new, round(s.seconds, 6)]
                        for s in last_n_days(summaries, end, 30)],
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(fixtures, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(progress.log)} log entries)")


if __name__ == "__main__":
    main()
