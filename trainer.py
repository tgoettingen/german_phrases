"""German Phrase Trainer: spaced-repetition study plus browsing, lists and daily progress.

Run: python trainer.py

Shares data/progress.json with app.py, so both apps see the same learning state
(don't run both at the same time, or one will overwrite the other's progress).
"""
import csv
import calendar
import math
import random
import sys
import time
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from answers import check
from app import CJK_FONTS, UI_FONTS, pick_font
from display_options import (AUTOPLAY_CONTENT, DIRECTIONS, LANG_FIELD, LANG_LABELS, LANGS,
                             autoplay_steps, card_sides, clean_content, clean_langs, phrase_text)
from learning_log import (GOOD_DAY, HARD_DAY, MISSED, NO_DATA, STUDIED, DaySummary, classify,
                          last_n_days, streaks, summarize)
from phrase_filters import DIFFICULT_LAPSES, FILTERS, SORTS, select, was_forgotten
from phrase_import import CONVERTERS, REQUIRED, custom_collections, import_phrases, valid_name
from phrase_loader import Phrase, collections, load_all
from progress import Progress
from srs import AGAIN, GOOD, RATING_NAMES, RATINGS, format_interval
from study import PracticeSession, StudySession, statistics, todays_phrases
from tts import MAX_RATE, MIN_RATE, Speaker

ALL_TOPICS = "All topics"
ANSWER_MODES = {"reveal": "Reveal answer", "type": "Type the answer"}
EXTRA_NEW = 10
EXAMPLE_KEYS = ("d", "f", "g")  # speak example 1-3
CHART_DAYS = 30
# Text size in percent of the normal size; Ctrl/Cmd + and - change it in steps.
TEXT_SIZES = (70, 200, 10)
BASE_FONTS = {  # name: (family kind, size, weight)
    "front": ("ui", 26, "bold"), "front_chinese": ("cjk", 26, "bold"),
    "back": ("ui", 18, "normal"), "chinese": ("cjk", 18, "normal"),
    "small": ("ui", 10, "normal"), "example": ("ui", 13, "normal"), "section": ("ui", 12, "bold"),
    "tile": ("ui", 18, "bold"), "cell": ("ui", 9, "normal"),
}
TK_FONTS = ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont", "TkFixedFont",
            "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont")

# Ink and surfaces, plus a validated two-slot categorical palette for the chart.
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
SURFACE, GRID, BASELINE = "#fcfcfb", "#e1e0d9", "#c3c2b7"
SERIES_RECALLED, SERIES_FORGOTTEN = "#2a78d6", "#eb6834"
# Day highlights use the reserved status colors, always paired with an icon and a label.
DAY_STYLES = {  # kind: (cell tint, accent, icon, legend text)
    GOOD_DAY: ("#d3eed3", "#0ca30c", "★", "Good day: goal reached, 85%+ recalled"),
    STUDIED: ("#cde2fb", "#2a78d6", "✓", "Studied"),
    HARD_DAY: ("#fbe1d6", "#ec835a", "!", "Hard day: under 70% recalled"),
    MISSED: ("#f6d4d4", "#d03b3b", "✗", "Missed day: no study"),
    NO_DATA: (SURFACE, BASELINE, "", ""),
}
ROW_TINTS = {"forgotten": "#fbe1d6", "difficult": "#f6d4d4", "again": "#fbe1d6"}


def topics_for(phrases: list[Phrase], level: str) -> list[str]:
    return list(dict.fromkeys(p.topic for p in phrases if level == "ALL" or p.level == level))


def filter_phrases(phrases: list[Phrase], level: str, topic: str) -> list[Phrase]:
    return [p for p in phrases
            if (level == "ALL" or p.level == level) and (topic in ("ALL", ALL_TOPICS) or p.topic == topic)]


def card_status(progress: Progress, phrase: Phrase, today: date) -> str:
    s = progress.state(phrase.id)
    if s.is_new:
        return "New"
    if s.is_due(today):
        status = "Due today"
    else:
        status = f"Next review {s.due} (in {format_interval((date.fromisoformat(s.due) - today).days)})"
    if s.lapses:
        status += f" · forgotten {s.lapses}×"
    return status


def phrase_info(progress: Progress, phrase: Phrase, today: date) -> str:
    star = "★ " if phrase.id in progress.starred else ""
    return f"{star}{phrase.id} · {phrase.topic} · {card_status(progress, phrase, today)}"


def nice_step(raw: float) -> float:
    """Round a gridline step up to 1, 2 or 5 × 10^n."""
    if raw <= 0:
        return 1
    exp = 10 ** math.floor(math.log10(raw))
    return next(m * exp for m in (1, 2, 5, 10) if m * exp >= raw)


def labeled_combo(parent, label, var, values, width, on_change):
    if label:
        ttk.Label(parent, text=label).pack(side="left", padx=(0, 4))
    box = ttk.Combobox(parent, textvariable=var, values=list(values), state="readonly", width=width)
    box.pack(side="left", padx=(0, 12))
    box.bind("<<ComboboxSelected>>", lambda e: (parent.winfo_toplevel().focus_set(), on_change()))
    return box


def labeled_spin(parent, label, var, low, high, step, on_change, width=5):
    ttk.Label(parent, text=label).pack(side="left", padx=(0, 4))
    spin = ttk.Spinbox(parent, from_=low, to=high, increment=step, textvariable=var, width=width,
                       command=on_change)
    spin.pack(side="left", padx=(0, 12))
    spin.bind("<Return>", lambda e: on_change())
    spin.bind("<FocusOut>", lambda e: on_change())
    return spin


def voice_controls(parent, app: "TrainerApp", side="left", compact=False) -> None:
    """Voice, speed and a test button; `compact` shows the voice only, for crowded rows.

    Every tab shares the same choice, so they stay in sync.
    """
    if not app.speaker.available:
        return
    box = ttk.Frame(parent)
    box.pack(side=side)
    if len(app.speaker.voices) > 1:
        labeled_combo(box, "Voice", app.voice_var, app.voice_names, 15, app.save_voice)
    if compact:
        return
    labeled_spin(box, "Speed", app.rate_var, MIN_RATE, MAX_RATE, 0.1, app.save_voice, width=4)
    ttk.Button(box, text="▶ Test", command=app.test_voice, takefocus=False).pack(side="left")


def lang_checkboxes(parent, lang_vars: dict, on_change) -> None:
    """German / English / 中文 checkboxes; `on_change(lang)` gets the one just clicked."""
    for lang in LANGS:
        ttk.Checkbutton(parent, text=LANG_LABELS[lang], variable=lang_vars[lang], takefocus=False,
                        command=lambda lang=lang: on_change(lang)).pack(side="left", padx=(0, 8))


def checked_langs(lang_vars: dict, clicked: str) -> list[str] | None:
    """The ticked languages; if none would be left, ticks `clicked` again and returns None."""
    langs = [lang for lang in LANGS if lang_vars[lang].get()]
    if not langs:
        lang_vars[clicked].set(True)
        return None
    return langs


def read_int(var: tk.Variable, default: int, low: int = 0) -> int:
    try:
        return max(low, int(var.get()))
    except (tk.TclError, ValueError):
        var.set(default)
        return default


class CardView(ttk.Frame):
    """Shows one phrase: front, answer (translations) and example sentences.

    With `on_speak`, each German example gets a clickable 🔊 that reads it aloud
    (shortcut keys D, F, G for examples 1-3).
    """

    def __init__(self, parent, fonts: dict, on_speak=None):
        super().__init__(parent, padding=(24, 6))
        self.fonts = fonts
        self.on_speak = on_speak
        self.examples_visible = False
        self.info = ttk.Label(self, font=fonts["small"], foreground=MUTED)
        self.info.pack(anchor="w")
        self.banner = ttk.Label(self, font=fonts["small"], foreground=INK_2)
        self.front = ttk.Label(self, font=fonts["front"], justify="center", anchor="center")
        self.front.pack(fill="x", pady=(18, 8))
        self.separator = ttk.Separator(self)
        # One line per answer language: up to two, when Browse or Auto play show all three.
        self.answers = [ttk.Label(self, font=fonts["back"], justify="center", anchor="center")
                        for _ in range(len(LANGS) - 1)]
        self.examples = tk.Text(self, wrap="word", height=7, relief="flat", borderwidth=0,
                                font=fonts["example"], cursor="arrow",
                                background=parent.winfo_toplevel().cget("background"))
        self.examples.tag_configure("de", spacing1=8)
        self.examples.tag_configure("en", foreground=MUTED, lmargin1=18, lmargin2=18)
        self.examples.tag_configure("speak", foreground=SERIES_RECALLED)
        self.examples.tag_configure("reading", background=DAY_STYLES[STUDIED][0])
        self.examples.tag_bind("speak", "<Enter>", lambda e: self.examples.configure(cursor="hand2"))
        self.examples.tag_bind("speak", "<Leave>", lambda e: self.examples.configure(cursor="arrow"))
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event: tk.Event) -> None:
        for label in (self.front, *self.answers):
            label.configure(wraplength=max(200, event.width - 56))

    def _hide_all(self) -> None:
        for w in (self.banner, self.separator, *self.answers, self.examples):
            w.pack_forget()
        self.examples_visible = False

    def message(self, text: str) -> None:
        self._hide_all()
        self.info.configure(text="")
        self.front.configure(text=text)

    def show(self, phrase: Phrase, direction: str = "de_to_en", show_back: bool = True,
             show_examples: bool = True, example_en: bool = True, info: str = "",
             banner: str = "", langs=None) -> None:
        """`langs` (front language first, then the answers) overrides the sides of `direction`."""
        self._hide_all()
        self.info.configure(text=info)
        if banner:
            self.banner.configure(text=banner)
            self.banner.pack(anchor="w", before=self.front)
        fronts, answers = (langs[:1], langs[1:]) if langs else card_sides(direction)
        self.front.configure(text="\n".join(phrase_text(phrase, lang) for lang in fronts),
                             font=self.fonts["front_chinese" if list(fronts) == ["zh"] else "front"])
        show_back = show_back and bool(answers)
        if show_back or show_examples:
            self.separator.pack(fill="x", pady=6)
        if show_back:
            for label, lang in zip(self.answers, answers):
                label.configure(text=phrase_text(phrase, lang),
                                font=self.fonts["chinese" if lang == "zh" else "back"])
                label.pack(fill="x", pady=(6, 2))
        if show_examples:
            self.examples.configure(state="normal")
            self.examples.delete("1.0", "end")
            for i, (german, english) in enumerate(phrase.examples):
                line = ("de", f"line{i}")  # line{i} marks the sentence for highlighting
                if self.on_speak:
                    tag = f"speak{i}"  # rebinding the same tag replaces the previous sentence
                    self.examples.insert("end", f"🔊{EXAMPLE_KEYS[i].upper()}", ("de", "speak", tag),
                                         "  ", "de", german, line, "\n", "de")
                    self.examples.tag_bind(tag, "<Button-1>",
                                           lambda e, text=german: self.on_speak(text))
                else:
                    self.examples.insert("end", "• ", "de", german, line, "\n", "de")
                if example_en:
                    self.examples.insert("end", f"{english}\n", "en")
            self.examples.configure(state="disabled")
            self.examples.pack(fill="both", expand=True, pady=(6, 0))
            self.examples_visible = True

    def highlight_example(self, index: int | None) -> None:
        """Mark the example being read aloud (None clears the mark)."""
        self.examples.tag_remove("reading", "1.0", "end")
        if index is not None and self.examples.tag_ranges(f"line{index}"):
            self.examples.tag_add("reading", *self.examples.tag_ranges(f"line{index}"))

