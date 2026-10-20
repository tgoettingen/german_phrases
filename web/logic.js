// Learning logic of the German Phrase Trainer, ported from the Python app
// (srs.py, study.py, phrase_filters.py, learning_log.py, answers.py, progress.py).
// Keep it in step with the Python code: tests/parity.test.js checks both give the same results.

// ---------------------------------------------------------------- dates (ISO "YYYY-MM-DD")

export function todayISO(now = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

const toUTC = (iso) => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10));

export function addDays(iso, days) {
  return new Date(toUTC(iso) + days * 86400000).toISOString().slice(0, 10);
}

export function daysBetween(fromIso, toIso) {
  return Math.round((toUTC(toIso) - toUTC(fromIso)) / 86400000);
}

// Python's round(): halves go to the even neighbour (round(2.5) == 2).
export function pyRound(x) {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}

const roundTo = (x, digits) => Number(x.toFixed(digits));

// Python's str.casefold() for the text in this app (German ß folds to "ss").
export const casefold = (text) => text.toLowerCase().replace(/ß/g, "ss");

const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

// ---------------------------------------------------------------- srs.py

export const AGAIN = 1, HARD = 2, GOOD = 3, EASY = 4;
export const RATINGS = [AGAIN, HARD, GOOD, EASY];
export const RATING_NAMES = { 1: "Again", 2: "Hard", 3: "Good", 4: "Easy" };
export const START_EASE = 2.5;
export const MIN_EASE = 1.3;
export const MAX_INTERVAL = 3650;
export const MATURE_INTERVAL = 21;

const CARD_FIELDS = { reps: 0, interval: 0, ease: START_EASE, lapses: 0, due: "", last_review: "" };

export function newCard(data = {}) {
  const card = { ...CARD_FIELDS };
  for (const key of Object.keys(CARD_FIELDS)) if (key in data) card[key] = data[key];
  return card;
}

export const isNew = (s) => !s.last_review;
export const isDue = (s, today) => !isNew(s) && s.due <= today;

export function nextInterval(state, rating) {
  if (rating === AGAIN) return 0;
  let interval;
  if (state.reps === 0) interval = { [HARD]: 1, [GOOD]: 1, [EASY]: 4 }[rating];
  else if (state.reps === 1) interval = { [HARD]: 3, [GOOD]: 6, [EASY]: 8 }[rating];
  else {
    const factor = { [HARD]: 1.2, [GOOD]: state.ease, [EASY]: state.ease * 1.3 }[rating];
    interval = Math.max(state.interval + 1, pyRound(state.interval * factor));
  }
  return Math.min(interval, MAX_INTERVAL);
}

export function review(state, rating, today) {
  if (!RATINGS.includes(rating)) throw new Error(`invalid rating ${rating}`);
  const interval = nextInterval(state, rating);
  let { ease, reps, lapses } = state;
  if (rating === AGAIN) {
    if (reps > 0) lapses += 1;
    reps = 0;
    ease -= 0.2;
  } else {
    reps += 1;
    ease += { [HARD]: -0.15, [GOOD]: 0, [EASY]: 0.15 }[rating];
  }
  return {
    reps, interval, ease: roundTo(Math.max(MIN_EASE, ease), 2), lapses,
    due: addDays(today, interval), last_review: today,
  };
}

export function formatInterval(days) {
  if (days === 0) return "now";
  if (days < 30) return `${days}d`;
  if (days < 365) return `${(days / 30).toFixed(1)}mo`.replace(".0mo", "mo");
  return `${(days / 365).toFixed(1)}y`.replace(".0y", "y");
}

// ---------------------------------------------------------------- progress.py

export const DEFAULT_SETTINGS = {
  level: "B1", direction: "de_to_en", new_per_day: 20,
  topic: "ALL", answer_mode: "reveal", daily_goal: 30,
};

export class Progress {
  // `onSave` stores the data (localStorage in the app, nothing in tests).
  constructor(data = null, onSave = () => {}) {
    this.onSave = onSave;
    this.cards = {};
    this.settings = { ...DEFAULT_SETTINGS };
    this.daily = { date: "", new: 0, reviews: 0 };
    this.log = []; // one entry per rating: [iso_date, phrase_id, rating, seconds, was_new]
    this.starred = new Set();
    if (data) this.load(data);
  }

