
const replay = !location.pathname.endsWith('/client/global');
// Match the pinned Classic renderer's country palette.
const colors = ['#efc4e4','#79afc6','#a4c499','#a08a75','#c48f85','#eaeaaf','#a87e9f'];
const svgNS = 'http://www.w3.org/2000/svg';
const $ = id => document.getElementById(id);
const frames = [];
let index = 0, playing = replay, timer, failed = false;
function svg(tag, attrs, title) {
  const el = document.createElementNS(svgNS, tag);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
  if (title) { const label = document.createElementNS(svgNS, 'title'); label.textContent = title; el.append(label); }
  return el;
}
function color(countryID) { return colors[(countryID || 0) - 1] || '#f6f2e6'; }
function phaseLabel(phase) { return phase === 'Diplomacy' ? 'Movement' : phase === 'Finished' ? 'Final' : phase; }
function countdown() {
  const frame = frames[index], game = frame?.game;
  const active = !failed && !frame?.ending && game?.gameOver === 'No' &&
    ['Diplomacy', 'Retreats', 'Builds'].includes(game.phase) && game.processStatus !== 'Paused' &&
    Number.isFinite(game.processTime) && game.processTime > 0;
  const seconds = active ? Math.max(0, Math.ceil(game.processTime - Date.now() / 1000)) : null;
  $('deadline').textContent = seconds === null ? '—' : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
function render() {
  const frame = frames[index];
  if (!frame) return;
  const game = frame.game;
  const board = game.territories.length ? game : frames.slice(0, index).reverse().find(x => x.game.territories.length)?.game || game;
  const previous = frames[index - 1]?.game;
  const territories = new Map(frame.variant.territories.map(t => [t.id, t]));
  const controlled = new Map(board.territories.map(t => [t.terrID, t.ownerCountryID]));
  const priorControl = new Map((previous?.territories || []).map(t => [t.terrID, t.ownerCountryID]));
  $('phase').textContent = `${game.turnText} · ${phaseLabel(game.phase)}`;
  if (!replay) countdown();
  if (game.phase === 'Pre-game') {
    $('outcome').textContent = 'Starting position — units appear in Spring 1901';
  } else if (game.gameOver === 'No') {
    $('outcome').textContent = `${board.units.length} units · ${frame.variant.supplyCenterCount} supply centers`;
  } else {
    $('outcome').textContent = `Game ${game.gameOver.toLowerCase()} · final positions shown`;
  }
  $('note').textContent = board === game ? 'Supply center rings show current control. A and F mark armies and fleets; arrows show moves since the previous recorded phase.' : 'The upstream engine omits board positions after a draw. This is the last recorded board; final country results appear in the Powers list.';
  const centers = $('centers'), moves = $('moves'), units = $('units');
  centers.replaceChildren(); moves.replaceChildren(); units.replaceChildren();
  for (const t of frame.variant.territories.filter(t => t.supply && t.coast !== 'Child')) {
    const owner = controlled.get(t.id);
    const changed = previous && priorControl.get(t.id) !== owner;
    centers.append(svg('circle', {cx:t.smallMapX,cy:t.smallMapY,r:6,fill:color(owner),class:`center${owner ? '' : ' neutral'}${changed ? ' changed' : ''}`}, `${t.name}: ${frame.variant.countries.find(c => c.countryID === owner)?.name || 'neutral'} supply center`));
  }
  const oldUnits = new Map((previous?.units || []).map(u => [u.id, u]));
  // Draw dislodged units last so the invading army cannot cover them.
  for (const u of [...board.units].sort((a, b) => Number(a.retreating) - Number(b.retreating))) {
    const t = territories.get(u.terrID);
    if (!t) continue;
    const old = oldUnits.get(u.id), from = old && territories.get(old.terrID);
    if (from && old.terrID !== u.terrID) moves.append(svg('line', {x1:from.smallMapX,y1:from.smallMapY,x2:t.smallMapX,y2:t.smallMapY,class:'move'}, `${u.type} moved from ${from.name} to ${t.name}`));
    const group = svg('g', u.retreating ? {transform:'translate(10,-10)', opacity:0.8} : {}, `${frame.variant.countries.find(c => c.countryID === u.countryID)?.name || 'Unknown'} ${u.type} at ${t.name}${u.retreating ? ' (retreating)' : ''}`);
    group.append(svg('rect', {x:t.smallMapX-7,y:t.smallMapY-7,width:14,height:14,rx:4,fill:color(u.countryID),class:'unit'}));
    const text = svg('text', {x:t.smallMapX,y:t.smallMapY+1,class:'unit-label'}); text.textContent = u.type === 'Fleet' ? 'F' : 'A'; group.append(text);
    units.append(group);
  }
  const powers = $('powers'); powers.replaceChildren();
  for (const country of frame.variant.countries) {
    const member = game.members.find(m => m.countryID === country.countryID);
    const row = document.createElement('div'); row.className = 'power';
    const dot = document.createElement('span'); dot.className = 'swatch'; dot.style.background = color(country.countryID);
    const name = document.createElement('span'); name.textContent = country.name;
    const status = document.createElement('small'); status.textContent = member?.status || 'Playing'; name.append(status);
    const count = document.createElement('span'); count.className = 'count'; count.textContent = `${member?.supplyCenterNo ?? 0} SC · ${member?.unitNo ?? 0} units`;
    row.append(dot, name, count); powers.append(row);
  }
  renderHistory(frame);
  $('counter').textContent = `Phase ${index + 1} of ${frames.length}`;
  for (const [i, button] of [...$('timeline').children].entries()) {
    button.classList.toggle('active', i === index);
    button.setAttribute('aria-current', i === index ? 'step' : 'false');
  }
}
function show(i) {
  index = Math.max(0, Math.min(i, frames.length - 1));
  try { render(); } catch { fail('Unsupported or corrupt replay frame'); }
}
function advance() {
  if (index + 1 < frames.length) show(index + 1);
  else if ($('loop').checked) show(0);
  else { playing = false; schedule(); }
}
function schedule() { clearInterval(timer); if (playing && frames.length > 1) timer = setInterval(advance, Number($('speed').value)); $('play').textContent = playing ? 'Pause' : 'Play'; }
$('previous').onclick = () => { playing = false; schedule(); show(index - 1); };
$('next').onclick = () => { playing = false; schedule(); show(index + 1); };
$('play').onclick = () => { playing = !playing; schedule(); };
$('speed').onchange = schedule;
function country(frame, id) {
  return frame.variant.countries.find(c => c.countryID === id)?.name || 'Public';
}
function renderOrders(frame, phase) {
  const names = new Map(frame.variant.territories.map(t => [t.id, t.name]));
  $('orders').replaceChildren();
  for (const order of phase?.orders || []) {
    const row = document.createElement('li');
    const places = [order.terrID, order.fromTerrID, order.toTerrID].filter(Boolean).map(id => names.get(id)).join(' → ');
    row.textContent = `${country(frame, order.countryID)}: ${order.unitType || ''} ${places} · ${order.type}${order.viaConvoy ? ' via convoy' : ''}${order.dislodged ? ' · dislodged' : ''}${order.success ? ' · succeeded' : ''}`;
    $('orders').append(row);
  }
  $('history-empty').textContent = phase ? '' : 'No adjudicated orders yet.';
}
function renderHistory(frame) {
  const phases = frame.history?.phases || [];
  const select = $('history-phase');
  select.replaceChildren();
  phases.forEach((phase, i) => {
    const option = document.createElement('option');
    option.value = i; option.textContent = `${phase.turnText} · ${phaseLabel(phase.phase)}`;
    select.append(option);
  });
  if (!phases.length) {
    const option = document.createElement('option');
    option.textContent = 'No completed phases';
    select.append(option);
  }
  if (phases.length) select.value = phases.length - 1;
  select.disabled = !phases.length;
  select.onchange = () => renderOrders(frame, phases[select.value]);
  renderOrders(frame, phases.at(-1));
  $('native-map').hidden = !frame.map;
  if (frame.map) {
    const label = frame.map.turn < 0 ? 'Opening positions' : `${frame.map.turn % 2 ? 'Autumn' : 'Spring'}, ${1901 + Math.floor(frame.map.turn / 2)}`;
    $('map-caption').textContent = `${label} · upstream adjudication map`;
    $('season-map').src = frame.map.png;
  } else $('season-map').removeAttribute('src');
  $('press').replaceChildren();
  for (const message of frame.messages?.messages || []) {
    const row = document.createElement('p');
    // Text only: upstream messages may contain HTML or player-supplied markup.
    row.textContent = `${country(frame, message.fromCountryID)}: ${message.message}`;
    $('press').append(row);
  }
  if (!$('press').children.length) $('press').textContent = 'No public press.';
  if (frame.ending) {
    const reason = {end_year: 'Year limit reached', episode_timeout: 'Time limit reached'}[frame.ending.reason];
    $('outcome').textContent = `Game ${frame.ending.outcome}${reason ? ' · ' + reason : ''}`;
  }
}
function notify(type, detail = {}) {
  if (parent !== window) parent.postMessage({src: 'coworld-replay', type, ...detail}, '*');
}
function fail(message) {
  failed = true;
  playing = false; schedule();
  $('connection').textContent = message;
  $('connection').setAttribute('role', 'alert');
  notify('error', {message});
}
function validate(data) {
  if (!Array.isArray(data) || !data.length || data.some(frame =>
    !frame?.game || !Array.isArray(frame.game.units) || !Array.isArray(frame.game.territories) ||
    !Array.isArray(frame.game.members) || !Array.isArray(frame.variant?.territories) ||
    !Array.isArray(frame.variant?.countries) || !Array.isArray(frame.history?.phases) ||
    !Array.isArray(frame.messages?.messages) ||
    (frame.map && !/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(frame.map.png)))) {
    throw new Error('Unsupported or corrupt replay');
  }
}
function timeline() {
  $('timeline').replaceChildren();
  frames.forEach((frame, i) => {
    const button = document.createElement('button');
    button.textContent = `${frame.game.turnText} · ${phaseLabel(frame.game.phase)}`;
    button.onclick = () => { playing = false; schedule(); show(i); };
    $('timeline').append(button);
  });
}
$('season-map').onerror = () => fail('Replay map image is corrupt');
const background = new Image();
background.src = 'smallmap.png';
$('background').setAttribute('href', background.src);
notify('loading');
// fetch/decompression and image decoding are asynchronous browser APIs. Readiness
// uses a task boundary (not animation frames, which offscreen iframes may suspend).
async function start() {
  await background.decode();
  if (replay) {
    const replayURL = new URLSearchParams(location.hash.slice(1)).get('replay') || new URLSearchParams(location.search).get('replay');
    if (!replayURL) throw new Error('Missing replay URL');
    notify('phase', {phase: 'replay_fetch_start'});
    const response = await fetch(replayURL);
    if (!response.ok) throw new Error(`Replay download failed (${response.status})`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    const compression = bytes[0] === 0x1f && bytes[1] === 0x8b ? 'gzip' :
      (bytes[0] & 15) === 8 && (bytes[0] >> 4) <= 7 && ((bytes[0] << 8) + bytes[1]) % 31 === 0 ? 'deflate' : null;
    notify('phase', {phase: 'replay_fetch_end', bytes: bytes.length, compressed: !!compression});
    const text = compression ? await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream(compression))).text() : new TextDecoder().decode(bytes);
    const data = JSON.parse(text);
    validate(data);
    frames.push(...data);
    notify('phase', {phase: 'replay_parsed'});
    timeline(); show(0);
    if (frames[0].map) await $('season-map').decode();
    setTimeout(() => { if (!failed) { notify('ready'); schedule(); } }, 0);
    if (!failed) $('connection').textContent = 'Recorded match';
  } else {
    document.querySelector('.controls').hidden = true;
    $('live-deadline').hidden = false;
    countdown();
    setInterval(countdown, 1000);
    const address = new URL(new URLSearchParams(location.search).get('address') || '../global', location.href);
    address.protocol = address.protocol === 'https:' || address.protocol === 'wss:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(address);
    ws.onmessage = event => {
      try {
        const frame = JSON.parse(event.data);
        validate([frame]);
        if (!frames.length || JSON.stringify(frames.at(-1).lifecycle) !== JSON.stringify(frame.lifecycle)) frames.push(frame);
        else frames[frames.length - 1] = frame;
        show(frames.length - 1);
        $('connection').textContent = frame.ending ? 'Match finished' : 'Live match · read only';
      } catch { fail('Public game state unavailable'); }
    };
    ws.onerror = () => fail('Unable to connect to the public game');
    ws.onclose = () => {
      if (!frames.at(-1)?.ending) fail('Disconnected from the public game. Reload to reconnect.');
    };
  }
}
start().catch(error => fail(error instanceof SyntaxError ? 'Unsupported or corrupt replay' : error.message));