# ---------------------------------------------------------------- Study tab

class StudyTab(ttk.Frame):
    def __init__(self, parent, app: "TrainerApp"):
        super().__init__(parent)
        self.app = app
        self.session: StudySession | PracticeSession | None = None
        self.practice_title = ""
        self.revealed = False
        self.view_index: int | None = None  # index into session.rated while looking back
        self.suggested: int | None = None   # rating suggested by the typed-answer check
        self.shown_at = time.monotonic()
        self._build()
        self.start_session()

    def _build(self) -> None:
        s, fonts = self.app.progress.settings, self.app.fonts
        row1 = ttk.Frame(self, padding=(10, 8, 10, 2))
        row1.pack(fill="x")
        self.level_var = tk.StringVar(value=s["level"])
        self.app.level_box(row1, self.level_var, self.on_level_changed)
        self.topic_var = tk.StringVar(value=ALL_TOPICS if s["topic"] == "ALL" else s["topic"])
        # The Settings tab adds its own topic box here, so both get the topics of the level.
        self.topic_boxes = [labeled_combo(row1, "Topic", self.topic_var, [], 30, self.on_settings_changed)]
        self._update_topics()
        self.direction_var = tk.StringVar(value=DIRECTIONS[s["direction"]])
        labeled_combo(row1, "", self.direction_var, DIRECTIONS.values(), 22, self.on_settings_changed)
        self.mode_var = tk.StringVar(value=ANSWER_MODES[s["answer_mode"]])
        labeled_combo(row1, "", self.mode_var, ANSWER_MODES.values(), 15, self.on_settings_changed)

        row2 = ttk.Frame(self, padding=(10, 2, 10, 4))
        row2.pack(fill="x")
        self.new_var = tk.IntVar(value=s["new_per_day"])  # set in the Settings tab
        self.goal_var = tk.IntVar(value=s["daily_goal"])
        self.goal_bar = ttk.Progressbar(row2, length=120, maximum=1.0)
        self.goal_bar.pack(side="left", padx=(0, 8))
        self.status = ttk.Label(row2, font=fonts["small"])
        self.status.pack(side="left")

        self.practice_bar = ttk.Frame(self, padding=(10, 2))
        self.practice_label = ttk.Label(self.practice_bar, font=fonts["small"], foreground=INK_2)
        self.practice_label.pack(side="left")
        ttk.Button(self.practice_bar, text="End practice", takefocus=False,
                   command=self.start_session).pack(side="right")

        # Bottom rows first so the card takes the remaining space.
        self.buttons = ttk.Frame(self, padding=(10, 6, 10, 10))
        self.buttons.pack(fill="x", side="bottom")
        self.nav = ttk.Frame(self, padding=(10, 0))
        self.nav.pack(fill="x", side="bottom")
        self.answer_row = ttk.Frame(self, padding=(24, 4))
        self.answer_row.pack(fill="x", side="bottom")

        def nav_button(text, command, side="left"):
            b = ttk.Button(self.nav, text=text, command=command, takefocus=False)
            b.pack(side=side, padx=3)
            return b
        self.back_button = nav_button("◀ Back (←)", self.go_back)
        self.forward_button = nav_button("Skip ▶ (→)", self.go_forward)
        self.undo_button = nav_button("Undo (Ctrl+Z)", self.undo, "right")
        self.star_button = nav_button("☆ Star (M)", self.toggle_star, "right")
        self.examples_button = nav_button("🔊 Examples (E, D/F/G)", self.speak_examples, "right")
        self.speak_button = nav_button("🔊 Speak (S)", self.speak, "right")
        voice_controls(self.nav, self.app, side="right", compact=True)
        if not self.app.speaker.available:
            self.speak_button.state(["disabled"])
        if sys.platform == "darwin":
            self.undo_button.configure(text="Undo (⌘Z)")

        self.answer_var = tk.StringVar()
        self.answer_entry = ttk.Entry(self.answer_row, textvariable=self.answer_var,
                                      font=fonts["back"], width=40)
        self.answer_entry.bind("<Return>", lambda e: (self.check_answer(), "break")[1])
        self.answer_result = ttk.Label(self.answer_row, font=fonts["small"])

        self.card = CardView(self, fonts, self.app.speak_function())
        self.card.pack(fill="both", expand=True)

        self.show_button = ttk.Button(self.buttons, text="Show answer  (Space)",
                                      command=self.reveal, takefocus=False)
        self.rate_buttons = {r: ttk.Button(self.buttons, takefocus=False,
                                           command=lambda r=r: self.rate(r)) for r in RATINGS}
        self.more_button = ttk.Button(self.buttons, text=f"Learn {EXTRA_NEW} more new phrases",
                                      command=self.learn_more, takefocus=False)
        self.return_button = ttk.Button(self.buttons, text="Return to current card  (→)",
                                        command=self.show_card, takefocus=False)

    # ----- settings

    def _update_topics(self) -> None:
        topics = [ALL_TOPICS, *topics_for(self.app.all_phrases, self.level_var.get())]
        for box in self.topic_boxes:
            box.configure(values=topics)
        if self.topic_var.get() not in topics:
            self.topic_var.set(ALL_TOPICS)

    def on_level_changed(self) -> None:
        self._update_topics()
        self.on_settings_changed()

    def on_settings_changed(self) -> None:
        s = self.app.progress.settings
        new = dict(
            level=self.level_var.get(),
            topic="ALL" if self.topic_var.get() == ALL_TOPICS else self.topic_var.get(),
            direction=next(k for k, v in DIRECTIONS.items() if v == self.direction_var.get()),
            answer_mode=next(k for k, v in ANSWER_MODES.items() if v == self.mode_var.get()),
            new_per_day=read_int(self.new_var, s["new_per_day"]),
            daily_goal=read_int(self.goal_var, s["daily_goal"], low=1),
        )
        changed = {k for k, v in new.items() if s.get(k) != v}
        if not changed:
            return
        s.update(new)
        self.app.progress.save()
        if changed & {"level", "topic", "new_per_day"}:
            self.start_session()
        elif changed & {"direction", "answer_mode"}:
            self.show_card()
        else:
            self.update_status()

    # ----- session flow

    @property
    def settings(self) -> dict:
        return self.app.progress.settings

    def start_session(self) -> None:
        s = self.settings
        phrases = filter_phrases(self.app.all_phrases, s["level"], s["topic"])
        self.session = StudySession(phrases, self.app.progress)
        self.practice_bar.pack_forget()
        self.show_card()

    def start_practice(self, phrases: list[Phrase], title: str) -> None:
        if not phrases:
            messagebox.showinfo("Practice", "There are no phrases to practice.")
            return
        self.session = PracticeSession(phrases)
        self.practice_title = title
        self.practice_bar.pack(fill="x", after=self.status.master)
        self.show_card()

    @property
    def practicing(self) -> bool:
        return isinstance(self.session, PracticeSession)

    def show_card(self) -> None:
        self.view_index = None
        self.revealed = False
        self.suggested = None
        self.shown_at = time.monotonic()
        self._clear_buttons()
        self.update_status()
        phrase = self.session.current
        self._update_nav(phrase)
        if phrase is None:
            if self.practicing:
                self.card.message("Practice round finished!")
            else:
                self.card.message("All done for today!\nCome back tomorrow for your reviews.")
                self.more_button.pack(expand=True)
            self.update_examples_button()
            self.app.root.focus_set()
            return
        self.card.show(phrase, self.settings["direction"], show_back=False, show_examples=False,
                       info=phrase_info(self.app.progress, phrase, date.today()))
        self.update_examples_button()
        if self.settings["answer_mode"] == "type":
            self.answer_var.set("")
            self.answer_result.configure(text="")
            self.answer_entry.pack(side="left", padx=(0, 8))
            ttk.Button(self.answer_row, text="Check (Enter)", takefocus=False,
                       command=self.check_answer).pack(side="left")
            self.answer_result.pack(side="left", padx=12)
            self.answer_entry.focus_set()
        else:
            self.app.root.focus_set()
            self.show_button.pack(expand=True, ipadx=20, ipady=6)

    def _clear_buttons(self) -> None:
        for w in self.buttons.winfo_children():
            w.pack_forget()
        for w in self.answer_row.winfo_children():
            if isinstance(w, ttk.Button):
                w.destroy()
            else:
                w.pack_forget()

    def _update_nav(self, phrase: Phrase | None) -> None:
        has_history = bool(self.session.rated)
        at_start = self.view_index == 0
        self.back_button.state(["!disabled"] if has_history and not at_start else ["disabled"])
        self.forward_button.configure(text="Skip ▶ (→)" if self.view_index is None else "Forward ▶ (→)")
        can_forward = self.view_index is not None or len(self.session.queue) > 1
        self.forward_button.state(["!disabled"] if can_forward else ["disabled"])
        self.undo_button.state(["!disabled"] if self.session.rated and self.view_index is None
                               else ["disabled"])
        starred = phrase is not None and phrase.id in self.app.progress.starred
        self.star_button.configure(text="★ Starred (M)" if starred else "☆ Star (M)")
        self.star_button.state(["!disabled"] if phrase else ["disabled"])
        self.update_examples_button()

    def update_examples_button(self) -> None:
        enabled = self.app.speaker.available and self.card.examples_visible
        self.examples_button.state(["!disabled"] if enabled else ["disabled"])

    def reveal(self) -> None:
        phrase = self.session.current
        if phrase is None or self.revealed or self.view_index is not None:
            return
        self.revealed = True
        self.card.show(phrase, self.settings["direction"],
                       info=phrase_info(self.app.progress, phrase, date.today()))
        self.update_examples_button()
        self.show_button.pack_forget()
        preview = self.session.preview()
        for r, button in self.rate_buttons.items():
            if self.practicing:
                when = "again soon" if r == AGAIN else "done"
            else:
                when = format_interval(preview[r])
            mark = "▶ " if r == self.suggested else ""
            button.configure(text=f"{mark}{RATING_NAMES[r]} ({r})  ·  {when}")
            button.pack(side="left", expand=True, fill="x", padx=4, ipady=8)

    def check_answer(self) -> None:
        phrase = self.session.current
        if phrase is None or self.view_index is not None:
            return
        if self.revealed:  # second Enter accepts the suggested rating
            if self.suggested:
                self.rate(self.suggested)
            return
        expected = phrase_text(phrase, card_sides(self.settings["direction"])[1][0])
        score, self.suggested = check(self.answer_var.get(), expected)
        verdict = {GOOD: "✓ Correct", AGAIN: "✗ Not quite"}.get(self.suggested, "≈ Almost")
        self.answer_result.configure(text=f"{verdict} ({score:.0%})  ·  Enter = accept ▶, or 1-4")
        self.reveal()
        self.app.root.focus_set()

    def rate(self, rating: int) -> None:
        if not self.revealed or self.view_index is not None or self.session.current is None:
            return
        self.session.rate(rating, time.monotonic() - self.shown_at)
        self.show_card()

    def undo(self) -> None:
        if self.view_index is None and self.session.undo():
            self.show_card()

    def go_back(self) -> None:
        rated = self.session.rated
        if not rated or self.view_index == 0:
            return
        self.view_index = len(rated) - 1 if self.view_index is None else self.view_index - 1
        self._show_history()

    def go_forward(self) -> None:
        if self.view_index is None:
            if self.session.skip():
                self.show_card()
            return
        self.view_index += 1
        if self.view_index >= len(self.session.rated):
            self.show_card()
        else:
            self._show_history()

    def _show_history(self) -> None:
        phrase, rating = self.session.rated[self.view_index]
        self._clear_buttons()
        self.card.show(phrase, self.settings["direction"],
                       info=phrase_info(self.app.progress, phrase, date.today()),
                       banner=f"Looking back: card {self.view_index + 1} of {len(self.session.rated)} "
                              f"rated in this session · you rated it {RATING_NAMES[rating]}")
        self.return_button.pack(expand=True, ipadx=20, ipady=6)
        self._update_nav(phrase)

    def visible_phrase(self) -> Phrase | None:
        if self.view_index is not None:
            return self.session.rated[self.view_index][0]
        return self.session.current

    def speak(self) -> None:
        phrase = self.visible_phrase()
        # When German is the answer, speaking it before the reveal would give the answer away.
        if phrase and (self.revealed or self.view_index is not None
                       or "de" in card_sides(self.settings["direction"])[0]):
            self.app.speaker.speak(phrase.german)

    def speak_examples(self, index: int | None = None) -> None:
        """Speak all German examples, or only example `index`, when they are on screen."""
        phrase = self.visible_phrase()
        if phrase and self.card.examples_visible:
            self.app.speak_examples(phrase, index)

    def toggle_star(self) -> None:
        phrase = self.visible_phrase()
        if phrase is None:
            return
        self.app.toggle_star(phrase.id)
        self.card.info.configure(text=phrase_info(self.app.progress, phrase, date.today()))
        self._update_nav(phrase)

    def learn_more(self) -> None:
        if self.session.add_new(EXTRA_NEW) == 0:
            messagebox.showinfo("German Phrases", "You have started every phrase in this selection.")
        self.show_card()

    def update_status(self) -> None:
        if self.practicing:
            left = len(self.session.queue)
            self.practice_label.configure(
                text=f"Practice: {self.practice_title} · {left} of {self.session.total} left · "
                     "your review schedule is not changed")
        left = self.session.remaining()
        today = date.today()
        done = sum(self.app.progress.counters(today)[k] for k in ("new", "reviews"))
        goal = self.settings["daily_goal"]
        current, _ = streaks(summarize(self.app.progress.log), today)
        self.goal_bar.configure(value=min(1.0, done / goal))
        self.status.configure(
            text=f"Today {done}/{goal}    To study: {left['new']} new · {left['review']} review    "
                 f"Streak: {current} day{'s' if current != 1 else ''}")

    def on_key(self, key: str) -> None:
        if self.view_index is not None:
            actions = {"left": self.go_back, "right": self.go_forward, "return": self.show_card,
                       "s": self.speak, "e": self.speak_examples, "m": self.toggle_star}
        else:
            actions = {"space": self.reveal, "left": self.go_back, "right": self.go_forward,
                       "s": self.speak, "e": self.speak_examples, "m": self.toggle_star,
                       "return": self.check_answer if self.suggested else self.reveal}
            actions.update({str(r): (lambda r=r: self.rate(r)) for r in RATINGS})
        actions.update({k: (lambda i=i: self.speak_examples(i)) for i, k in enumerate(EXAMPLE_KEYS)})
        action = actions.get(key)
        if action:
            action()

    def on_show(self) -> None:
        self.update_status()
        phrase = self.visible_phrase()
        if phrase is not None:
            self.card.info.configure(text=phrase_info(self.app.progress, phrase, date.today()))
            self._update_nav(phrase)