  load(data) {
    this.cards = {};
    for (const [pid, s] of Object.entries(data.cards || {})) this.cards[pid] = newCard(s);
    this.settings = { ...DEFAULT_SETTINGS, ...(data.settings || {}) };
    this.daily = { date: "", new: 0, reviews: 0, ...(data.daily || {}) };
    this.log = data.log || [];
    this.starred = new Set(data.starred || []);
  }

  toJSON() {
    // Same layout and key order as progress.py, so the file works in both apps.
    return {
      settings: this.settings, daily: this.daily, starred: [...this.starred].sort(),
      log: this.log, cards: this.cards,
    };
  }

  save() {
    this.onSave(this);
  }

  state(pid) {
    return this.cards[pid] || newCard();
  }

  counters(today) {
    if (this.daily.date !== today) this.daily = { date: today, new: 0, reviews: 0 };
    return this.daily;
  }
}

// ---------------------------------------------------------------- study.py

export const AGAIN_GAP = 3;
export const MAX_LOGGED_SECONDS = 60;

export class StudySession {
  constructor(phrases, progress, today = todayISO()) {
    this.phrases = phrases;
    this.progress = progress;
    this.today = today;
    this.undoSteps = [];
    this.rated = []; // [phrase, rating], oldest first
    const due = phrases.filter((p) => isDue(progress.state(p.id), today));
    due.sort((a, b) => cmp(progress.state(a.id).due, progress.state(b.id).due));
    const newLeft = Math.max(0, progress.settings.new_per_day - progress.counters(today).new);
    this.queue = [...due, ...this.newPhrases(newLeft)];
  }

  newPhrases(limit, queued = new Set()) {
    return this.phrases
      .filter((p) => !queued.has(p.id) && isNew(this.progress.state(p.id)))
      .slice(0, limit);
  }

  get current() {
    return this.queue[0] || null;
  }

  preview() {
    const state = this.progress.state(this.current.id);
    return Object.fromEntries(RATINGS.map((r) => [r, nextInterval(state, r)]));
  }

  rate(rating, seconds = 0) {
    const phrase = this.current;
    if (!phrase) throw new Error("no card to rate");
    const old = this.progress.cards[phrase.id] || null;
    const daily = this.progress.counters(this.today);
    this.undoSteps.push({ id: phrase.id, old, queue: [...this.queue], daily: { ...daily } });

    const state = old || newCard();
    daily[isNew(state) ? "new" : "reviews"] += 1;
    this.progress.cards[phrase.id] = review(state, rating, this.today);
    this.progress.log.push([this.today, phrase.id, rating,
      roundTo(Math.min(seconds, MAX_LOGGED_SECONDS), 1), isNew(state) ? 1 : 0]);
    this.rated.push([phrase, rating]);
    this.queue.shift();
    if (rating === AGAIN) this.queue.splice(Math.min(AGAIN_GAP, this.queue.length), 0, phrase);
    this.progress.save();
  }

  undo() {
    const step = this.undoSteps.pop();
    if (!step) return false;
    if (step.old === null) delete this.progress.cards[step.id];
    else this.progress.cards[step.id] = step.old;
    this.queue = step.queue;
    this.progress.daily = step.daily;
    const log = this.progress.log;
    if (log.length && log[log.length - 1][1] === step.id) log.pop();
    this.rated.pop();
    this.progress.save();
    return true;
  }

  skip() {
    if (this.queue.length < 2) return false;
    this.queue.push(this.queue.shift());
    return true;
  }

  addNew(count) {
    const extra = this.newPhrases(count, new Set(this.queue.map((p) => p.id)));
    this.queue.push(...extra);
    return extra.length;
  }

  remaining() {
    const fresh = this.queue.filter((p) => isNew(this.progress.state(p.id))).length;
    return { new: fresh, review: this.queue.length - fresh };
  }
}

// Drill a fixed list without touching the schedule or the learning log.
export class PracticeSession {
  constructor(phrases) {
    this.queue = [...phrases];
    this.rated = [];
    this.undoSteps = [];
    this.total = phrases.length;
  }

  get current() {
    return this.queue[0] || null;
  }

  preview() {
    return Object.fromEntries(RATINGS.map((r) => [r, 0]));
  }

