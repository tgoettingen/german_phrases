"""Persist per-phrase review state, daily counters and settings in a JSON file."""
import json
import os
import tempfile
from datetime import date
from pathlib import Path

from display_options import clean_direction
from srs import CardState

DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "progress.json"
DEFAULT_SETTINGS = {
    "level": "B1",            # "B1", "B2", "C1" or "ALL"
    "direction": "de_to_en",  # a key of display_options.DIRECTIONS
    "new_per_day": 20,
    # Used by trainer.py only:
    "topic": "ALL",
    "answer_mode": "reveal",  # "reveal" or "type"
    "daily_goal": 30,         # ratings per day that make a "good day"
    "voice": "",              # speech voice name, "" = best German voice found
    "speech_rate": 0.9,       # speech speed, 1.0 = normal
    "text_size": 100,         # percent of the normal text size
    "autoplay_content": "phrase_examples",  # a key of display_options.AUTOPLAY_CONTENT
    "autoplay_langs": ["de", "en", "zh"],    # phrase languages Auto play speaks, in order
    "lists_langs": ["de", "en", "zh"],       # language columns in the Lists tab
    "lists_examples": False,                 # examples column in the Lists tab
}


class Progress:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        self.cards: dict[str, CardState] = {}
        self.settings: dict = dict(DEFAULT_SETTINGS)
        self.daily: dict = {"date": "", "new": 0, "reviews": 0}
        # One entry per rating: [iso_date, phrase_id, rating, seconds, was_new].
        self.log: list[list] = []
        self.starred: set[str] = set()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.cards = {pid: CardState.from_dict(s) for pid, s in data.get("cards", {}).items()}
        self.settings.update(data.get("settings", {}))
        self.settings["direction"] = clean_direction(self.settings["direction"])
        self.daily.update(data.get("daily", {}))
        self.log = data.get("log", [])
        self.starred = set(data.get("starred", []))

    def save(self) -> None:
        data = {
            "settings": self.settings,
            "daily": self.daily,
            "starred": sorted(self.starred),
            "log": self.log,
            "cards": {pid: s.to_dict() for pid, s in self.cards.items()},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file first so a crash never leaves a half-written file.
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, self.path)

    def state(self, phrase_id: str) -> CardState:
        return self.cards.get(phrase_id) or CardState()

    def counters(self, today: date) -> dict:
        """Today's new/review counters, reset when the date changes."""
        if self.daily.get("date") != today.isoformat():
            self.daily = {"date": today.isoformat(), "new": 0, "reviews": 0}
        return self.daily