# ---------------------------------------------------------------- Browse tab

class BrowseTab(ttk.Frame):
    def __init__(self, parent, app: "TrainerApp"):
        super().__init__(parent)
        self.app = app
        self.items: list[Phrase] = []
        self.index = 0
        self.peek = False  # temporarily show translations while they are hidden
        self._setting_scale = False
        self._build()
        self.refresh_items()

    def _build(self) -> None:
        fonts = self.app.fonts
        bar = ttk.Frame(self, padding=(10, 8, 10, 2))
        bar.pack(fill="x")
        self.level_var = tk.StringVar(value=self.app.progress.settings["level"])
        self.app.level_box(bar, self.level_var, self.on_level_changed)
        self.topic_var = tk.StringVar(value=ALL_TOPICS)
        self.topic_box = labeled_combo(bar, "Topic", self.topic_var, [], 30, self.refresh_items)
        self.translate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Show translations", variable=self.translate_var,
                        command=self.show, takefocus=False).pack(side="left", padx=(0, 12))
        ttk.Label(bar, text="Go to #").pack(side="left")
        self.goto_var = tk.StringVar()
        goto = ttk.Entry(bar, textvariable=self.goto_var, width=8)
        goto.pack(side="left", padx=4)
        goto.bind("<Return>", lambda e: self.go_to())
        ttk.Label(bar, text="(number or ID, e.g. 125 or B2-0042)", foreground=MUTED,
                  font=fonts["small"]).pack(side="left")

        row = ttk.Frame(self, padding=(10, 2))
        row.pack(fill="x")
        self.position = ttk.Label(row, width=16, font=fonts["small"])
        self.position.pack(side="left")
        self.scale = ttk.Scale(row, from_=1, to=2, command=self.on_scale)
        self.scale.pack(side="left", fill="x", expand=True, padx=8)
        voice_controls(row, self.app, side="right", compact=True)

        nav = ttk.Frame(self, padding=(10, 8))
        nav.pack(fill="x", side="bottom")
        for text, command, side in (
            ("◀ Previous (←)", lambda: self.move(-1), "left"),
            ("Next ▶ (→)", lambda: self.move(1), "left"),
            ("Random (R)", self.random, "left"),
            ("Translations (Space)", self.toggle_peek, "left"),
            ("Practice this selection", self.practice, "right"),
        ):
            ttk.Button(nav, text=text, command=command, takefocus=False).pack(side=side, padx=3)
        self.star_button = ttk.Button(nav, command=self.toggle_star, takefocus=False)
        self.star_button.pack(side="right", padx=3)
        examples = ttk.Button(nav, text="🔊 Examples (E, D/F/G)", command=self.speak_examples,
                              takefocus=False)
        examples.pack(side="right", padx=3)
        speak = ttk.Button(nav, text="🔊 Speak (S)", command=self.speak, takefocus=False)
        speak.pack(side="right", padx=3)
        if not self.app.speaker.available:
            speak.state(["disabled"])
            examples.state(["disabled"])

        self.card = CardView(self, fonts, self.app.speak_function())
        self.card.pack(fill="both", expand=True)

    def on_level_changed(self) -> None:
        topics = [ALL_TOPICS, *topics_for(self.app.all_phrases, self.level_var.get())]
        self.topic_box.configure(values=topics)
        if self.topic_var.get() not in topics:
            self.topic_var.set(ALL_TOPICS)
        self.refresh_items()

    def refresh_items(self, keep_id: str | None = None) -> None:
        if not self.topic_box.cget("values"):
            self.topic_box.configure(
                values=[ALL_TOPICS, *topics_for(self.app.all_phrases, self.level_var.get())])
        keep_id = keep_id or (self.items[self.index].id if self.items else None)
        self.items = filter_phrases(self.app.all_phrases, self.level_var.get(), self.topic_var.get())
        ids = [p.id for p in self.items]
        self.index = ids.index(keep_id) if keep_id in ids else 0
        self.scale.configure(to=max(2, len(self.items)))
        self.show()

    def show(self) -> None:
        if not self.items:
            self.card.message("No phrases in this selection.")
            return
        phrase = self.items[self.index]
        translations = self.translate_var.get() or self.peek
        self.card.show(phrase, langs=LANGS, show_back=translations, show_examples=True,
                       example_en=translations,
                       info=phrase_info(self.app.progress, phrase, date.today()))
        self.position.configure(text=f"{self.index + 1} / {len(self.items)}")
        self._setting_scale = True
        self.scale.set(self.index + 1)
        self._setting_scale = False
        starred = phrase.id in self.app.progress.starred
        self.star_button.configure(text="★ Starred (M)" if starred else "☆ Star (M)")

    def move(self, step: int) -> None:
        if self.items:
            self.index = (self.index + step) % len(self.items)
            self.peek = False
            self.show()

    def random(self) -> None:
        if self.items:
            self.index = random.randrange(len(self.items))
            self.peek = False
            self.show()

    def on_scale(self, value: str) -> None:
        if self._setting_scale or not self.items:
            return
        index = min(len(self.items) - 1, max(0, round(float(value)) - 1))
        if index != self.index:
            self.index = index
            self.show()

    def go_to(self) -> None:
        target = self.goto_var.get().strip().upper()
        self.app.root.focus_set()
        if target.isdigit() and 1 <= int(target) <= len(self.items):
            self.index = int(target) - 1
            self.show()
        elif target in self.app.by_id:
            self.open_phrase(target)
        else:
            messagebox.showinfo("Go to", f"No phrase {target!r} in this selection.")

    def open_phrase(self, phrase_id: str) -> None:
        if phrase_id not in {p.id for p in self.items}:
            self.level_var.set(self.app.by_id[phrase_id].level)
            self.topic_var.set(ALL_TOPICS)
            self.on_level_changed()
        self.refresh_items(keep_id=phrase_id)

    def toggle_peek(self) -> None:
        if not self.translate_var.get():
            self.peek = not self.peek
            self.show()

    def speak(self) -> None:
        if self.items:
            self.app.speaker.speak(self.items[self.index].german)

    def speak_examples(self, index: int | None = None) -> None:
        if self.items:
            self.app.speak_examples(self.items[self.index], index)

    def toggle_star(self) -> None:
        if self.items:
            self.app.toggle_star(self.items[self.index].id)
            self.show()

    def practice(self) -> None:
        self.app.practice(self.items, f"{self.level_var.get()} · {self.topic_var.get()}")

    def on_key(self, key: str) -> None:
        actions = {"left": lambda: self.move(-1), "right": lambda: self.move(1), "r": self.random,
                   "space": self.toggle_peek, "s": self.speak, "e": self.speak_examples,
                   "m": self.toggle_star}
        actions.update({k: (lambda i=i: self.speak_examples(i)) for i, k in enumerate(EXAMPLE_KEYS)})
        action = actions.get(key)
        if action:
            action()

    def on_show(self) -> None:
        self.show()


