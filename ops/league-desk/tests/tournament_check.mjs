// Statistical checks for static/tournament-worker.js. Run: node tests/tournament_check.mjs
import assert from "node:assert/strict";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const core = require("../league_desk/static/tournament-worker.js");
const {rng, latinCycle, prepare, fitAdditive, fitPlackettLuce, analyze, simulateGame, POWERS} = core;
let passed = 0;
function check(name, test) { test(); passed++; console.log(`ok - ${name}`); }

// Synthetic league: `strengths` per player id, power effects, Gaussian-ish noise; scores sum to 1.
function synthetic(count, strengths, powerEffects, seed, noise = 0.08) {
  const random = rng(seed), ids = Object.keys(strengths), games = [];
  for (let g = 0; g < count; g++) {
    const table = core.shuffle(ids.slice(), random).slice(0, POWERS);
    const powers = core.shuffle([0, 1, 2, 3, 4, 5, 6], random);
    const raw = table.map((id, i) => {
      const gauss = (random() + random() + random() - 1.5) * noise * 2;
      return Math.max(0, strengths[id] + powerEffects[powers[i]] + gauss);
    });
    const total = raw.reduce((a, b) => a + b, 0);
    games.push({seats: table.map((id, i) => ({player_id: id, policy_id: id, filler: false, power: powers[i],
                                             score: raw[i] / total}))});
  }
  return games;
}
const chosenOf = ids => ids.map(id => ({player_id: id, policy_ids: [id]}));

check("Latin square: each player plays each power exactly once per cycle", () => {
  for (const order of [[0, 1, 2, 3, 4, 5, 6], [3, 6, 0, 2, 5, 1, 4]]) {
    const games = latinCycle(order);
    assert.equal(games.length, 7);
    for (const powers of games) assert.deepEqual([...powers].sort(), [0, 1, 2, 3, 4, 5, 6]);
    for (let player = 0; player < 7; player++)
      assert.deepEqual(games.map(g => g[player]).sort(), [0, 1, 2, 3, 4, 5, 6]);
  }
});

check("Additive fit recovers known player and power effects", () => {
  const strengths = {a: 0.25, b: 0.18, c: 0.15, d: 0.13, e: 0.12, f: 0.10, g: 0.07, h: 0.14, i: 0.14};
  const effects = [0.04, -0.02, 0.01, -0.03, 0.0, 0.03, -0.03];
  const ids = Object.keys(strengths);
  const data = prepare(synthetic(3000, strengths, effects, 3), chosenOf(ids));
  const model = fitAdditive(data.games, data.entities);
  // Scores are renormalised after generation, so compare centred, scale-free orderings and gaps.
  const theta = Array.from(model.theta.slice(0, ids.length));
  const truth = ids.map(id => strengths[id]);
  const gapFit = theta[0] - theta[6], gapTrue = truth[0] - truth[6];
  assert.ok(Math.abs(gapFit - gapTrue) / gapTrue < 0.2, `gap ${gapFit} vs ${gapTrue}`);
  const fitted = [...theta.keys()].sort((x, y) => theta[y] - theta[x]).slice(0, 3);
  assert.deepEqual(fitted, [0, 1, 2]);
  const beta = Array.from(model.beta);
  assert.ok(Math.abs(beta.reduce((a, b) => a + b, 0)) < 1e-9, "power effects sum to zero");
  beta.forEach((b, p) => assert.ok(Math.abs(b - effects[p]) < 0.015, `power ${p}: ${b} vs ${effects[p]}`));
});

check("Plackett-Luce MM fit recovers known worths", () => {
  const worth = {a: 4, b: 2, c: 1.5, d: 1, e: 1, f: 0.7, g: 0.5, h: 1, i: 1.2};
  const powerWorth = [1.5, 1, 1, 0.8, 1, 1.2, 0.7];
  const random = rng(11), ids = Object.keys(worth), games = [];
  for (let g = 0; g < 4000; g++) {
    const table = core.shuffle(ids.slice(), random).slice(0, 7), powers = core.shuffle([0, 1, 2, 3, 4, 5, 6], random);
    const keys = table.map((id, i) => Math.log(worth[id] * powerWorth[powers[i]]) - Math.log(-Math.log(random())));
    const order = keys.map((k, i) => [k, i]).sort((x, y) => y[0] - x[0]).map(([, i]) => i);
    const scores = new Array(7); order.forEach((seat, place) => { scores[seat] = (7 - place) / 28; });
    games.push({seats: table.map((id, i) => ({player_id: id, policy_id: id, filler: false, power: powers[i],
                                             score: scores[i]}))});
  }
  const data = prepare(games, chosenOf(ids));
  const model = fitPlackettLuce(data.games, data.entities, rng(5));
  // Compare log-worth ratios to player d (true worth 1) and power 1 (true worth 1).
  ids.forEach((id, e) => {
    const ratio = Math.log(model.gamma[e] / model.gamma[3]), expected = Math.log(worth[id]);
    assert.ok(Math.abs(ratio - expected) < 0.12, `${id}: ${ratio.toFixed(3)} vs ${expected.toFixed(3)}`);
  });
  powerWorth.forEach((w, p) => {
    const ratio = Math.log(model.delta[p] / model.delta[1]);
    assert.ok(Math.abs(ratio - Math.log(w)) < 0.12, `power ${p}: ${ratio.toFixed(3)} vs ${Math.log(w).toFixed(3)}`);
  });
});

