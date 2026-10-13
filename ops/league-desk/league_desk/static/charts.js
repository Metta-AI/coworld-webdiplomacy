/* Plot owns every chart; chart data is escaped JSON from the same panel metrics as the reading. */
(() => {
  const navy = "#1a3875", gold = "#80601f", grey = "#aaa49a";
  function timeAxis(data) {
    const times = data.map(d => d.time).filter(Number.isFinite);
    const short = Math.max(...times) - Math.min(...times) < 2 * 86400;
    return {type: "time", label: "Pacific time", tickFormat: d => short
      ? d.toLocaleTimeString("en-US", {timeZone: "America/Los_Angeles", hour: "numeric", minute: "2-digit"})
      : d.toLocaleDateString("en-US", {timeZone: "America/Los_Angeles"})};
  }
  function draw(node) {
    const chart = JSON.parse(node.dataset.chart), data = chart.data;
    const width = Math.max(260, node.clientWidth);
    let options = {width, height: 210, marginLeft: 52, y: {grid: true, label: chart.label},
      color: {range: [navy, gold, grey]}, marks: []};
    if (chart.kind === "bars") {
      options.x = {type: "band", label: "Pacific day"};
      options.marks = [Plot.barY(data, {x: "day", y: "value", fill: "series", title: d => `${d.series}: ${d.value}`})];
    } else if (chart.kind === "daily-dots") {
      options.x = {type: "band", label: "Pacific day"};
      options.marks = [Plot.dot(data, {x: "day", y: "value", stroke: "series",
        title: d => `${d.series}: median ${d.value.toFixed(2)}, p90 ${d.p90.toFixed(2)} min; n=${d.n}`}),
        Plot.tickY(data, {x: "day", y: "p90", stroke: "series"})];
    } else if (chart.kind === "dots") {
      options.x = timeAxis(data);
      options.marks = [Plot.dot(data, {x: d => new Date(d.time * 1000), y: "value", fill: navy,
        title: d => `${d.value.toFixed(2)} minutes`}), Plot.dot(data.filter(d => d.reference !== null),
        {x: d => new Date(d.time * 1000), y: "reference", symbol: "cross", stroke: gold})];
    } else if (chart.kind === "intervals") {
      options.height = Math.max(150, data.length * 30 + 50);
      options.marginLeft = 130; options.y = {label: null}; options.x = {label: "Rating (μ ± 3σ)", grid: true};
      options.marks = [Plot.ruleY(data, {y: "player", x1: "low", x2: "high", stroke: navy}),
        Plot.dot(data, {y: "player", x: "mu", fill: navy}), Plot.dot(data, {y: "player", x: "value", fill: gold})];
    } else if (chart.kind === "ratings" || chart.kind === "bands") {
      const valid = data.filter(d => d.value !== null), latest = new Map();
      valid.forEach(d => latest.set(d.player_id, d));
      const top = [...latest.values()].sort((a, b) => b.value - a.value).slice(0, 3).map(d => d.player_id);
      const color = d => top.includes(d.player_id) ? [navy, gold, "#5573a0"][top.indexOf(d.player_id)] : grey;
      options.x = timeAxis(data);
      options.y = {label: "Cumulative rating", grid: true};
      const mark = {x: d => new Date(d.time * 1000), y: "value", z: "series", stroke: color};
      options.marks = [Plot.line(valid, mark), Plot.dot(valid, {...mark, r: 2,
        title: d => `${d.player}: ${d.value.toFixed(2)}; ${new Date(d.time * 1000).toLocaleString("en-US", {timeZone: "America/Los_Angeles"})}`})];
      if (chart.kind === "bands") options.marks.unshift(Plot.areaY(data.filter(d => d.low !== null),
        {...mark, y1: "low", y2: "high", fill: color, fillOpacity: .1}));
    } else if (chart.kind === "timing") {
      options.height = 100; options.y = {axis: null}; options.x = {label: "Minutes"};
      options.marks = [Plot.barX(data, {x: "value", y: () => "Representative game", fill: "part",
        title: d => `${d.part}: ${d.value.toFixed(2)} minutes`})];
    } else if (chart.kind === "matrix") {
      options.marginLeft = 120; options.marginBottom = 90;
      options.height = Math.max(260, new Set(data.map(d => d.a)).size * 38 + 100);
      options.x = {label: "Opponent", tickRotate: -30}; options.y = {label: "Player"};
      options.color = {type: "linear", domain: [0, .5, 1], range: [gold, "#fffdf4", navy]};
      options.marks = [Plot.cell(data.filter(d => d.a !== d.b && d.share === null),
        {x: "opponent", y: "player", fill: "none", stroke: grey, strokeDasharray: "3,3"}),
        Plot.cell(data.filter(d => d.share !== null), {x: "opponent", y: "player", fill: "share", inset: 1,
          title: d => `${d.player} ahead of ${d.opponent}: ${(100 * d.share).toFixed(1)}%; ${d.n} games, ${d.ties} ties`}),
        Plot.text(data.filter(d => d.share !== null), {x: "opponent", y: "player",
          text: d => `${Math.round(d.share * 100)}%`, fill: d => d.share > .75 || d.share < .25 ? "#fffdf4" : navy})];
    }
    const plot = Plot.plot({...options, className: "desk-plot"});
    // Plot injects a default stylesheet. Our external CSS supplies it under the page's strict CSP.
    plot.querySelectorAll("style").forEach(style => style.remove());
    node.replaceChildren(plot);
  }
  document.querySelectorAll(".plot").forEach(node => draw(node));
})();