# ---------------------------------------------------------------- Lists tab

class ListsTab(ttk.Frame):
    COLUMNS = {  # id: (heading, width, stretch)
        "n": ("#", 50, False), "id": ("ID", 80, False), "german": ("German", 260, True),
        "english": ("English", 220, True), "chinese": ("中文", 150, True),
        "examples": ("Examples", 360, True), "status": ("Status", 230, False),
    }

    def __init__(self, parent, app: "TrainerApp"):
        super().__init__(parent)
        self.app = app
        self.shown: list[Phrase] = []
        self._search_job = None
        self._build()

    def _build(self) -> None:
        fonts = self.app.fonts
        row1 = ttk.Frame(self, padding=(10, 8, 10, 2))
        row1.pack(fill="x")
        self.kind_var = tk.StringVar(value=FILTERS["learned"])
        labeled_combo(row1, "Show", self.kind_var, FILTERS.values(), 32, self.refresh)
        self.level_var = tk.StringVar(value="ALL")
        self.app.level_box(row1, self.level_var, self.on_level_changed)
        self.topic_var = tk.StringVar(value=ALL_TOPICS)
        self.topic_box = labeled_combo(row1, "Topic", self.topic_var,
                                       [ALL_TOPICS, *topics_for(self.app.all_phrases, "ALL")],
                                       26, self.refresh)
        self.sort_var = tk.StringVar(value=SORTS["id"])
        labeled_combo(row1, "Sort", self.sort_var, SORTS.values(), 24, self.refresh)

        row2 = ttk.Frame(self, padding=(10, 2, 10, 4))
        row2.pack(fill="x")
        ttk.Label(row2, text="Search").pack(side="left", padx=(0, 4))
        self.search_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.search_var, width=22).pack(side="left", padx=(0, 12))
        self.search_var.trace_add("write", lambda *a: self._schedule_refresh())
        self.limit_var = tk.IntVar(value=50)
        labeled_spin(row2, "Number of items", self.limit_var, 0, 3000, 10, self.refresh, width=6)
        ttk.Label(row2, text="(0 = all)", foreground=MUTED, font=fonts["small"]).pack(side="left",
                                                                                     padx=(0, 12))
        s = self.app.progress.settings
        shown = clean_langs(s.get("lists_langs"))
        self.lang_vars = {lang: tk.BooleanVar(value=lang in shown) for lang in LANGS}
        lang_checkboxes(row2, self.lang_vars, self.on_columns_changed)
        self.examples_var = tk.BooleanVar(value=bool(s.get("lists_examples", False)))
        ttk.Checkbutton(row2, text="Examples", variable=self.examples_var, takefocus=False,
                        command=self.on_columns_changed).pack(side="left", padx=(0, 8))
        ttk.Button(row2, text="Export…", command=self.export).pack(side="right", padx=3)
        ttk.Button(row2, text="Practice these", command=self.practice).pack(side="right", padx=3)
        ttk.Button(row2, text="▶ Auto play these",
                   command=lambda: self.app.auto_play(self.shown, f"{self.kind_var.get()} "
                                                      f"({len(self.shown)})")).pack(side="right", padx=3)

        self.summary = ttk.Label(self, padding=(12, 0), font=fonts["small"], foreground=INK_2)
        self.summary.pack(fill="x")

        frame = ttk.Frame(self, padding=(10, 4, 10, 10))
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=list(self.COLUMNS), show="headings")
        for col, (heading, width, stretch) in self.COLUMNS.items():
            self.tree.heading(col, text=heading)
            self.tree.column(col, width=width, stretch=stretch, anchor="w")
        for tag, tint in ROW_TINTS.items():
            self.tree.tag_configure(tag, background=tint)
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self.open_selected)
        self.tree.bind("<Return>", self.open_selected)
        ttk.Label(self, padding=(12, 0, 12, 8), font=fonts["small"], foreground=MUTED,
                  text="Highlighted rows: orange = forgotten before, red = difficult "
                       f"(forgotten {DIFFICULT_LAPSES}+ times). Double-click a row to open it in Browse."
                  ).pack(fill="x")

    def _key(self, mapping: dict, var: tk.StringVar) -> str:
        return next(k for k, v in mapping.items() if v == var.get())

    def on_level_changed(self) -> None:
        topics = [ALL_TOPICS, *topics_for(self.app.all_phrases, self.level_var.get())]
        self.topic_box.configure(values=topics)
        if self.topic_var.get() not in topics:
            self.topic_var.set(ALL_TOPICS)
        self.refresh()

    def _schedule_refresh(self) -> None:
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(300, self.refresh)

    def langs(self) -> list[str]:
        return [lang for lang in LANGS if self.lang_vars[lang].get()]

    def on_columns_changed(self, clicked: str | None = None) -> None:
        if clicked and checked_langs(self.lang_vars, clicked) is None:
            self.summary.configure(text="At least one language is needed.")
            return
        s, new = self.app.progress.settings, {"lists_langs": self.langs(),
                                              "lists_examples": bool(self.examples_var.get())}
        if any(s.get(k) != v for k, v in new.items()):
            s.update(new)
            self.app.progress.save()
        self.refresh()

    def visible_columns(self) -> list[str]:
        cols = ["n", "id", *(LANG_FIELD[lang] for lang in self.langs())]
        if self.examples_var.get():
            cols.append("examples")
        return cols + ["status"]

    def refresh(self) -> None:
        self._search_job = None
        progress, today = self.app.progress, date.today()
        phrases = filter_phrases(self.app.all_phrases, self.level_var.get(), self.topic_var.get())
        matching = select(phrases, progress, self._key(FILTERS, self.kind_var),
                          self.search_var.get(), self._key(SORTS, self.sort_var), today=today)
        limit = read_int(self.limit_var, 50)
        self.shown = matching[:limit] if limit else matching
        self.tree.configure(displaycolumns=self.visible_columns())
        self.tree.delete(*self.tree.get_children())
        for n, p in enumerate(self.shown, 1):
            s = progress.state(p.id)
            tags = (("difficult",) if s.lapses >= DIFFICULT_LAPSES
                    else ("forgotten",) if was_forgotten(s) else ())
            star = "★ " if p.id in progress.starred else ""
            examples = "  |  ".join(de for de, _ in p.examples)
            self.tree.insert("", "end", iid=p.id, tags=tags, values=(
                n, star + p.id, p.german, p.english, p.chinese, examples, card_status(progress, p, today)))
        self.summary.configure(text=f"Showing {len(self.shown)} of {len(matching)} matching phrases")

    def open_selected(self, event=None) -> None:
        selection = self.tree.selection()
        if selection:
            self.app.open_in_browse(selection[0])

    def practice(self) -> None:
        self.app.practice(self.shown, f"{self.kind_var.get()} ({len(self.shown)})")

    def export(self) -> None:
        if not self.shown:
            messagebox.showinfo("Export", "The list is empty.")
            return
        path = filedialog.asksaveasfilename(
            title="Export list", defaultextension=".csv",
            filetypes=[("CSV (Excel)", "*.csv"), ("Text for printing", "*.txt")])
        if not path:
            return
        langs, with_examples = self.langs(), self.examples_var.get()
        with_english = "en" in langs  # examples are German, with their English translation
        if path.lower().endswith(".txt"):
            with open(path, "w", encoding="utf-8") as f:
                for n, p in enumerate(self.shown, 1):
                    f.write(f"{n}. " + "  —  ".join(phrase_text(p, lang) for lang in langs) + "\n")
                    if with_examples:
                        for de, en in p.examples:
                            f.write(f"     • {de}" + (f"  ({en})" if with_english else "") + "\n")
        else:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                header = ["id", "level", "topic", *(LANG_FIELD[lang] for lang in langs)]
                header += ["examples"] if with_examples else []
                writer.writerow(header + ["status"])
                for p in self.shown:
                    row = [p.id, p.level, p.topic, *(phrase_text(p, lang) for lang in langs)]
                    if with_examples:
                        row.append(" | ".join(f"{de} ({en})" if with_english else de
                                              for de, en in p.examples))
                    writer.writerow(row + [card_status(self.app.progress, p, date.today())])
        messagebox.showinfo("Export", f"Saved {len(self.shown)} phrases to\n{path}")

    def on_key(self, key: str) -> None:
        pass

    def on_show(self) -> None:
        self.refresh()


# ---------------------------------------------------------------- Progress tab

