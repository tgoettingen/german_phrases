import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from answers import check, normalize
from display_options import (DIRECTIONS, autoplay_steps, card_sides, clean_content, clean_direction,
                             clean_langs, phrase_text)
from learning_log import (GOOD_DAY, HARD_DAY, MISSED, NO_DATA, STUDIED, classify, last_n_days,
                          streaks, summarize)
from phrase_filters import select
from phrase_loader import Phrase
from progress import Progress
from srs import AGAIN, EASY, GOOD, HARD
from study import PracticeSession, StudySession, todays_phrases
from tts import default_voice, parse_voices, sapi_rate, speakable

TODAY = date(2026, 3, 10)


def make_phrases(n: int) -> list[Phrase]:
    return [Phrase(f"B1-{i:04d}", "B1", "Topic", f"wort {i}", f"word {i}", f"词 {i}",
                   [(f"Satz {i}.", f"Sentence {i}.")] * 3) for i in range(1, n + 1)]


def log_day(day: date, ratings: list[int]) -> list[list]:
    return [[day.isoformat(), f"B1-{i:04d}", r, 5.0, 0] for i, r in enumerate(ratings, 1)]


class AnswersTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize("sich um etw. kümmern"), "um kuemmern")
        self.assertEqual(normalize("Straße"), "strasse")
        self.assertEqual(normalize("to meet the requirements"), "meet the requirements")

    def test_exact_and_umlaut_free_answers_are_correct(self):
        self.assertEqual(check("den Wecker stellen", "den Wecker stellen")[1], GOOD)
        self.assertEqual(check("sich um etwas kuemmern", "sich um etw. kümmern")[1], GOOD)

    def test_small_typo_is_hard_and_wrong_is_again(self):
        self.assertEqual(check("den Weker stelen", "den Wecker stellen")[1], HARD)
        self.assertEqual(check("Brot kaufen", "den Wecker stellen")[1], AGAIN)
        self.assertEqual(check("", "den Wecker stellen")[1], AGAIN)

    def test_any_alternative_counts(self):
        self.assertEqual(check("to brief sb.", "to put sb. in the picture, to brief sb.")[1], GOOD)


class LearningLogTest(unittest.TestCase):
    def setUp(self):
        self.days = summarize(
            log_day(TODAY - timedelta(days=5), [GOOD] * 30)                  # good day
            + log_day(TODAY - timedelta(days=4), [GOOD] * 5)                 # studied, below goal
            + log_day(TODAY - timedelta(days=3), [AGAIN] * 5 + [GOOD] * 5)  # hard day
            # TODAY - 2 days: missed
            + log_day(TODAY - timedelta(days=1), [EASY, HARD, AGAIN])
        )

    def kind(self, offset: int) -> str:
        return classify(TODAY - timedelta(days=offset), self.days, goal=30, today=TODAY)

    def test_classify(self):
        self.assertEqual(self.kind(5), GOOD_DAY)
        self.assertEqual(self.kind(4), STUDIED)
        self.assertEqual(self.kind(3), HARD_DAY)
        self.assertEqual(self.kind(2), MISSED)
        self.assertEqual(self.kind(0), NO_DATA)   # today is not missed yet
        self.assertEqual(self.kind(30), NO_DATA)  # before the first study day

    def test_summary(self):
        s = self.days[TODAY - timedelta(days=3)]
        self.assertEqual((s.total, s.forgotten, s.recalled), (10, 5, 5))
        self.assertAlmostEqual(s.accuracy, 0.5)
        self.assertEqual(s.forgotten_ids, [f"B1-{i:04d}" for i in range(1, 6)])
        self.assertEqual(s.seconds, 50)

    def test_streaks(self):
        self.assertEqual(streaks(self.days, TODAY), (1, 3))
        self.assertEqual(streaks({}, TODAY), (0, 0))

    def test_last_n_days_fills_gaps(self):
        data = last_n_days(self.days, TODAY, 7)
        self.assertEqual([d.total for d in data], [0, 30, 5, 10, 0, 3, 0])
        self.assertEqual(data[-1].day, TODAY)


class FiltersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.progress = Progress(Path(self.tmp.name) / "p.json")
        self.progress.settings["new_per_day"] = 4
        self.phrases = make_phrases(10)
        s = StudySession(self.phrases, self.progress, TODAY)
        for rating in (GOOD, AGAIN, GOOD, EASY):
            s.rate(rating)
        self.progress.starred = {"B1-0010"}

    def tearDown(self):
        self.tmp.cleanup()

    def ids(self, **kw):
        return [p.id for p in select(self.phrases, self.progress, today=TODAY, **kw)]

    def test_kinds(self):
        self.assertEqual(self.ids(kind="learned"), ["B1-0001", "B1-0002", "B1-0003", "B1-0004"])
        self.assertEqual(len(self.ids(kind="to_learn")), 6)
        self.assertEqual(self.ids(kind="forgotten"), ["B1-0002"])
        self.assertEqual(self.ids(kind="due"), ["B1-0002"])
        self.assertEqual(self.ids(kind="starred"), ["B1-0010"])

    def test_limit_search_and_sort(self):
        self.assertEqual(len(self.ids(kind="all", limit=3)), 3)
        self.assertEqual(self.ids(kind="all", query="Sentence 7"), ["B1-0007"])
        self.assertEqual(self.ids(kind="all", query="词 10"), ["B1-0010"])
        self.assertEqual(self.ids(kind="learned", sort="due")[0], "B1-0002")


class SessionNavigationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.progress = Progress(Path(self.tmp.name) / "p.json")
        self.progress.settings["new_per_day"] = 5
        self.phrases = make_phrases(10)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rating_is_logged_and_undo_removes_it(self):
        s = StudySession(self.phrases, self.progress, TODAY)
        s.rate(GOOD, seconds=500)
        self.assertEqual(self.progress.log, [[TODAY.isoformat(), "B1-0001", GOOD, 60, 1]])
        self.assertEqual(s.rated, [(self.phrases[0], GOOD)])
        s.undo()
        self.assertEqual((self.progress.log, s.rated), ([], []))
        self.assertEqual(Progress(self.progress.path).log, [])

    def test_skip_moves_card_to_end(self):
        s = StudySession(self.phrases, self.progress, TODAY)
        first = s.current
        self.assertTrue(s.skip())
        self.assertEqual(s.queue[-1], first)
        self.assertNotEqual(s.current, first)

    def test_todays_phrases_reviewed_first_then_waiting(self):
        s = StudySession(self.phrases, self.progress, TODAY)
        s.rate(AGAIN)   # B1-0001 forgotten: reviewed today and still waiting
        s.rate(GOOD)    # B1-0002 done for today
        ids = [p.id for p in todays_phrases(self.phrases, self.progress, TODAY)]
        self.assertEqual(ids, ["B1-0001", "B1-0002", "B1-0003", "B1-0004", "B1-0005"])
        tomorrow = [p.id for p in todays_phrases(self.phrases, self.progress, TODAY + timedelta(1))]
        self.assertEqual(tomorrow[:2], ["B1-0001", "B1-0002"])  # due reviews come first
        self.assertNotIn("B1-0006", tomorrow[:5])

    def test_practice_does_not_change_progress(self):
        p = PracticeSession(self.phrases[:3])
        p.rate(AGAIN)
        p.rate(GOOD)
        self.assertEqual(len(p.queue), 2)
        self.assertEqual(p.queue[1], self.phrases[0])  # forgotten card comes back
        self.assertTrue(p.undo())
        self.assertEqual(len(p.queue), 3)
        self.assertEqual(self.progress.cards, {})


