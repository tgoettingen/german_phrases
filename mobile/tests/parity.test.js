// Checks logic.js against results recorded from the Python app (tools/make_fixtures.py).
// Run: node --test tests/   (from the mobile folder)
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import * as L from "../logic.js";

const read = (name) => JSON.parse(readFileSync(new URL(name, import.meta.url), "utf-8"));
const fx = read("./fixtures.json");
const phrases = read("../phrases.json").map(L.phraseFromRow);
const ids = (list) => list.map((p) => p.id);

test("scheduling matches srs.py", () => {
  for (const steps of fx.srs) {
    let state = L.newCard();
    for (const [rating, today, preview, expected] of steps) {
      assert.deepEqual(L.RATINGS.map((r) => L.nextInterval(state, r)), preview);
      state = L.review(state, rating, today);
      assert.deepEqual(state, expected);
    }
  }
});

test("interval labels match format_interval", () => {
  for (const [days, label] of fx.format_interval) assert.equal(L.formatInterval(days), label, `${days}`);
});

test("typed answers are scored like answers.check", () => {
  for (const [typed, expected, score, rating] of fx.check) {
    const [s, r] = L.check(typed, expected);
    assert.ok(Math.abs(s - score) < 1e-9, `${typed} / ${expected}: ${s} != ${score}`);
    assert.equal(r, rating, `${typed} / ${expected}`);
  }
});

test("directions and Auto play steps match display_options.py", () => {
  const { card_sides: sides, clean_langs: langs, autoplay_steps: steps } = fx.display;
  for (const [direction, expected] of sides) assert.deepEqual(L.cardSides(direction), expected, `${direction}`);
  for (const [value, expected] of langs) assert.deepEqual(L.cleanLangs(value), expected, `${value}`);
  for (const [pid, content, chosen, expected] of steps) {
    const phrase = phrases.find((p) => p.id === pid);
    assert.deepEqual(L.autoplaySteps(phrase, content, chosen), expected, `${pid} / ${content} / ${chosen}`);
  }
});

// Replays 45 simulated study days and compares every queue, then the saved progress file.
const progress = new L.Progress();
Object.assign(progress.settings, fx.settings);
const pool = L.filterPhrases(phrases, "B1", "ALL");

test("study sessions match study.py day by day", () => {
  for (const day of fx.days) {
    const session = new L.StudySession(pool, progress, day.today);
    assert.deepEqual(ids(session.queue), day.start_queue, `start of ${day.today}`);
    for (const [kind, ...rest] of day.ops) {
      const [queue, remaining] = rest.slice(-2);
      if (kind === "rate") session.rate(rest[0], rest[1]);
      else if (kind === "undo") assert.equal(session.undo(), rest[0]);
      else if (kind === "skip") assert.equal(session.skip(), rest[0]);
      else assert.equal(session.addNew(rest[0]), rest[1]);
      assert.deepEqual(ids(session.queue), queue, `${kind} on ${day.today}`);
      assert.deepEqual(session.remaining(), remaining);
    }
    assert.deepEqual(ids(L.todaysPhrases(pool, progress, day.today)), day.todays, day.today);
    assert.deepEqual(L.statistics(phrases, progress, day.today), day.stats, day.today);
    for (const [pid, status] of Object.entries(day.status)) {
      assert.equal(L.cardStatus(progress, phrases.find((p) => p.id === pid), day.today), status);
    }
  }
  assert.deepEqual(JSON.parse(JSON.stringify(progress)), fx.progress);
});

test("lists filter, search and sort like phrase_filters.select", () => {
  progress.starred = new Set(fx.starred);
  for (const [kind, sort, query, count, first, digest] of fx.select) {
    const got = ids(L.select(phrases, progress, { kind, sort, query, today: fx.end }));
    const label = `${kind} / ${sort} / "${query}"`;
    assert.equal(got.length, count, label);
    assert.deepEqual(got.slice(0, 20), first, label);
    assert.equal(createHash("sha1").update(got.join(",")).digest("hex"), digest, label);
  }
});

test("calendar days and streaks match learning_log.py", () => {
  const days = L.summarize(progress.log);
  for (const [day, kind] of fx.classify) assert.equal(L.classify(day, days, 25, fx.end), kind, day);
  for (const [day, pair] of fx.streaks) assert.deepEqual(L.streaks(days, day), pair, day);
  const got = L.lastNDays(days, fx.end, 30).map((s) =>
    [s.day, L.total(s), L.recalled(s), L.forgotten(s), s.new, Number(s.seconds.toFixed(6))]);
  assert.deepEqual(got, fx.last_n_days);
});

test("a progress file round-trips unchanged", () => {
  const copy = new L.Progress(JSON.parse(JSON.stringify(fx.progress)));
  assert.deepEqual(JSON.parse(JSON.stringify(copy)), fx.progress);
});