class ProgressTab(ttk.Frame):
    def __init__(self, parent, app: "TrainerApp"):
        super().__init__(parent)
        self.app = app
        today = date.today()
        self.month = (today.year, today.month)
        self.selected = today
        self.days: dict[date, DaySummary] = {}
        self.stats_window: tk.Toplevel | None = None
        self._build()

    def _build(self) -> None:
        fonts = self.app.fonts
        tiles = ttk.Frame(self, padding=(10, 8))
        tiles.pack(fill="x")
        self.tiles = {}
        for key, caption in (("today", "Today / goal"), ("streak", "Current streak"),
                             ("longest", "Longest streak"), ("days", "Days studied"),
                             ("learned", "Phrases learned"), ("total", "Total reviews")):
            box = ttk.Frame(tiles, padding=(12, 4))
            box.pack(side="left", expand=True, fill="x")
            value = ttk.Label(box, font=fonts["tile"])
            value.pack(anchor="w")
            ttk.Label(box, text=caption, font=fonts["small"], foreground=INK_2).pack(anchor="w")
            self.tiles[key] = value
        ttk.Button(tiles, text="Level statistics…", command=self.show_level_stats).pack(side="right")

        body = ttk.Frame(self, padding=(10, 0))
        body.pack(fill="both", expand=True)

        cal = ttk.Frame(body)
        cal.pack(side="left", fill="y", padx=(0, 16))
        head = ttk.Frame(cal)
        head.pack(fill="x", pady=(0, 4))
        ttk.Button(head, text="◀", width=3, command=lambda: self.shift_month(-1)).pack(side="left")
        self.month_label = ttk.Label(head, font=fonts["section"], anchor="center")
        self.month_label.pack(side="left", expand=True, fill="x")
        ttk.Button(head, text="▶", width=3, command=lambda: self.shift_month(1)).pack(side="right")
        grid = ttk.Frame(cal)
        grid.pack()
        for col, name in enumerate(calendar.day_abbr):
            ttk.Label(grid, text=name, font=fonts["small"], foreground=MUTED,
                      anchor="center").grid(row=0, column=col, sticky="ew")
        self.cells = []
        for row in range(6):
            for col in range(7):
                border = tk.Frame(grid, background=SURFACE, padx=2, pady=2)
                border.grid(row=row + 1, column=col, padx=1, pady=1)
                label = tk.Label(border, width=6, height=2, font=fonts["cell"], background=SURFACE,
                                 foreground=INK, justify="center")
                label.pack()
                self.cells.append((border, label))
        legend = ttk.Frame(cal, padding=(0, 8))
        legend.pack(fill="x")
        for kind in (GOOD_DAY, STUDIED, HARD_DAY, MISSED):
            tint, accent, icon, text = DAY_STYLES[kind]
            row = ttk.Frame(legend)
            row.pack(anchor="w", pady=1)
            tk.Label(row, text=icon, width=3, background=tint, foreground=INK,
                     highlightthickness=2, highlightbackground=accent).pack(side="left", padx=(0, 6))
            ttk.Label(row, text=text, font=fonts["small"]).pack(side="left")

        detail = ttk.Frame(body)
        detail.pack(side="left", fill="both", expand=True)
        self.day_title = ttk.Label(detail, font=fonts["section"])
        self.day_title.pack(anchor="w")
        self.day_kind = ttk.Label(detail, font=fonts["small"])
        self.day_kind.pack(anchor="w", pady=(2, 0))
        self.day_text = ttk.Label(detail, font=fonts["small"], foreground=INK_2, justify="left")
        self.day_text.pack(anchor="w", pady=(2, 6))
        tree_frame = ttk.Frame(detail)
        tree_frame.pack(fill="both", expand=True)
        self.day_tree = ttk.Treeview(tree_frame, columns=("id", "german", "english", "rating"),
                                     show="headings", height=8)
        for col, heading, width in (("id", "ID", 80), ("german", "German", 220),
                                    ("english", "English", 200), ("rating", "Rating", 80)):
            self.day_tree.heading(col, text=heading)
            self.day_tree.column(col, width=width, stretch=col in ("german", "english"))
        self.day_tree.tag_configure("again", background=ROW_TINTS["again"])
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.day_tree.yview)
        self.day_tree.configure(yscrollcommand=scroll.set)
        self.day_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.day_tree.bind("<Double-1>", self._open_day_phrase)
        buttons = ttk.Frame(detail, padding=(0, 6))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Practice this day's forgotten phrases",
                   command=lambda: self.practice_day(forgotten_only=True)).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Practice all phrases of this day",
                   command=lambda: self.practice_day(forgotten_only=False)).pack(side="left",
                                                                                 padx=(0, 6))
        ttk.Button(buttons, text="▶ Auto play this day", command=self.auto_play_day).pack(side="left")

        chart_box = ttk.Frame(self, padding=(10, 4, 10, 10))
        chart_box.pack(fill="x", side="bottom")
        ttk.Label(chart_box, text=f"Reviews per day, last {CHART_DAYS} days",
                  font=fonts["section"]).pack(anchor="w")
        self.chart = tk.Canvas(chart_box, height=190, background=SURFACE, highlightthickness=0)
        self.chart.pack(fill="x")
        self.chart.bind("<Configure>", lambda e: self.draw_chart())

    # ----- data

    def refresh(self) -> None:
        progress, today = self.app.progress, date.today()
        self.days = summarize(progress.log)
        current, longest = streaks(self.days, today)
        goal = progress.settings["daily_goal"]
        done = self.days[today].total if today in self.days else 0
        learned = sum(1 for s in progress.cards.values() if not s.is_new)
        values = {
            "today": f"{done} / {goal}", "streak": f"{current} d", "longest": f"{longest} d",
            "days": str(sum(1 for s in self.days.values() if s.total)),
            "learned": f"{learned} / {len(self.app.all_phrases)}",
            "total": str(len(progress.log)),
        }
        for key, value in values.items():
            self.tiles[key].configure(text=value)
        self.draw_calendar()
        self.show_day(self.selected)
        self.draw_chart()

    def kind(self, day: date) -> str:
        return classify(day, self.days, self.app.progress.settings["daily_goal"], date.today())

    def shift_month(self, step: int) -> None:
        year, month = self.month
        month += step
        year, month = year + (month - 1) // 12, (month - 1) % 12 + 1
        self.month = (year, month)
        self.draw_calendar()

    def draw_calendar(self) -> None:
        year, month = self.month
        self.month_label.configure(text=f"{calendar.month_name[month]} {year}")
        weeks = calendar.Calendar().monthdatescalendar(year, month)
        days = [d for week in weeks for d in week] + [None] * 42
        today = date.today()
        for (border, label), day in zip(self.cells, days[:42]):
            if day is None or day.month != month:
                border.grid_remove()
                continue
            border.grid()
            kind = self.kind(day)
            tint, _, icon, _ = DAY_STYLES[kind]
            summary = self.days.get(day)
            count = f" {summary.total}" if summary and summary.total else ""
            label.configure(text=f"{day.day}\n{icon}{count}", background=tint,
                            foreground=INK if day <= today else MUTED)
            frame_color = INK if day == self.selected else MUTED if day == today else SURFACE
            border.configure(background=frame_color)
            for widget in (border, label):
                widget.bind("<Button-1>", lambda e, d=day: self.select_day(d))

    def select_day(self, day: date) -> None:
        self.selected = day
        if (day.year, day.month) != self.month:
            self.month = (day.year, day.month)
        self.draw_calendar()
        self.show_day(day)
        self.draw_chart()

    def show_day(self, day: date) -> None:
        summary = self.days.get(day) or DaySummary(day)
        kind = self.kind(day)
        _, _, icon, text = DAY_STYLES[kind]
        self.day_title.configure(text=day.strftime("%A, %d %B %Y"))
        if kind == NO_DATA:
            text = "Today: no reviews yet" if day == date.today() else "No study data"
        self.day_kind.configure(text=f"{icon} {text}".strip())
        if summary.total:
            r = summary.ratings
            minutes = summary.seconds / 60
            self.day_text.configure(text=(
                f"{summary.total} ratings · {summary.new} new phrases · "
                f"{summary.accuracy:.0%} recalled · {minutes:.0f} min\n"
                f"Again {r[1]} · Hard {r[2]} · Good {r[3]} · Easy {r[4]}"))
        else:
            self.day_text.configure(text="")
        self.day_tree.delete(*self.day_tree.get_children())
        by_id = self.app.by_id
        # Latest rating per phrase, forgotten ones first.
        latest: dict[str, int] = {}
        worst: dict[str, int] = {}
        for pid, rating in summary.reviews:
            latest[pid] = rating
            worst[pid] = min(worst.get(pid, 9), rating)
        for pid in sorted(latest, key=lambda p: (worst[p] != AGAIN, p)):
            p = by_id.get(pid)
            if p is None:
                continue
            label = RATING_NAMES[latest[pid]]
            if worst[pid] == AGAIN and latest[pid] != AGAIN:
                label = f"Again → {label}"
            self.day_tree.insert("", "end", values=(pid, p.german, p.english, label),
                                 tags=("again",) if worst[pid] == AGAIN else ())

    def _open_day_phrase(self, event=None) -> None:
        selection = self.day_tree.selection()
        if selection:
            self.app.open_in_browse(self.day_tree.item(selection[0], "values")[0])

    def practice_day(self, forgotten_only: bool) -> None:
        summary = self.days.get(self.selected)
        if not summary:
            messagebox.showinfo("Practice", "No phrases were reviewed on this day.")
            return
        ids = summary.forgotten_ids if forgotten_only else sorted({pid for pid, _ in summary.reviews})
        phrases = [self.app.by_id[i] for i in ids if i in self.app.by_id]
        what = "forgotten on" if forgotten_only else "reviewed on"
        self.app.practice(phrases, f"phrases {what} {self.selected:%d %b}")

    def auto_play_day(self) -> None:
        summary = self.days.get(self.selected)
        ids = dict.fromkeys(pid for pid, _ in summary.reviews) if summary else {}
        phrases = [self.app.by_id[i] for i in ids if i in self.app.by_id]
        self.app.auto_play(phrases, f"Phrases reviewed on {self.selected:%d %b %Y}")

    # ----- chart

    def draw_chart(self) -> None:
        c = self.chart
        c.delete("all")
        width, height = c.winfo_width(), c.winfo_height()
        if width < 100:
            return
        today = date.today()
        data = last_n_days(self.days, today, CHART_DAYS)
        goal = self.app.progress.settings["daily_goal"]
        top = max([d.total for d in data] + [goal, 5])
        step = nice_step(top / 4)
        y_max = step * math.ceil(top / step)
        left, right, top_px, bottom = 44, width - 16, 30, height - 22
        small = self.app.fonts["small"]

        def y(value: float) -> float:
            return bottom - (bottom - top_px) * value / y_max

        tick = 0.0
        while tick <= y_max + 1e-9:
            c.create_line(left, y(tick), right, y(tick), fill=GRID if tick else BASELINE)
            c.create_text(left - 6, y(tick), text=f"{tick:g}", anchor="e", fill=MUTED, font=small)
            tick += step
        c.create_line(left, y(goal), right, y(goal), fill=MUTED, dash=(4, 3))

        # Legend (two series, so it is always shown) plus the goal line.
        x = left
        for color, text in ((SERIES_RECALLED, "Recalled"), (SERIES_FORGOTTEN, "Forgotten")):
            c.create_rectangle(x, 8, x + 10, 18, fill=color, outline="")
            item = c.create_text(x + 16, 13, text=text, anchor="w", fill=INK_2, font=small)
            x = c.bbox(item)[2] + 16
        c.create_line(x, 13, x + 18, 13, fill=MUTED, dash=(4, 3))
        c.create_text(x + 24, 13, text=f"Daily goal ({goal})", anchor="w", fill=INK_2, font=small)

        slot = (right - left) / len(data)
        bar = max(4.0, min(28.0, slot * 0.62))
        for i, d in enumerate(data):
            x0 = left + i * slot + (slot - bar) / 2
            x1 = x0 + bar
            if d.recalled:
                c.create_rectangle(x0, y(d.recalled), x1, bottom, fill=SERIES_RECALLED, outline="")
            if d.forgotten:
                # 2px surface gap between the stacked segments.
                c.create_rectangle(x0, y(d.total), x1, y(d.recalled) - 2,
                                   fill=SERIES_FORGOTTEN, outline="")
            if d.day == self.selected:
                c.create_rectangle(x0 - 3, top_px - 4, x1 + 3, bottom, outline=INK, dash=(2, 2))
            if d.day == today or (i % 7 == 0 and len(data) - 1 - i >= 3):
                c.create_text((x0 + x1) / 2, bottom + 4, text=f"{d.day.day} {d.day:%b}",
                              anchor="n", fill=MUTED, font=small)
            # Hit target: the whole column, bigger than the bar itself.
            hit = c.create_rectangle(left + i * slot, top_px, left + (i + 1) * slot, bottom,
                                     fill="", outline="")
            c.tag_bind(hit, "<Enter>", lambda e, d=d: self._tooltip(e.x, d))
            c.tag_bind(hit, "<Leave>", lambda e: c.delete("tip"))
            c.tag_bind(hit, "<Button-1>", lambda e, d=d: self.select_day(d.day))

    def _tooltip(self, x: int, d: DaySummary) -> None:
        c = self.chart
        c.delete("tip")
        if d.total:
            text = (f"{d.day:%a %d %b}: {d.total} ratings\n"
                    f"{d.recalled} recalled · {d.forgotten} forgotten · {d.accuracy:.0%}")
        else:
            text = f"{d.day:%a %d %b}: no reviews"
        # Disabled items are ignored by the pointer: a tooltip under the mouse would otherwise
        # fire <Leave> on the bar, delete itself, fire <Enter> again... and freeze the window.
        item = c.create_text(0, 0, text=text, anchor="nw", fill=INK, font=self.app.fonts["small"],
                             tags="tip", state="disabled")
        x0, y0, x1, y1 = c.bbox(item)
        w, h = x1 - x0, y1 - y0
        tx = min(max(4, x + 12), c.winfo_width() - w - 12)
        c.move(item, tx + 6, 28)
        box = c.create_rectangle(tx, 24, tx + w + 12, 32 + h, fill="white", outline=BASELINE,
                                 tags="tip", state="disabled")
        c.tag_raise(item, box)

    def show_level_stats(self) -> None:
        """Open the statistics window, or refresh and raise it if it is already open."""
        root = self.app.root
        win = self.stats_window
        if win is None or not win.winfo_exists():
            win = self.stats_window = tk.Toplevel(root)
            win.title("Level statistics")
            win.transient(root)  # stays in front of the main window
            columns = ("level", "total", "new", "learning", "young", "mature", "due")
            tree = win.tree = ttk.Treeview(win, columns=columns, show="headings", height=4)
            for col in columns:
                tree.heading(col, text=col.capitalize())
                tree.column(col, width=80, anchor="center")
            tree.pack(padx=12, pady=(12, 6))
            ttk.Label(win, padding=(12, 0), foreground=MUTED,
                      text="Learning: forgotten or just started · Young: interval < 21 days · "
                           "Mature: interval 21+ days").pack()
            ttk.Button(win, text="Close (Esc)", command=win.destroy).pack(pady=10)
            win.bind("<Escape>", lambda e: win.destroy())

        tree = win.tree
        tree.delete(*tree.get_children())
        for level, row in statistics(self.app.all_phrases, self.app.progress).items():
            tree.insert("", "end", values=(level, *(row[c] for c in tree["columns"][1:])))

        # Center over the main window so it can't open hidden or off-screen.
        win.update_idletasks()
        x = root.winfo_rootx() + (root.winfo_width() - win.winfo_reqwidth()) // 2
        y = root.winfo_rooty() + (root.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.deiconify()
        win.lift()
        win.focus_force()

    def on_key(self, key: str) -> None:
        step = {"left": -1, "right": 1}.get(key)
        if step:
            self.select_day(self.selected + timedelta(days=step))

    def on_show(self) -> None:
        self.refresh()


# ---------------------------------------------------------------- Auto play tab

# Seconds of silence after each part; the user can tune them, saved in the settings.
PAUSES = {
    "recall": "Recall",    # after the phrase is spoken: time to recall the meaning
    "answer": "Answer",    # after the answer appears, before the first example
    "example": "Example",  # after each example sentence
    "next": "Next",        # after the last example, before the next phrase
}
DEFAULT_PAUSE = 1.0
MAX_PAUSE = 10.0
TODAY_SOURCE = "Today's phrases"
SPEECH_TIMEOUT = 30.0  # never wait longer than this for one sentence
VOICE_SAMPLE = "Guten Tag! So klingt diese Stimme."


class AutoPlayTab(ttk.Frame):
    """Hands-free practice: speak the phrase, pause, show the answer, read the examples, next.

    Only listens and shows; it never changes the review schedule.
    """

    def __init__(self, parent, app: "TrainerApp"):
        super().__init__(parent)
        self.app = app
        self.items: list[Phrase] = []
        self.index = 0
        self.source_title = TODAY_SOURCE
        self.playing = False
        self._run = 0           # bumps on every start/stop so stale callbacks do nothing
        self._steps = None
        self._job = None        # pending after() call, cancelled on stop
        self._build()
        self.load_today()

    def _build(self) -> None:
        fonts = self.app.fonts
        bar = ttk.Frame(self, padding=(10, 8, 10, 2))
        bar.pack(fill="x")
        self.play_button = ttk.Button(bar, text="▶ Play (Space)", command=self.toggle, width=16,
                                      takefocus=False)
        self.play_button.pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="◀ Previous (←)", command=lambda: self.jump(-1),
                   takefocus=False).pack(side="left", padx=3)
        ttk.Button(bar, text="Next ▶ (→)", command=lambda: self.jump(1),
                   takefocus=False).pack(side="left", padx=(3, 16))
        ttk.Button(bar, text="Load today's phrases", command=self.load_today,
                   takefocus=False).pack(side="right")

        # Pauses and Repeat are set in the Settings tab; these variables are shared with it.
        saved = self.settings.get("autoplay_pauses", {})
        self.pause_vars: dict[str, tk.DoubleVar] = {
            key: tk.DoubleVar(value=saved.get(key, DEFAULT_PAUSE)) for key in PAUSES}
        self.loop_var = tk.BooleanVar(value=self.settings.get("autoplay_loop", False))
        # What to play; the Settings tab shows the same controls.
        self.content_var = tk.StringVar(
            value=AUTOPLAY_CONTENT[clean_content(self.settings.get("autoplay_content"))])
        playing = clean_langs(self.settings.get("autoplay_langs"))
        self.lang_vars = {lang: tk.BooleanVar(value=lang in playing) for lang in LANGS}
        row = ttk.Frame(self, padding=(10, 4, 10, 2))
        row.pack(fill="x")
        self.content_controls(row)

        row = ttk.Frame(self, padding=(10, 4, 10, 2))
        row.pack(fill="x")
        voice_controls(row, self.app)
        ttk.Label(row, text="Pauses and Repeat: see the Settings tab.", font=fonts["small"],
                  foreground=MUTED).pack(side="left", padx=12)

        row = ttk.Frame(self, padding=(10, 2))
        row.pack(fill="x")
        self.source_label = ttk.Label(row, font=fonts["small"], foreground=INK_2)
        self.source_label.pack(side="left")
        self.step_label = ttk.Label(row, font=fonts["small"])
        self.step_label.pack(side="right")
        self.bar = ttk.Progressbar(self, maximum=1.0)
        self.bar.pack(fill="x", padx=12, pady=(2, 0))

        self.card = CardView(self, fonts, self.app.speak_function())
        self.card.pack(fill="both", expand=True)
        if not self.app.speaker.available:
            ttk.Label(self, padding=(12, 6), foreground=MUTED, font=fonts["small"],
                      text="No speech voice was found, so Auto play only shows the cards "
                           "with timed pauses.").pack(fill="x", side="bottom")

    def content_controls(self, parent) -> None:
        labeled_combo(parent, "Play", self.content_var, AUTOPLAY_CONTENT.values(), 18,
                      self.on_content_changed)
        ttk.Label(parent, text="Phrase in").pack(side="left", padx=(0, 6))
        lang_checkboxes(parent, self.lang_vars, self.on_content_changed)

    # ----- what to play

    def content(self) -> str:
        return next(k for k, v in AUTOPLAY_CONTENT.items() if v == self.content_var.get())

    def langs(self) -> list[str]:
        return clean_langs([lang for lang in LANGS if self.lang_vars[lang].get()])

    def on_content_changed(self, clicked: str | None = None) -> None:
        if clicked and checked_langs(self.lang_vars, clicked) is None:
            self.step_label.configure(text="At least one language is needed")
            return
        self.save_settings()
        if not self.playing and self.items:  # while playing, the next phrase uses the new choice
            self._show_still()

    def load_today(self) -> None:
        s = self.app.progress.settings
        phrases = filter_phrases(self.app.all_phrases, s["level"], s["topic"])
        self.load(todays_phrases(phrases, self.app.progress),
                  f"{TODAY_SOURCE} ({s['level']}, {'all topics' if s['topic'] == 'ALL' else s['topic']})")

    def load(self, phrases: list[Phrase], title: str) -> None:
        self.stop()
        self.items, self.index, self.source_title = list(phrases), 0, title
        self._show_still()

    def _show_still(self) -> None:
        """Show the current item without playing."""
        self._update_labels("Press Play to start" if self.items else "")
        if not self.items:
            self.card.message("No phrases to play.\nStudy some phrases first, or use "
                              "“Auto play these” in the Lists tab.")
            return
        phrase, langs = self.items[self.index], self.langs()
        self.card.show(phrase, langs=langs, show_examples=self.content() != "phrase",
                       example_en="en" in langs,
                       info=phrase_info(self.app.progress, phrase, date.today()))

    def _update_labels(self, step: str) -> None:
        total = len(self.items)
        self.source_label.configure(
            text=f"{self.source_title} · phrase {min(self.index + 1, total)} of {total}" if total
            else self.source_title)
        self.step_label.configure(text=step)
        self.bar.configure(value=(self.index + 1) / total if total else 0)

    # ----- playback

    def toggle(self) -> None:
        self.stop() if self.playing else self.play()

    def play(self) -> None:
        if not self.items:
            return
        self._run += 1
        self.playing = True
        self.play_button.configure(text="■ Pause (Space)")
        self._steps = self._item_steps()
        self._next_step(self._run)

    def stop(self) -> None:
        """Pause; Play starts the current phrase again from its beginning."""
        self._run += 1
        self.playing = False
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self.app.speaker.stop()
        self.play_button.configure(text="▶ Play (Space)")
        self.card.highlight_example(None)
        if self.items:
            self._update_labels("Paused")

    def jump(self, step: int) -> None:
        if not self.items:
            return
        was_playing = self.playing
        self.stop()
        self.index = (self.index + step) % len(self.items)
        self._show_still()
        if was_playing:
            self.play()

    @property
    def settings(self) -> dict:
        return self.app.progress.settings

    def pause(self, key: str) -> float:
        """Current pause length; invalid input falls back to the last valid value."""
        var = self.pause_vars[key]
        try:
            value = float(var.get())
        except (tk.TclError, ValueError):
            value = self.settings.get("autoplay_pauses", {}).get(key, DEFAULT_PAUSE)
            var.set(value)
        return min(MAX_PAUSE, max(0.0, value))

    def save_settings(self) -> None:
        new = {"autoplay_pauses": {key: self.pause(key) for key in PAUSES},
               "autoplay_loop": bool(self.loop_var.get()),
               "autoplay_content": self.content(), "autoplay_langs": self.langs()}
        if any(self.settings.get(k) != v for k, v in new.items()):
            self.settings.update(new)
            self.app.progress.save()

    def reset_pauses(self) -> None:
        for var in self.pause_vars.values():
            var.set(DEFAULT_PAUSE)
        self.save_settings()

    def _item_steps(self):
        """One phrase after another: yields ("speak", text, lang) or ("wait", seconds)."""
        while self.index < len(self.items):
            phrase, content, langs = self.items[self.index], self.content(), self.langs()
            info = phrase_info(self.app.progress, phrase, date.today())
            for kind, *args in autoplay_steps(phrase, content, langs):
                if kind == "show":
                    shown, examples = args
                    self.card.show(phrase, langs=langs[:shown], show_examples=examples,
                                   example_en="en" in langs, info=info)
                elif kind == "status":
                    self._update_labels(args[0])
                elif kind == "highlight":
                    self.card.highlight_example(args[0])
                elif kind == "wait":
                    # Read the value at each step, so changes apply while playing.
                    yield ("wait", self.pause(args[0]))
                else:
                    yield (kind, *args)
            if self.index + 1 >= len(self.items) and self.loop_var.get():
                self.index = 0
            else:
                self.index += 1
        self.index = len(self.items) - 1
        self.stop()
        self._update_labels(f"Finished: all {len(self.items)} phrases played")

    def _next_step(self, run: int) -> None:
        if run != self._run:
            return
        try:
            kind, value, *lang = next(self._steps)
        except StopIteration:
            return
        if run != self._run:  # the generator itself stopped playback
            return
        if kind == "wait":
            self._job = self.after(int(value * 1000), self._next_step, run)
        elif self.app.speaker.has_voice(lang[0]):
            self.app.speaker.speak(value, lang[0])
            self._wait_for_speech(run, time.monotonic())
        else:  # no voice: give roughly the time it takes to read the sentence
            self._job = self.after(int((1.0 + 0.06 * len(value)) * 1000), self._next_step, run)

    def _wait_for_speech(self, run: int, started: float) -> None:
        if run != self._run:
            return
        if self.app.speaker.busy and time.monotonic() - started < SPEECH_TIMEOUT:
            self._job = self.after(100, self._wait_for_speech, run, started)
        else:
            self._next_step(run)

    # ----- keys and tab events

    def on_key(self, key: str) -> None:
        phrase = self.items[self.index] if self.items else None
        actions = {"space": self.toggle, "left": lambda: self.jump(-1),
                   "right": lambda: self.jump(1), "escape": self.stop}
        if phrase and not self.playing:
            actions["s"] = lambda: self.app.speaker.speak(phrase.german)
            actions["e"] = lambda: self.app.speak_examples(phrase)
            actions.update({k: (lambda i=i: self.app.speak_examples(phrase, i))
                            for i, k in enumerate(EXAMPLE_KEYS)})
        action = actions.get(key)
        if action:
            action()

    def on_show(self) -> None:
        if not self.playing and self.source_title.startswith(TODAY_SOURCE):
            self.load_today()  # pick up phrases studied since the tab was last opened

    def on_hide(self) -> None:
        if self.playing:
            self.stop()


