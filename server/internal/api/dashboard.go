// Dashboard page (M7): minimal single-file UI at GET / that streams
// /ws/alerts and renders a live table. No external dependencies.
package api

import (
	"net/http"
	"os"

	"github.com/gin-gonic/gin"
)

// DashboardHandler serves the single-file live alerts page.
func DashboardHandler() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Data(http.StatusOK, "text/html; charset=utf-8", []byte(dashboardHTML))
	}
}

// MountSnapshots serves detector snapshots under /snapshots/*filepath when
// dir exists. Missing dir is fine (dashboard shows the path as text).
func MountSnapshots(r *gin.Engine, dir string) {
	if dir == "" {
		return
	}
	if st, err := os.Stat(dir); err != nil || !st.IsDir() {
		return
	}
	r.Static("/snapshots", dir)
}

const dashboardHTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Drone Detect — Live Alerts</title>
<style>
:root { color-scheme: light dark; }
body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 16px; }
header { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; }
#status { font-size: 13px; padding: 2px 10px; border-radius: 999px; background: #8883; }
#status.on { background: #16a34a33; color: #16a34a; }
#status.off { background: #dc262633; color: #dc2626; }
table { border-collapse: collapse; width: 100%; margin-top: 12px; font-size: 14px; }
th, td { border: 1px solid #8884; padding: 6px 8px; text-align: left; vertical-align: middle; }
th { position: sticky; top: 0; background: inherit; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-weight: 600; font-size: 12px; }
.badge.authorized { background: #16a34a22; color: #16a34a; border: 1px solid #16a34a66; }
.badge.unauthorized { background: #dc262622; color: #dc2626; border: 1px solid #dc262666; }
.badge.unidentified { background: #d9770622; color: #d97706; border: 1px solid #d9770666; }
img.thumb { width: 128px; height: auto; display: block; border-radius: 6px; }
.mono { font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
small { color: #888; }
</style>
</head>
<body>
<header>
<h1 style="margin:0">Live Alerts</h1>
<span id="status" class="off">disconnected</span>
<span id="count"></span>
<small id="hint"></small>
</header>
<table>
<thead><tr>
<th>Time</th><th>Zone</th><th>Decision</th><th>Reason</th>
<th>Identity</th><th>Drone</th><th>Conf</th><th>Snapshot</th>
</tr></thead>
<tbody id="rows"></tbody>
</table>
<script>
(function () {
  var rows = document.getElementById('rows');
  var status = document.getElementById('status');
  var countEl = document.getElementById('count');
  var hint = document.getElementById('hint');
  var seen = 0;
  var backoff = 1000;
  var maxBackoff = 30000;
  var pageToken = new URLSearchParams(location.search).get('token') || '';

  function snapUrl(p) {
    if (!p) return '';
    // Detector stores repo-relative paths like data/snapshots/2026-06-09/x.jpg.
    // The server mounts that dir at /snapshots/.
    var i = p.replace(/\\/g, '/').lastIndexOf('/snapshots/');
    if (i >= 0) return '/snapshots' + p.replace(/\\/g, '/').slice(i + '/snapshots'.length);
    return p;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function add(a) {
    seen++;
    countEl.textContent = seen + ' alert' + (seen === 1 ? '' : 's');
    var tr = document.createElement('tr');
    var dec = a.decision || '';
    var drone = a.drone ? ((a.drone.serial_number || '') + ' ' + (a.drone.model || '')).trim() : '';
    var ident = (a.identity && a.identity.method ? a.identity.method : 'none') +
      ' / ' + (a.identity && a.identity.result ? a.identity.result : '');
    var snap = snapUrl(a.snapshot_path);
    var thumb = snap ? '<a href="' + esc(snap) + '" target="_blank" rel="noopener">' +
      '<img class="thumb" src="' + esc(snap) + '" loading="lazy" onerror="this.remove()"></a>' +
      '<div class="mono">' + esc(a.snapshot_path || '') + '</div>' : '<span class="mono"></span>';
    tr.innerHTML =
      '<td class="mono">' + esc(a.detected_at || '') + '</td>' +
      '<td>' + esc(a.zone_id || '') + '</td>' +
      '<td><span class="badge ' + esc(dec) + '">' + esc(dec) + '</span></td>' +
      '<td>' + esc(a.reason || '') + '</td>' +
      '<td class="mono">' + esc(ident) + '</td>' +
      '<td>' + esc(drone) + '</td>' +
      '<td class="mono">' + esc(a.confidence == null ? '' : a.confidence) + '</td>' +
      '<td>' + thumb + '</td>';
    rows.prepend(tr);
    while (rows.children.length > 200) rows.lastChild.remove();
  }
  function connect() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var url = proto + '//' + location.host + '/ws/alerts' + (pageToken ? '?token=' + encodeURIComponent(pageToken) : '');
    hint.textContent = pageToken ? '' : 'tip: append ?token=SECRET when ALERT_TOKEN is set';
    var ws;
    try { ws = new WebSocket(url); } catch (e) { retry(); return; }
    ws.onopen = function () {
      status.textContent = 'connected';
      status.className = 'on';
      backoff = 1000;
    };
    ws.onmessage = function (ev) {
      try { add(JSON.parse(ev.data)); } catch (e) { /* ignore bad frame */ }
    };
    ws.onclose = function () {
      status.textContent = 'disconnected — retrying…';
      status.className = 'off';
      retry();
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
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
