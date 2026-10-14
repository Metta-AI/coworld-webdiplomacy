/* Tournament planner statistics: model fits, tournament simulators and the bootstrap.
 *
 * Runs as a Web Worker for the page (tournament.js) and as a CommonJS module for
 * tests/tournament_check.mjs. Everything above the worker wiring is a pure function of
 * its arguments and a seeded random source, so a run is reproducible from its seed.
 *
 * Two models of one seven-seat game, both fitted on league games:
 *   A "Player + power": score = theta[entity] + beta[power] + noise, least squares with
 *     sum-to-zero power effects. A simulated seat draws its noise from its own entity's
 *     residuals, is clamped at 0, and the seven scores are rescaled to sum to 1 (league
 *     scores per game sum to 1).
 *   B "Head-to-head": Plackett-Luce finishing orders with worth = gamma[entity] * delta[power],
 *     fitted by the MM algorithm (Hunter 2004). A simulated game draws a finishing order and
 *     gives it the sorted score vector of a randomly drawn real game, so solo and draw shapes
 *     stay realistic.
 * Entities are the chosen players (indices 0..K-1) plus one nuisance entity per other policy
 * version seen in the data, so opponents of different strength are not averaged together.
 * A power of -1 means the power is unknown: model A treats it as an average power (effect 0),
 * model B as worth 1.
 */
