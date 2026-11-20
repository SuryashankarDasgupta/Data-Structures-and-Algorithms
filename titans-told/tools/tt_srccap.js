// Titans Told genuine-source capture (browser half of tt_sources.py; run by it, one job per call).
// Opens the real page in Chromium, highlights the exact quoted line on the page (fails if the line is not there),
// adds a SOURCE label, then saves a still (png) or a 4-second scroll-to-quote screen recording (webm).
// usage: node tt_srccap.js '<json job>'   job = {url, quote, mode: "still"|"scroll", out_png, out_dir, label_date}
// prints one JSON line: {ok, reason, final_url, title, host, video, anim_start_ms}
const { chromium } = require('playwright');

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';

(async () => {
  const job = JSON.parse(process.argv[2]);
  const out = { ok: false, reason: '', final_url: '', title: '', host: '', video: '', anim_start_ms: 0 };
  const browser = await chromium.launch();
  const scroll = job.mode === 'scroll';
  const ctxOpts = scroll
    ? { viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, userAgent: UA,
        recordVideo: { dir: job.out_dir, size: { width: 1920, height: 1080 } } }
    : { viewport: { width: 1600, height: 900 }, deviceScaleFactor: 2, userAgent: UA };
  const ctx = await browser.newContext(ctxOpts);
  const page = await ctx.newPage();
  const t0 = Date.now();
  try {
    const resp = await page.goto(job.url, { waitUntil: 'domcontentloaded', timeout: 45000 });
    if (resp && resp.status() >= 400) throw new Error('HTTP ' + resp.status());
    await page.waitForTimeout(2500);
    // consent / cookie buttons (main page and frames)
    const btn = /^\s*(accept|accept all|accept cookies|agree|i agree|got it|ok|okay|allow all|continue|close)\s*$/i;
    for (const f of page.frames()) {
      try {
        const els = await f.$$('button, a[role=button], [role=button]');
        for (const e of els) {
          const tx = ((await e.innerText().catch(() => '')) || '').trim();
          if (btn.test(tx) && await e.isVisible().catch(() => false)) { await e.click({ timeout: 1500 }).catch(() => {}); }
        }
      } catch (e) {}
    }
    await page.waitForTimeout(800);
    out.final_url = page.url();
    out.title = (await page.title()) || '';
    if (/page not found|^404|404 not found|error 404/i.test(out.title)) throw new Error('page not found (' + out.title.slice(0, 60) + ')');
    const res = await page.evaluate(([quote, date, finalUrl]) => {
      // hide overlays: Wayback toolbar, fixed banners about cookies/subscriptions/sign-in
      const wm = document.getElementById('wm-ipp-base'); if (wm) wm.remove();
      for (const el of document.querySelectorAll('body *')) {
        const cs = getComputedStyle(el);
        if ((cs.position === 'fixed' || cs.position === 'sticky') && el.offsetHeight > 40) {
          const t = (el.innerText || '').toLowerCase();
          if (/cookie|consent|privacy|subscribe|sign in|log in|newsletter|notification|advertis/.test(t) || cs.position === 'fixed') el.style.display = 'none';
        }
      }
      document.documentElement.style.overflow = 'auto'; document.body.style.overflow = 'auto';
      // text only: hide photos, videos and embeds (news photos belong to agencies such as Getty/AP; rule 9r.3)
      for (const el of document.querySelectorAll('img, picture, video, iframe, svg image, figure, [style*="background-image"]')) el.style.visibility = 'hidden';
      for (const el of document.querySelectorAll('figure, picture')) el.style.display = 'none';
      document.body.style.zoom = '1.25';
      const norm = s => s.replace(/[‘’‛]/g, "'").replace(/[“”]/g, '"').replace(/[–—]/g, '-')
        .replace(/ /g, ' ').replace(/\s+/g, ' ').toLowerCase();
      // map normalised text back to text nodes
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
        acceptNode: n => (n.parentElement && !/^(SCRIPT|STYLE|NOSCRIPT)$/.test(n.parentElement.tagName) && n.nodeValue.trim()) ? 1 : 2 });
      let full = '', map = [];   // map[i] = [node, offset] for each char of full
      let n;
      while ((n = walker.nextNode())) {
        const v = n.nodeValue;
        for (let i = 0; i < v.length; i++) {
          let c = norm(v[i]);
          if (c === ' ' && full.endsWith(' ')) continue;
          full += c; map.push([n, i]);
        }
        if (!full.endsWith(' ')) { full += ' '; map.push([n, v.length]); }
      }
      const q = norm(quote).trim();
      let tries = [q.slice(0, 160), q.split(' ').slice(0, 10).join(' '), q.split(' ').slice(0, 6).join(' ')];
      let at = -1, len = 0;
      for (const [k, t] of tries.entries()) { if (t.length >= (k === 0 ? 4 : 20)) { at = full.indexOf(t); if (at >= 0) { len = t.length; break; } } }
      const body = norm(document.body.innerText || '');
      if (at < 0) {
        const pay = /subscribe to (continue|read)|already a subscriber|create a free account|to continue reading|verify you are human|access denied/.test(body);
        return { found: false, pay, words: body.split(' ').length };
      }
      // wrap each text-node segment of the match in <mark>
      const segs = new Map();
      for (let i = at; i < at + len; i++) {
        const [node, off] = map[i]; if (off >= node.nodeValue.length) continue;
        const s = segs.get(node); if (s) { s[1] = off + 1; } else segs.set(node, [off, off + 1]);
      }
      const marks = [];
      for (const [node, [a, b]] of segs) {
        const r = document.createRange(); r.setStart(node, a); r.setEnd(node, b);
        const m = document.createElement('mark');
        m.style.cssText = 'color:inherit;background:linear-gradient(#FFE14D,#FFE14D) no-repeat;background-size:0% 100%;' +
          'transition:background-size .9s ease-out;padding:0 2px;border-radius:2px;box-shadow:none';
        try { r.surroundContents(m); marks.push(m); } catch (e) {}
      }
      // SOURCE label (bottom-left), never covering the quote
      let host = location.hostname.replace(/^www\./, '');
      let label = 'SOURCE  ' + host + '  ·  accessed ' + date;
      const wb = finalUrl.match(/web\.archive\.org\/web\/(\d{4})(\d{2})(\d{2})\d*\/(?:https?:\/\/)?(?:www\.)?([^\/]+)/);
      if (wb) {
        const mon = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+wb[2] - 1];
        host = wb[4]; label = 'SOURCE  ' + host + '  ·  archived ' + (+wb[3]) + ' ' + mon + ' ' + wb[1] + ' (Wayback Machine)';
      }
      const lab = document.createElement('div');
      lab.textContent = label;
      lab.style.cssText = 'position:fixed;left:28px;bottom:26px;z-index:2147483647;background:rgba(17,17,17,.88);color:#fff;' +
        'font:700 22px/1.2 Arial,Helvetica,sans-serif;letter-spacing:.5px;padding:12px 18px;border-radius:8px;' +
        'border-left:6px solid #FFE14D;max-width:70vw;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
      document.body.appendChild(lab);
      window.__ttMarks = marks;
      return { found: marks.length > 0, host };
    }, [job.quote, job.label_date, out.final_url]);
    out.host = res.host || '';
    if (!res.found) throw new Error(res.pay ? 'paywalled or blocked page' : 'quote not found on the page (' + (res.words || 0) + ' words)');
    if (scroll) {
      // start a screen above the quote, glide to it (2.4 s), sweep the highlighter (0.9 s), hold (0.7 s)
      await page.evaluate(() => {
        const m = window.__ttMarks[0]; const y = m.getBoundingClientRect().top + scrollY - innerHeight / 2;
        scrollTo(0, Math.max(0, y - innerHeight * 1.1));
      });
      await page.waitForTimeout(400);
      out.anim_start_ms = Date.now() - t0;
      await page.evaluate(() => new Promise(done => {
        const m = window.__ttMarks[0]; const y1 = Math.max(0, m.getBoundingClientRect().top + scrollY - innerHeight / 2);
        const y0 = scrollY, T = 2400, s = performance.now();
        const step = now => { const k = Math.min(1, (now - s) / T), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
          scrollTo(0, y0 + (y1 - y0) * e); if (k < 1) requestAnimationFrame(step); else done(); };
        requestAnimationFrame(step);
      }));
      await page.evaluate(() => window.__ttMarks.forEach(m => m.style.backgroundSize = '100% 100%'));
      await page.waitForTimeout(1700);
      await page.screenshot({ path: job.out_png });
    } else {
      await page.evaluate(() => { const m = window.__ttMarks[0]; m.scrollIntoView({ block: 'center' });
        window.__ttMarks.forEach(x => { x.style.transition = 'none'; x.style.backgroundSize = '100% 100%'; }); });
      await page.waitForTimeout(600);
      await page.screenshot({ path: job.out_png });
    }
    out.ok = true;
  } catch (e) {
    out.reason = String(e.message || e).slice(0, 200);
  }
  const vid = page.video();
  await ctx.close();
  if (vid) { try { out.video = await vid.path(); } catch (e) {} }
  await browser.close();
  console.log(JSON.stringify(out));
})();
