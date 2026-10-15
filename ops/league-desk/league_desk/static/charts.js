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
    return [navy, "#4576aa", "#5573a0", "#6e527d", "#706387", "#527878"][hash % 6];
  }
  // Validated categorical order (dataviz reference palette, checked against the paper surface).
  const series = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
  function seriesColors(names) { return names.map((_, i) => series[i % series.length]); }
  // Hover card for one stacked segment: the whole stack for that x value, as a pie and a table.
  function breakdown(data, x, format, color) {
    const stacks = d3.group(data, d => d[x]);
    return d => {
      const rows = [...stacks.get(d[x])].sort((a, b) => b.value - a.value), total = d3.sum(rows, r => r.value);
      return deskTip.encode({title: String(d[x]), pie: true, totalDisplay: format(total),
        rows: rows.map(r => ({label: r.series, value: r.value, display: format(r.value), color: color(r), active: r === d}))});
    };
  }
  function clean(plot) { plot.querySelectorAll("style").forEach(style => style.remove()); return plot; }
  function legend(labels,colors) {
    const result=document.createElement('p');result.className='chart-legend';
    labels.forEach((label,i)=>{
      const swatch=document.createElementNS('http://www.w3.org/2000/svg','svg');
      swatch.setAttribute('width','10');swatch.setAttribute('height','10');
      const square=document.createElementNS('http://www.w3.org/2000/svg','rect');
      square.setAttribute('width','10');square.setAttribute('height','10');square.setAttribute('fill',colors[i]);
      swatch.append(square);const item=document.createElement('span');
      item.append(swatch,document.createTextNode(' '+label));result.append(item);
    });return result;
  }
  function draw(node) { drawChart(node); deskTip.adopt(node); }
  function drawChart(node) {
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
        const marks = [Plot.areaY(rows, {x, y1:'low', y2:'high', z:d=>d.plot_series || d.series, fill:color, fillOpacity:.13}),
          Plot.line(rows, {x, y:'mu', z:d=>d.plot_series || d.series, stroke:color, strokeWidth:1}),
          Plot.line(rows, {x, y:'value', z:d=>d.plot_series || d.series, stroke:color, strokeWidth:2.5}),
          Plot.dot(rows, {x, y:'value', fill:color, r:2, title:d=>`${d.player}: MMR ${d.value}; μ ${d.mu}`}),
          Plot.ruleX(chart.markers || [],{x:d=>new Date(d.time*1000),stroke:grey,strokeDasharray:'2,3',title:'label'})];
        section.append(label, clean(Plot.plot({width:Math.max(230, Math.floor(width / Math.max(1, Math.floor(width/260))) - 16),
          height:170, marginLeft:45, x:{...timeAxis(data), domain:times, ticks:3}, y:{domain, grid:true, label:null},
          marks, className:'desk-plot'}))); grid.append(section);
      }
      node.replaceChildren(grid); return;
    }
    let options = {width, height: 210, marginLeft: 52, y: {grid: true, label: chart.label},
      color: {range: [navy, "#7d97b6", grey]}, marks: []};
    if (chart.kind === "daily-spend" || chart.kind === "source-days") {
      options.x = {type:'band',label:'Pacific day',tickFormat:d=>d.slice(5)};
      options.y.zero = true;
      options.color = {domain:chart.kind==='daily-spend'?['Compute','Estimated LLM']:['League rounds','Experience requests'],
        range:[navy,'#7d97b6']};
      if (chart.kind==='daily-spend') {
        options.marks = [Plot.barY(data,{x:'day',y:'value',fill:'series',
          title:breakdown(data,'day',v=>`$${v.toFixed(3)}`,r=>r.series==='Compute'?navy:'#7d97b6')})];
        const budgets = chart.budgets || [];
        const dailyBudgets = [...new Set(data.map(d=>d.day))].map(day=>({day,value:budgets.find(d=>d.day===day)?.value}));
        options.marks.push(Plot.lineY(dailyBudgets,{x:'day',y:'value',stroke:navy,strokeDasharray:'4,3'}),
          Plot.tickY(budgets,{x:'day',y:'value',stroke:navy,title:d=>`Observed budget: $${d.value}`}));
        if (budgets.length) options.marks.push(Plot.text(budgets.slice(-1),{x:'day',y:'value',text:()=> 'Observed budget',
          textAnchor:'end',dy:-8,fill:navy}));
      } else options.marks = [Plot.lineY(data,{x:'day',y:'value',stroke:'series'}),
        Plot.dot(data,{x:'day',y:'value',stroke:'series',title:d=>`${d.day} · ${d.series}: $${d.value.toFixed(3)}`})];
    } else if (chart.kind === "pie") {
      // Share of the whole: a donut in the fixed categorical order, with a legend carrying each value and share.
      const rows = data.filter(d => d.value > 0), total = d3.sum(rows, d => d.value);
      const colors = seriesColors(rows.map(d => d.label)), size = Math.min(220, width);
      const svg = d3.create('svg').attr('width', size).attr('height', size).attr('viewBox', [-size/2, -size/2, size, size])
        .attr('class', 'desk-plot').attr('role', 'img').attr('aria-label', chart.label);
      const arc = d3.arc().innerRadius(size * .27).outerRadius(size / 2 - 2).padAngle(.012);
      svg.selectAll('path').data(d3.pie().sort(null).value(d => d.value)(rows)).join('path')
        .attr('d', arc).attr('fill', (_, i) => colors[i]).attr('stroke', 'var(--bg)').attr('stroke-width', 2)
        .append('title').text(d => `${d.data.label}: $${d.data.value.toFixed(3)} (${(100*d.data.value/total).toFixed(1)}%)`);
      svg.append('text').attr('text-anchor', 'middle').attr('dy', '.35em').attr('fill', navy)
        .attr('font-weight', 600).text(`$${total.toFixed(2)}`);
      const container = document.createElement('div'); container.className = 'pie';
      const key = legend(rows.map(d => `${d.label} $${d.value.toFixed(2)} (${(100*d.value/total).toFixed(0)}%)`), colors);
      container.append(svg.node(), key); node.replaceChildren(container); return;
    } else if (chart.kind === "bars") {
      options.x = {type: "band", label: chart.x_label || "Pacific day"};
      const days = [...new Set(data.map(d=>d.day))];
      const inset = Math.max(0, ((width - 72) / Math.max(1,days.length) * .9 - 44) / 2);
      options.y.zero = true;
      const stacked = !chart.counts && data.some(d => d.key);
      // Eight hues at most: the largest seven series keep their own colour, the rest share "Other" (hover names them).
      const totals = d3.rollups(data, rows => d3.sum(rows, d => d.value), d => d.series).sort((a, b) => b[1] - a[1]);
      const named = totals.length > 8 ? totals.slice(0, 7).map(t => t[0]) : totals.map(t => t[0]);
      const group = d => named.includes(d.series) ? d.series : "Other";
      if (stacked) {
        const names = named.length < totals.length ? [...named, "Other"] : named;
        options.color = {domain: names, range: [...seriesColors(named), grey].slice(0, names.length)};
        options.legendNames = names;
      }
      options.marks = [Plot.barY(data, {x: "day", y: "value", insetLeft:inset, insetRight:inset,
        fill: stacked ? group : navy,
        title: stacked ? breakdown(data, "day", String, d => options.color.range[options.color.domain.indexOf(group(d))])
          : d => `${d.series}: ${d.value}`})];
      if (chart.counts && days.length <= 7) options.marks.push(Plot.text(
        d3.rollups(data, rows=>d3.sum(rows,d=>d.value), d=>d.day).map(([day,value])=>({day,value})),
        {x:'day',y:'value',text:d=>String(d.value),dy:-9,fill:navy}));
    } else if (chart.kind === "daily-dots") {
      options.y.domain = [0, d3.max(data, d=>Math.max(d.value,d.p90)) * 1.1];
      options.x = {type: "band", label: chart.x_label || "Pacific day"};
      options.marks = [Plot.dot(data, {x: "day", y: "value", stroke: "series",
        title: d => `${d.series}: median ${d.value.toFixed(2)}, p90 ${d.p90.toFixed(2)} min; n=${d.n}`}),
        Plot.tickY(data, {x: "day", y: "p90", stroke: "series"})];
    } else if (chart.kind === "dots") {
      options.x = timeAxis(data);
      options.y.domain = [0, Math.max(chart.reference || 0, d3.max(data,d=>Math.max(d.value,d.reference || 0))) * 1.15];
      options.marks = [Plot.dot(data, {x: d => new Date(d.time * 1000), y: "value", fill: navy,
        title: d => `${d.value.toFixed(2)} minutes`}), Plot.dot(data.filter(d => d.reference !== null),
        {x: d => new Date(d.time * 1000), y: "reference", symbol: "cross", stroke: navy})];
      if (chart.reference != null) options.marks.push(
        Plot.ruleY([chart.reference],{stroke:navy,strokeDasharray:'4,3'}),
        Plot.text([chart.reference],{y:d=>d,text:d=>`Current interval · ${d} min`,frameAnchor:'right',textAnchor:'end',dy:-8,fill:navy}));
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
      // Scale to the MMR lines, not the μ ± 3σ bands: the wide bands would squeeze the lines together.
      const [lo, hi] = d3.extent(valid, d => d.value), pad = Math.max(.5, (hi - lo) * .08);
      options.y = {label:'Cumulative rating', grid:true, domain:[lo - pad, hi + pad]};
      const mark = {x:d=>new Date(d.time*1000), y:'value', z:d=>d.plot_series || d.series, stroke:color};
      options.marks = [...d3.group(data, d=>d.player_id)].map(([id, rows]) =>
        Plot.areaY(rows, {...mark, y1:'low', y2:'high', fill:entityColor(id), fillOpacity:.14,
          ariaLabel:()=>`interval ${id}`, clip:true}));
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
        marks:[Plot.line(data,{x:d=>new Date(d.time*1000),y:'value',z:d=>d.plot_series || d.series,stroke:navy}),
          Plot.dot(data,{x:d=>new Date(d.time*1000),y:'value',fill:navy,r:1.5})]};
    } else if (chart.kind === "policy-power") {
      const labels = new Map(data.map(d=>[d.policy_id,d.policy]));
      options.height = Math.max(200,labels.size*32+70); options.marginLeft = Math.min(width*.45,Math.max(120,...[...labels.values()].map(s=>s.length*5.5)));
      options.x = {domain:[...new Set(data.map(d=>d.power))],label:'Power',tickFormat:d=>d.slice(0,3)};
      options.y = {domain:[...labels.keys()],label:null,tickFormat:id=>{const label=labels.get(id),limit=Math.floor((options.marginLeft-12)/6);
        return width<500 && label.length>limit?label.slice(0,limit-1)+'…':label}};
      const extent = Math.max(.01,...data.filter(d=>d.games>=chart.minimum).map(d=>Math.abs(d.mean)));
      options.color = {type:'linear',domain:[-extent,0,extent],range:[gold,'#fffdf4',navy]};
      options.marks = [Plot.cell(data.filter(d=>d.games<chart.minimum),{x:'power',y:'policy_id',fill:'none',stroke:grey,
        strokeDasharray:'3,3',inset:1,title:d=>`${d.policy}, ${d.power}: ${d.games} games; fewer than five`}),
        Plot.cell(data.filter(d=>d.games>=chart.minimum),{x:'power',y:'policy_id',fill:'mean',inset:1,
          title:d=>`${d.policy}, ${d.power}: ${d.mean}; ${d.games} games`}),
        Plot.text(data.filter(d=>d.games>=chart.minimum),{x:'power',y:'policy_id',text:d=>d.mean.toFixed(2),
          fill:d=>Math.abs(d.mean)>extent*.65?'#fffdf4':navy})];
    } else if (chart.kind === "seat-dots") {
      const labels = new Map(data.map(d=>[d.key,d.player]));
      options.height = Math.max(170, chart.order.length*32+65); options.marginLeft = 140; options.marginTop = 32;
      options.x = {label:chart.label,grid:true,domain:[0,Math.max(chart.reference || 0,d3.max(data,d=>d.value))*1.08]};
      options.y = {label:null,domain:chart.order,tickFormat:key=>labels.get(key)};
      options.marks = [Plot.dot(data,{x:'value',y:'key',stroke:navy,fill:navy,fillOpacity:.3,r:3,
        title:d=>`${d.player} · slot ${d.slot}: $${d.value.toFixed(3)}`})];
      if (chart.reference != null) options.marks.push(Plot.ruleX([chart.reference],{stroke:navy,strokeDasharray:'4,3'}),
        Plot.text([chart.reference],{x:d=>d,text:d=>`Current cap · $${d}`,frameAnchor:'top',textAnchor:'end',dx:-4,dy:-12,fill:navy}));
    } else if (chart.kind === "models") {
      const container = document.createElement('div');
      const sources = [...new Set(data.map(d=>d.source))];
      const colors = [navy,'#7d97b6','#b6c3d4'];
      const legend = document.createElement('p'); legend.className = 'note';
      legend.textContent = 'Estimated USD · ' + sources.map((source,i)=>`${source} (${['dark','medium','light'][i] || 'blue'} blue)`).join(' · ');
      container.append(legend);
      const max = d3.max(chart.order, model=>d3.sum(data.filter(d=>d.model===model),d=>d.value));
      for (const model of chart.order) {
        const label = document.createElement('p'); label.className = 'model-label'; label.textContent = model;
        const last = model === chart.order[chart.order.length-1];
        container.append(label,clean(Plot.plot({width,height:last?50:28,marginLeft:40,marginTop:5,marginBottom:last?22:3,
          x:{domain:[0,max],label:null,ticks:4,axis:last?'bottom':null},y:{axis:null},color:{domain:sources,range:colors},
          marks:[Plot.barX(data.filter(d=>d.model===model),{x:'value',y:()=>model,fill:'source',
            title:d=>`${d.source}: $${d.value.toFixed(3)}`})],className:'desk-plot'})));
      }
      node.replaceChildren(container); return;
    } else if (chart.kind === "instrument-rows") {
      const container=document.createElement('div'), max=Math.max(1,d3.max(data,d=>d.value)||0);
      for (let i=0;i<data.length;i++) {
        const row=data[i], label=document.createElement('p');label.className='model-label';label.textContent=row.label;
        const last=i===data.length-1;
        container.append(label,clean(Plot.plot({width,height:last?64:35,marginLeft:5,marginRight:55,
          marginTop:5,marginBottom:last?35:3,x:{domain:[0,max],label:last?chart.label:null,ticks:3,axis:last?'bottom':null},
          y:{axis:null},marks:[Plot.barX([row],{x:'value',y:'label',fill:navy}),
            Plot.text([row],{x:'value',y:'label',text:'value_label',dx:5,textAnchor:'start',fill:navy})]})));
      }
      node.replaceChildren(container);return;
    } else if (chart.kind === "amounts") {
      options.x = {label:chart.label || 'USD', grid:true}; options.y = {label:null, domain:chart.order, tickFormat:d=>d}; options.marginLeft = Math.min(width*.65,Math.max(130,...data.map(d=>d.label.length*6)));
      options.height = Math.min(500,Math.max(160,data.length*23+45));
      // Rows with a series stack into one bar per label; a value_label then sits at the end of the whole bar.
      const stacked = data.some(d=>d.series);
      if (stacked) {
        options.color = {domain:[...new Set(data.map(d=>d.series))]}; options.color.range = seriesColors(options.color.domain);
        options.legendNames = options.color.domain;
      }
      options.marks = [Plot.barX(data,{x:'value',y:'label',fill:stacked?'series':navy,
        title:d=>`${d.label}${stacked?` · ${d.series}`:''}: ${d.value.toFixed(3)}`})];
      if (data.some(d=>d.value_label)) {
        options.marginRight = 65;
        const ends = stacked ? d3.rollups(data, rows=>({value:d3.sum(rows,r=>r.value),
          value_label:rows.find(r=>r.value_label)?.value_label}), d=>d.label).map(([label,end])=>({label,...end})) : data;
        options.marks.push(Plot.text(ends.filter(d=>d.value_label),
          {x:'value',y:'label',text:'value_label',textAnchor:'start',dx:5,fill:navy}));
      }
      if (chart.reference !== null && chart.reference !== undefined)
        options.marks.push(Plot.ruleX([chart.reference],{stroke:gold,strokeDasharray:'4,3'}));
    } else if (chart.kind === "boxes") {
      // Precomputed five-number summaries: whisker rule, middle-half box, median tick, outlier dots.
      const tip = d => `${d.label} · ${d.n} games\nMedian ${d.median.toFixed(1)} min\nMiddle half ${d.q1.toFixed(1)}–${d.q3.toFixed(1)} min\nWhiskers ${d.low.toFixed(1)}–${d.high.toFixed(1)} min\n${d.outliers.length} outliers`;
      options.height = Math.max(110, data.length * 48 + 50); options.marginLeft = 110;
      options.y = {label: null, domain: data.map(d => d.label)};
      options.x = {label: chart.label, grid: true, zero: true};
      const outliers = data.flatMap(d => d.outliers.map(value => ({label: d.label, value})));
      options.marks = [Plot.ruleY(data, {y: 'label', x1: 'low', x2: 'high', stroke: navy}),
        Plot.tickX(data, {y: 'label', x: 'low', stroke: navy}), Plot.tickX(data, {y: 'label', x: 'high', stroke: navy}),
        Plot.barX(data, {y: 'label', x1: 'q1', x2: 'q3', fill: '#d9e1ec', stroke: navy, insetTop: 8, insetBottom: 8, title: tip}),
        Plot.tickX(data, {y: 'label', x: 'median', stroke: navy, strokeWidth: 3, insetTop: 8, insetBottom: 8, title: tip}),
        Plot.dot(outliers, {y: 'label', x: 'value', stroke: grey, r: 2.5, title: d => `${d.label}: ${d.value.toFixed(1)} min (outlier)`})];
    } else if (chart.kind === "timing") {
      options.height = 100; options.y = {axis: null}; options.x = {label: "Minutes"};
      options.marks = [Plot.barX(data, {x: "value", y: () => "Representative game", fill: "part",
        title: d => `${d.part}: ${d.value.toFixed(2)} minutes`})];
    } else if (chart.kind === "count-matrix") {
      // Games two players shared: one sequential hue, darker = more often paired.
      const labels = new Map(data.map(d => [d.a, d.player])), max = d3.max(data, d => d.n) || 1;
      const short = id => { const s = labels.get(id); return s.length > 14 ? s.slice(0, 13) + '…' : s; };
      options.marginLeft = 110; options.marginBottom = 90;
      options.height = Math.max(260, chart.order.length * 30 + 100);
      options.x = {label: null, domain: chart.order, tickRotate: -35, tickFormat: short};
      options.y = {label: null, domain: chart.order, tickFormat: short};
      options.color = {type: 'linear', domain: [0, max], range: ['#f3efe4', navy]};
      options.marks = [Plot.cell(data, {x: 'b', y: 'a', fill: 'n', inset: 1,
          title: d => `${d.player} with ${d.opponent}\n${d.n} games together\n${(100*d.n/d.own).toFixed(0)}% of ${d.player}'s ${d.own} games\n${(100*d.n/d.other).toFixed(0)}% of ${d.opponent}'s ${d.other} games`}),
        Plot.text(data, {x: 'b', y: 'a', text: d => String(d.n), fill: d => d.n > max * .55 ? '#fffdf4' : navy})];
    } else if (chart.kind === "paired-dots") {
      // One row per policy; each series (e.g. phase type) is a dot, so pairs read side by side.
      const names = [...new Set(data.map(d => d.series))], rows = [...new Set(data.map(d => d.label))];
      options.height = Math.max(120, rows.length * 26 + 60);
      options.marginLeft = Math.min(width * .5, Math.max(120, ...rows.map(r => r.length * 5.6)));
      options.y = {label: null, domain: rows};
      options.x = {label: chart.label, grid: true, domain: [0, Math.max(10, d3.max(data, d => d.value) * 1.1)]};
      options.color = {domain: names, range: seriesColors(names)}; options.legendNames = names;
      options.marks = [Plot.ruleY(rows, {stroke: '#ece6d8'}),
        Plot.dot(data, {x: 'value', y: 'label', fill: 'series', r: 5,
          title: d => `${d.label}\n${d.series}: ${d.value_label} of the phase\n${d.n} measured games`})];
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
    const stackLegend = Boolean(options.legendNames); delete options.legendNames;
    const plot = Plot.plot({...options, className: "desk-plot"});
    // Plot injects a default stylesheet. Our external CSS supplies it under the page's strict CSP.
    clean(plot);
    if (chart.kind === 'ratings') {
      const selectBand = id => plot.querySelectorAll('[aria-label^="interval "]').forEach(group => {
        group.setAttribute('opacity', group.getAttribute('aria-label') === `interval ${id}` ? '1' : '0');
      });
      selectBand(chart.selected);
      plot.addEventListener('input',()=>{
        selectBand(plot.value?.player_id || chart.selected);
        // The pointer tracks the nearest point anywhere over the plot; the chart's card follows it.
        const d = plot.value;
        plot.tip = d ? `${d.player}\nMMR ${d.value.toFixed(2)}${d.mu != null ? ` · μ ${d.mu.toFixed(2)}` : ""}\n${new Date(d.time*1000).toLocaleString('en-US',{timeZone:'America/Los_Angeles',dateStyle:'medium',timeStyle:'short'})} PT` : undefined;
      });
      plot.addEventListener('pointerleave',()=>selectBand(chart.selected));
    }
    node.replaceChildren(plot);
    if (chart.kind==='daily-spend' || chart.kind==='source-days' || stackLegend)
      node.prepend(legend(options.color.domain,options.color.range));
  }
  function drawAll() {
    document.querySelectorAll('.plot').forEach(node => {
      if (node.dataset.drawn !== node.dataset.chart || Number(node.dataset.width) !== Math.max(260,node.clientWidth)) draw(node);
    });
  }
  window.deskCharts = {drawAll}; drawAll();
  let resize; window.addEventListener('resize',()=>{clearTimeout(resize);resize=setTimeout(drawAll,150);});
})();
