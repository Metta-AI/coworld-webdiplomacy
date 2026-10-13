"""Run against browser_fixture.py on localhost:8661; requires project-local Playwright."""
import time

from playwright.sync_api import sync_playwright


def wait(page, expression, arg=None):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if page.evaluate(expression, arg):
            return
        time.sleep(.02)
    raise AssertionError("Browser condition timed out: " + expression)


BASE = "http://127.0.0.1:8661"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors, external, fragments = [], [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: external.append(request.url) if not request.url.startswith(BASE) else None)
    page.on("request", lambda request: fragments.append(request.url) if "/fragments?" in request.url else None)
    page.clock.install()
    assert page.goto(BASE).status == 200
    page.evaluate("document.fonts.ready")
    assert page.evaluate('document.fonts.check(\'700 12px "Merriweather"\')')
    assert page.locator('.panel').count() == 24
    assert page.locator('.plot:empty').count() == 0
    ratings = page.locator('.panel[data-swap="MMR over time"]')
    assert ratings.locator('g[aria-label="line"] path').first.get_attribute('d').count('L') >= 2
    assert page.locator('.multiples section').count() == 2
    assert page.locator('.cell svg').count() == 4
    assert page.locator('.panel[data-swap="Head to head"] .plot text').filter(has_text='100%').count() == 1
    assert 'History starts at first run' in ratings.inner_text()
    page.select_option('#player', 'Ada')
    wait(page, 'document.querySelector(\'[aria-label="interval Ada"]\')?.getAttribute("opacity")==="1"')
    target = ratings.locator('g[aria-label="dot"] circle').filter(has_text='Bert').first
    target.hover(force=True)
    wait(page, 'document.querySelector(\'[aria-label="interval Bert"]\')?.getAttribute("opacity")==="1"')
    page.locator('#pause').hover()
    wait(page, 'document.querySelector(\'[aria-label="interval Ada"]\')?.getAttribute("opacity")==="1"')
    page.evaluate('window.originalMain=document.querySelector("main")')
    ratings.locator('details').evaluate('(e)=>e.open=true')
    page.evaluate('window.scrollTo(0,700)')
    previous = page.locator('#desk-content').get_attribute('data-rendered')
    page.clock.fast_forward(60001)
    wait(page, '(old)=>document.querySelector("#desk-content").dataset.rendered!==old', arg=previous)
    assert page.evaluate('window.originalMain===document.querySelector("main")')
    assert ratings.locator('details').get_attribute('open') is not None
    assert abs(page.evaluate('window.scrollY') - 700) < 3
    page.get_by_role('button', name='Pause', exact=True).click()
    count = len(fragments)
    before = page.locator('[data-age]').first.inner_text()
    page.clock.fast_forward(120001)
    assert len(fragments) == count
    assert before != page.locator('[data-age]').first.inner_text()
    page.reload()
    assert page.get_by_role('button', name='Resume', exact=True).get_attribute('aria-pressed') == 'true'
    page.get_by_role('button', name='Resume', exact=True).click()
    wait(page, 'document.querySelector("#refresh-status").textContent.includes("Automatic")')
    page.evaluate('''window.testHidden=true;
      Object.defineProperty(document,'hidden',{configurable:true,get:()=>window.testHidden});
                    document.dispatchEvent(new Event('visibilitychange'));''')
    count = len(fragments)
    page.clock.fast_forward(120001)
    assert len(fragments) == count
    page.evaluate("window.testHidden=false;document.dispatchEvent(new Event('visibilitychange'))")
    wait(page, 'document.querySelector("#refresh-status").textContent.includes("Automatic")')
    assert len(fragments) > count
    page.select_option('#range', '24h')
    wait(page, 'document.querySelector(\'[data-swap="scope"]\').textContent.includes("24 hours")')
    page.select_option('#version', 'cow_old')
    wait(page, 'document.querySelector(\'[data-swap="scope"]\').textContent.includes("9.9.0")')
    assert 'range=24h' in page.url and 'version=cow_old' in page.url
    page.go_back()
    wait(page, 'document.querySelector("#version").value==="all"')
    wait(page, 'document.querySelector(\'[data-swap="scope"]\').textContent.includes("all versions")')
    assert page.locator('#player').input_value() == 'Ada'
    # Deliver an old selection late; it must not replace the new selection.
    page.evaluate('''window.realFetch=window.fetch; window.fetch=(url,options)=> {
      if(String(url).includes('range=30d')) return realFetch(url,options).then(
        r=>new Promise(resolve=>setTimeout(()=>resolve(r),500)));
      return realFetch(url,options);
    };''')
    page.select_option('#range', '30d')
    page.select_option('#range', '7d')
    page.clock.fast_forward(1000)
    wait(page, 'document.querySelector(\'[data-swap="scope"]\').textContent.includes("7 days")')
    page.clock.fast_forward(1000)
    assert '7 days' in page.locator('[data-swap="scope"]').inner_text()
    page.evaluate('window.fetch=window.realFetch')
    old = page.locator('.panel[data-swap="Competing players"] .reading').inner_text()
    page.route('**/fragments?**', lambda route: route.fulfill(status=503, body='unavailable'), times=1)
    page.clock.fast_forward(60001)
    wait(page, 'document.querySelector("#refresh-status").textContent.includes("failed")')
    assert page.locator('.panel[data-swap="Competing players"] .reading').inner_text() == old
    with page.expect_response(lambda r: r.url.endswith('/refresh') and r.status == 202):
        page.get_by_role('button', name='Refresh', exact=True).click()
    wait(page, 'document.querySelector("#refresh-status").textContent.includes("waiting")')
    page.set_viewport_size({"width": 390, "height": 844})
    page.clock.fast_forward(200)
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
    assert not errors, errors
    assert not external, external
    browser.close()
print('Browser acceptance passed: local fonts/charts, lines/bands/cells, refresh, pause, visibility, '
      'filters, history, races, errors, narrow layout.')
