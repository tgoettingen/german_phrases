# German Phrases

A flashcard app for learning 4,000 German phrases (B1: 1,000, B2: 1,500, C1: 1,500) and
3,000 words (1,000 each in the collections *Wort-B1*, *Wort-B2*, *Wort-C1*), with English and Chinese
translations and three example sentences each. It schedules reviews with spaced repetition
(an SM-2 variant, like Anki). Pure Python standard library, so it runs on Windows, macOS and Linux.

## Run

```bash
python app.py          # Windows
python3 app.py         # macOS / Linux
```

Requires Python 3.10+ with tkinter. The python.org installers include it; with Homebrew on
macOS run `brew install python-tk` once, on Debian/Ubuntu `sudo apt install python3-tk`.

## How to study

1. Pick a level (B1, B2, C1 or ALL), a direction and how many new phrases per day.
2. Read the phrase and recall the meaning, then press **Space** to show the answer.
3. Rate how well you knew it:

| Key | Rating | Effect |
|-----|--------|--------|
| 1 | Again | Forgotten: the card comes back in a few cards, and its interval restarts |
| 2 | Hard  | Recalled with effort: shorter interval |
| 3 | Good  | Recalled: normal interval (1 day, 6 days, then × ease) |
| 4 | Easy  | Effortless: longer interval |

Each button shows the next interval. **Ctrl+Z** (**Cmd+Z** on macOS) undoes the last rating.
Due reviews come before new phrases. When you are done, you can learn 10 extra new phrases.

Progress is saved after every rating to `data/progress.json`. Copy that file to move your
progress to another computer.

## Phrase Trainer (extended app)

```bash
python trainer.py
```

Same study method and the same progress file as `app.py`, organised in six tabs:

- **Study**: spaced-repetition study with a topic filter and a daily goal. Level, topic,
  direction and answer mode can be changed here or in Settings.
  - **← Back / Forward →** steps through the cards you already rated in this session;
    **→** on the current card skips it to the end of the queue.
  - **Type the answer** mode checks what you type, ignores umlaut spelling (ae/oe/ue/ss)
    and *etw./jdn.* placeholders, and suggests a rating (press Enter to accept).
  - **S** speaks the phrase (German voice of the OS), **M** stars it.
  - While the examples are shown, click the 🔊 next to a German example, or press **D**, **F**
    or **G** for example 1, 2 or 3; **E** (or the *Examples* button) reads all three.
    Only the German sentences are spoken. This works in Browse and Auto play too.
- **Browse**: move freely through all phrases (←/→, Random, slider, go to number or ID),
  with translations shown or hidden (Space peeks).
- **Auto play**: hands-free listening practice. By default it plays all of today's phrases
  (already reviewed today, then still due or new), one after another:
  speak the phrase → pause to recall the meaning → show the answer → pause → read each
  German example, highlighted, with a pause after each → pause → next phrase.
  The four pauses (**Recall**, **Answer**, **Example**, **Next**) and *Repeat from the start*
  are set in the Settings tab; changes apply immediately, even while playing.
  **Space** plays/pauses (resuming restarts the current phrase), **← / →** jumps, **Esc** stops.
  Lists has *Auto play these* and the Progress calendar has *Auto play this day*.
  Auto play never changes your review schedule.
- **Voice** and **Speed** can be chosen in each tab that speaks (Study, Browse, Auto play) and in
  Settings; *▶ Test* plays a sample. All tabs share the same choice, and it is saved. On Windows 10/11
  the trainer uses the natural-sounding voices Katja (female) and Stefan (male); more voices:
  Settings → Time & language → Speech → Add voices.
- **Lists**: learned, to be learned, due, forgotten, difficult, starred or well-known phrases;
  choose the number of items, with or without translation and examples, search and sort.
  **Practice these** drills the list without changing your schedule; **Export…** saves CSV or
  printable text. Forgotten phrases are highlighted.
- **Progress**: a calendar of your learning days with highlights: good days (goal reached and
  85%+ recalled), studied days, hard days (under 70% recalled) and missed days (no study).
  Click a day to see what you reviewed, forgotten phrases first, and practice them again.
  Also streaks, totals, a 30-day chart and statistics per level.
- **Settings**: all settings in one place: study (level, topic, direction, answer mode, new
  phrases per day, daily goal), text size, speech (voice, speed), Auto play (pauses from 0 to
  10 s, *Reset to 1 s*, repeat), phrase collections and where the progress file is. Everything is
  saved automatically.
  - **Text size** from 70 % to 200 %; in every tab **Ctrl +** / **Ctrl −** change it and
    **Ctrl 0** resets it (**⌘** on macOS). Large sizes may need a bigger window.
  - **Import phrases…** adds phrases from a file as a new *collection* with a name you choose
    (letters, digits, `-`, `_`), saved as `data/phrases_<name>.csv`. It appears under *Level* in
    every tab next to B1/B2/C1, with IDs like `BERUF-0001`. Importing again into the same name
    adds to it; phrases already in it (same German text) and rows without German or English are
    skipped. The file uses the columns of `data/phrases_B1.csv`: `topic`, `german`, `english`,
    `chinese`, `examples` (only `german` and `english` are required; `id`/`level` are assigned;
    comma, semicolon or tab separated; examples like `Satz. (Sentence.) | Satz 2. (Sentence 2.)`).
  - Other file formats: add a converter function in `phrase_import.py` (see the module docstring);
    it then shows up under *Format* in the import dialog.

Don't run `app.py` and `trainer.py` at the same time: both write `data/progress.json`.

## Android phone app

`mobile/` contains the Phrase Trainer as an installable web app for Android, with the same tabs and
the same `progress.json` format (export/import to move progress). See `mobile/README.md`.

## Files

| File | Purpose |
|------|---------|
| `app.py` | simple flashcard app |
| `trainer.py` | extended trainer: study, browse, lists, progress calendar |
| `learning_log.py` | per-day summaries, day highlights, streaks |
| `phrase_filters.py` | list filters, search and sorting |
| `answers.py` | checks typed answers |
| `tts.py` | text-to-speech with the OS voices (voice and speed selectable) |
| `study.py` | study session: daily queue, rating, undo, statistics |
| `srs.py` | spaced-repetition scheduler |
| `progress.py` | saves and loads progress and settings |
| `phrase_loader.py` | loads `data/phrases_*.csv` (B1/B2/C1 and imported collections) into `Phrase` objects |
| `phrase_import.py` | imports phrase files as named collections; converters for file formats |
| `tools/build_phrases.py` | rebuilds the phrase CSVs from `data/chunks/` (`--kind words`: the word collections from `data/word_chunks/`); existing IDs are kept, new entries are appended up to `--target`/`--targets B2=1500,C1=1500` |
| `tests/` | unit tests: `python -m unittest discover -s tests` |
| `mobile/` | Android phone app (installable web app), see `mobile/README.md` |
| `web/` | browser app for PC and phone (the mobile app with a desktop sidebar), see `web/README.md` |

## new requirements

- study and other place, it should allow only select english -> german, or german to english, or chinese to german, or german to chinese, and not allow any other combination.
- auto play should allow which part to autoplay, e.g. only the phrase (in different language?), or phrase + examples, or only examples, etc. and not allow any other combination. also in the lists tab, it should also possible to display different combinations, German on/off, english on/off, chinese on/off. 