# ---------------------------------------------------------------- Settings tab

class SettingsTab(ttk.Frame):
    """All settings in one place.

    The controls share their variables with the other tabs, so a change here shows up there
    at once and the other way round. Built after the other tabs.
    """

    def __init__(self, parent, app: "TrainerApp"):
        super().__init__(parent)
        self.app = app
        # Scrollable, so large text sizes still reach every section.
        background = ttk.Style(self).lookup("TFrame", "background")
        self.canvas = tk.Canvas(self, highlightthickness=0, background=background)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas, padding=(12, 10))
        window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(window, width=e.width))
        self.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", self._on_wheel))
        self.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))
        self._build()

    def _on_wheel(self, event: tk.Event) -> None:
        if self.canvas.yview() != (0.0, 1.0):
            step = -1 if event.delta > 0 else 1
            self.canvas.yview_scroll(step if sys.platform == "darwin" else step * 3, "units")

    def section(self, title: str) -> ttk.Frame:
        frame = ttk.LabelFrame(self.body, text=title, padding=(10, 6))
        frame.pack(fill="x", pady=(0, 10))
        return frame

    def line(self, frame, text: str = "") -> ttk.Frame:
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        if text:
            ttk.Label(row, text=text, font=self.app.fonts["small"], foreground=MUTED,
                      wraplength=760, justify="left").pack(side="left")
        return row

    def _build(self) -> None:
        study, autoplay, speaker = self.app.study, self.app.autoplay, self.app.speaker

        box = self.section("Study")
        row = self.line(box)
        self.app.level_box(row, study.level_var, study.on_level_changed)
        study.topic_boxes.append(
            labeled_combo(row, "Topic", study.topic_var, [], 30, study.on_settings_changed))
        study._update_topics()
        row = self.line(box)
        labeled_combo(row, "Direction", study.direction_var, DIRECTIONS.values(), 22,
                      study.on_settings_changed)
        labeled_combo(row, "Answer", study.mode_var, ANSWER_MODES.values(), 15,
                      study.on_settings_changed)
        row = self.line(box)
        labeled_spin(row, "New phrases per day", study.new_var, 0, 200, 5, study.on_settings_changed)
        labeled_spin(row, "Daily goal (ratings)", study.goal_var, 5, 500, 5, study.on_settings_changed)
        self.line(box, "Level, topic, direction and answer mode can also be changed in the Study tab.")

        box = self.section("Display")
        row = self.line(box)
        labeled_spin(row, "Text size (%)", self.app.text_size_var, *TEXT_SIZES,
                     lambda: self.app.apply_text_size(self.app.text_size_var.get()))
        ttk.Button(row, text="Reset to 100 %", command=lambda: self.app.apply_text_size(100),
                   takefocus=False).pack(side="left")
        mod = "⌘" if sys.platform == "darwin" else "Ctrl"
        self.line(box, f"Shortcuts in every tab: {mod} + bigger, {mod} − smaller, {mod} 0 normal size.")

        box = self.section("Speech")
        if speaker.available:
            voice_controls(self.line(box), self.app)
            self.line(box, "The voice can also be chosen in the Study, Browse and Auto play tabs. "
                           "1.0 = normal speed. "
                           "More voices: Windows Settings → Time & language → Speech → Add voices.")
        else:
            self.line(box, "No speech voice was found.")

        box = self.section("Auto play")
        autoplay.content_controls(self.line(box))
        self.line(box, "Phrase in: the languages spoken, in this order (at least one). "
                       "Examples are German, followed by their English translation when English "
                       "is ticked. Also in the Auto play tab.")
        row = self.line(box)
        ttk.Label(row, text="Pauses in seconds:").pack(side="left", padx=(0, 8))
        for key, label in PAUSES.items():
            labeled_spin(row, label, autoplay.pause_vars[key], 0, MAX_PAUSE, 0.5,
                         autoplay.save_settings, width=4)
        ttk.Button(row, text="Reset to 1 s", command=autoplay.reset_pauses,
                   takefocus=False).pack(side="left")
        self.line(box, "Recall: silence after the phrase is spoken · Answer: after the translation "
                       "appears · Example: after each example · Next: before the next phrase.")
        ttk.Checkbutton(self.line(box), text="Repeat from the start", variable=autoplay.loop_var,
                        command=autoplay.save_settings, takefocus=False).pack(side="left")

        box = self.section("Phrase collections")
        row = self.line(box)
        ttk.Button(row, text="Import phrases…", command=self.import_dialog,
                   takefocus=False).pack(side="left", padx=(0, 12))
        self.collections_label = ttk.Label(row)
        self.collections_label.pack(side="left")
        self.update_collections()
        self.line(box, "Add phrases from a file as a new collection with its own name, or add more "
                       "to one you imported before. It appears under Level in every tab. App CSV: "
                       "the columns of data/phrases_B1.csv — topic, german, english, chinese, "
                       f"examples ({' and '.join(REQUIRED)} required; examples like "
                       "“Satz. (Sentence.) | Satz 2. (Sentence 2.)”).")

        box = self.section("Progress file")
        ttk.Label(self.line(box), text=str(self.app.progress.path)).pack(side="left")
        self.line(box, "All settings and your progress are saved automatically in this file. "
                       "Copy it to move your progress to another computer. "
                       "Don't run app.py and trainer.py at the same time.")

    def update_collections(self) -> None:
        counts: dict[str, int] = {}
        for p in self.app.all_phrases:
            counts[p.level] = counts.get(p.level, 0) + 1
        self.collections_label.configure(
            text=" · ".join(f"{name} {count}" for name, count in counts.items()))

    def import_dialog(self) -> None:
        ImportDialog(self.app)

    def on_key(self, key: str) -> None:
        pass

    def on_show(self) -> None:
        pass


