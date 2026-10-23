const form = document.getElementById('send');
const box = document.getElementById('msgs');
const trace = document.getElementById('trace');
const session = 'live' + Math.random().toString(36).slice(2, 10);
let live = false, n = 0;
function bubble(cls, text, meta) {
  const d = document.createElement('div'); d.className = 'b ' + cls;
  const p = document.createElement('p'); p.textContent = text; d.appendChild(p);
  if (meta) { const s = document.createElement('small'); s.textContent = meta; d.appendChild(s); }
  box.appendChild(d); box.scrollTop = box.scrollHeight;
}
form.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const input = form.querySelector('input'); const text = input.value.trim();
  if (!text) return;
  if (!live) { box.innerHTML = ''; trace.innerHTML = ''; live = true; }
  input.value = ''; bubble('in', text);
  const r = await fetch('/console/api/message', {method: 'POST',
    headers: {'content-type': 'application/json'}, body: JSON.stringify({session, text})});
  const t = await r.json(); n += 1;
  if (t.reply) bubble('out', t.reply, t.intent + ' · ' + t.confidence.toFixed(2) + ' · ' + t.action);
  const tr = document.createElement('tr');
  for (const v of [n, t.intent, t.confidence.toFixed(2), t.action]) {
    const td = document.createElement('td'); td.textContent = v; tr.appendChild(td);
  }
  trace.appendChild(tr);
});