  rate(rating) {
    const phrase = this.current;
    if (!phrase) throw new Error("no card to rate");
    this.undoSteps.push([...this.queue]);
    this.rated.push([phrase, rating]);
    this.queue.shift();
    if (rating === AGAIN) this.queue.splice(Math.min(AGAIN_GAP, this.queue.length), 0, phrase);
  }

  undo() {
    if (!this.undoSteps.length) return false;
    this.queue = this.undoSteps.pop();
    this.rated.pop();
    return true;
  }

  skip() {
    if (this.queue.length < 2) return false;
    this.queue.push(this.queue.shift());
    return true;
  }

  remaining() {
    return { new: 0, review: this.queue.length };
  }
}

// Phrases already reviewed today (in review order), then those still waiting in today's queue.
export function todaysPhrases(phrases, progress, today = todayISO()) {
  const allowed = new Map(phrases.map((p) => [p.id, p]));
  const reviewed = new Set(progress.log.filter(([d, pid]) => d === today && allowed.has(pid))
    .map(([, pid]) => pid));
  const waiting = new StudySession(phrases, progress, today).queue.filter((p) => !reviewed.has(p.id));
  return [...[...reviewed].map((pid) => allowed.get(pid)), ...waiting];
}

// Card counts per level: new / learning / young / mature / due today.
export function statistics(phrases, progress, today = todayISO()) {
  const stats = {};
  for (const p of phrases) {
    const row = (stats[p.level] ||= { total: 0, new: 0, learning: 0, young: 0, mature: 0, due: 0 });
    const s = progress.state(p.id);
    row.total += 1;
    if (isNew(s)) {
      row.new += 1;
      continue;
    }
    if (s.reps === 0) row.learning += 1;
    else if (s.interval >= MATURE_INTERVAL) row.mature += 1;
    else row.young += 1;
    if (isDue(s, today)) row.due += 1;
  }
  return stats;
}

// ---------------------------------------------------------------- phrase_filters.py

export const DIFFICULT_LAPSES = 3;
export const FILTERS = {
  learned: "Learned (studied at least once)",
  to_learn: "To be learned (new)",
  due: "Due for review today",
  forgotten: "Forgotten at least once",
  difficult: `Difficult (forgotten ${DIFFICULT_LAPSES}+ times)`,
  starred: "Starred",
  mature: "Well known (interval 21+ days)",
  all: "All phrases",
};
export const SORTS = {
  id: "Original order",
  due: "Next review date",
  lapses: "Most forgotten first",
  ease: "Hardest first (lowest ease)",
  recent: "Most recently reviewed",
  alpha: "German A-Z",
};

export const wasForgotten = (s) => s.lapses > 0 || (!isNew(s) && s.reps === 0);

export function matches(p, kind, progress, today) {
  const s = progress.state(p.id);
  switch (kind) {
    case "learned": return !isNew(s);
    case "to_learn": return isNew(s);
    case "due": return isDue(s, today);
    case "forgotten": return wasForgotten(s);
    case "difficult": return s.lapses >= DIFFICULT_LAPSES;
    case "starred": return progress.starred.has(p.id);
    case "mature": return s.interval >= 21;
    case "all": return true;
    default: throw new Error(`unknown filter ${kind}`);
  }
}

const searchCache = new WeakMap();
export function searchText(p) {
  let text = searchCache.get(p);
  if (text === undefined) {
    const examples = p.examples.map(([de, en]) => `${de} ${en}`).join(" ");
    text = casefold(`${p.id} ${p.german} ${p.english} ${p.chinese} ${examples}`);
    searchCache.set(p, text);
  }
  return text;
}

export function select(phrases, progress, { kind = "all", query = "", sort = "id", limit = 0,
  today = todayISO() } = {}) {
  query = casefold(query).trim();
  const result = phrases.filter((p) => matches(p, kind, progress, today)
    && (!query || searchText(p).includes(query)));
  const st = (p) => progress.state(p.id);
  const keys = {
    id: null,
    due: (p) => st(p).due || "9999",
    lapses: (p) => -st(p).lapses,
    ease: (p) => st(p).ease,
    recent: (p) => st(p).last_review,
    alpha: (p) => casefold(p.german),
  };
  const key = keys[sort];
  if (key) {
    const sign = sort === "recent" ? -1 : 1; // stable, like Python's sort(reverse=True)
    result.sort((a, b) => sign * cmp(key(a), key(b)));
  }
  return limit ? result.slice(0, limit) : result;
}