class DisplayOptionsTest(unittest.TestCase):
    def setUp(self):
        self.phrase = make_phrases(1)[0]

    def test_six_directions_always_have_german_on_one_side(self):
        # The original two keep their meaning: English and 中文 together.
        self.assertEqual(card_sides("de_to_en"), (("de",), ("en", "zh")))
        self.assertEqual(card_sides("en_to_de"), (("en", "zh"), ("de",)))
        self.assertEqual(card_sides("de_to_en_only"), (("de",), ("en",)))
        self.assertEqual(card_sides("en_only_to_de"), (("en",), ("de",)))
        self.assertEqual(card_sides("de_to_zh"), (("de",), ("zh",)))
        self.assertEqual(card_sides("zh_to_de"), (("zh",), ("de",)))
        self.assertEqual(len(DIRECTIONS), 6)
        for front, back in map(card_sides, DIRECTIONS):
            self.assertTrue((front == ("de",)) != (back == ("de",)))  # German on exactly one side
        self.assertEqual(phrase_text(self.phrase, "zh"), "词 1")

    def test_invalid_values_fall_back(self):
        self.assertEqual(clean_direction("en_zh"), "de_to_en")
        self.assertEqual(clean_direction(None), "de_to_en")
        self.assertEqual(clean_content("everything"), "phrase_examples")
        self.assertEqual(clean_langs([]), ["de", "en", "zh"])
        self.assertEqual(clean_langs(["zh", "fr", "de"]), ["de", "zh"])  # fixed order, known only
        self.assertEqual(clean_langs("de"), ["de", "en", "zh"])

    def test_progress_file_with_unknown_direction_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "progress.json"
            path.write_text('{"settings": {"direction": "en_zh"}}', encoding="utf-8")
            settings = Progress(path).settings
        self.assertEqual(settings["direction"], "de_to_en")
        self.assertEqual(settings["lists_langs"], ["de", "en", "zh"])

    def spoken(self, content, langs):
        return [(s[2], s[1]) for s in autoplay_steps(self.phrase, content, langs) if s[0] == "speak"]

    def test_phrase_only_speaks_the_chosen_languages_in_order(self):
        self.assertEqual(self.spoken("phrase", ["zh", "de"]), [("de", "wort 1"), ("zh", "词 1")])
        self.assertEqual(self.spoken("phrase", ["en"]), [("en", "word 1")])
        steps = autoplay_steps(self.phrase, "phrase", ["de"])
        self.assertNotIn(("wait", "recall"), steps)  # nothing to recall with a single language
        self.assertFalse(any(s[0] == "highlight" for s in steps))

    def test_examples_follow_the_phrase(self):
        spoken = self.spoken("phrase_examples", ["de", "en"])
        self.assertEqual(spoken[:2], [("de", "wort 1"), ("en", "word 1")])
        self.assertEqual(spoken[2:4], [("de", "Satz 1."), ("en", "Sentence 1.")])
        self.assertEqual(len(spoken), 2 + 3 * 2)
        # Without English the examples are German only
        self.assertEqual(len(self.spoken("phrase_examples", ["de", "zh"])), 2 + 3)

    def test_examples_only_skips_the_phrase(self):
        self.assertEqual(self.spoken("examples", ["de", "zh"]), [("de", "Satz 1.")] * 3)
        steps = autoplay_steps(self.phrase, "examples", ["de", "zh"])
        self.assertEqual(steps[0], ("show", 2, True))
        self.assertEqual(steps[-1], ("wait", "next"))


class SpeakableTest(unittest.TestCase):
    def test_expands_abbreviations(self):
        self.assertEqual(speakable("sich um etw. kümmern"), "sich um etwas kümmern")
        self.assertEqual(speakable("jdm. helfen"), "jemandem helfen")


class VoiceTest(unittest.TestCase):
    LISTING = "winrt\nMicrosoft Hedda|Female|de-DE\nMicrosoft Stefan|Male|de-DE\n" \
              "Microsoft Katja|Female|de-DE\n"

    def test_parse_voices(self):
        voices = parse_voices(self.LISTING)
        self.assertEqual([v.name for v in voices],
                         ["Microsoft Hedda", "Microsoft Stefan", "Microsoft Katja"])
        self.assertEqual(voices[1].label, "Stefan (male)")
        self.assertEqual(parse_voices("sapi\nMicrosoft Hedda Desktop|NotSet|de-DE")[0].label, "Hedda")

    def test_parse_voices_keeps_english_and_chinese(self):
        voices = parse_voices(self.LISTING + "Microsoft Zira|Female|en-US\nMicrosoft Huihui|Female|zh-CN\n"
                              "Microsoft Ayumi|Female|ja-JP\n")
        self.assertEqual([v.lang for v in voices], ["de", "de", "de", "en", "zh"])
        self.assertEqual(default_voice(voices).name, "Microsoft Katja")
        self.assertEqual(default_voice(voices, "zh").name, "Microsoft Huihui")
        self.assertIsNone(default_voice(voices[:3], "en"))

    def test_default_voice_prefers_katja_and_avoids_hedda(self):
        voices = parse_voices(self.LISTING)
        self.assertEqual(default_voice(voices).name, "Microsoft Katja")
        self.assertEqual(default_voice(voices[:2]).name, "Microsoft Stefan")
        self.assertIsNone(default_voice([]))

    def test_sapi_rate(self):
        self.assertEqual(sapi_rate(1.0), 0)
        self.assertEqual(sapi_rate(0.9), -1)
        self.assertEqual(sapi_rate(3.0), 10)


if __name__ == "__main__":
    unittest.main()