(function (root) {
  "use strict";
  const POWERS = 7;
  const Z = {0.8: 0.8416, 0.9: 1.2816, 0.95: 1.6449};

  // mulberry32: small, fast, seedable; Math.random cannot be replayed.
  function rng(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function shuffle(values, random) {
    for (let i = values.length - 1; i > 0; i--) {
      const j = Math.floor(random() * (i + 1));
      [values[i], values[j]] = [values[j], values[i]];
    }
    return values;
  }
  function quantile(sorted, q) {
    if (!sorted.length) return null;
    const index = (sorted.length - 1) * q, lo = Math.floor(index), hi = Math.min(lo + 1, sorted.length - 1);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (index - lo);
  }
  function mean(values) { return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null; }
  function sd(values) {
    const m = mean(values);
    return values.length > 1 ? Math.sqrt(values.reduce((a, v) => a + (v - m) ** 2, 0) / (values.length - 1)) : null;
  }

  /* Cyclic Latin square: in game g of a cycle, the player at position i of `order` plays
   * power (i + g) mod 7. Over seven games every player plays every power exactly once. */
  function latinCycle(order) {
    const games = [];
    for (let g = 0; g < POWERS; g++) {
      const powers = new Array(order.length);
      order.forEach((player, i) => { powers[player] = (i + g) % POWERS; });
      games.push(powers);
    }
    return games;
  }

  /* Map raw games to entity indices. `chosen` is [{player_id, policy_ids}]; a seat belongs to a
   * chosen player when it is not a filler seat and its policy version is one of theirs. */
  function prepare(games, chosen) {
    const owner = new Map();
    chosen.forEach((player, index) => player.policy_ids.forEach(id => owner.set(id, index)));
    const others = new Map(), prepared = [];
    for (const game of games) {
      const seats = game.seats.map(seat => {
        let entity = seat.filler ? undefined : owner.get(seat.policy_id);
        if (entity === undefined) {
          if (!others.has(seat.policy_id)) others.set(seat.policy_id, chosen.length + others.size);
          entity = others.get(seat.policy_id);
        }
        return {e: entity, p: seat.power === null || seat.power === undefined ? -1 : seat.power, s: seat.score};
      });
      prepared.push({seats});
    }
    return {games: prepared, entities: chosen.length + others.size, chosen: chosen.length};
  }

  /* Model A by backfitting: alternate power means and entity means of the residual until stable. */
  function fitAdditive(games, entities) {
    const theta = new Float64Array(entities), beta = new Float64Array(POWERS);
    const sums = new Float64Array(entities), counts = new Float64Array(entities);
    for (const g of games) for (const s of g.seats) { sums[s.e] += s.s; counts[s.e]++; }
    for (let e = 0; e < entities; e++) theta[e] = counts[e] ? sums[e] / counts[e] : 1 / POWERS;
    for (let iteration = 0; iteration < 200; iteration++) {
      const bSum = new Float64Array(POWERS), bCount = new Float64Array(POWERS);
      for (const g of games) for (const s of g.seats) if (s.p >= 0) { bSum[s.p] += s.s - theta[s.e]; bCount[s.p]++; }
      for (let p = 0; p < POWERS; p++) beta[p] = bCount[p] ? bSum[p] / bCount[p] : 0;
      const centre = beta.reduce((a, b) => a + b, 0) / POWERS;
      for (let p = 0; p < POWERS; p++) beta[p] -= centre;
      sums.fill(0);
      for (const g of games) for (const s of g.seats) sums[s.e] += s.s - (s.p >= 0 ? beta[s.p] : 0);
      let change = 0;
      for (let e = 0; e < entities; e++) {
        const next = counts[e] ? sums[e] / counts[e] : theta[e];
        change = Math.max(change, Math.abs(next - theta[e])); theta[e] = next;
      }
      if (change < 1e-10) break;
    }
    const residuals = Array.from({length: entities}, () => []), all = [];
    for (const g of games) for (const s of g.seats) {
      const r = s.s - theta[s.e] - (s.p >= 0 ? beta[s.p] : 0);
      residuals[s.e].push(r); all.push(r);
    }
    return {kind: "A", theta, beta, residuals, pooled: all, sigma: sd(all)};
  }

  /* Model B: Plackett-Luce with worth gamma[e] * delta[p], cyclic MM updates (Hunter 2004).
   * Ties in score are broken at random, once per fit (so the bootstrap varies them too).
   * Every entity and power also plays one virtual win and one virtual loss against a worth-1
   * reference: this keeps never-winning entities finite and pins the overall scale. */
  function fitPlackettLuce(games, entities, random, maxIterations = 500) {
    const orders = games.map(g => {
      const keyed = g.seats.map(s => ({s, tie: random()}));
      keyed.sort((a, b) => b.s.s - a.s.s || a.tie - b.tie);
      return keyed.map(k => k.s);
    });
    const gamma = new Float64Array(entities).fill(1), delta = new Float64Array(POWERS).fill(1);
    const winsE = new Float64Array(entities), winsP = new Float64Array(POWERS);
    for (const order of orders) order.forEach((s, k) => {
      if (k < order.length - 1) { winsE[s.e]++; if (s.p >= 0) winsP[s.p]++; }
    });
    const worth = s => gamma[s.e] * (s.p >= 0 ? delta[s.p] : 1);
    const cumulative = order => {
      // cum[k] = sum over stages t <= k (and t < n-1) of 1 / (total worth still unplaced at t).
      const n = order.length, cum = new Float64Array(n);
      let remaining = 0;
      for (const s of order) remaining += worth(s);
      let running = 0;
      for (let k = 0; k < n; k++) {
        if (k < n - 1) running += 1 / remaining;
        cum[k] = running; remaining -= worth(order[k]);
      }
      return cum;
    };
    let iterations = 0;
    for (; iterations < maxIterations; iterations++) {
      const denomE = new Float64Array(entities);
      for (const order of orders) {
        const cum = cumulative(order);
        order.forEach((s, k) => { denomE[s.e] += (s.p >= 0 ? delta[s.p] : 1) * cum[k]; });
      }
      let change = 0;
      for (let e = 0; e < entities; e++) {
        const next = (winsE[e] + 1) / (denomE[e] + 2 / (gamma[e] + 1));
        change = Math.max(change, Math.abs(Math.log(next / gamma[e]))); gamma[e] = next;
      }
      const denomP = new Float64Array(POWERS);
      for (const order of orders) {
        const cum = cumulative(order);
        order.forEach((s, k) => { if (s.p >= 0) denomP[s.p] += gamma[s.e] * cum[k]; });
      }
      for (let p = 0; p < POWERS; p++) {
        const next = (winsP[p] + 1) / (denomP[p] + 2 / (delta[p] + 1));
        change = Math.max(change, Math.abs(Math.log(next / delta[p]))); delta[p] = next;
      }
      if (change < 1e-7) break;
    }
    const shapes = games.map(g => g.seats.map(s => s.s).sort((a, b) => b - a));
    return {kind: "B", gamma, delta, shapes, iterations};
  }

  /* One simulated game: `players` are entity indices, `powers` their powers; returns scores. */
  function simulateGame(model, players, powers, random) {
    const n = players.length, scores = new Array(n);
    if (model.kind === "A") {
      let total = 0;
      for (let i = 0; i < n; i++) {
        const own = model.residuals[players[i]], pool = own.length >= 5 ? own : model.pooled;
        const noise = pool[Math.floor(random() * pool.length)];
        scores[i] = Math.max(0, model.theta[players[i]] + model.beta[powers[i]] + noise); total += scores[i];
      }
      for (let i = 0; i < n; i++) scores[i] = total > 0 ? scores[i] / total : 1 / n;
      return scores;
    }
    // Gumbel-max: sorting log-worth plus Gumbel noise draws a Plackett-Luce order.
    const keys = players.map((e, i) => ({i, k: Math.log(model.gamma[e] * model.delta[powers[i]])
      - Math.log(-Math.log(random() || 1e-300))}));
    keys.sort((a, b) => b.k - a.k);
    const shape = model.shapes[Math.floor(random() * model.shapes.length)];
    keys.forEach((key, place) => { scores[key.i] = shape[place]; });
    return scores;
  }

  // The "true" strength order under a fitted model, best first, among the chosen entities.
  function strengthOrder(model, chosen) {
    const value = e => model.kind === "A" ? model.theta[e] : Math.log(model.gamma[e]);
    return Array.from({length: chosen}, (_, e) => e).sort((a, b) => value(b) - value(a));
  }
  function leaders(totals, random) {
    // Indices of first and second place; exact ties are broken at random.
    const order = totals.map((t, i) => ({i, t, r: random()})).sort((a, b) => b.t - a.t || a.r - b.r);
    return [order[0].i, order[1].i];
  }

  /* Full-table rotation: `cycles` Latin-square cycles of 7 games with all 7 players seated.
   * Records cumulative totals after each cycle listed in `checkpoints`. */
  function runRotation(model, cycles, reshuffle, random, checkpoints = []) {
    const totals = new Array(POWERS).fill(0), snapshots = {};
    const players = [0, 1, 2, 3, 4, 5, 6], wanted = new Set(checkpoints);
    for (let c = 1; c <= cycles; c++) {
      const order = reshuffle ? shuffle(players.slice(), random) : players;
      for (const powers of latinCycle(order)) {
        const scores = simulateGame(model, players, powers, random);
        for (let i = 0; i < POWERS; i++) totals[i] += scores[i];
      }
      if (wanted.has(c)) snapshots[c] = totals.slice();
    }
    return {totals, snapshots};
  }

  /* Evolutionary (Moran-style): a population of `copies` individuals per player; each game seats
   * 7 individuals drawn without replacement at random powers; the top scorer's type gains one
   * individual and the bottom scorer's type loses one. Runs to `games`, and on to fixation
   * (one type left) or `cap`, so the fixation time is known in every mode. */
  function runEvolution(model, types, copies, games, cap, random, checkpoints = []) {
    const counts = new Array(types).fill(copies), size = types * copies, snapshots = {};
    const wanted = new Set(checkpoints);
    let atGames = null, fixedAt = null;
    const population = new Array(size), powers = [0, 1, 2, 3, 4, 5, 6];
    for (let step = 1; step <= Math.max(games, cap); step++) {
      let k = 0;
      counts.forEach((n, type) => { for (let j = 0; j < n; j++) population[k++] = type; });
      for (let i = 0; i < POWERS; i++) {  // partial Fisher-Yates: the first 7 are the table
        const j = i + Math.floor(random() * (size - i));
        [population[i], population[j]] = [population[j], population[i]];
      }
      const table = population.slice(0, POWERS);
      shuffle(powers, random);
      const scores = simulateGame(model, table, powers, random);
      const order = scores.map((s, i) => ({i, s, r: random()})).sort((a, b) => b.s - a.s || a.r - b.r);
      const top = table[order[0].i], bottom = table[order[POWERS - 1].i];
      if (top !== bottom) { counts[top]++; counts[bottom]--; }
      if (wanted.has(step)) snapshots[step] = counts.slice();
      if (step === games) atGames = counts.slice();
      if (fixedAt === null && counts.some(n => n === size)) fixedAt = step;
      if (step >= games && fixedAt !== null) break;
    }
    for (const c of checkpoints) if (!snapshots[c]) snapshots[c] = (atGames || counts).slice();
    return {counts: atGames || counts, snapshots, fixedAt};
  }

  function resample(games, random) {
    return games.map(() => games[Math.floor(random() * games.length)]);
  }
  function fit(kind, games, entities, random) {
    return kind === "A" ? fitAdditive(games, entities) : fitPlackettLuce(games, entities, random);
  }

  /* Games needed for the better of a pair to finish ahead with probability q: per-cycle score
   * differences are independent, so after n cycles P(ahead) ~ Phi(sqrt(n) * d / s). */
  function cyclesNeeded(d, s, q) {
    if (!(d > 0)) return null;
    return Math.max(1, Math.ceil((Z[q] * s / d) ** 2));
  }

  /* The whole planner for one model: point fit, bootstrap replicates and simulations.
   * settings: {format, cycles, reshuffle, copies, games, toFixation, replicates, sims, seed}
   * `progress(done, total)` is called between replicates. */
  function analyze(kind, data, settings, progress = () => {}) {
    const random = rng(settings.seed + (kind === "A" ? 0 : 7919));
    const {games, entities, chosen} = data;
    const rotation = settings.format === "rotation";
    const sigma = fitAdditive(games, entities).sigma;
    const checkpoints = rotation
      ? [...new Set([1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, settings.cycles])].sort((a, b) => a - b)
      : [...new Set([10, 25, 50, 75, 100, 150, 200, 300, 400, 500, settings.games])].filter(
          g => g <= Math.max(500, settings.games)).sort((a, b) => a - b);
    const horizon = checkpoints[checkpoints.length - 1];
    const size = rotation ? settings.cycles : settings.games;
    const replicateWins = [], totals = Array.from({length: chosen}, () => []), margins = [];
    const curve = Object.fromEntries(checkpoints.map(c => [c, {strongest: 0, clear: 0, fixed: 0, n: 0}]));
    const fixation = [];
    let fixationRuns = 0;
    const evoCap = settings.toFixation ? 20000 : Math.max(size, 3000);
    for (let r = 0; r < settings.replicates; r++) {
      const sample = r === 0 ? games : resample(games, random);
      const model = fit(kind, sample, entities, random);
      const strongest = strengthOrder(model, chosen)[0];
      const wins = new Array(chosen).fill(0);
      for (let m = 0; m < settings.sims; m++) {
        if (rotation) {
          const run = runRotation(model, horizon, settings.reshuffle, random, checkpoints);
          const final = run.snapshots[size];
          const [first, second] = leaders(final, random);
          wins[first]++; margins.push(final[first] - final[second]);
          final.forEach((t, i) => totals[i].push(t));
          for (const c of checkpoints) {
            const [a, b] = leaders(run.snapshots[c], random), cell = curve[c];
            const lead = run.snapshots[c][a] - run.snapshots[c][b];
            cell.n++; cell.strongest += a === strongest;
            // A "clear" lead: two equally strong players would exceed it only 5% of the time.
            cell.clear += lead > Z[0.95] * Math.sqrt(2 * c * POWERS) * sigma;
          }
        } else {
          const cap = settings.toFixation ? evoCap : Math.max(horizon, evoCap);
          // After fixation (or the cap) the state no longer changes, so later checkpoints reuse the end state.
          const run = runEvolution(model, chosen, settings.copies, settings.toFixation ? 0 : horizon, cap,
                                   random, checkpoints);
          const final = settings.toFixation ? run.counts : run.snapshots[size];
          const [first, second] = leaders(final, random);
          wins[first]++; margins.push((final[first] - final[second]) / (chosen * settings.copies));
          final.forEach((n, i) => totals[i].push(n / (chosen * settings.copies)));
          fixationRuns++;
          if (run.fixedAt !== null) fixation.push(run.fixedAt);
          for (const c of checkpoints) {
            const [a] = leaders(run.snapshots[c], random), cell = curve[c];
            cell.n++; cell.strongest += a === strongest;
            cell.fixed += run.fixedAt !== null && run.fixedAt <= c;
          }
        }
      }
      replicateWins.push(wins.map(w => w / settings.sims));
      progress(r + 1, settings.replicates);
    }
    const players = Array.from({length: chosen}, (_, i) => {
      const shares = replicateWins.map(w => w[i]).sort((a, b) => a - b), values = totals[i].sort((a, b) => a - b);
      // Median, so the headline always sits inside its own range (a mean can be dragged outside it).
      return {pWin: quantile(shares, 0.5), pLow: quantile(shares, 0.05), pHigh: quantile(shares, 0.95),
              total: mean(values), totalLow: quantile(values, 0.05), totalHigh: quantile(values, 0.95),
              point: replicateWins[0][i]};
    });
    margins.sort((a, b) => a - b);
    const result = {
      kind, players, sigma, size,
      margin: {values: histogram(margins, 24), median: quantile(margins, 0.5),
               low: quantile(margins, 0.05), high: quantile(margins, 0.95)},
      curve: checkpoints.map(c => ({x: rotation ? c * POWERS : c, cycles: rotation ? c : null,
        strongest: curve[c].n ? curve[c].strongest / curve[c].n : null,
        clear: rotation && curve[c].n ? curve[c].clear / curve[c].n : null,
        fixed: !rotation && curve[c].n ? curve[c].fixed / curve[c].n : null})).filter(p => p.strongest !== null),
    };
    const pointModel = fit(kind, games, entities, rng(settings.seed + 17));
    result.order = strengthOrder(pointModel, chosen);
    result.effects = kind === "A" ? Array.from(pointModel.beta) : Array.from(pointModel.delta);
    result.strength = Array.from({length: chosen}, (_, e) => kind === "A" ? pointModel.theta[e]
      : Math.log(pointModel.gamma[e]));
    if (rotation) {
      const needs = pairNeeds(pointModel, settings.reshuffle, rng(settings.seed + 29));
      // Rank by simulated expected totals: clamping and rescaling can reorder close raw strengths.
      result.order = needs.order; result.pairs = needs.pairs; result.perCycle = needs.perCycle;
    }
    else {
      fixation.sort((a, b) => a - b);
      result.fixation = {mean: mean(fixation), median: quantile(fixation, 0.5), low: quantile(fixation, 0.05),
                         high: quantile(fixation, 0.95), fixed: fixation.length, runs: fixationRuns, cap: evoCap};
    }
    return result;
  }

  // Adjacent pairs in simulated expected-total order; per-cycle differences from simulated cycles.
  function pairNeeds(model, reshuffle, random, cycles = 3000) {
    const runs = [];
    for (let c = 0; c < cycles; c++) runs.push(runRotation(model, 1, reshuffle, random).totals);
    const perCycle = Array.from({length: POWERS}, (_, i) => mean(runs.map(t => t[i])));
    const order = perCycle.map((_, i) => i).sort((a, b) => perCycle[b] - perCycle[a]);
    const diffs = order.slice(0, -1).map((_, k) => runs.map(t => t[order[k]] - t[order[k + 1]]));
    return {order, perCycle, pairs: diffs.map((values, k) => {
      const d = mean(values), s = sd(values);
      return {better: order[k], worse: order[k + 1], perCycle: d, sd: s,
              need: Object.fromEntries([0.8, 0.9, 0.95].map(q => {
                const n = cyclesNeeded(d, s, q); return [q, n === null ? null : n * POWERS];
              }))};
    })};
  }

  function histogram(sorted, bins) {
    if (!sorted.length) return [];
    const lo = sorted[0], hi = sorted[sorted.length - 1], width = (hi - lo) / bins;
    // Every run ended with the same margin (e.g. evolution to one survivor): one narrow bar.
    if (!(width > 0)) return [{x0: lo - 0.01, x1: lo + 0.01, share: 1}];
    const counts = new Array(bins).fill(0);
    for (const v of sorted) counts[Math.min(bins - 1, Math.floor((v - lo) / width))]++;
    return counts.map((n, i) => ({x0: lo + i * width, x1: lo + (i + 1) * width, share: n / sorted.length}));
  }

  const core = {rng, shuffle, quantile, latinCycle, prepare, fitAdditive, fitPlackettLuce, simulateGame,
                strengthOrder, runRotation, runEvolution, resample, analyze, cyclesNeeded, pairNeeds, POWERS};

  if (typeof module === "object" && module.exports) module.exports = core;
  else if (typeof importScripts === "function") {
    // Worker wiring: one run per message; the page terminates the worker to cancel a run.
    root.onmessage = event => {
      const {id, games, chosen, settings} = event.data;
      const data = prepare(games, chosen);
      const results = {};
      const total = 2 * settings.replicates;
      for (const [k, kind] of ["A", "B"].entries()) {
        results[kind] = analyze(kind, data, settings, done => {
          root.postMessage({id, type: "progress", done: k * settings.replicates + done, total});
        });
      }
      root.postMessage({id, type: "result", results, entities: data.entities, games: data.games.length});
    };
  }
})(typeof self !== "undefined" ? self : globalThis);
