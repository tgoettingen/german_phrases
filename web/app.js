// German Phrase Trainer for phones: the five tabs of trainer.py (Study, Browse, Auto play,
// Lists, Progress) as an installable web app. The learning logic lives in logic.js.
import * as L from "./logic.js";

const STORAGE_KEY = "german-phrases/progress";
const VOICE_KEY = "german-phrases/voice";
const RATE_KEY = "german-phrases/rate";
const VOICE_SAMPLE = "Guten Tag! So klingt diese Stimme.";
const EXTRA_NEW = 10;
const EXAMPLE_KEYS = ["d", "f", "g"]; // speak example 1-3
const CHART_DAYS = 30;
const PAUSES = { recall: "Recall", answer: "Answer", example: "Example", next: "Next" };
const DEFAULT_PAUSE = 1;
const MAX_PAUSE = 10;
const TODAY_SOURCE = "Today's phrases";
const SPEECH_TIMEOUT = 30000; // never wait longer than this for one sentence (ms)

const SERIES_RECALLED = "#2a78d6", SERIES_FORGOTTEN = "#eb6834";
const MUTED = "#898781", INK_2 = "#52514e", GRID = "#e1e0d9", BASELINE = "#c3c2b7";
const DAY_STYLES = { // kind: [cell tint, accent, icon, legend text]
  [L.GOOD_DAY]: ["#d3eed3", "#0ca30c", "★", "Good day: goal reached, 85%+ recalled"],
  [L.STUDIED]: ["#cde2fb", "#2a78d6", "✓", "Studied"],
  [L.HARD_DAY]: ["#fbe1d6", "#ec835a", "!", "Hard day: under 70% recalled"],
  [L.MISSED]: ["#f6d4d4", "#d03b3b", "✗", "Missed day: no study"],
  [L.NO_DATA]: ["#fcfcfb", "#c3c2b7", "", ""],
};
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];

// ---------------------------------------------------------------- small helpers

const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  node.append(...children.filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

function setOptions(select, entries, value) {
  select.replaceChildren(...entries.map(([v, label]) => el("option", { value: v, text: label })));
  select.value = entries.some(([v]) => v === value) ? value : entries[0]?.[0] ?? "";
}

const pairs = (values) => values.map((v) => [v, v]);
const topicOptions = (level) => pairs([L.ALL_TOPICS, ...L.topicsFor(app.phrases, level)]);

function readInt(input, fallback, low = 0) {
  const value = parseInt(input.value, 10);
  if (Number.isNaN(value)) {
    input.value = fallback;
    return fallback;
  }
  return Math.max(low, value);
}

let toastTimer = null;
function toast(text) {
  const node = $("toast");
  node.textContent = text;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, 3500);
}