// ---------------------------------------------------------------- learning_log.py

export const GOOD_DAY = "good", STUDIED = "studied", HARD_DAY = "hard", MISSED = "missed",
  NO_DATA = "none";
export const GOOD_ACCURACY = 0.85;
export const HARD_ACCURACY = 0.70;
export const MIN_HARD_RATINGS = 10;

export function daySummary(day) {
  return { day, ratings: { 1: 0, 2: 0, 3: 0, 4: 0 }, new: 0, seconds: 0, reviews: [] };
}

export const total = (s) => s.ratings[1] + s.ratings[2] + s.ratings[3] + s.ratings[4];
export const forgotten = (s) => s.ratings[AGAIN];
export const recalled = (s) => total(s) - forgotten(s);
export const accuracy = (s) => (total(s) ? recalled(s) / total(s) : 0);
export const forgottenIds = (s) =>
  [...new Set(s.reviews.filter(([, r]) => r === AGAIN).map(([pid]) => pid))].sort();

// {iso_day: summary} from the review log.
export function summarize(log) {
  const days = {};
  for (const [day, pid, rating, seconds, wasNew] of log) {
    const s = (days[day] ||= daySummary(day));
    s.ratings[rating] += 1;
    s.new += wasNew;
    s.seconds += seconds;
    s.reviews.push([pid, rating]);
  }
  return days;
}

export function classify(day, days, goal, today) {
  const s = days[day];
  if (s && total(s)) {
    if (accuracy(s) < HARD_ACCURACY && total(s) >= MIN_HARD_RATINGS) return HARD_DAY;
    if (total(s) >= goal && accuracy(s) >= GOOD_ACCURACY) return GOOD_DAY;
    return STUDIED;
  }
  const keys = Object.keys(days);
  const first = keys.length ? keys.reduce((a, b) => (b < a ? b : a)) : null;
  if (first === null || day < first || day >= today) return NO_DATA;
  return MISSED;
}

// [current streak, longest streak] of consecutive study days.
export function streaks(days, today) {
  const studied = new Set(Object.keys(days).filter((d) => total(days[d])));
  let longest = 0, run = 0, prev = null;
  for (const d of [...studied].sort()) {
    run = prev && daysBetween(prev, d) === 1 ? run + 1 : 1;
    longest = Math.max(longest, run);
    prev = d;
  }
  let current = 0;
  let d = studied.has(today) ? today : addDays(today, -1);
  while (studied.has(d)) {
    current += 1;
    d = addDays(d, -1);
  }
  return [current, longest];
}

export function lastNDays(days, today, n) {
  const out = [];
  for (let i = n - 1; i >= 0; i--) {
    const d = addDays(today, -i);
    out.push(days[d] || daySummary(d));
  }
  return out;
}

// ---------------------------------------------------------------- answers.py

const WORD = "[\\p{L}\\p{N}_]";
const OPTIONAL = new RegExp(`(?<!${WORD})(etw|etwas|jdn|jemanden|jdm|jemandem|jds|jemandes|sich`
  + `|sth|sb|someone|somebody|something|oneself)(?!${WORD})\\.?`, "giu");
const UMLAUTS = { "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss" };

export function normalize(text) {
  text = casefold(text);
  for (const [k, v] of Object.entries(UMLAUTS)) text = text.replaceAll(k, v);
  text = text.replace(OPTIONAL, " ");
  text = text.replace(/[^\p{L}\p{N}_\s]/gu, " ");
  text = text.split(/\s+/).filter(Boolean).join(" ");
  return text.startsWith("to ") ? text.slice(3) : text;
}

export function alternatives(expected) {
  const parts = expected.split(/[,;/]/).filter((p) => p.trim());
  return parts.length > 1 ? [expected, ...parts] : [expected];
}

