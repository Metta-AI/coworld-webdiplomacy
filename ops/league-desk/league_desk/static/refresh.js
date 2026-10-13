/* Cache fragments only. A refresh request signals the collector; it never waits for remote scans. */
(() => {
  const form = document.querySelector('#filters'), pause = document.querySelector('#pause');
  const status = document.querySelector('#refresh-status');
  let paused = sessionStorage.getItem('desk-paused') === 'true', timer, controller, sequence = 0;
  let received = Date.now();
  let watchUntil = 0, requestedGeneration = 0;
  const params = () => {
    const query = new URLSearchParams(new FormData(form));
    // An empty history temporarily removes the player control; preserve its URL selection for Back/Forward.
    if (!form.elements.player && new URLSearchParams(location.search).has('player'))
      query.set('player', new URLSearchParams(location.search).get('player'));
    return query;
  };
  const message = text => { status.textContent = text; };
  function schedule() {
    clearTimeout(timer);
    if ((!paused || watchUntil > Date.now()) && !document.hidden)
      timer = setTimeout(() => update(watchUntil > Date.now()), watchUntil > Date.now() ? 2000 : 60000);
  }
  function age() {
    document.querySelectorAll('[data-age]').forEach(node => {
      if (node.dataset.age === '') return;
      const seconds = Math.max(0, Math.floor(Number(node.dataset.age) + (Date.now() - received) / 1000));
      node.textContent = seconds > 120 ? `${Math.round(seconds / 60)} min old` : `${seconds} s old`;
    });
    document.querySelectorAll('.panel').forEach(panel => {
      let stale = false;
      panel.querySelectorAll('[data-source]').forEach(source => {
        const value = source.querySelector('[data-age]').dataset.age;
        const expired = value !== '' && Number(value) + (Date.now()-received)/1000 > Number(source.dataset.threshold);
        source.classList.toggle('bad', source.dataset.error === 'true' || expired);
        stale ||= source.classList.contains('bad');
      });
      const label = panel.querySelector('.panel-age');
      if (label) { label.classList.toggle('bad', stale); label.querySelector('[data-stale-status]').textContent = stale ? ' · stale or failed' : ''; }
    });
  }
  function swap(html) {
    const next = new DOMParser().parseFromString(html, 'text/html');
    const current = document.querySelector('#desk-content'), incoming = next.querySelector('#desk-content');
    const focus = document.activeElement.id, scroll = [window.scrollX, window.scrollY];
    incoming.querySelectorAll('[data-swap]').forEach(replacement => {
      const old = [...current.querySelectorAll('[data-swap]')].find(n => n.dataset.swap === replacement.dataset.swap);
      if (!old) return;
      const opened = [...old.querySelectorAll('details')].map(n => n.open);
      const scrolled = [...old.querySelectorAll('.table-scroll')].map(n => [n.scrollLeft, n.scrollTop]);
      const charts = [...old.querySelectorAll('.plot')];
      replacement.querySelectorAll('.plot').forEach((node, i) => {
        if (charts[i] && charts[i].dataset.chart === node.dataset.chart) node.replaceWith(charts[i]);
      });
      replacement.querySelectorAll('details').forEach((node, i) => { node.open = opened[i] ?? node.open; });
      old.replaceChildren(...replacement.childNodes);
      old.querySelectorAll('.table-scroll').forEach((node, i) => {
        if (scrolled[i]) { node.scrollLeft = scrolled[i][0]; node.scrollTop = scrolled[i][1]; }
      });
    });
    current.dataset.generation = incoming.dataset.generation;
    current.dataset.rendered = incoming.dataset.rendered;
    received = Date.now();
    const options = next.querySelector('#version-options');
    if (options) {
      const selected = form.elements.version.value;
      form.elements.version.replaceChildren(...options.content.cloneNode(true).childNodes);
      form.elements.version.value = selected;
    }
    window.deskCharts.drawAll();
    if (focus) document.getElementById(focus)?.focus({preventScroll: true});
    window.scrollTo(...scroll);
    if (watchUntil && Number(incoming.dataset.generation) > requestedGeneration) {
      watchUntil = 0; message('Collector updated the cache; slow groups keep their deadlines.');
    } else if (watchUntil > Date.now()) message('Collector requested; waiting for a cache update.');
    else if (watchUntil) { watchUntil = 0; message('No collector update observed yet; cached data retained.'); }
    else message(paused ? 'Paused' : 'Automatic refresh every 60 s');
  }
  function update(manual = false) {
    if (document.hidden || (!manual && paused)) return;
    clearTimeout(timer); controller?.abort(); controller = new AbortController();
    const id = ++sequence, signal = controller.signal;
    return fetch(`/fragments?${params()}`, {signal, cache: 'no-store'})
      .then(response => { if (!response.ok) throw new Error('Cache refresh failed'); return response.text(); })
      .then(html => { if (id === sequence) swap(html); })
      .catch(error => { if (error.name !== 'AbortError' && id === sequence) message('Refresh failed; last contents retained.'); })
      .finally(() => { if (id === sequence) schedule(); });
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('button[data-alert]');
    if (!button) return;
    button.disabled = true;
    fetch(`/alerts/${button.dataset.alert}?dismissed=${button.dataset.dismiss}`, {method: 'POST'})
      .then(response => { if (!response.ok) throw new Error('Alert change failed'); return update(true); })
      .catch(() => { button.disabled = false; message('Alert change failed; try again.'); });
  });
  function navigate() {
    history.pushState(null, '', `/?${params()}`); watchUntil = 0; update(true);
  }
  document.addEventListener('change', event => { if (event.target.form === form) navigate(); });
  form.addEventListener('submit', event => {
    event.preventDefault();
    requestedGeneration = Number(document.querySelector('#desk-content').dataset.generation);
    fetch('/refresh', {method: 'POST', headers: {'X-Requested-With': 'LeagueDesk'}})
      .then(response => { if (!response.ok) throw new Error('Refresh not queued');
        watchUntil = Date.now() + 60000; return update(true); })
      .catch(() => message('Collector request failed; last contents retained.'));
  });
  function pauseState() { pause.setAttribute('aria-pressed', String(paused)); pause.textContent = paused ? 'Resume' : 'Pause'; }
  pause.addEventListener('click', () => {
    paused = !paused; sessionStorage.setItem('desk-paused', String(paused)); pauseState();
    controller?.abort(); ++sequence; clearTimeout(timer);
    message(paused ? 'Paused; ages continue to advance.' : 'Resuming');
    if (!paused) update();
  });
  document.addEventListener('visibilitychange', () => {
    controller?.abort(); ++sequence; clearTimeout(timer);
    if (!document.hidden && !paused) update();
  });
  window.addEventListener('popstate', () => {
    const query = new URLSearchParams(location.search);
    for (const [key, fallback] of [['league','press'], ['range','7d'], ['version','all'], ['player','']]) {
      if (form.elements[key]) form.elements[key].value = query.get(key) || fallback;
    }
    update(true);
  });
  pauseState(); if (paused) message('Paused');
  setInterval(age, 1000); schedule();
})();