function download(text, name, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = el("a", { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

// Dates are ISO strings; these format them like the desktop app's strftime calls.
const isoParts = (iso) => [+iso.slice(0, 4), +iso.slice(5, 7), +iso.slice(8, 10)];
const weekday = (iso) => {
  const [year, month, day] = isoParts(iso);
  return new Date(Date.UTC(year, month - 1, day)).getUTCDay();
};
const dd = (iso) => iso.slice(8, 10);
const mon = (iso) => MONTHS[isoParts(iso)[1] - 1].slice(0, 3);
const fmtLong = (iso) => `${WEEKDAYS[weekday(iso)]}, ${dd(iso)} ${MONTHS[isoParts(iso)[1] - 1]} ${iso.slice(0, 4)}`;
const fmtDayMon = (iso) => `${dd(iso)} ${mon(iso)}`;

// ---------------------------------------------------------------- speech

class Speaker {
  constructor() {
    this.synth = window.speechSynthesis || null;
    this.voices = [];
    this.voiceName = localStorage.getItem(VOICE_KEY) || "";
    this.rate = Number(localStorage.getItem(RATE_KEY)) || 1; // 1 = normal speed
    this.utterance = null; // keep a reference: Chrome drops events of collected utterances
    this.onVoices = () => {};
    if (this.synth) {
      this.loadVoices();
      this.synth.addEventListener?.("voiceschanged", () => this.loadVoices());
    }
  }

  get available() {
    return Boolean(this.synth);
  }

  loadVoices() {
    this.voices = this.synth.getVoices().filter((v) => v.lang.toLowerCase().replace("_", "-").startsWith("de"));
    this.onVoices();
  }

  get voice() {
    return this.voices.find((v) => v.name === this.voiceName)
      || this.voices.find((v) => /^de[-_]DE/i.test(v.lang)) || this.voices[0] || null;
  }

  setVoice(name) {
    this.voiceName = name;
    localStorage.setItem(VOICE_KEY, name);
  }

  setRate(rate) {
    this.rate = Math.min(1.5, Math.max(0.5, Number(rate) || 1));
    localStorage.setItem(RATE_KEY, String(this.rate));
  }

  // Resolves when the sentence has been spoken (or was interrupted).
  speak(text) {
    if (!this.synth) return Promise.resolve();
    this.synth.cancel();
    const u = new SpeechSynthesisUtterance(L.speakable(text));
    u.lang = "de-DE";
    u.rate = this.rate;
    if (this.voice) u.voice = this.voice;
    this.utterance = u;
    return new Promise((resolve) => {
      u.onend = u.onerror = () => {
        if (this.utterance === u) this.utterance = null;
        resolve();
      };
      this.synth.speak(u);
    });
  }

  stop() {
    this.utterance = null;
    this.synth?.cancel();
  }
}

// ---------------------------------------------------------------- card

// Shows one phrase: front, answer (translations) and example sentences with 🔊 buttons.
class CardView {
  constructor(root) {
    this.root = root;
    this.phrase = null;
    this.examplesVisible = false;
    this.items = [];
  }

  message(text) {
    this.phrase = null;
    this.examplesVisible = false;
    this.items = [];
    this.root.replaceChildren(el("div", { class: "message", text }));
  }

  show(phrase, { direction = "de_to_en", showBack = true, showExamples = true, exampleEn = true,
    info = "", banner = "" } = {}) {
    this.phrase = phrase;
    const toGerman = direction !== "de_to_en";
    const front = toGerman ? `${phrase.english}\n${phrase.chinese}` : phrase.german;
    const back = toGerman ? phrase.german : phrase.english;
    const chinese = toGerman ? "" : phrase.chinese;
    const parts = [el("div", { class: "info", text: info })];
    if (banner) parts.push(el("div", { class: "banner", text: banner }));
    parts.push(el("div", { class: "front", lang: toGerman ? null : "de", text: front }));
    if (showBack || showExamples) parts.push(el("hr"));
    if (showBack) {
      parts.push(el("div", { class: "back", lang: toGerman ? "de" : null, text: back }));
      if (chinese) parts.push(el("div", { class: "chinese", lang: "zh", text: chinese }));
    }
    this.items = [];
    if (showExamples) {
      const speech = app.speaker.available;
      if (speech) {
        parts.push(el("div", { class: "examples-head" },
          el("button", { type: "button", onclick: () => app.speakExamples(phrase) }, "🔊 All examples")));
      }
      const list = el("ul", { class: "examples" });
      phrase.examples.forEach(([german, english], i) => {
        const item = el("li", {},
          speech ? el("button", { class: "say", type: "button", "aria-label": `Speak example ${i + 1}`,
            onclick: () => app.speakExamples(phrase, i) }, "🔊") : null,
          el("div", {}, el("div", { class: "de", lang: "de", text: german }),
            exampleEn && english ? el("div", { class: "en", text: english }) : null));
        this.items.push(item);
        list.append(item);
      });
      parts.push(list);
    }
    this.examplesVisible = showExamples;
    this.root.replaceChildren(...parts);
  }

  setInfo(text) {
    const node = this.root.querySelector(".info");
    if (node) node.textContent = text;
  }

  // Mark the example being read aloud (null clears the mark).
  highlightExample(index) {
    this.items.forEach((item, i) => item.classList.toggle("reading", i === index));
    if (index !== null) this.items[index]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

const info = (phrase) => L.phraseInfo(app.progress, phrase, L.todayISO());

// ---------------------------------------------------------------- Study tab

class StudyTab {
  constructor() {
    this.session = null;
    this.practiceTitle = "";
    this.revealed = false;
    this.viewIndex = null; // index into session.rated while looking back
    this.suggested = null; // rating suggested by the typed-answer check
    this.shownAt = performance.now();
    this.card = new CardView($("study-card"));
    $("study-summary").onclick = () => settings.open();
    $("practice-end").onclick = () => this.startSession();
    $("study-back").onclick = () => this.goBack();
    $("study-forward").onclick = () => this.goForward();
    $("study-speak").onclick = () => this.speak();
    $("study-star").onclick = () => this.toggleStar();
    $("study-undo").onclick = () => this.undo();
    $("answer-check").onclick = () => this.checkAnswer();
    $("answer-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        this.checkAnswer();
      }
    });
    // Tapping the card shows the answer, like Space on the PC.
    $("study-card").addEventListener("click", (e) => {
      if (!e.target.closest("button")) this.reveal();
    });
    this.startSession();
  }

  get settings() {
    return app.progress.settings;
  }

  get practicing() {
    return this.session instanceof L.PracticeSession;
  }

  startSession() {
    const s = this.settings;
    this.session = new L.StudySession(L.filterPhrases(app.phrases, s.level, s.topic), app.progress,
      L.todayISO());
    $("practice-bar").hidden = true;
    this.showCard();
  }

  startPractice(phrases, title) {
    if (!phrases.length) {
      toast("There are no phrases to practice.");
      return;
    }
    this.session = new L.PracticeSession(phrases);
    this.practiceTitle = title;
    $("practice-bar").hidden = false;
    this.showCard();
  }

  setButtons(...buttons) {
    $("study-buttons").replaceChildren(...buttons);
  }

  showCard() {
    this.viewIndex = null;
    this.revealed = false;
    this.suggested = null;
    this.shownAt = performance.now();
    this.updateStatus();
    const phrase = this.session.current;
    this.updateNav(phrase);
    $("answer-row").hidden = true;
    if (!phrase) {
      if (this.practicing) {
        this.card.message("Practice round finished!");
        this.setButtons(el("button", { class: "single primary", onclick: () => this.startSession() },
          "Back to today's study"));
      } else {
        this.card.message("All done for today!\nCome back tomorrow for your reviews.");
        this.setButtons(el("button", { class: "single", onclick: () => this.learnMore() },
          `Learn ${EXTRA_NEW} more new phrases`));
      }
      return;
    }
    this.card.show(phrase, { direction: this.settings.direction, showBack: false, showExamples: false,
      info: info(phrase) });
    if (this.settings.answer_mode === "type") {
      $("answer-row").hidden = false;
      $("answer-input").value = "";
      $("answer-result").textContent = "";
      $("answer-check").textContent = "Check";
      this.setButtons();
      $("answer-input").focus();
    } else {
      this.setButtons(el("button", { class: "single primary", onclick: () => this.reveal() },
        "Show answer"));
    }
  }

  updateNav(phrase) {
    const { rated, queue } = this.session;
    $("study-back").disabled = !(rated.length && this.viewIndex !== 0);
    $("study-forward").textContent = this.viewIndex === null ? "Skip ▶" : "Forward ▶";
    $("study-forward").disabled = !(this.viewIndex !== null || queue.length > 1);
    $("study-undo").disabled = !(rated.length && this.viewIndex === null);
    $("study-star").textContent = phrase && app.progress.starred.has(phrase.id) ? "★" : "☆";
    $("study-star").disabled = !phrase;
    $("study-speak").disabled = !phrase || !app.speaker.available;
  }

  reveal() {
    const phrase = this.session.current;
    if (!phrase || this.revealed || this.viewIndex !== null) return;
    this.revealed = true;
    this.card.show(phrase, { direction: this.settings.direction, info: info(phrase) });
    const preview = this.session.preview();
    this.setButtons(...L.RATINGS.map((r) => {
      const when = this.practicing ? (r === L.AGAIN ? "again soon" : "done") : L.formatInterval(preview[r]);
      const mark = r === this.suggested ? "▶ " : "";
      return el("button", { class: `rate r${r}${r === this.suggested ? " suggested" : ""}`,
        onclick: () => this.rate(r) }, `${mark}${L.RATING_NAMES[r]}`, el("small", { text: when }));
    }));
  }

  checkAnswer() {
    const phrase = this.session.current;
    if (!phrase || this.viewIndex !== null) return;
    if (this.revealed) { // a second Check accepts the suggested rating
      if (this.suggested) this.rate(this.suggested);
      return;
    }
    const expected = this.settings.direction === "en_to_de" ? phrase.german : phrase.english;
    const [score, suggested] = L.check($("answer-input").value, expected);
    this.suggested = suggested;
    const verdict = { [L.GOOD]: "✓ Correct", [L.AGAIN]: "✗ Not quite" }[suggested] || "≈ Almost";
    $("answer-result").textContent = `${verdict} (${Math.round(score * 100)}%) · Accept ▶ or pick a rating`;
    $("answer-check").textContent = "Accept ▶";
    $("answer-input").blur(); // hide the keyboard so the rating buttons are visible
    this.reveal();
  }

  rate(rating) {
    if (!this.revealed || this.viewIndex !== null || !this.session.current) return;
    this.session.rate(rating, (performance.now() - this.shownAt) / 1000);
    this.showCard();
  }

  undo() {
    if (this.viewIndex === null && this.session.undo()) this.showCard();
  }

  goBack() {
    const { rated } = this.session;
    if (!rated.length || this.viewIndex === 0) return;
    this.viewIndex = this.viewIndex === null ? rated.length - 1 : this.viewIndex - 1;
    this.showHistory();
  }

  goForward() {
    if (this.viewIndex === null) {
      if (this.session.skip()) this.showCard();
      return;
    }
    this.viewIndex += 1;
    if (this.viewIndex >= this.session.rated.length) this.showCard();
    else this.showHistory();
  }

  showHistory() {
    const [phrase, rating] = this.session.rated[this.viewIndex];
    $("answer-row").hidden = true;
    this.card.show(phrase, { direction: this.settings.direction, info: info(phrase),
      banner: `Looking back: card ${this.viewIndex + 1} of ${this.session.rated.length} rated in this `
        + `session · you rated it ${L.RATING_NAMES[rating]}` });
    this.setButtons(el("button", { class: "single", onclick: () => this.showCard() },
      "Return to current card"));
    this.updateNav(phrase);
  }

  visiblePhrase() {
    return this.viewIndex !== null ? this.session.rated[this.viewIndex][0] : this.session.current;
  }

  speak() {
    const phrase = this.visiblePhrase();
    // In English → German mode, speaking before the reveal would give the answer away.
    if (phrase && (this.revealed || this.viewIndex !== null || this.settings.direction === "de_to_en")) {
      app.speaker.speak(phrase.german);
    }
  }

  speakExamples(index = null) {
    const phrase = this.visiblePhrase();
    if (phrase && this.card.examplesVisible) app.speakExamples(phrase, index);
  }

  toggleStar() {
    const phrase = this.visiblePhrase();
    if (!phrase) return;
    app.toggleStar(phrase.id);
    this.card.setInfo(info(phrase));
    this.updateNav(phrase);
  }

  learnMore() {
    if (this.session.addNew(EXTRA_NEW) === 0) toast("You have started every phrase in this selection.");
    this.showCard();
  }

  updateStatus() {
    const s = this.settings;
    if (this.practicing) {
      $("practice-label").textContent = `Practice: ${this.practiceTitle} · ${this.session.queue.length} of `
        + `${this.session.total} left · your review schedule is not changed`;
    }
    const left = this.session.remaining();
    const today = L.todayISO();
    const counters = app.progress.counters(today);
    const done = counters.new + counters.reviews;
    const [streak] = L.streaks(L.summarize(app.progress.log), today);
    $("goal-bar").value = Math.min(1, done / s.daily_goal);
    $("study-status").textContent = `Today ${done}/${s.daily_goal} · To study: ${left.new} new · `
      + `${left.review} review · Streak: ${streak} day${streak !== 1 ? "s" : ""}`;
    $("study-summary").replaceChildren(...[
      s.level, s.topic === "ALL" ? L.ALL_TOPICS : s.topic,
      s.direction === "de_to_en" ? "DE → EN/中文" : "EN/中文 → DE",
      s.answer_mode === "type" ? "Type" : "Reveal", `${s.new_per_day} new/day`, "⚙ Change",
    ].map((text) => el("span", { text })));
  }

  onKey(key) {
    let actions;
    if (this.viewIndex !== null) {
      actions = { left: () => this.goBack(), right: () => this.goForward(), return: () => this.showCard() };
    } else {
      actions = { space: () => this.reveal(), left: () => this.goBack(), right: () => this.goForward(),
        return: () => (this.suggested ? this.checkAnswer() : this.reveal()) };
      for (const r of L.RATINGS) actions[String(r)] = () => this.rate(r);
    }
    Object.assign(actions, { s: () => this.speak(), e: () => this.speakExamples(), m: () => this.toggleStar() });
    EXAMPLE_KEYS.forEach((k, i) => { actions[k] = () => this.speakExamples(i); });
    actions[key]?.();
  }

  onShow() {
    if (!this.practicing && this.session.today !== L.todayISO()) { // a new day started
      this.startSession();
      return;
    }
    this.updateStatus();
    const phrase = this.visiblePhrase();
    if (phrase) {
      this.card.setInfo(info(phrase));
      this.updateNav(phrase);
    }
  }
}

// ---------------------------------------------------------------- Browse tab

class BrowseTab {
  constructor() {
    this.items = [];
    this.index = 0;
    this.peek = false; // temporarily show translations while they are hidden
    this.card = new CardView($("browse-card"));
    setOptions($("browse-level"), pairs(app.levels), app.progress.settings.level);
    $("browse-level").onchange = () => this.onLevelChanged();
    $("browse-topic").onchange = () => this.refreshItems();
    $("browse-translate").onchange = () => this.show();
    $("browse-goto").onsubmit = (e) => {
      e.preventDefault();
      this.goTo();
    };
    $("browse-scale").oninput = () => this.onScale();
    $("browse-prev").onclick = () => this.move(-1);
    $("browse-next").onclick = () => this.move(1);
    $("browse-random").onclick = () => this.random();
    $("browse-peek").onclick = () => this.togglePeek();
    $("browse-speak").onclick = () => this.speak();
    $("browse-star").onclick = () => this.toggleStar();
    $("browse-practice").onclick = () => app.practice(this.items,
      `${$("browse-level").value} · ${$("browse-topic").value}`);
    onSwipe($("browse-card"), (step) => this.move(step));
    setOptions($("browse-topic"), topicOptions($("browse-level").value), L.ALL_TOPICS);
    this.refreshItems();
  }

  onLevelChanged() {
    setOptions($("browse-topic"), topicOptions($("browse-level").value), $("browse-topic").value);
    this.refreshItems();
  }

  refreshItems(keepId = null) {
    keepId ||= this.items[this.index]?.id;
    this.items = L.filterPhrases(app.phrases, $("browse-level").value, $("browse-topic").value);
    const index = this.items.findIndex((p) => p.id === keepId);
    this.index = Math.max(0, index);
    $("browse-scale").max = Math.max(2, this.items.length);
    this.show();
  }

  show() {
    if (!this.items.length) {
      this.card.message("No phrases in this selection.");
      return;
    }
    const phrase = this.items[this.index];
    const translations = $("browse-translate").checked || this.peek;
    this.card.show(phrase, { showBack: translations, exampleEn: translations, info: info(phrase) });
    $("browse-position").textContent = `${this.index + 1} / ${this.items.length}`;
    $("browse-scale").value = this.index + 1;
    $("browse-star").textContent = app.progress.starred.has(phrase.id) ? "★" : "☆";
    $("browse-peek").disabled = $("browse-translate").checked;
    $("browse-speak").disabled = !app.speaker.available;
  }

  move(step) {
    if (!this.items.length) return;
    this.index = (this.index + step + this.items.length) % this.items.length;
    this.peek = false;
    this.show();
  }

  random() {
    if (!this.items.length) return;
    this.index = Math.floor(Math.random() * this.items.length);
    this.peek = false;
    this.show();
  }

  onScale() {
    if (!this.items.length) return;
    const index = Math.min(this.items.length - 1, Math.max(0, Math.round(+$("browse-scale").value) - 1));
    if (index !== this.index) {
      this.index = index;
      this.show();
    }
  }

  goTo() {
    const input = $("browse-goto-input");
    const target = input.value.trim().toUpperCase();
    input.blur();
    if (/^\d+$/.test(target) && +target >= 1 && +target <= this.items.length) {
      this.index = +target - 1;
      this.show();
    } else if (app.byId.has(target)) {
      this.openPhrase(target);
    } else {
      toast(`No phrase "${target}" in this selection.`);
    }
  }

  openPhrase(pid) {
    if (!this.items.some((p) => p.id === pid)) {
      $("browse-level").value = app.byId.get(pid).level;
      setOptions($("browse-topic"), topicOptions($("browse-level").value), L.ALL_TOPICS);
    }
    this.refreshItems(pid);
  }

  togglePeek() {
    if (!$("browse-translate").checked) {
      this.peek = !this.peek;
      this.show();
    }
  }

  speak() {
    if (this.items.length) app.speaker.speak(this.items[this.index].german);
  }

  speakExamples(index = null) {
    if (this.items.length) app.speakExamples(this.items[this.index], index);
  }

  toggleStar() {
    if (!this.items.length) return;
    app.toggleStar(this.items[this.index].id);
    this.show();
  }

  onKey(key) {
    const actions = { left: () => this.move(-1), right: () => this.move(1), r: () => this.random(),
      space: () => this.togglePeek(), s: () => this.speak(), e: () => this.speakExamples(),
      m: () => this.toggleStar() };
    EXAMPLE_KEYS.forEach((k, i) => { actions[k] = () => this.speakExamples(i); });
    actions[key]?.();
  }

  onShow() {
    this.show();
  }
}

// Horizontal swipe on a card: left = next, right = previous.
function onSwipe(node, move) {
  let start = null;
  node.addEventListener("touchstart", (e) => {
    start = e.touches.length === 1 ? [e.touches[0].clientX, e.touches[0].clientY] : null;
  }, { passive: true });
  node.addEventListener("touchend", (e) => {
    if (!start) return;
    const dx = e.changedTouches[0].clientX - start[0];
    const dy = e.changedTouches[0].clientY - start[1];
    start = null;
    if (Math.abs(dx) > 60 && Math.abs(dx) > 2 * Math.abs(dy)) move(dx < 0 ? 1 : -1);
  });
}

// ---------------------------------------------------------------- Auto play tab

// Hands-free practice: speak the phrase, pause, show the answer, read the examples, next.
// Only listens and shows; it never changes the review schedule.
class AutoPlayTab {
  constructor() {
    this.items = [];
    this.index = 0;
    this.sourceTitle = TODAY_SOURCE;
    this.playing = false;
    this.run = 0; // bumps on every start/stop so a stale playback loop ends
    this.timer = null;
    this.wakeLock = null;
    this.card = new CardView($("auto-card"));
    const saved = this.settings.autoplay_pauses || {};
    this.pauseInputs = {};
    $("auto-pauses").replaceChildren(...Object.entries(PAUSES).map(([key, label]) => {
      const input = el("input", { type: "number", min: 0, max: MAX_PAUSE, step: 0.5, inputmode: "decimal",
        value: saved[key] ?? DEFAULT_PAUSE, onchange: () => this.saveSettings() });
      this.pauseInputs[key] = input;
      return el("label", {}, `${label} (s)`, input);
    }));
    $("auto-loop").checked = Boolean(this.settings.autoplay_loop);
    $("auto-loop").onchange = () => this.saveSettings();
    $("auto-play").onclick = () => this.toggle();
    $("auto-prev").onclick = () => this.jump(-1);
    $("auto-next").onclick = () => this.jump(1);
    $("auto-today").onclick = () => this.loadToday();
    $("auto-reset").onclick = () => this.resetPauses();
    $("auto-novoice").hidden = app.speaker.available;
    this.updatePauseSummary();
    this.loadToday();
  }

  get settings() {
    return app.progress.settings;
  }

  loadToday() {
    const s = this.settings;
    const phrases = L.filterPhrases(app.phrases, s.level, s.topic);
    this.load(L.todaysPhrases(phrases, app.progress, L.todayISO()),
      `${TODAY_SOURCE} (${s.level}, ${s.topic === "ALL" ? "all topics" : s.topic})`);
  }

  load(phrases, title) {
    this.stop();
    this.items = [...phrases];
    this.index = 0;
    this.sourceTitle = title;
    this.showStill();
  }

  showStill() {
    this.updateLabels(this.items.length ? "Press Play to start" : "");
    if (!this.items.length) {
      this.card.message("No phrases to play.\nStudy some phrases first, or use “Auto play” in the Lists tab.");
      return;
    }
    this.card.show(this.items[this.index], { info: info(this.items[this.index]) });
  }

  updateLabels(step) {
    const total = this.items.length;
    $("auto-source").textContent = total
      ? `${this.sourceTitle} · phrase ${Math.min(this.index + 1, total)} of ${total}` : this.sourceTitle;
    $("auto-step").textContent = step;
    $("auto-bar").value = total ? (this.index + 1) / total : 0;
  }

  toggle() {
    if (this.playing) this.stop();
    else this.play();
  }

  play() {
    if (!this.items.length) return;
    this.run += 1;
    this.playing = true;
    $("auto-play").textContent = "■ Pause";
    this.keepScreenOn();
    this.playLoop(this.run);
  }

  // Pause; Play starts the current phrase again from its beginning.
  stop() {
    this.run += 1;
    this.playing = false;
    clearTimeout(this.timer);
    app.speaker.stop();
    $("auto-play").textContent = "▶ Play";
    this.card.highlightExample(null);
    if (this.items.length) this.updateLabels("Paused");
    this.wakeLock?.release().catch(() => {});
    this.wakeLock = null;
  }

  jump(step) {
    if (!this.items.length) return;
    const wasPlaying = this.playing;
    this.stop();
    this.index = (this.index + step + this.items.length) % this.items.length;
    this.showStill();
    if (wasPlaying) this.play();
  }

  async keepScreenOn() {
    try {
      const lock = await navigator.wakeLock?.request("screen");
      if (this.playing) this.wakeLock = lock;
      else lock?.release();
    } catch {
      this.wakeLock = null; // not allowed (e.g. battery saver): playback still works
    }
  }

  // Current pause length; invalid input falls back to the last saved value.
  pause(key) {
    const input = this.pauseInputs[key];
    let value = parseFloat(input.value);
    if (Number.isNaN(value)) {
      value = this.settings.autoplay_pauses?.[key] ?? DEFAULT_PAUSE;
      input.value = value;
    }
    return Math.min(MAX_PAUSE, Math.max(0, value));
  }

  saveSettings() {
    const next = { autoplay_pauses: Object.fromEntries(Object.keys(PAUSES).map((k) => [k, this.pause(k)])),
      autoplay_loop: $("auto-loop").checked };
    if (Object.entries(next).some(([k, v]) => JSON.stringify(this.settings[k]) !== JSON.stringify(v))) {
      Object.assign(this.settings, next);
      app.progress.save();
    }
    this.updatePauseSummary();
  }

  updatePauseSummary() {
    $("auto-pause-summary").textContent = Object.keys(PAUSES).map((k) => `${this.pause(k)}`).join(" / ") + " s";
  }

  resetPauses() {
    for (const input of Object.values(this.pauseInputs)) input.value = DEFAULT_PAUSE;
    this.saveSettings();
  }

  wait(seconds) {
    // Read at each step, so changes apply while playing. stop() clears the timer.
    return new Promise((resolve) => { this.timer = setTimeout(resolve, seconds * 1000); });
  }

  say(text) {
    if (!app.speaker.available) { // no voice: give roughly the time it takes to read the sentence
      return this.wait(1 + 0.06 * text.length);
    }
    let timeout;
    return Promise.race([
      app.speaker.speak(text),
      new Promise((resolve) => { timeout = setTimeout(resolve, SPEECH_TIMEOUT); }),
    ]).finally(() => clearTimeout(timeout));
  }

  // One phrase after another: speak, recall pause, answer, examples, next.
  async playLoop(run) {
    const live = () => run === this.run;
    while (this.index < this.items.length) {
      const phrase = this.items[this.index];
      const text = info(phrase);
      this.card.show(phrase, { showBack: false, showExamples: false, info: text });
      this.updateLabels("🔊 Listen");
      await this.say(phrase.german);
      if (!live()) return;
      this.updateLabels("💭 What does it mean?");
      await this.wait(this.pause("recall"));
      if (!live()) return;
      this.card.show(phrase, { info: text });
      this.updateLabels("Answer");
      await this.wait(this.pause("answer"));
      if (!live()) return;
      for (const [i, [german]] of phrase.examples.entries()) {
        this.card.highlightExample(i);
        this.updateLabels(`🔊 Example ${i + 1} of ${phrase.examples.length}`);
        await this.say(german);
        if (!live()) return;
        await this.wait(this.pause("example"));
        if (!live()) return;
      }
      this.card.highlightExample(null);
      this.updateLabels("Next phrase…");
      await this.wait(this.pause("next"));
      if (!live()) return;
      if (this.index + 1 >= this.items.length && $("auto-loop").checked) this.index = 0;
      else this.index += 1;
    }
    this.index = this.items.length - 1;
    this.stop();
    this.updateLabels(`Finished: all ${this.items.length} phrases played`);
  }

  onKey(key) {
    const phrase = this.items[this.index];
    const actions = { space: () => this.toggle(), left: () => this.jump(-1), right: () => this.jump(1),
      escape: () => this.stop() };
    if (phrase && !this.playing) {
      actions.s = () => app.speaker.speak(phrase.german);
      actions.e = () => app.speakExamples(phrase);
      EXAMPLE_KEYS.forEach((k, i) => { actions[k] = () => app.speakExamples(phrase, i); });
    }
    actions[key]?.();
  }

  onShow() {
    if (this.playing) {
      if (!this.wakeLock) this.keepScreenOn(); // the lock is dropped while the app is hidden
    } else if (this.sourceTitle.startsWith(TODAY_SOURCE)) {
      this.loadToday(); // pick up phrases studied since the tab was last opened
    }
  }

  onHide() {
    if (this.playing) this.stop();
  }
}

// ---------------------------------------------------------------- Lists tab

class ListsTab {
  constructor() {
    this.shown = [];
    this.searchJob = null;
    setOptions($("lists-kind"), Object.entries(L.FILTERS), "learned");
    setOptions($("lists-level"), pairs(app.levels), "ALL");
    setOptions($("lists-topic"), topicOptions("ALL"), L.ALL_TOPICS);
    setOptions($("lists-sort"), Object.entries(L.SORTS), "id");
    for (const id of ["lists-kind", "lists-topic", "lists-sort", "lists-limit", "lists-translation",
      "lists-examples"]) $(id).onchange = () => this.refresh();
    $("lists-level").onchange = () => {
      setOptions($("lists-topic"), topicOptions($("lists-level").value), $("lists-topic").value);
      this.refresh();
    };
    $("lists-search").oninput = () => {
      clearTimeout(this.searchJob);
      this.searchJob = setTimeout(() => this.refresh(), 300);
    };
    $("lists-autoplay").onclick = () => app.autoPlay(this.shown, `${this.title} (${this.shown.length})`);
    $("lists-practice").onclick = () => app.practice(this.shown, `${this.title} (${this.shown.length})`);
    $("lists-export").onclick = () => this.export();
    $("export-list").addEventListener("close", () => this.saveExport($("export-list").returnValue));
  }

  get title() {
    return L.FILTERS[$("lists-kind").value];
  }

  refresh() {
    const today = L.todayISO();
    const { progress } = app;
    const phrases = L.filterPhrases(app.phrases, $("lists-level").value, $("lists-topic").value);
    const matching = L.select(phrases, progress, { kind: $("lists-kind").value,
      query: $("lists-search").value, sort: $("lists-sort").value, today });
    const limit = readInt($("lists-limit"), 50);
    this.shown = limit ? matching.slice(0, limit) : matching;
    const translation = $("lists-translation").checked, examples = $("lists-examples").checked;
    const rows = document.createDocumentFragment();
    this.shown.forEach((p, i) => {
      const s = progress.state(p.id);
      const tag = s.lapses >= L.DIFFICULT_LAPSES ? "difficult" : L.wasForgotten(s) ? "forgotten" : "";
      rows.append(el("li", { class: tag, onclick: () => app.openInBrowse(p.id) },
        el("div", { class: "head" }, el("span", { text: `${i + 1}. ${p.id}` }),
          el("span", { text: L.cardStatus(progress, p, today) })),
        el("div", { class: "de", lang: "de", text: (progress.starred.has(p.id) ? "★ " : "") + p.german }),
        translation ? el("div", { class: "tr", text: `${p.english} · ${p.chinese}` }) : null,
        examples ? el("div", { class: "ex", lang: "de", text: p.examples.map(([de]) => de).join("  |  ") }) : null));
    });
    $("lists-rows").replaceChildren(rows);
    $("lists-summary").textContent = `Showing ${this.shown.length} of ${matching.length} matching phrases`;
  }

  export() {
    if (!this.shown.length) {
      toast("The list is empty.");
      return;
    }
    $("export-list").returnValue = "";
    $("export-list").showModal();
  }

  saveExport(format) {
    if (!format) return;
    const withTranslation = $("lists-translation").checked, withExamples = $("lists-examples").checked;
    const today = L.todayISO();
    let text;
    if (format === "txt") {
      text = this.shown.map((p, i) => {
        let line = `${i + 1}. ${p.german}`;
        if (withTranslation) line += `  —  ${p.english}  /  ${p.chinese}`;
        const lines = [line];
        if (withExamples) {
          for (const [de, en] of p.examples) lines.push(`     • ${de}${withTranslation ? `  (${en})` : ""}`);
        }
        return lines.join("\n");
      }).join("\n") + "\n";
    } else {
      const header = ["id", "level", "topic", "german", ...(withTranslation ? ["english", "chinese"] : []),
        ...(withExamples ? ["examples"] : []), "status"];
      const rows = this.shown.map((p) => [p.id, p.level, p.topic, p.german,
        ...(withTranslation ? [p.english, p.chinese] : []),
        ...(withExamples ? [p.examples.map(([de, en]) => (withTranslation ? `${de} (${en})` : de)).join(" | ")] : []),
        L.cardStatus(app.progress, p, today)]);
      text = "﻿" + [header, ...rows].map(csvRow).join("\r\n") + "\r\n"; // BOM so Excel reads UTF-8
    }
    const name = `german-phrases-${$("lists-kind").value}.${format}`;
    download(text, name, format === "csv" ? "text/csv" : "text/plain");
    toast(`Saved ${this.shown.length} phrases to ${name}`);
  }

  onKey() {}

  onShow() {
    this.refresh();
  }
}

// One CSV line, quoted like Python's csv module.
const csvRow = (fields) => fields.map((f) => (/[",\r\n]/.test(f) ? `"${f.replaceAll('"', '""')}"` : f)).join(",");

// ---------------------------------------------------------------- Progress tab

class ProgressTab {
  constructor() {
    const today = L.todayISO();
    this.month = [+today.slice(0, 4), +today.slice(5, 7)];
    this.selected = today;
    this.days = {};
    $("month-prev").onclick = () => this.shiftMonth(-1);
    $("month-next").onclick = () => this.shiftMonth(1);
    $("level-stats-open").onclick = () => this.showLevelStats();
    $("day-forgotten").onclick = () => this.practiceDay(true);
    $("day-all").onclick = () => this.practiceDay(false);
    $("day-autoplay").onclick = () => this.autoPlayDay();
    $("chart-title").textContent = `Reviews per day, last ${CHART_DAYS} days`;
    $("legend").replaceChildren(...[L.GOOD_DAY, L.STUDIED, L.HARD_DAY, L.MISSED].map((kind) => {
      const [tint, accent, icon, text] = DAY_STYLES[kind];
      return el("div", {}, el("span", { class: "swatch", style: `background:${tint};border-color:${accent}`,
        text: icon }), text);
    }));
    window.addEventListener("resize", () => {
      if (app.current === "progress") this.drawChart();
    });
  }

  refresh() {
    const { progress } = app;
    const today = L.todayISO();
    this.days = L.summarize(progress.log);
    const [current, longest] = L.streaks(this.days, today);
    const goal = progress.settings.daily_goal;
    const done = this.days[today] ? L.total(this.days[today]) : 0;
    const learned = Object.values(progress.cards).filter((s) => !L.isNew(s)).length;
    const tiles = [
      [`${done} / ${goal}`, "Today / goal"], [`${current} d`, "Current streak"],
      [`${longest} d`, "Longest streak"],
      [String(Object.values(this.days).filter((s) => L.total(s)).length), "Days studied"],
      [`${learned} / ${app.phrases.length}`, "Phrases learned"], [String(progress.log.length), "Total reviews"],
    ];
    $("tiles").replaceChildren(...tiles.map(([value, caption]) =>
      el("div", { class: "tile" }, el("strong", { text: value }), el("span", { text: caption }))));
    this.drawCalendar();
    this.showDay(this.selected);
    this.drawChart();
  }

  kind(day) {
    return L.classify(day, this.days, app.progress.settings.daily_goal, L.todayISO());
  }

  shiftMonth(step) {
    let [year, month] = this.month;
    month += step;
    this.month = [year + Math.floor((month - 1) / 12), ((month - 1) % 12 + 12) % 12 + 1];
    this.drawCalendar();
  }

  drawCalendar() {
    const [year, month] = this.month;
    const today = L.todayISO();
    $("month-label").textContent = `${MONTHS[month - 1]} ${year}`;
    const first = `${year}-${String(month).padStart(2, "0")}-01`;
    const offset = (weekday(first) + 6) % 7; // weeks start on Monday, like Python's calendar
    const length = new Date(year, month, 0).getDate();
    const cells = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => el("div", { class: "dow", text: d }));
    for (let i = 0; i < offset; i++) cells.push(el("div"));
    for (let n = 1; n <= length; n++) {
      const day = L.addDays(first, n - 1);
      const [tint, , icon] = DAY_STYLES[this.kind(day)];
      const summary = this.days[day];
      const count = summary && L.total(summary) ? ` ${L.total(summary)}` : "";
      const classes = [day === this.selected && "selected", day === today && "today", day > today && "future"];
      cells.push(el("button", { class: classes.filter(Boolean).join(" "), style: `background:${tint}`,
        "aria-label": fmtLong(day), onclick: () => this.selectDay(day) }, `${n}\n${icon}${count}`));
    }
    $("calendar-grid").replaceChildren(...cells);
  }

  selectDay(day) {
    this.selected = day;
    this.month = [+day.slice(0, 4), +day.slice(5, 7)];
    this.drawCalendar();
    this.showDay(day);
    this.drawChart();
  }

  showDay(day) {
    const summary = this.days[day] || L.daySummary(day);
    const kind = this.kind(day);
    let [, , icon, text] = DAY_STYLES[kind];
    $("day-title").textContent = fmtLong(day);
    if (kind === L.NO_DATA) text = day === L.todayISO() ? "Today: no reviews yet" : "No study data";
    $("day-kind").textContent = `${icon} ${text}`.trim();
    const n = L.total(summary);
    if (n) {
      const r = summary.ratings;
      $("day-text").textContent = `${n} ratings · ${summary.new} new phrases · `
        + `${Math.round(L.accuracy(summary) * 100)}% recalled · ${Math.round(summary.seconds / 60)} min\n`
        + `Again ${r[1]} · Hard ${r[2]} · Good ${r[3]} · Easy ${r[4]}`;
    } else {
      $("day-text").textContent = "";
    }
    // Latest rating per phrase, forgotten ones first.
    const latest = new Map(), worst = new Map();
    for (const [pid, rating] of summary.reviews) {
      latest.set(pid, rating);
      worst.set(pid, Math.min(worst.get(pid) ?? 9, rating));
    }
    const order = [...latest.keys()].sort((a, b) =>
      (worst.get(a) !== L.AGAIN) - (worst.get(b) !== L.AGAIN) || (a < b ? -1 : a > b ? 1 : 0));
    $("day-rows").replaceChildren(...order.filter((pid) => app.byId.has(pid)).map((pid) => {
      const p = app.byId.get(pid);
      let label = L.RATING_NAMES[latest.get(pid)];
      if (worst.get(pid) === L.AGAIN && latest.get(pid) !== L.AGAIN) label = `Again → ${label}`;
      return el("li", { class: worst.get(pid) === L.AGAIN ? "again" : "", onclick: () => app.openInBrowse(pid) },
        el("div", { class: "head" }, el("span", { text: pid }), el("span", { text: label })),
        el("div", { class: "de", lang: "de", text: p.german }), el("div", { class: "tr", text: p.english }));
    }));
  }

  practiceDay(forgottenOnly) {
    const summary = this.days[this.selected];
    if (!summary) {
      toast("No phrases were reviewed on this day.");
      return;
    }
    const ids = forgottenOnly ? L.forgottenIds(summary) : [...new Set(summary.reviews.map(([pid]) => pid))].sort();
    const what = forgottenOnly ? "forgotten on" : "reviewed on";
    app.practice(ids.filter((i) => app.byId.has(i)).map((i) => app.byId.get(i)),
      `phrases ${what} ${fmtDayMon(this.selected)}`);
  }

  autoPlayDay() {
    const summary = this.days[this.selected];
    const ids = summary ? [...new Set(summary.reviews.map(([pid]) => pid))] : [];
    app.autoPlay(ids.filter((i) => app.byId.has(i)).map((i) => app.byId.get(i)),
      `Phrases reviewed on ${fmtDayMon(this.selected)} ${this.selected.slice(0, 4)}`);
  }

  drawChart() {
    const box = $("chart");
    const width = Math.max(300, box.clientWidth || 340), height = 200;
    const today = L.todayISO();
    const data = L.lastNDays(this.days, today, CHART_DAYS);
    const goal = app.progress.settings.daily_goal;
    const top = Math.max(...data.map(L.total), goal, 5);
    const step = L.niceStep(top / 4);
    const yMax = step * Math.ceil(top / step);
    const left = 34, right = width - 10, topPx = 30, bottom = height - 22;
    const y = (v) => bottom - ((bottom - topPx) * v) / yMax;
    const parts = [];
    const text = (x, yy, s, anchor, extra = "") =>
      `<text x="${x}" y="${yy}" text-anchor="${anchor}" font-size="11" fill="${MUTED}" ${extra}>${s}</text>`;
    for (let tick = 0; tick <= yMax + 1e-9; tick += step) {
      parts.push(`<line x1="${left}" x2="${right}" y1="${y(tick)}" y2="${y(tick)}" stroke="${tick ? GRID : BASELINE}"/>`,
        text(left - 5, y(tick) + 4, tick, "end"));
    }
    parts.push(`<line x1="${left}" x2="${right}" y1="${y(goal)}" y2="${y(goal)}" stroke="${MUTED}" stroke-dasharray="4 3"/>`);
    // Legend: two series, so it is always shown, plus the goal line.
    parts.push(`<rect x="${left}" y="8" width="10" height="10" fill="${SERIES_RECALLED}"/>`,
      text(left + 15, 17, "Recalled", "start", `fill="${INK_2}"`),
      `<rect x="${left + 75}" y="8" width="10" height="10" fill="${SERIES_FORGOTTEN}"/>`,
      text(left + 90, 17, "Forgotten", "start", `fill="${INK_2}"`),
      `<line x1="${left + 155}" x2="${left + 173}" y1="13" y2="13" stroke="${MUTED}" stroke-dasharray="4 3"/>`,
      text(left + 178, 17, `Daily goal (${goal})`, "start", `fill="${INK_2}"`));
    const slot = (right - left) / data.length;
    const bar = Math.max(4, Math.min(28, slot * 0.62));
    data.forEach((d, i) => {
      const x0 = left + i * slot + (slot - bar) / 2, x1 = x0 + bar;
      const rec = L.recalled(d), n = L.total(d);
      if (rec) parts.push(`<rect x="${x0}" y="${y(rec)}" width="${bar}" height="${bottom - y(rec)}" fill="${SERIES_RECALLED}"/>`);
      if (L.forgotten(d)) { // 2px gap between the stacked segments
        parts.push(`<rect x="${x0}" y="${y(n)}" width="${bar}" height="${Math.max(0, y(rec) - 2 - y(n))}" fill="${SERIES_FORGOTTEN}"/>`);
      }
      if (d.day === this.selected) {
        parts.push(`<rect x="${x0 - 3}" y="${topPx - 4}" width="${bar + 6}" height="${bottom - topPx + 4}" fill="none" stroke="#0b0b0b" stroke-dasharray="2 2"/>`);
      }
      if (d.day === today || (i % 7 === 0 && data.length - 1 - i >= 3)) {
        parts.push(text((x0 + x1) / 2, bottom + 15, fmtDayMon(d.day).replace(/^0/, ""), "middle"));
      }
      // Tap target: the whole column, bigger than the bar itself.
      parts.push(`<rect class="hit" data-day="${d.day}" x="${left + i * slot}" y="${topPx}" width="${slot}" height="${bottom - topPx}"/>`);
    });
    box.innerHTML = `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img"
      aria-label="Reviews per day">${parts.join("")}</svg>`;
    box.querySelectorAll(".hit").forEach((hit) => { hit.onclick = () => this.selectDay(hit.dataset.day); });
    const d = data.find((s) => s.day === this.selected);
    const date = d ? `${WEEKDAYS[weekday(d.day)].slice(0, 3)} ${fmtDayMon(d.day)}` : "";
    $("chart-info").textContent = !d ? "Tap a bar to see that day." : L.total(d)
      ? `${date}: ${L.total(d)} ratings · ${L.recalled(d)} recalled · ${L.forgotten(d)} forgotten · `
        + `${Math.round(L.accuracy(d) * 100)}%`
      : `${date}: no reviews`;
  }

  showLevelStats() {
    const columns = ["level", "total", "new", "learning", "young", "mature", "due"];
    const stats = L.statistics(app.phrases, app.progress, L.todayISO());
    $("level-stats-table").replaceChildren(
      el("tr", {}, ...columns.map((c) => el("th", { text: c[0].toUpperCase() + c.slice(1) }))),
      ...Object.entries(stats).map(([level, row]) =>
        el("tr", {}, el("td", { text: level }), ...columns.slice(1).map((c) => el("td", { text: row[c] })))));
    $("level-stats").showModal();
  }

  onKey(key) {
    const step = { left: -1, right: 1 }[key];
    if (step) this.selectDay(L.addDays(this.selected, step));
  }

  onShow() {
    this.refresh();
  }
}

// ---------------------------------------------------------------- settings and progress file

const settings = {
  setup() {
    setOptions($("set-level"), pairs(app.levels), "B1");
    setOptions($("set-direction"), Object.entries(L.DIRECTIONS), "de_to_en");
    $("settings-open").onclick = () => this.open();
    $("set-level").onchange = () => {
      setOptions($("set-topic"), topicOptions($("set-level").value), $("set-topic").value);
      this.apply();
    };
    for (const id of ["set-topic", "set-direction", "set-mode", "set-new", "set-goal"]) {
      $(id).onchange = () => this.apply();
    }
    $("set-voice").onchange = () => app.speaker.setVoice($("set-voice").value);
    $("set-rate").oninput = () => this.showRate();
    $("set-rate").onchange = () => app.speaker.setRate($("set-rate").value);
    $("set-voice-test").onclick = () => app.speaker.speak(VOICE_SAMPLE);
    app.speaker.onVoices = () => this.fillVoices();
    $("data-export").onclick = () => download(JSON.stringify(app.progress), "progress.json", "application/json");
    $("data-share").hidden = !navigator.canShare?.({ files: [new File(["{}"], "progress.json")] });
    $("data-share").onclick = () => navigator.share({ title: "German Phrases progress",
      files: [new File([JSON.stringify(app.progress)], "progress.json", { type: "application/json" })] })
      .catch(() => {});
    $("data-import").onclick = () => $("data-file").click();
    $("data-file").onchange = () => this.importFile($("data-file").files[0]);
  },

  open() {
    this.fill();
    $("settings").showModal();
  },

  fill() {
    const s = app.progress.settings;
    $("set-level").value = s.level;
    setOptions($("set-topic"), topicOptions(s.level), s.topic === "ALL" ? L.ALL_TOPICS : s.topic);
    $("set-direction").value = s.direction;
    $("set-mode").value = s.answer_mode;
    $("set-new").value = s.new_per_day;
    $("set-goal").value = s.daily_goal;
    this.fillVoices();
    this.updateInfo();
  },

  fillVoices() {
    const voices = app.speaker.voices;
    $("set-voice-row").hidden = voices.length < 2;
    $("set-speech").hidden = !app.speaker.available;
    setOptions($("set-voice"), voices.map((v) => [v.name, `${v.name} (${v.lang})`]), app.speaker.voice?.name);
    $("set-rate").value = app.speaker.rate;
    this.showRate();
  },

  showRate() {
    $("set-rate-value").textContent = `${Number($("set-rate").value).toFixed(1)}×`;
  },

  apply() {
    const s = app.progress.settings;
    const next = {
      level: $("set-level").value,
      topic: $("set-topic").value === L.ALL_TOPICS ? "ALL" : $("set-topic").value,
      direction: $("set-direction").value,
      answer_mode: $("set-mode").value,
      new_per_day: readInt($("set-new"), s.new_per_day),
      daily_goal: readInt($("set-goal"), s.daily_goal, 1),
    };
    const changed = Object.keys(next).filter((k) => s[k] !== next[k]);
    if (!changed.length) return;
    Object.assign(s, next);
    app.progress.save();
    const study = app.tabs.study;
    if (changed.some((k) => ["level", "topic", "new_per_day"].includes(k))) study.startSession();
    else if (changed.some((k) => ["direction", "answer_mode"].includes(k))) study.showCard();
    else study.updateStatus();
  },

  updateInfo() {
    const learned = Object.values(app.progress.cards).filter((c) => !L.isNew(c)).length;
    $("data-info").textContent = `On this phone: ${learned} phrases learned, ${app.progress.log.length} ratings.`;
  },

  async importFile(file) {
    $("data-file").value = "";
    if (!file) return;
    let data;
    try {
      data = JSON.parse(await file.text());
      if (typeof data.cards !== "object" || !Array.isArray(data.log)) throw new Error("not a progress file");
    } catch (e) {
      $("data-info").textContent = `Could not read ${file.name}: ${e.message}`;
      return;
    }
    const learned = Object.values(data.cards).filter((c) => c.last_review).length;
    if (!confirm(`Replace the progress on this phone with ${file.name}?\n\n`
      + `${learned} phrases learned, ${data.log.length} ratings.`)) return;
    app.progress.load(data);
    app.progress.save();
    app.tabs.study.startSession();
    app.tabs.autoplay.loadToday();
    app.tabs[app.current].onShow();
    this.fill(); // show the imported settings
    $("data-info").textContent += " Imported.";
  },
};

// ---------------------------------------------------------------- app

const app = {
  phrases: [],
  byId: new Map(),
  progress: null,
  speaker: null,
  tabs: {},
  current: "study",

  select(name) {
    if (name === this.current) return;
    if (name !== "autoplay") this.tabs.autoplay.onHide(); // don't keep talking in the background
    $(this.current).hidden = true;
    $(name).hidden = false;
    for (const button of document.querySelectorAll(".tabs button")) {
      button.classList.toggle("active", button.dataset.tab === name);
    }
    this.current = name;
    window.scrollTo(0, 0);
    this.tabs[name].onShow();
  },

  practice(phrases, title) {
    this.select("study");
    this.tabs.study.startPractice(phrases, title);
  },

  autoPlay(phrases, title) {
    if (!phrases.length) {
      toast("There are no phrases to play.");
      return;
    }
    this.select("autoplay");
    this.tabs.autoplay.load(phrases, title);
    this.tabs.autoplay.play();
  },

  openInBrowse(pid) {
    this.select("browse");
    this.tabs.browse.openPhrase(pid);
  },

  toggleStar(pid) {
    const { starred } = this.progress;
    if (starred.has(pid)) starred.delete(pid);
    else starred.add(pid);
    this.progress.save();
  },

  // Speak the German examples only: all of them, or just example `index`.
  speakExamples(phrase, index = null) {
    const german = phrase.examples.map(([de]) => de);
    if (index === null) this.speaker.speak(german.join(" "));
    else if (index < german.length) this.speaker.speak(german[index]);
  },
};

function loadProgress() {
  let data = null;
  try {
    data = JSON.parse(localStorage.getItem(STORAGE_KEY));
  } catch {
    data = null;
  }
  return new L.Progress(data, (progress) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(progress));
    } catch (e) {
      toast(`Could not save your progress: ${e.message}`);
    }
  });
}

function onKey(e) {
  if (e.target.closest("input, select, textarea") || document.querySelector("dialog[open]")) return;
  if (e.ctrlKey || e.metaKey) { // Ctrl+Z / Cmd+Z undoes the last rating
    if (e.key.toLowerCase() === "z") app.tabs.study.undo();
    return;
  }
  const names = { " ": "space", ArrowLeft: "left", ArrowRight: "right", Enter: "return", Escape: "escape" };
  const key = names[e.key] || e.key.toLowerCase();
  if (key === "return" && e.target.closest("button")) return; // Enter presses the focused button
  if (key === "space") e.preventDefault(); // no page scroll, no second press of a focused button
  app.tabs[app.current].onKey(key);
}

async function main() {
  app.progress = loadProgress();
  app.speaker = new Speaker();
  try {
    const response = await fetch("phrases.json");
    app.phrases = (await response.json()).map(L.phraseFromRow);
  } catch (e) {
    $("study-card").textContent = `Could not load the phrases: ${e.message}`;
    return;
  }
  app.byId = new Map(app.phrases.map((p) => [p.id, p]));
  app.levels = L.levelChoices(app.phrases);
  settings.setup();
  app.tabs = { study: new StudyTab(), browse: new BrowseTab(), autoplay: new AutoPlayTab(),
    lists: new ListsTab(), progress: new ProgressTab() };
  for (const button of document.querySelectorAll(".tabs button")) {
    button.onclick = () => app.select(button.dataset.tab);
  }
  document.addEventListener("keydown", onKey);
  // Coming back to the app (maybe the next morning): refresh the open tab.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") app.tabs[app.current].onShow();
  });
  navigator.storage?.persist?.(); // ask the browser not to clear the progress when space is low
  if ("serviceWorker" in navigator && location.protocol !== "file:") {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
}

main();