check("Simulated scores are non-negative and sum to 1 under both models", () => {
  const strengths = {a: 0.3, b: 0.15, c: 0.12, d: 0.12, e: 0.11, f: 0.1, g: 0.1};
  const data = prepare(synthetic(300, strengths, [0, 0, 0, 0, 0, 0, 0], 2), chosenOf(Object.keys(strengths)));
  for (const model of [fitAdditive(data.games, data.entities), fitPlackettLuce(data.games, data.entities, rng(1))]) {
    const random = rng(4);
    for (let i = 0; i < 200; i++) {
      const scores = simulateGame(model, [0, 1, 2, 3, 4, 5, 6], [6, 5, 4, 3, 2, 1, 0], random);
      assert.ok(scores.every(s => s >= 0));
      assert.ok(Math.abs(scores.reduce((a, b) => a + b, 0) - 1) < 1e-9);
    }
  }
});

const base = {format: "rotation", cycles: 10, reshuffle: true, copies: 3, games: 100, toFixation: false,
              replicates: 10, sims: 60, seed: 1};
check("A dominant player wins almost always with enough cycles (both models)", () => {
  const strengths = {a: 0.4, b: 0.1, c: 0.1, d: 0.1, e: 0.1, f: 0.1, g: 0.1};
  const data = prepare(synthetic(400, strengths, [0, 0, 0, 0, 0, 0, 0], 7), chosenOf(Object.keys(strengths)));
  for (const kind of ["A", "B"]) {
    const result = analyze(kind, data, base);
    assert.ok(result.players[0].pWin > 0.97, `${kind}: ${result.players[0].pWin}`);
    assert.equal(result.order[0], 0);
    const evo = analyze(kind, data, {...base, format: "evolution", toFixation: true, replicates: 4, sims: 40});
    assert.ok(evo.players[0].pWin > 0.9, `${kind} evolution: ${evo.players[0].pWin}`);
    assert.ok(evo.fixation.fixed === evo.fixation.runs && evo.fixation.mean > 0);
  }
});

check("Equal players: P(win) intervals mostly cover the fair 1/7", () => {
  const strengths = {a: 0.14, b: 0.14, c: 0.14, d: 0.14, e: 0.14, f: 0.14, g: 0.14};
  const data = prepare(synthetic(600, strengths, [0, 0, 0, 0, 0, 0, 0], 9), chosenOf(Object.keys(strengths)));
  const result = analyze("A", data, {...base, replicates: 40, sims: 100});
  // Headline P(win) is a per-player median across refits, so the seven only roughly sum to 1.
  assert.ok(Math.abs(result.players.reduce((sum, p) => sum + p.pWin, 0) - 1) < 0.2);
  // 90% intervals: about one in ten misses the truth, so allow two of seven.
  const covering = result.players.filter(p => p.pLow <= 1 / 7 && p.pHigh >= 1 / 7).length;
  assert.ok(covering >= 5, `${covering}/7 intervals cover 1/7`);
});

check("Bootstrap spread of P(win) shrinks with more data", () => {
  const strengths = {a: 0.19, b: 0.16, c: 0.14, d: 0.13, e: 0.13, f: 0.13, g: 0.12};
  const width = count => {
    const data = prepare(synthetic(count, strengths, [0, 0, 0, 0, 0, 0, 0], 13), chosenOf(Object.keys(strengths)));
    const result = analyze("A", data, {...base, cycles: 5, replicates: 40, sims: 150});
    return result.players.reduce((sum, p) => sum + (p.pHigh - p.pLow), 0);
  };
  const small = width(60), large = width(1500);
  assert.ok(large < small * 0.7, `spread ${large.toFixed(3)} should be well below ${small.toFixed(3)}`);
});

check("Games needed falls as the gap between a pair grows", () => {
  const close = {a: 0.16, b: 0.15, c: 0.14, d: 0.14, e: 0.14, f: 0.14, g: 0.13};
  const wide = {a: 0.22, b: 0.15, c: 0.14, d: 0.14, e: 0.14, f: 0.14, g: 0.13};
  const need = strengths => {
    const data = prepare(synthetic(1500, strengths, [0, 0, 0, 0, 0, 0, 0], 17), chosenOf(Object.keys(strengths)));
    return analyze("A", data, {...base, replicates: 2, sims: 10}).pairs[0].need[0.9];
  };
  assert.ok(need(wide) < need(close), "a wider gap needs fewer games");
});

check("Filler seats and unchosen policy versions never count as a chosen player", () => {
  const games = [{seats: [
    {player_id: "p", policy_id: "v2", filler: false, power: 0, score: 0.5},
    {player_id: "p", policy_id: "v2", filler: true, power: 1, score: 0.1},
    {player_id: "p", policy_id: "v1", filler: false, power: 2, score: 0.1},
    {player_id: "q", policy_id: "x", filler: false, power: null, score: 0.3}]}];
  const data = prepare(games, [{player_id: "p", policy_ids: ["v2"]}]);
  assert.deepEqual(data.games[0].seats.map(s => s.e), [0, 1, 2, 3]);
  assert.equal(data.games[0].seats[3].p, -1);
});

console.log(`${passed} checks passed`);