class ImportDialog(tk.Toplevel):
    """Choose a file, its format and the collection name, then import."""

    def __init__(self, app: "TrainerApp"):
        super().__init__(app.root)
        self.app = app
        self.title("Import phrases")
        self.transient(app.root)
        self.resizable(False, False)
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        self.file_var = tk.StringVar()
        self.format_var = tk.StringVar(value=next(iter(CONVERTERS)))
        self.name_var = tk.StringVar()
        ttk.Label(frame, text="File").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.file_var, width=48).grid(row=0, column=1, sticky="ew",
                                                                     padx=6)
        ttk.Button(frame, text="Choose…", command=self.choose_file).grid(row=0, column=2)
        ttk.Label(frame, text="Format").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(frame, textvariable=self.format_var, values=list(CONVERTERS), state="readonly",
                     width=30).grid(row=1, column=1, sticky="w", padx=6)
        ttk.Label(frame, text="Collection").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Combobox(frame, textvariable=self.name_var, values=custom_collections(),
                     width=22).grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(frame, text="A new name (letters, digits, - or _), or pick an imported collection "
                              "to add to it.", font=app.fonts["small"], foreground=MUTED,
                  wraplength=460, justify="left").grid(row=3, column=1, columnspan=2, sticky="w",
                                                       padx=6)
        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Import", command=self.run).pack(side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.choose_file()

    def choose_file(self) -> None:
        conv = CONVERTERS[self.format_var.get()]
        path = filedialog.askopenfilename(
            parent=self, title="Import phrases",
            filetypes=[(conv.name, " ".join(f"*{ext}" for ext in conv.extensions)),
                       ("All files", "*.*")])
        if path:
            self.file_var.set(path)
            if not self.name_var.get():  # suggest a name from the file name
                stem = "".join(c for c in Path(path).stem if c.isalnum() or c in "-_")[:20]
                self.name_var.set("" if valid_name(stem) else stem)

    def run(self) -> None:
        path, name = self.file_var.get().strip(), self.name_var.get().strip()
        problem = ("Choose a file to import." if not path else
                   "Type a name for the collection." if not name else valid_name(name))
        if problem:
            messagebox.showwarning("Import phrases", problem, parent=self)
            return
        try:
            result = import_phrases(Path(path), name, self.format_var.get())
        except (OSError, ValueError, UnicodeDecodeError, csv.Error) as exc:
            messagebox.showerror("Import phrases", f"Could not import the file:\n{exc}", parent=self)
            return
        skipped = []
        if result.duplicates:
            skipped.append(f"{result.duplicates} already in the collection")
        if result.invalid:
            rows = ", ".join(map(str, result.invalid[:10])) + (" …" if len(result.invalid) > 10 else "")
            skipped.append(f"{len(result.invalid)} without German or English (rows {rows})")
        text = f"Added {result.added} phrases to “{name}”."
        if skipped:
            text += "\nSkipped: " + "; ".join(skipped) + "."
        self.destroy()
        if result.added:
            self.app.reload_phrases()
        messagebox.showinfo("Import phrases", text, parent=self.app.root)


