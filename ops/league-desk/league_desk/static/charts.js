/* Plot owns every chart; chart data is escaped JSON from the same panel metrics as the reading. */
(() => {
  const navy = "#1a3875", gold = "#80601f", grey = "#aaa49a";
  function timeAxis(data) {
    const times = data.map(d => d.time).filter(Number.isFinite);
    const [first,last] = d3.extent(times), short = last - first < 2 * 86400;
    return {type: "time", label: "Pacific time", tickFormat: d => short
      ? d.toLocaleTimeString("en-US", {timeZone: "America/Los_Angeles", hour: "numeric", minute: "2-digit"})
      : d.toLocaleDateString("en-US", {timeZone: "America/Los_Angeles"})};
  }
  function entityColor(key) {
    let hash = 0; for (const c of key) hash = ((hash * 31) + c.charCodeAt(0)) >>> 0;
    return [navy, gold, "#5573a0", "#5d6d41", "#706387", "#527878"][hash % 6];
  }
  function clean(plot) { plot.querySelectorAll("style").forEach(style => style.remove()); return plot; }
  function draw(node) {
    const chart = JSON.parse(node.dataset.chart), data = chart.data;
    const width = Math.max(260, node.clientWidth);
    node.dataset.drawn = node.dataset.chart; node.dataset.width = String(width);
    if (chart.kind === "bands") {
      const groups = d3.group(data, d => `${d.division_id}:${d.player_id}`);
      const values = data.flatMap(d => [d.low, d.high, d.value]).filter(v => v !== null);
      const domain = d3.extent(values), times = d3.extent(data, d => new Date(d.time * 1000));
      const grid = document.createElement('div'); grid.className = 'multiples';
      for (const rows of groups.values()) {
        const section = document.createElement('section'), label = document.createElement('h4');
        const last = rows[rows.length - 1]; label.textContent = `${last.player} · ±${last.high === null ? '?' : ((last.high-last.low)/2).toFixed(2)}`;
        const x = d => new Date(d.time * 1000), color = entityColor(last.player_id);
        const marks = [Plot.areaY(rows.filter(d => d.low !== null), {x, y1:'low', y2:'high', z:'series', fill:color, fillOpacity:.13}),
          Plot.line(rows, {x, y:'mu', z:'series', stroke:color}),
          Plot.line(rows, {x, y:'value', z:'series', stroke:color, strokeDasharray:'3,2'}),
          Plot.dot(rows, {x, y:'value', fill:color, r:2, title:d=>`${d.player}: MMR ${d.value}; μ ${d.mu}`}),
          Plot.ruleX(chart.markers || [],{x:d=>new Date(d.time*1000),stroke:grey,strokeDasharray:'2,3',title:'label'})];
        section.append(label, clean(Plot.plot({width:Math.max(230, Math.floor(width / Math.max(1, Math.floor(width/260))) - 16),
          height:170, marginLeft:45, x:{...timeAxis(data), domain:times, ticks:3}, y:{domain, grid:true, label:null},
          marks, className:'desk-plot'}))); grid.append(section);
      }
      node.replaceChildren(grid); return;
    }
    let options = {width, height: 210, marginLeft: 52, y: {grid: true, label: chart.label},
      color: {range: [navy, gold, grey]}, marks: []};
    if (chart.kind === "bars") {
      options.x = {type: "band", label: chart.x_label || "Pacific day"};
      options.marks = [Plot.barY(data, {x: "day", y: "value", fill: d => entityColor(d.key || d.series), title: d => `${d.series}: ${d.value}`})];
    } else if (chart.kind === "daily-dots") {
      options.x = {type: "band", label: chart.x_label || "Pacific day"};
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
    } else if (chart.kind === "ratings") {
      const valid = data.filter(d => d.value !== null), latest = new Map();
      valid.forEach(d => latest.set(`${d.division_id}:${d.player_id}`, d));
      const top = [...latest.values()].sort((a,b) => b.value-a.value).slice(0,3);
      const color = d => top.some(r => r.player_id === d.player_id) ? entityColor(d.player_id) : grey;
      options.x = timeAxis(data); options.marginRight = 80;
      options.y = {label:'Cumulative rating', grid:true};
      const mark = {x:d=>new Date(d.time*1000), y:'value', z:'series', stroke:color};
      options.marks = [...d3.group(data.filter(d=>d.low !== null), d=>d.player_id)].map(([id, rows]) =>
        Plot.areaY(rows, {...mark, y1:'low', y2:'high', fill:entityColor(id), fillOpacity:.14,
          ariaLabel:()=>`interval ${id}`}));
      options.marks.push(Plot.line(valid, mark), Plot.dot(valid, {...mark, r:2,
        title:d=>`${d.player}: ${d.value.toFixed(2)}`}),
        Plot.text(top, {...mark, text:d=>d.player.length>18 ? d.player.slice(0,17)+'…' : d.player, title:'player', textAnchor:'start', dx:5, fill:color, stroke:null}),
        Plot.dot(valid, Plot.pointer({...mark, fill:navy, r:4, maxRadius:1000})));
    } else if (chart.kind === "interval-cell") {
      options = {width:150, height:30, margin:4, x:{domain:chart.domain, axis:null}, y:{axis:null},
        marks:[Plot.ruleY(data, {y:()=>0, x1:'low', x2:'high', stroke:navy}),
          Plot.dot(data, {y:()=>0, x:'mu', fill:navy, r:3}), Plot.dot(data,{y:()=>0,x:'value',fill:gold,r:2})]};
    } else if (chart.kind === "spark") {
      options = {width:130,height:30,margin:3,x:{type:'time',axis:null},y:{axis:null},
        marks:[Plot.line(data,{x:d=>new Date(d.time*1000),y:'value',z:'series',stroke:navy}),
          Plot.dot(data,{x:d=>new Date(d.time*1000),y:'value',fill:navy,r:1.5})]};
    } else if (chart.kind === "amounts") {
      options.x = {label:chart.label || 'USD', grid:true}; options.y = {label:null, tickFormat:d=>d.length>20 ? d.slice(0,19)+'…' : d}; options.marginLeft = 130;
      options.height = Math.min(500,Math.max(160,data.length*23+45));
      options.marks = [Plot.barX(data,{x:'value',y:'label',fill:navy,title:d=>`${d.label}: ${d.value.toFixed(3)}`})];
      if (chart.reference !== null && chart.reference !== undefined)
        options.marks.push(Plot.ruleX([chart.reference],{stroke:gold,strokeDasharray:'4,3'}));
    } else if (chart.kind === "timing") {
      options.height = 100; options.y = {axis: null}; options.x = {label: "Minutes"};
      options.marks = [Plot.barX(data, {x: "value", y: () => "Representative game", fill: "part",
        title: d => `${d.part}: ${d.value.toFixed(2)} minutes`})];
    } else if (chart.kind === "matrix") {
      options.marginLeft = 120; options.marginBottom = 90;
      options.height = Math.max(260, new Set(data.map(d => d.a)).size * 38 + 100);
      const labels = new Map(data.map(d=>[d.a,d.player]));
      options.x = {label: "Opponent", tickRotate: -30, tickFormat:id=>labels.get(id)};
      options.y = {label: "Player", tickFormat:id=>labels.get(id)};
      options.color = {type: "linear", domain: [0, .5, 1], range: [gold, "#fffdf4", navy]};
      options.marks = [Plot.cell(data.filter(d => d.a !== d.b && d.share === null),
        {x: "b", y: "a", fill: "none", stroke: grey, strokeDasharray: "3,3"}),
        Plot.cell(data.filter(d => d.share !== null), {x: "b", y: "a", fill: "share", inset: 1,
          title: d => `${d.player} ahead of ${d.opponent}: ${(100 * d.share).toFixed(1)}%; ${d.n} games, ${d.ties} ties`}),
        Plot.text(data.filter(d => d.share !== null), {x: "b", y: "a",
          text: d => `${Math.round(d.share * 100)}%`, fill: d => d.share > .75 || d.share < .25 ? "#fffdf4" : navy})];
    }
    if (chart.markers?.length && ['ratings','dots','bars','daily-dots'].includes(chart.kind)) {
      const temporal = ['ratings','dots'].includes(chart.kind);
      const date = seconds => new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(seconds*1000));
      const markers = temporal ? chart.markers : chart.markers.filter(m=>data.some(d=>d.day===date(m.time)));
      options.marks.push(Plot.ruleX(markers,{x:d=>temporal ? new Date(d.time*1000) : date(d.time), stroke:grey,
        strokeDasharray:'2,3', title:'label'}));
    }
    const plot = Plot.plot({...options, className: "desk-plot"});
    // Plot injects a default stylesheet. Our external CSS supplies it under the page's strict CSP.
    clean(plot);
    if (chart.kind === 'ratings') {
      const selectBand = id => plot.querySelectorAll('[aria-label^="interval "]').forEach(group => {
        group.setAttribute('opacity', group.getAttribute('aria-label') === `interval ${id}` ? '1' : '0');
      });
      selectBand(chart.selected);
      plot.addEventListener('input',()=>selectBand(plot.value?.player_id || chart.selected));
      plot.addEventListener('pointerleave',()=>selectBand(chart.selected));
    }
    node.replaceChildren(plot);
  }
  function drawAll() {
    document.querySelectorAll('.plot').forEach(node => {
      if (node.dataset.drawn !== node.dataset.chart || Number(node.dataset.width) !== Math.max(260,node.clientWidth)) draw(node);
    });
  }
  window.deskCharts = {drawAll}; drawAll();
  let resize; window.addEventListener('resize',()=>{clearTimeout(resize);resize=setTimeout(drawAll,150);});
})();
