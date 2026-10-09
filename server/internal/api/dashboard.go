// Dependency-free live view over /ws/alerts.
package api

import (
	"net/http"
	"os"

	"github.com/gin-gonic/gin"
)

// DashboardHandler serves the live alerts page.
func DashboardHandler() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Data(http.StatusOK, "text/html; charset=utf-8", []byte(dashboardHTML))
	}
}

// MountSnapshots exposes dir at /snapshots; the dir is created when missing
// so session thumbnails keep working and dashboard pictures never go dark.
func MountSnapshots(r *gin.Engine, dir string) {
	if dir == "" {
		return
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return
	}
	r.Static("/snapshots", dir)
}

const dashboardHTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#08111d">
<title>Drone Detect — Operations</title>
<style>
:root {
  color-scheme: dark;
  --bg: #080c12;
  --surface: #101720;
  --surface-raised: #151f2a;
  --line: #253241;
  --text: #e8eef5;
  --muted: #8292a3;
  --cyan: #52d5e8;
  --green: #65d6a3;
  --amber: #e8b96b;
  --red: #f1767d;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: radial-gradient(ellipse at 15% -30%, #142638 0, transparent 48%), var(--bg);
  color: var(--text);
  font: 14px/1.5 Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
}
.shell { max-width: 1600px; margin: 0 auto; padding: 25px clamp(16px, 3vw, 42px) 48px; }
.topbar { display: flex; justify-content: space-between; align-items: center; gap: 18px; padding-bottom: 22px; border-bottom: 1px solid #ffffff0c; }
.brand { display: flex; align-items: center; gap: 12px; }
.brand-mark { display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid #52d5e833; border-radius: 9px; background: #52d5e812; color: var(--cyan); font-size: 15px; font-weight: 800; }
.eyebrow { margin: 0 0 4px; color: var(--muted); font-size: 10px; font-weight: 750; letter-spacing: .16em; text-transform: uppercase; }
h1 { margin: 0; font-size: clamp(21px, 2.5vw, 28px); line-height: 1.15; letter-spacing: -.035em; }
.subtitle { margin: 5px 0 0; color: var(--muted); font-size: 12px; }
.top-actions { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; justify-content: flex-end; }
.live-pill, .count-pill { display: inline-flex; align-items: center; gap: 8px; min-height: 32px; padding: 0 11px; border: 1px solid var(--line); border-radius: 8px; background: #111923; color: #c7d5e2; font-size: 11px; font-weight: 650; }
.live-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--amber); box-shadow: 0 0 10px currentColor; }
.live-pill.on { color: var(--green); border-color: #65d6a344; }
.live-pill.on .live-dot { background: var(--green); }
.live-pill.off { color: var(--amber); }
.count-pill { color: var(--cyan); }
.workspace { display: grid; grid-template-columns: minmax(0, 1fr) 310px; gap: 16px; margin-top: 18px; align-items: start; }
.main-column { min-width: 0; }
.viewer, .panel { overflow: hidden; border: 1px solid var(--line); border-radius: 11px; background: linear-gradient(145deg, #121b26, #0c121a); box-shadow: 0 16px 42px #0004; }
.viewer-head, .panel-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; min-height: 49px; padding: 0 15px; border-bottom: 1px solid #ffffff0c; }
.viewer-title { display: flex; align-items: center; gap: 9px; font-size: 12px; font-weight: 700; }
.stream-mark { width: 8px; height: 8px; border: 1px solid var(--cyan); border-radius: 2px; transform: rotate(45deg); }
.viewer-meta, .panel-note { color: var(--muted); font: 10px ui-monospace, Consolas, monospace; }
.frame { position: relative; display: grid; min-height: 420px; max-height: 68vh; aspect-ratio: 16 / 9; place-items: center; overflow: hidden; background: radial-gradient(ellipse at center, #172431 0, #0b1119 72%); }
.frame::before { position: absolute; inset: 0; background-image: linear-gradient(#ffffff07 1px, transparent 1px), linear-gradient(90deg, #ffffff07 1px, transparent 1px); background-size: 32px 32px; content: ""; mask-image: linear-gradient(transparent, #000 20%, #000 80%, transparent); }
.frame img { position: relative; z-index: 1; display: block; width: 100%; height: 100%; object-fit: contain; }
.frame img[hidden] { display: none; }
.frame-empty { position: absolute; z-index: 2; display: grid; max-width: 320px; gap: 8px; padding: 24px; color: var(--muted); text-align: center; }
.frame-empty strong { color: #dbe7f2; font-size: 14px; }
.frame-empty span { font-size: 12px; }
.frame-reticle { position: absolute; z-index: 2; inset: 18px; pointer-events: none; background: linear-gradient(var(--cyan),var(--cyan)) left top / 22px 1px no-repeat, linear-gradient(var(--cyan),var(--cyan)) left top / 1px 22px no-repeat, linear-gradient(var(--cyan),var(--cyan)) right top / 22px 1px no-repeat, linear-gradient(var(--cyan),var(--cyan)) right top / 1px 22px no-repeat, linear-gradient(var(--cyan),var(--cyan)) left bottom / 22px 1px no-repeat, linear-gradient(var(--cyan),var(--cyan)) left bottom / 1px 22px no-repeat, linear-gradient(var(--cyan),var(--cyan)) right bottom / 22px 1px no-repeat, linear-gradient(var(--cyan),var(--cyan)) right bottom / 1px 22px no-repeat; opacity: .55; }
.viewer-foot { display: flex; justify-content: space-between; gap: 12px; padding: 10px 15px; border-top: 1px solid #ffffff0c; color: var(--muted); font: 10px ui-monospace, Consolas, monospace; }
.inspector { display: grid; gap: 12px; }
.panel { padding-bottom: 14px; }
.panel-head { min-height: 45px; margin-bottom: 13px; }
.panel-head h2 { margin: 0; font-size: 11px; font-weight: 750; letter-spacing: .12em; text-transform: uppercase; }
.kv { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; padding: 0 14px; }
.kv + .kv { margin-top: 11px; }
.key { color: var(--muted); font-size: 10px; }
.value { color: #e4edf5; font-size: 12px; font-weight: 650; text-align: right; overflow-wrap: anywhere; }
.value.cyan { color: var(--cyan); }
.value.muted { color: var(--muted); font-weight: 500; }
.meter { height: 4px; margin: 7px 14px 0; overflow: hidden; border-radius: 5px; background: #253241; }
.meter span { display: block; width: 0; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #2c9eb5, var(--cyan)); transition: width .25s ease; }
.family-box { margin: 12px 14px 0; padding: 10px; border: 1px solid #52d5e82b; border-radius: 8px; background: #52d5e80a; }
.family-box .key { display: block; margin-bottom: 4px; }
.family-box .value { display: flex; justify-content: space-between; gap: 8px; text-align: left; }
.experimental { color: var(--amber); font-size: 9px; }
.feed { display: grid; gap: 0; }
.feed-row { display: grid; grid-template-columns: 8px 1fr auto; align-items: center; gap: 9px; padding: 10px 14px; border-top: 1px solid #ffffff0a; animation: arrive .2s ease-out; }
@keyframes arrive { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
.feed-dot { width: 7px; height: 7px; border-radius: 2px; background: var(--cyan); transform: rotate(45deg); }
.feed-main { min-width: 0; }
.feed-title { overflow: hidden; color: #dce7f1; font-size: 11px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.feed-sub { overflow: hidden; color: var(--muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.feed-score { color: var(--cyan); font: 10px ui-monospace, Consolas, monospace; }
.feed-empty { padding: 14px; color: var(--muted); font-size: 11px; text-align: center; }
@media (max-width: 680px) {
  .shell { padding-top: 17px; }
  .topbar { align-items: flex-start; flex-direction: column; }
  .top-actions { justify-content: flex-start; }
  .workspace { grid-template-columns: 1fr; }
  .frame { min-height: 250px; max-height: 58vh; }
  .inspector { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<main class="shell">
  <header class="topbar">
    <div>
      <div class="brand"><span class="brand-mark" aria-hidden="true">CV</span><div>
        <p class="eyebrow">Drone Detect · Computer Vision</p>
        <h1>Inference Studio</h1>
      </div></div>
      <p class="subtitle">Live video inference · object tracking · visual family estimate</p>
    </div>
    <div class="top-actions">
      <span id="status" class="live-pill off"><i class="live-dot"></i><span>Connecting</span></span>
      <span id="count" class="count-pill">0 alerts</span>
    </div>
  </header>
  <div class="workspace">
    <div class="main-column">
      <section class="viewer" aria-label="Live inference preview">
        <div class="viewer-head"><div class="viewer-title"><span class="stream-mark"></span>Latest annotated detection</div><span id="hint" class="viewer-meta">WAITING FOR DETECTION</span></div>
        <div class="frame" id="frame">
          <div id="frame-empty" class="frame-empty"><strong>Waiting for a detection snapshot</strong><span>Start the detector with an image or video source to see the latest annotated result here.</span></div>
          <img id="latest-image" alt="Latest annotated drone detection" hidden>
          <div class="frame-reticle" aria-hidden="true"></div>
        </div>
        <div class="viewer-foot"><span id="frame-source">EVENT SNAPSHOT · NOT RECEIVED</span><span id="frame-time">NO DETECTION YET</span></div>
      </section>
      <section class="panel" style="margin-top:14px" aria-label="Recent detections">
        <div class="panel-head"><h2>Detection stream</h2><span class="panel-note">LATEST EVENTS</span></div>
        <div id="feed" class="feed" aria-live="polite"><div id="feed-empty" class="feed-empty">No detections received yet.</div></div>
      </section>
    </div>
    <aside class="inspector">
      <section class="panel" aria-label="Selected detection details">
        <div class="panel-head"><h2>Detection details</h2><span id="selected-decision" class="panel-note">—</span></div>
        <div class="kv"><span class="key">Object class</span><span class="value">Drone</span></div>
        <div class="kv"><span class="key">Detection score</span><span id="selected-score" class="value cyan">—</span></div>
        <div class="meter"><span id="score-meter"></span></div>
        <div class="family-box"><span class="key">Visual family · experimental</span><span class="value"><span id="selected-family" class="value muted">Awaiting estimate</span><span id="family-score" class="experimental"></span></span></div>
        <div class="kv" style="margin-top:13px"><span class="key">Track / zone</span><span id="selected-track" class="value">—</span></div>
        <div class="kv"><span class="key">Registered identity</span><span id="selected-identity" class="value muted">Not resolved</span></div>
        <div class="kv"><span class="key">Decision</span><span id="selected-reason" class="value muted">Waiting for event</span></div>
      </section>
      <section class="panel" aria-label="Model status">
        <div class="panel-head"><h2>Pipeline</h2><span class="panel-note">REAL TIME</span></div>
        <div class="kv"><span class="key">Detector</span><span class="value">YOLO · drone</span></div>
        <div class="kv"><span class="key">Tracking</span><span class="value">Per-frame ID</span></div>
        <div class="kv"><span class="key">Family model</span><span class="value cyan">Experimental</span></div>
      </section>
    </aside>
  </div>
</main>
<script>
(function () {
  var feed = document.getElementById('feed');
  var status = document.getElementById('status');
  var countEl = document.getElementById('count');
  var hint = document.getElementById('hint');
  var image = document.getElementById('latest-image');
  var frameEmpty = document.getElementById('frame-empty');
  var feedEmpty = document.getElementById('feed-empty');
  var seen = 0;
  var backoff = 1000;
  var maxBackoff = 30000;
  var pageToken = new URLSearchParams(location.search).get('token') || '';

  function snapUrl(p) {
    if (!p) return '';
    var normalized = String(p).replace(/\\/g, '/');
    var i = normalized.lastIndexOf('/snapshots/');
    if (i >= 0) normalized = '/snapshots' + normalized.slice(i + '/snapshots'.length);
    else if (normalized.indexOf('data/snapshots/') >= 0) {
      normalized = '/snapshots/' + normalized.split('data/snapshots/').pop();
    }
    try {
      var url = new URL(normalized, location.origin);
      return url.origin === location.origin && url.pathname.indexOf('/snapshots/') === 0 ? url.href : '';
    } catch (e) { return ''; }
  }
  function element(tag, className, text) {
    var item = document.createElement(tag);
    if (className) item.className = className;
    if (text != null) item.textContent = String(text);
    return item;
  }
  function formatTime(raw) {
    var date = new Date(raw || '');
    return isNaN(date.getTime()) ? (raw || 'Time unavailable') : date.toLocaleString();
  }
  function percent(raw) {
    var value = Number(raw);
    return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
  }
  function visualFamily(a) {
    var family = a.visual && a.visual.model_family ? String(a.visual.model_family).replace(/_/g, ' ') : '';
    if (!family || family.toLowerCase() === 'no drone') return '';
    return family.toLowerCase().indexOf('dji ') === 0 ? family : 'DJI ' + family;
  }
  function updateInspector(a, family) {
    var confidence = percent(a.confidence);
    document.getElementById('selected-score').textContent = confidence.toFixed(2);
    document.getElementById('score-meter').style.width = (confidence * 100) + '%';
    document.getElementById('selected-decision').textContent = String(a.decision || 'UNIDENTIFIED').toUpperCase();
    var familyName = document.getElementById('selected-family');
    familyName.textContent = family || 'No family estimate';
    familyName.className = 'value' + (family ? ' cyan' : ' muted');
    document.getElementById('family-score').textContent = family && a.visual.model_confidence != null ? percent(a.visual.model_confidence).toFixed(2) : '';
    document.getElementById('selected-track').textContent = (a.track_id != null ? '#' + a.track_id : '—') + ' / ' + (a.zone_id || 'zone unavailable');
    var registered = a.drone ? [a.drone.manufacturer, a.drone.model].filter(Boolean).join(' ') : '';
    document.getElementById('selected-identity').textContent = registered || 'Not resolved';
    document.getElementById('selected-identity').className = 'value' + (registered ? '' : ' muted');
    document.getElementById('selected-reason').textContent = a.reason || 'No decision detail';
    document.getElementById('frame-time').textContent = formatTime(a.detected_at).toUpperCase();
  }
  function add(a) {
    seen++;
    countEl.textContent = seen + ' alert' + (seen === 1 ? '' : 's');
    var family = visualFamily(a);
    updateInspector(a, family);
    var snap = snapUrl(a.snapshot_path);
    if (snap) {
      var imageURL = new URL(snap);
      imageURL.searchParams.set('_frame', String(Date.now()));
      image.src = imageURL.href;
      image.hidden = false;
      frameEmpty.hidden = true;
      document.getElementById('frame-source').textContent = 'SOURCE · ANNOTATED SNAPSHOT';
    }
    var track = a.track_id != null ? '#' + a.track_id : 'Drone';
    var feedRow = element('div', 'feed-row');
    feedRow.appendChild(element('span', 'feed-dot'));
    var feedMain = element('div', 'feed-main');
    feedMain.appendChild(element('div', 'feed-title', family || 'Drone detected'));
    feedMain.appendChild(element('div', 'feed-sub', track + ' · ' + (a.zone_id || 'zone unavailable') + ' · ' + formatTime(a.detected_at)));
    feedRow.appendChild(feedMain);
    feedRow.appendChild(element('span', 'feed-score', percent(a.confidence).toFixed(2)));
    feed.prepend(feedRow);
    feedEmpty.hidden = true;
    while (feed.children.length > 13) feed.lastChild.remove();
    hint.textContent = snap ? 'ANNOTATED FRAME · LIVE' : 'EVENT RECEIVED · NO SNAPSHOT';
  }
  function connect() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var url = proto + '//' + location.host + '/ws/alerts' + (pageToken ? '?token=' + encodeURIComponent(pageToken) : '');
    hint.textContent = pageToken ? 'AUTHENTICATED STREAM' : 'CONNECTING TO ALERT STREAM';
    var ws;
    try { ws = new WebSocket(url); } catch (e) { setStatus('Retrying connection', false); retry(); return; }
    ws.onopen = function () {
      setStatus('Live connection', true);
      hint.textContent = 'CONNECTED · WAITING FOR FRAME';
      backoff = 1000;
    };
    ws.onmessage = function (ev) {
      try { add(JSON.parse(ev.data)); } catch (e) { /* ignore bad frame */ }
    };
    ws.onclose = function () {
      setStatus('Reconnecting', false);
      retry();
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
  }
  function setStatus(label, connected) {
    status.className = 'live-pill ' + (connected ? 'on' : 'off');
    status.lastElementChild.textContent = label;
  }
  function retry() {
    setTimeout(connect, backoff);
    backoff = Math.min(maxBackoff, backoff * 2);
  }
  connect();
})();
</script>
</body>
</html>`