// difflib.SequenceMatcher(None, a, b).ratio(), on code points like Python strings.
export function similarity(a, b) {
  a = Array.from(a);
  b = Array.from(b);
  const b2j = new Map();
  b.forEach((ch, i) => {
    if (!b2j.has(ch)) b2j.set(ch, []);
    b2j.get(ch).push(i);
  });
  if (b.length >= 200) { // difflib's "autojunk": ignore very common characters
    const ntest = Math.floor(b.length / 100) + 1;
    for (const [ch, idxs] of [...b2j]) if (idxs.length > ntest) b2j.delete(ch);
  }

  function longestMatch(alo, ahi, blo, bhi) {
    let besti = alo, bestj = blo, bestsize = 0;
    let j2len = new Map();
    for (let i = alo; i < ahi; i++) {
      const newj2len = new Map();
      for (const j of b2j.get(a[i]) || []) {
        if (j < blo) continue;
        if (j >= bhi) break;
        const k = (j2len.get(j - 1) || 0) + 1;
        newj2len.set(j, k);
        if (k > bestsize) [besti, bestj, bestsize] = [i - k + 1, j - k + 1, k];
      }
      j2len = newj2len;
    }
    while (besti > alo && bestj > blo && a[besti - 1] === b[bestj - 1]) {
      besti--; bestj--; bestsize++;
    }
    while (besti + bestsize < ahi && bestj + bestsize < bhi
      && a[besti + bestsize] === b[bestj + bestsize]) bestsize++;
    return [besti, bestj, bestsize];
  }

  let matched = 0;
  const queue = [[0, a.length, 0, b.length]];
  while (queue.length) {
    const [alo, ahi, blo, bhi] = queue.pop();
    const [i, j, k] = longestMatch(alo, ahi, blo, bhi);
    if (!k) continue;
    matched += k;
    if (alo < i && blo < j) queue.push([alo, i, blo, j]);
    if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
  }
  const length = a.length + b.length;
  return length ? (2 * matched) / length : 1;
}

// [similarity 0..1, suggested rating] for a typed answer.
export function check(typed, expected) {
  const typedN = normalize(typed);
  if (!typedN) return [0, AGAIN];
  const score = Math.max(...alternatives(expected).map((alt) => similarity(typedN, normalize(alt))));
  if (score >= 0.95) return [score, GOOD];
  if (score >= 0.8) return [score, HARD];
  return [score, AGAIN];
}

// ---------------------------------------------------------------- trainer.py helpers

export const LEVELS = ["B1", "B2", "C1"];
export const LEVEL_CHOICES = [...LEVELS, "ALL"];

// Built-in levels first, then the other collections (e.g. Wort-B1) in file order, then ALL.
export function levelChoices(phrases) {
  const others = [...new Set(phrases.map((p) => p.level))].filter((l) => !LEVELS.includes(l));
  return [...LEVELS, ...others, "ALL"];
}
export const ALL_TOPICS = "All topics";
export const DIRECTIONS = {
  de_to_en: "German → English / 中文",
  en_to_de: "English / 中文 → German",
};

export function phraseFromRow([id, level, topic, german, english, chinese, examples]) {
  return { id, level, topic, german, english, chinese, examples };
}

export function topicsFor(phrases, level) {
  return [...new Set(phrases.filter((p) => level === "ALL" || p.level === level).map((p) => p.topic))];
}

export function filterPhrases(phrases, level, topic) {
  return phrases.filter((p) => (level === "ALL" || p.level === level)
    && (topic === "ALL" || topic === ALL_TOPICS || p.topic === topic));
}

export function cardStatus(progress, phrase, today) {
  const s = progress.state(phrase.id);
  if (isNew(s)) return "New";
  let status = isDue(s, today) ? "Due today"
    : `Next review ${s.due} (in ${formatInterval(daysBetween(today, s.due))})`;
  if (s.lapses) status += ` · forgotten ${s.lapses}×`;
  return status;
}

export function phraseInfo(progress, phrase, today) {
  const star = progress.starred.has(phrase.id) ? "★ " : "";
  return `${star}${phrase.id} · ${phrase.topic} · ${cardStatus(progress, phrase, today)}`;
}

// Round a gridline step up to 1, 2 or 5 × 10^n.
export function niceStep(raw) {
  if (raw <= 0) return 1;
  const exp = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * exp).find((v) => v >= raw);
}

const ABBREVIATIONS = { "etw.": "etwas", "jdn.": "jemanden", "jdm.": "jemandem", "jds.": "jemandes" };

// Expand dictionary abbreviations so the voice reads them as words.
export function speakable(text) {
  for (const [short, full] of Object.entries(ABBREVIATIONS)) text = text.replaceAll(short, full);
  return text;
}
