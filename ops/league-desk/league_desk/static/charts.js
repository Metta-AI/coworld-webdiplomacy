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
  function clean(plot) { plot.querySelectorAll("style").forEach(style => style.remove()); return plot; }
  function legend(labels,colors) {
    const result=document.createElement('p');result.className='chart-legend';
    labels.forEach((label,i)=>{
      const swatch=document.createElementNS('http://www.w3.org/2000/svg','svg');
      swatch.setAttribute('width','10');swatch.setAttribute('height','10');
      const square=document.createElementNS('http://www.w3.org/2000/svg','rect');
      square.setAttribute('width','10');square.setAttribute('height','10');square.setAttribute('fill',colors[i]);
      swatch.append(square);result.append(swatch,document.createTextNode(' '+label+' · '));
    });return result;
  }
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
          title:d=>`${d.day} · ${d.series}: $${d.value.toFixed(3)}`})];
        const budgets = chart.budgets || [];
        const dailyBudgets = [...new Set(data.map(d=>d.day))].map(day=>({day,value:budgets.find(d=>d.day===day)?.value}));
        options.marks.push(Plot.lineY(dailyBudgets,{x:'day',y:'value',stroke:navy,strokeDasharray:'4,3'}),
          Plot.tickY(budgets,{x:'day',y:'value',stroke:navy,title:d=>`Observed budget: $${d.value}`}));
        if (budgets.length) options.marks.push(Plot.text(budgets.slice(-1),{x:'day',y:'value',text:()=> 'Observed budget',
          textAnchor:'end',dy:-8,fill:navy}));
      } else options.marks = [Plot.lineY(data,{x:'day',y:'value',stroke:'series'}),
        Plot.dot(data,{x:'day',y:'value',stroke:'series',title:d=>`${d.day} · ${d.series}: $${d.value.toFixed(3)}`})];
    } else if (chart.kind === "policy-models") {
      const container=document.createElement('div'), models=[...new Set(data.map(d=>d.model))];
      const colors=models.map((_,i)=>[navy,'#7d97b6','#6e527d','#4576aa','#aaa49a','#6f8372','#ad925a','#524d63'][i%8]);
      container.append(legend(models,colors));
      const groups=[...d3.group(data,d=>d.policy).values()], max=d3.max(groups,rows=>d3.sum(rows,d=>d.value));
      for (let i=0;i<groups.length;i++) {
        const rows=groups[i],label=document.createElement('p'),last=i===groups.length-1;
        label.className='model-label';label.textContent=rows[0].label;
        container.append(label,clean(Plot.plot({width,height:last?50:28,marginLeft:40,marginTop:5,marginBottom:last?22:3,
          x:{domain:[0,max],label:null,ticks:4,axis:last?'bottom':null},y:{axis:null},
          color:{domain:models,range:colors},marks:[Plot.barX(rows,{x:'value',y:()=>rows[0].policy,fill:'model',
            title:d=>`${d.model}: $${d.value.toFixed(3)}`})],className:'desk-plot'})));
      }
      node.replaceChildren(container);return;
    } else if (chart.kind === "bars") {
      options.x = {type: "band", label: chart.x_label || "Pacific day"};
      const days = [...new Set(data.map(d=>d.day))];
      const inset = Math.max(0, ((width - 72) / Math.max(1,days.length) * .9 - 44) / 2);
      options.y.zero = true;
      options.marks = [Plot.barY(data, {x: "day", y: "value", insetLeft:inset, insetRight:inset,
        fill: d => chart.counts || !d.key ? navy : entityColor(d.key), title: d => `${d.series}: ${d.value}`})];
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
      options.y = {label:'Cumulative rating', grid:true};
      const mark = {x:d=>new Date(d.time*1000), y:'value', z:d=>d.plot_series || d.series, stroke:color};
      options.marks = [...d3.group(data, d=>d.player_id)].map(([id, rows]) =>
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
        marks:[Plot.line(data,{x:d=>new Date(d.time*1000),y:'value',z:d=>d.plot_series || d.series,stroke:navy}),
          Plot.dot(data,{x:d=>new Date(d.time*1000),y:'value',fill:navy,r:1.5})]};
    } else if (chart.kind === "power-scores") {
      const eligible = data.filter(d=>d.games>=chart.minimum);
      options.height = 275; options.marginLeft = 65;
      options.y = {domain:data.map(d=>d.power),label:null};
      options.x = {label:'Mean score · 95% interval',grid:true,
        domain:d3.extent([0,chart.reference,...eligible.flatMap(d=>[d.low,d.high,d.mean]).filter(v=>v!==null)])};
      options.marks = [Plot.ruleX([chart.reference],{stroke:grey,strokeDasharray:'4,3'}),
        Plot.ruleY(eligible.filter(d=>d.low!==null),{y:'power',x1:'low',x2:'high',stroke:navy}),
        Plot.dot(eligible,{y:'power',x:'mean',fill:navy,title:d=>`${d.power}: ${d.mean}; ${d.games} games`}),
        Plot.text(data.filter(d=>d.games<chart.minimum),{y:'power',x:()=>0,text:d=>`${d.games} games · fewer than five`,
          textAnchor:'start',fill:grey})];
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
    } else if (chart.kind === "amounts") {
      options.x = {label:chart.label || 'USD', grid:true}; options.y = {label:null, domain:chart.order, tickFormat:d=>d}; options.marginLeft = Math.min(width*.65,Math.max(130,...data.map(d=>d.label.length*6)));
      options.height = Math.min(500,Math.max(160,data.length*23+45));
      options.marks = [Plot.barX(data,{x:'value',y:'label',fill:navy,title:d=>`${d.label}: ${d.value.toFixed(3)}`})];
      if (data.some(d=>d.value_label)) {
        options.marginRight = 65;
        options.marks.push(Plot.text(data,{x:'value',y:'label',text:'value_label',textAnchor:'start',dx:5,fill:navy}));
      }
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
    if (chart.kind==='daily-spend' || chart.kind==='source-days')
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
