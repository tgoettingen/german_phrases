"""Which languages a card, Auto play and the Lists tab show, shared by app.py and trainer.py.

mobile/logic.js has the same functions; tests/parity.test.js checks both agree.
"""
LANGS = ("de", "en", "zh")
LANG_FIELD = {"de": "german", "en": "english", "zh": "chinese"}
LANG_LABELS = {"de": "German", "en": "English", "zh": "中文"}

# Study always has German on one side; no other combination is allowed.
# "de_to_en" and "en_to_de" keep their old meaning (English and 中文 together), so existing
# progress files show the same cards as before.
DIRECTIONS = {
    "de_to_en": "German → English / 中文",
    "en_to_de": "English / 中文 → German",
    "de_to_en_only": "German → English",
    "en_only_to_de": "English → German",
    "de_to_zh": "German → 中文",
    "zh_to_de": "中文 → German",
}
DIRECTION_LANGS = {  # direction: (front languages, back languages)
    "de_to_en": (("de",), ("en", "zh")),
    "en_to_de": (("en", "zh"), ("de",)),
    "de_to_en_only": (("de",), ("en",)),
    "en_only_to_de": (("en",), ("de",)),
    "de_to_zh": (("de",), ("zh",)),
    "zh_to_de": (("zh",), ("de",)),
}
DEFAULT_DIRECTION = "de_to_en"

AUTOPLAY_CONTENT = {
    "phrase": "Phrase only",
    "phrase_examples": "Phrase + examples",
    "examples": "Examples only",
}
DEFAULT_AUTOPLAY_CONTENT = "phrase_examples"


def clean_direction(value) -> str:
    """A valid direction; anything else (an old or edited file) becomes German → English."""
    return value if value in DIRECTIONS else DEFAULT_DIRECTION


def clean_content(value) -> str:
    return value if value in AUTOPLAY_CONTENT else DEFAULT_AUTOPLAY_CONTENT


def clean_langs(value, default=LANGS) -> list[str]:
    """The known languages in `value`, in German, English, 中文 order; never empty."""
    chosen = [lang for lang in LANGS if isinstance(value, (list, tuple)) and lang in value]
    return chosen or list(default)


def phrase_text(phrase, lang: str) -> str:
    return getattr(phrase, LANG_FIELD[lang])


def card_sides(direction) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(front languages, back languages) of a study card; the typed answer is the first back one."""
    return DIRECTION_LANGS[clean_direction(direction)]


def autoplay_steps(phrase, content, langs) -> list[tuple]:
    """What Auto play does for one phrase, in order.

    ("show", n, examples): show the first n of `langs` on the card, and the examples or not
    ("status", text):      the step label
    ("speak", text, lang): say `text` in `lang`
    ("wait", pause):       wait the pause named "recall", "answer", "example" or "next"
    ("highlight", i):      mark example i (None clears the mark)
    """
    content, langs = clean_content(content), clean_langs(langs)
    with_examples = content != "phrase" and bool(phrase.examples)
    steps = []
    if content != "examples":
        first, rest = langs[0], langs[1:]
        steps += [("show", 1, False), ("status", "🔊 Listen"),
                  ("speak", phrase_text(phrase, first), first)]
        if rest:
            steps += [("status", "💭 What does it mean?"), ("wait", "recall"),
                      ("show", len(langs), with_examples)]
            for lang in rest:
                steps += [("status", f"🔊 {LANG_LABELS[lang]}"), ("speak", phrase_text(phrase, lang), lang)]
        else:
            steps.append(("show", 1, with_examples))
        steps += [("status", "Answer"), ("wait", "answer")]
    else:
        steps.append(("show", len(langs), with_examples))
    if with_examples:
        for i, (german, english) in enumerate(phrase.examples):
            steps += [("highlight", i), ("status", f"🔊 Example {i + 1} of {len(phrase.examples)}"),
                      ("speak", german, "de")]
            if "en" in langs and english:
                steps.append(("speak", english, "en"))
            steps.append(("wait", "example"))
        steps.append(("highlight", None))
    steps += [("status", "Next phrase…"), ("wait", "next")]
    return steps
