"""German phrase trainer: a tkinter flashcard app with spaced repetition.

Run: python app.py

Keys: Space/Enter = show answer, 1-4 = Again/Hard/Good/Easy, Ctrl+Z (Cmd+Z on macOS) = undo.
"""
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

from display_options import DIRECTIONS, card_sides, phrase_text
from phrase_loader import collections, load_all
from progress import Progress
from srs import RATING_NAMES, RATINGS, format_interval
from study import StudySession, statistics

LEVEL_CHOICES = (*collections(), "ALL")
EXTRA_NEW = 10

# Preferred fonts per platform; the first installed one is used.
UI_FONTS = {
    "darwin": ["Helvetica Neue", "Helvetica"],
    "win32": ["Segoe UI", "Arial"],
}.get(sys.platform, ["DejaVu Sans", "Liberation Sans"])
CJK_FONTS = {
    "darwin": ["PingFang SC", "Hiragino Sans GB", "STHeiti"],
    "win32": ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei"],
}.get(sys.platform, ["Noto Sans CJK SC", "WenQuanYi Micro Hei"])


def pick_font(candidates: list[str]) -> str:
    installed = set(tkfont.families())
    return next((f for f in candidates if f in installed), "TkDefaultFont")


class PhraseApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.progress = Progress()
        self.all_phrases = load_all()
        self.session: StudySession | None = None
        self.revealed = False

        ui, cjk = pick_font(UI_FONTS), pick_font(CJK_FONTS)
        self.fonts = {
            "front": (ui, 26, "bold"),
            "front_chinese": (cjk, 26, "bold"),
            "back": (ui, 18),
            "chinese": (cjk, 18),
            "small": (ui, 11),
            "example": (ui, 13),
        }

        root.title("German Phrases")
        root.geometry("820x640")
        root.minsize(600, 480)
        self._build_toolbar()
        self._build_card()
        self._build_buttons()
        self._bind_keys()
        self.start_session()

    # ---------- layout ----------

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.root, padding=(10, 8))
        bar.pack(fill="x")
        settings = self.progress.settings

        ttk.Label(bar, text="Level").pack(side="left")
        self.level_var = tk.StringVar(value=settings["level"])
        level = ttk.Combobox(bar, textvariable=self.level_var, values=LEVEL_CHOICES,
                             state="readonly", width=5)
        level.pack(side="left", padx=(4, 12))
        level.bind("<<ComboboxSelected>>", lambda e: self.on_settings_changed())

        self.direction_var = tk.StringVar(value=DIRECTIONS[settings["direction"]])
        direction = ttk.Combobox(bar, textvariable=self.direction_var,
                                 values=list(DIRECTIONS.values()), state="readonly", width=24)
        direction.pack(side="left", padx=(0, 12))
        direction.bind("<<ComboboxSelected>>", lambda e: self.on_settings_changed())

        ttk.Label(bar, text="New/day").pack(side="left")
        self.new_var = tk.IntVar(value=settings["new_per_day"])
        spin = ttk.Spinbox(bar, from_=0, to=200, increment=5, textvariable=self.new_var,
                           width=5, command=self.on_settings_changed)
        spin.pack(side="left", padx=(4, 12))
        spin.bind("<Return>", lambda e: self.on_settings_changed())
        spin.bind("<FocusOut>", lambda e: self.on_settings_changed())

        ttk.Button(bar, text="Statistics", command=self.show_statistics).pack(side="right")

        self.status = ttk.Label(self.root, padding=(12, 0), font=self.fonts["small"])
        self.status.pack(fill="x")

    def _build_card(self) -> None:
        card = ttk.Frame(self.root, padding=(24, 12))
        card.pack(fill="both", expand=True)
        self.topic = ttk.Label(card, font=self.fonts["small"], foreground="gray")
        self.topic.pack(anchor="w")
        self.front = ttk.Label(card, font=self.fonts["front"], justify="center", anchor="center")
        self.front.pack(fill="x", pady=(24, 12))
        self.separator = ttk.Separator(card)
        self.back = ttk.Label(card, font=self.fonts["back"], justify="center", anchor="center")
        self.examples = tk.Text(card, wrap="word", height=8, relief="flat", borderwidth=0,
                                font=self.fonts["example"], cursor="arrow",
                                background=self.root.cget("background"))
        self.examples.tag_configure("de", spacing1=8)
        self.examples.tag_configure("en", foreground="gray", lmargin1=18, lmargin2=18)
        self.wrapping = [self.front, self.back]
        card.bind("<Configure>", self._on_resize)

    def _build_buttons(self) -> None:
        self.button_bar = ttk.Frame(self.root, padding=(10, 10))
        self.button_bar.pack(fill="x", side="bottom")
        # takefocus=False: Space must never "click" a focused rating button.
        self.show_button = ttk.Button(self.button_bar, text="Show answer  (Space)",
                                      command=self.reveal, takefocus=False)
        self.rate_buttons = {
            r: ttk.Button(self.button_bar, command=lambda r=r: self.rate(r), takefocus=False)
            for r in RATINGS
        }
        self.more_button = ttk.Button(self.button_bar, text=f"Learn {EXTRA_NEW} more new phrases",
                                      command=self.learn_more, takefocus=False)

    def _bind_keys(self) -> None:
        def shortcut(action):
            # Ignore shortcuts while typing in the toolbar fields.
            return lambda e: None if isinstance(e.widget, (tk.Entry, ttk.Entry)) else action()

        self.root.bind("<space>", shortcut(self.reveal))
        self.root.bind("<Return>", shortcut(self.reveal))
        for r in RATINGS:
            self.root.bind(str(r), shortcut(lambda r=r: self.rate(r)))
        undo_key = "<Command-z>" if sys.platform == "darwin" else "<Control-z>"
        self.root.bind(undo_key, shortcut(self.undo))

    def _on_resize(self, event: tk.Event) -> None:
        for label in self.wrapping:
            label.configure(wraplength=max(200, event.width - 48))

    # ---------- session flow ----------

    def on_settings_changed(self) -> None:
        settings = self.progress.settings
        try:
            new_per_day = max(0, int(self.new_var.get()))
        except (tk.TclError, ValueError):
            new_per_day = settings["new_per_day"]
            self.new_var.set(new_per_day)
        direction = next(k for k, v in DIRECTIONS.items() if v == self.direction_var.get())
        changed = (settings["level"], settings["direction"], settings["new_per_day"]) != (
            self.level_var.get(), direction, new_per_day)
        if not changed:
            return
        settings.update(level=self.level_var.get(), direction=direction, new_per_day=new_per_day)
        self.progress.save()
        self.start_session()

    def start_session(self) -> None:
        level = self.progress.settings["level"]
        phrases = [p for p in self.all_phrases if level == "ALL" or p.level == level]
        self.session = StudySession(phrases, self.progress)
        self.show_card()

    def show_card(self) -> None:
        self.revealed = False
        self.root.focus_set()
        for w in (self.separator, self.back, self.examples):
            w.pack_forget()
        for w in (self.show_button, self.more_button, *self.rate_buttons.values()):
            w.pack_forget()
        self.update_status()

        phrase = self.session.current
        if phrase is None:
            self.topic.configure(text="")
            self.front.configure(text="All done for today!\nCome back tomorrow for your reviews.")
            self.more_button.pack(expand=True)
            return

        self.topic.configure(text=f"{phrase.id} · {phrase.topic}")
        front, back = card_sides(self.progress.settings["direction"])
        self.front.configure(text="\n".join(phrase_text(phrase, lang) for lang in front),
                             font=self.fonts["front_chinese" if front == ("zh",) else "front"])
        self.back.configure(text="\n".join(phrase_text(phrase, lang) for lang in back),
                            font=self.fonts["chinese" if back == ("zh",) else "back"])
        self.show_button.pack(expand=True, ipadx=20, ipady=6)

    def reveal(self) -> None:
        phrase = self.session.current
        if phrase is None or self.revealed:
            return
        self.revealed = True
        self.separator.pack(fill="x", pady=8)
        self.back.pack(fill="x", pady=(8, 8))
        self.examples.configure(state="normal")
        self.examples.delete("1.0", "end")
        for german, english in phrase.examples:
            self.examples.insert("end", f"• {german}\n", "de")
            self.examples.insert("end", f"{english}\n", "en")
        self.examples.configure(state="disabled")
        self.examples.pack(fill="both", expand=True, pady=(8, 0))

        self.show_button.pack_forget()
        preview = self.session.preview()
        for r, button in self.rate_buttons.items():
            button.configure(text=f"{RATING_NAMES[r]} ({r})  ·  {format_interval(preview[r])}")
            button.pack(side="left", expand=True, fill="x", padx=4, ipady=8)

    def rate(self, rating: int) -> None:
        if not self.revealed or self.session.current is None:
            return
        self.session.rate(rating)
        self.show_card()

    def undo(self) -> None:
        if self.session.undo():
            self.show_card()

    def learn_more(self) -> None:
        if self.session.add_new(EXTRA_NEW) == 0:
            messagebox.showinfo("German Phrases", "You have started every phrase at this level.")
        self.show_card()

    def update_status(self) -> None:
        left = self.session.remaining()
        today = self.progress.counters(self.session.today)
        self.status.configure(
            text=f"To study: {left['new']} new · {left['review']} review      "
                 f"Today: {today['new']} new learned · {today['reviews']} reviews")

    def show_statistics(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Statistics")
        columns = ("level", "total", "new", "learning", "young", "mature", "due")
        tree = ttk.Treeview(win, columns=columns, show="headings", height=5)
        for col in columns:
            tree.heading(col, text=col.capitalize())
            tree.column(col, width=80, anchor="center")
        stats = statistics(self.all_phrases, self.progress)
        for level, row in stats.items():
            tree.insert("", "end", values=(level, *(row[c] for c in columns[1:])))
        tree.pack(padx=12, pady=12)
        ttk.Label(win, padding=(12, 0, 12, 12), foreground="gray",
                  text="Learning: forgotten or just started · Young: interval < 21 days · "
                       "Mature: interval ≥ 21 days").pack()


def main() -> None:
    if sys.platform == "win32":
        try:  # crisp text on high-DPI Windows displays
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    PhraseApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