# ---------------------------------------------------------------- main window

class TrainerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.progress = Progress()
        self.all_phrases = load_all()
        self.by_id = {p.id: p for p in self.all_phrases}
        self.speaker = Speaker(self.progress.settings["voice"], self.progress.settings["speech_rate"])
        # Shared by the voice controls of every tab, so changing one updates all of them.
        self.voice_names = {v.label: v.name for v in self.speaker.voices}
        self.voice_var = tk.StringVar(value=self.speaker.voice.label if self.speaker.voice else "")
        self.rate_var = tk.DoubleVar(value=self.speaker.rate)

        # Font objects, so every widget using them follows the text size setting at once.
        families = {"ui": pick_font(UI_FONTS), "cjk": pick_font(CJK_FONTS)}
        self.fonts = {name: tkfont.Font(root, family=families[kind], size=size, weight=weight)
                      for name, (kind, size, weight) in BASE_FONTS.items()}
        self.tk_font_sizes = {}  # Tk's own fonts (buttons, lists, ...) and their normal sizes
        for name in TK_FONTS:
            try:
                self.tk_font_sizes[name] = tkfont.nametofont(name).cget("size")
            except tk.TclError:
                pass
        self.style = ttk.Style(root)
        self.text_size_var = tk.IntVar(value=100)
        self.apply_text_size(self.progress.settings["text_size"], save=False)
        self.level_boxes: list[ttk.Combobox] = []  # every Level dropdown, updated after an import

        root.title("German Phrase Trainer")
        root.geometry("1100x800")
        root.minsize(900, 640)
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)
        self.study = StudyTab(self.notebook, self)
        self.browse = BrowseTab(self.notebook, self)
        self.lists = ListsTab(self.notebook, self)
        self.progress_tab = ProgressTab(self.notebook, self)
        self.autoplay = AutoPlayTab(self.notebook, self)
        self.settings_tab = SettingsTab(self.notebook, self)  # last: it uses the other tabs' controls
        for tab, title in ((self.study, "  Study  "), (self.browse, "  Browse  "),
                           (self.autoplay, "  Auto play  "), (self.lists, "  Lists  "),
                           (self.progress_tab, "  Progress  "), (self.settings_tab, "  Settings  ")):
            self.notebook.add(tab, text=title)
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self.on_tab_changed())

        root.bind("<Key>", self.on_key)
        undo_key = "<Command-z>" if sys.platform == "darwin" else "<Control-z>"
        root.bind(undo_key, lambda e: None if self._typing(e) else self.study.undo())
        mod = "Command" if sys.platform == "darwin" else "Control"
        for keys, step in ((("plus", "equal", "KP_Add"), 1), (("minus", "KP_Subtract"), -1)):
            for key in keys:
                root.bind(f"<{mod}-{key}>", lambda e, step=step: self.change_text_size(step))
        root.bind(f"<{mod}-0>", lambda e: self.apply_text_size(100))
        root.bind(f"<{mod}-KP_0>", lambda e: self.apply_text_size(100))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = self.report_error

    def report_error(self, exc_type, exc, tb) -> None:
        """Show unexpected errors instead of failing silently, and keep a log for diagnosis."""
        import traceback
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        log_path = self.progress.path.parent / "error.log"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}\n{details}\n")
        except OSError:
            pass
        messagebox.showerror("German Phrase Trainer",
                             f"Something went wrong: {exc}\n\nDetails were saved to:\n{log_path}")

    # ----- text size

    def apply_text_size(self, percent, save: bool = True) -> None:
        low, high, step = TEXT_SIZES
        try:
            percent = int(percent)
        except (TypeError, ValueError, tk.TclError):
            percent = 100
        percent = min(high, max(low, round(percent / step) * step))
        self.text_size_var.set(percent)
        for name, font in self.fonts.items():
            font.configure(size=round(BASE_FONTS[name][1] * percent / 100))
        for name, size in self.tk_font_sizes.items():
            # Negative sizes are pixels, positive ones points; scaling keeps the sign.
            tkfont.nametofont(name).configure(size=round(size * percent / 100) or size)
        linespace = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        self.style.configure("Treeview", rowheight=max(24, linespace + 8))
        if save and self.progress.settings.get("text_size") != percent:
            self.progress.settings["text_size"] = percent
            self.progress.save()
        if save and hasattr(self, "notebook"):
            self.current_tab().on_show()  # redraw charts drawn with the old size

    def change_text_size(self, steps: int) -> None:
        self.apply_text_size(self.progress.settings["text_size"] + steps * TEXT_SIZES[2])

    # ----- phrase collections

    def level_choices(self) -> list[str]:
        return [*collections(), "ALL"]

    def level_box(self, parent, var: tk.StringVar, on_change) -> ttk.Combobox:
        box = labeled_combo(parent, "Level", var, self.level_choices(), 10, on_change)
        self.level_boxes.append(box)
        return box

    def reload_phrases(self) -> None:
        """Pick up imported collections in every tab."""
        self.all_phrases = load_all()
        self.by_id = {p.id: p for p in self.all_phrases}
        for box in self.level_boxes:
            box.configure(values=self.level_choices())
        self.study._update_topics()
        self.study.start_session()
        self.browse.on_level_changed()
        self.lists.on_level_changed()
        self.progress_tab.refresh()
        if not self.autoplay.playing:
            self.autoplay.load_today()
        self.settings_tab.update_collections()

    def current_tab(self):
        return self.root.nametowidget(self.notebook.select())

    @staticmethod
    def _typing(event: tk.Event) -> bool:
        return isinstance(event.widget, (tk.Entry, ttk.Entry))

    def on_key(self, event: tk.Event) -> None:
        if self._typing(event) or event.state & 0x4:  # typing, or a Ctrl shortcut
            return
        self.current_tab().on_key(event.keysym.lower())

    def speak_function(self):
        """Callback for the 🔊 icons next to the examples, or None if speech is unavailable."""
        return self.speaker.speak if self.speaker.available else None

    def speak_examples(self, phrase: Phrase, index: int | None = None) -> None:
        """Speak the German examples only: all of them, or just example `index`."""
        german = [de for de, _ in phrase.examples]
        if index is None:
            self.speaker.speak(" ".join(german))
        elif index < len(german):
            self.speaker.speak(german[index])

    def save_voice(self) -> None:
        speaker = self.speaker
        if self.voice_var.get() in self.voice_names:
            speaker.set_voice(self.voice_names[self.voice_var.get()])
        try:
            speaker.set_rate(self.rate_var.get())
        except tk.TclError:  # not a number: keep the current speed
            pass
        self.rate_var.set(speaker.rate)
        new = {"voice": speaker.voice.name if speaker.voice else "", "speech_rate": speaker.rate}
        if any(self.progress.settings.get(k) != v for k, v in new.items()):
            self.progress.settings.update(new)
            self.progress.save()

    def test_voice(self) -> None:
        self.save_voice()
        if self.autoplay.playing:
            self.autoplay.stop()
        self.speaker.speak(VOICE_SAMPLE)

    def toggle_star(self, phrase_id: str) -> None:
        self.progress.starred ^= {phrase_id}
        self.progress.save()

    def on_tab_changed(self) -> None:
        tab = self.current_tab()
        if tab is not self.autoplay:
            self.autoplay.on_hide()  # don't keep talking in the background
        tab.on_show()

    def practice(self, phrases: list[Phrase], title: str) -> None:
        self.notebook.select(self.study)
        self.study.start_practice(phrases, title)

    def auto_play(self, phrases: list[Phrase], title: str) -> None:
        if not phrases:
            messagebox.showinfo("Auto play", "There are no phrases to play.")
            return
        self.notebook.select(self.autoplay)
        self.autoplay.load(phrases, title)
        self.autoplay.play()

    def open_in_browse(self, phrase_id: str) -> None:
        self.notebook.select(self.browse)
        self.browse.open_phrase(phrase_id)

    def close(self) -> None:
        self.autoplay.stop()
        self.speaker.stop()
        self.root.destroy()


def main() -> None:
    if sys.platform == "win32":
        try:  # crisp text on high-DPI Windows displays
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    TrainerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
