/* Hermes 工作台 前端 */
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const state = { data: null, view: 'overview', busy: false, cfg: null, file: null, dirty: false };

/* ---------------- 工具 ---------------- */
function toast(msg, isErr = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast show' + (isErr ? ' err' : '');
  clearTimeout(t._t);
  t._t = setTimeout(() => (t.className = 'toast'), 2800);
}

function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}
function fmtDT(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit' });
}
function fmtMB(mb) {
  if (mb >= 1024) return (mb / 1024).toFixed(2) + ' GB';
  return mb + ' MB';
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, m =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}
function setCard(sel, level) {
  const el = typeof sel === 'string' ? $(sel) : sel;
  if (!el) return;
  el.closest('.card').classList.remove('ok', 'warn', 'risk');
  if (level) el.closest('.card').classList.add(level);
}
async function api(url, opt) {
  const r = await fetch(url, opt);
  const d = await r.json().catch(() => ({ ok: false, error: '返回不是 JSON' }));
  if (!r.ok && !d.error) d.error = 'HTTP ' + r.status;
  return d;
}
const post = (url, body) => api(url, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {})
});

/* ---------------- 视图切换 ---------------- */
const TITLES = { overview: '总览', chat: '对话', config: '配置', cost: '成本', skills: '技能',
                 memory: '记忆', task: '任务', scan: '体检', audit: '变更记录',
                 hermes: '功能', dashboard: '仪表盘', system: '系统', workspace: '工作区' };
const LOADERS = { skills: loadSkills, memory: loadMemory, task: loadCron,
                  audit: loadAudit, config: loadFiles, cost: loadCost,
                  hermes: loadHermes, dashboard: loadDashboard, system: loadSystem,
                  workspace: loadWorkspace };

$$('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => {
    const v = btn.dataset.view;
    state.view = v;
    $$('.nav-item').forEach(b => b.classList.toggle('active', b === btn));
    $$('.view').forEach(s => s.classList.toggle('active', s.id === 'view-' + v));
    $('#viewTitle').textContent = TITLES[v] || v;
    if (LOADERS[v]) LOADERS[v]();
    closeNavMobile();
  });
});

$$('.subtab').forEach(btn => {
  btn.addEventListener('click', () => {
    $$('.subtab').forEach(b => b.classList.toggle('active', b === btn));
    $$('.tabpane').forEach(p => p.classList.toggle('active', p.id === 'tab-' + btn.dataset.tab));
    if (btn.dataset.tab === 'mcp') loadMcp();
    if (btn.dataset.tab === 'provider') { loadProviders(); loadEnv(); }
    if (btn.dataset.tab === 'chatapi') loadChatApi();
    if (btn.dataset.tab === 'usage') loadCost();
    if (btn.dataset.tab === 'price') loadPricing();
    if (btn.dataset.tab === 'alert') loadNotify();
    if (btn.dataset.tab === 'alertlog') loadAlertLog();
  });
});

/* ---------------- 总览 ---------------- */
async function loadOverview() {
  try {
    const d = await api('/api/overview');
    if (!d.ok) throw new Error(d.error || '接口错误');
    state.data = d;
    renderOverview(d);
    drawChart(d.history || []);
    $('#stamp').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN');
  } catch (e) {
    toast('数据加载失败：' + e.message, true);
    $('#liveDot').className = 'dot down';
  }
}

function renderOverview(d) {
  const c = d.container || {}, s = d.system || {}, q = d.quota || {};

  $('#liveDot').className = 'dot ' + (c.alive ? 'live' : 'down');

  const stEl = $('#cStatus');
  stEl.textContent = c.alive ? '运行中' : '已停止';
  setCard(stEl, c.alive ? 'ok' : 'risk');
  $('#cStatusSub').textContent =
    `${c.mode === 'docker' ? '容器' : '进程'} ${c.name || '-'} · ${c.status || '-'}`;

  const qp = q.pct || 0;
  $('#cQuota').textContent = qp + '%';
  setCard($('#cQuota'), qp >= 90 ? 'risk' : qp >= 80 ? 'warn' : 'ok');
  const qb = $('#cQuotaBar');
  qb.style.width = Math.min(qp, 100) + '%';
  qb.classList.toggle('hot', qp >= 80);

  const mf = (d.memory || {}).files || 0;
  $('#cMem').textContent = mf;
  setCard($('#cMem'), mf > 80 ? 'warn' : null);
  $('#cMemSub').textContent = fmtMB((d.memory || {}).mb || 0) + (mf > 80 ? ' · 偏多' : '');

  const sk = (d.skills || {}).active || 0;
  $('#cSkills').textContent = sk;
  setCard($('#cSkills'), sk > 60 ? 'warn' : null);
  $('#cSkillsSub').textContent = '归档 ' + ((d.skills || {}).archived || 0) + ' 个';

  const errs = (d.logs || {}).errors_24h || 0;
  $('#cErr').textContent = errs;
  setCard($('#cErr'), errs > 50 ? 'risk' : errs > 5 ? 'warn' : 'ok');
  $('#cErrSub').textContent = errs > 5 ? '需要关注' : '正常';

  const load = s.load1 || 0, ncpu = s.ncpu || 1;
  const lp = Math.min(Math.round(load / ncpu * 100), 100);
  $('#cLoad').textContent = load.toFixed(2);
  setCard($('#cLoad'), lp >= 90 ? 'warn' : null);
  $('#cLoadSub').textContent = `${ncpu} 核 · 约 ${lp}%`;

  const mp = s.mem_used_pct || 0;
  $('#mMmem').textContent = mp + '%  (可用 ' + (s.mem_avail_mb || 0) + ' MB)';
  $('#bMem').style.width = mp + '%';
  $('#bMem').classList.toggle('hot', mp >= 85);

  const dp = s.disk_used_pct || 0;
  $('#mDisk').textContent = dp + '%  (余 ' + (s.disk_free_gb || 0) + ' GB)';
  $('#bDisk').style.width = dp + '%';
  $('#bDisk').classList.toggle('hot', dp >= 85);

  $('#mCpu').textContent = ncpu + ' 核';
  $('#bCpu').style.width = lp + '%';
  $('#bCpu').classList.toggle('hot', lp >= 85);

  $('#sysHint').textContent = `配额 ${fmtMB(q.used_mb || 0)} / ${fmtMB(q.limit_mb || 0)}`;

  $('#kProc').textContent = c.name || '-';
  const rs = c.restarts || 0;
  $('#kRestart').textContent = rs + (rs > 3 ? ' ⚠' : '');
  $('#kSess').textContent = d.sessions || 0;
  $('#kCron').textContent = d.cron || 0;

  const samples = (d.logs || {}).samples || [];
  $('#logBox').innerHTML = samples.length
    ? samples.map(x => `<div>${escapeHtml(x)}</div>`).join('')
    : '<div class="empty">暂无错误，一切正常</div>';

  $('#footMode').textContent = c.mode || '-';
  $('#footDir').textContent = d.hermes_dir || '-';
  $('#footDir').title = d.hermes_dir || '';
  $('#footQuota').textContent = fmtMB(q.limit_mb || 0);
}

/* ---------------- 图表 ---------------- */
function drawChart(hist) {
  const cv = $('#chartTrend');
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!W || !H) return;
  cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext('2d');
  g.scale(dpr, dpr);
  g.clearRect(0, 0, W, H);

  const pad = { t: 12, r: 10, b: 22, l: 30 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;

  const csG = getComputedStyle(document.documentElement);
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  g.strokeStyle = isLight ? 'rgba(15,23,42,.12)' : 'rgba(255,255,255,.07)';
  g.lineWidth = 1; g.font = '10px sans-serif';
  g.fillStyle = isLight ? 'rgba(15,23,42,.45)' : 'rgba(255,255,255,.32)';
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + ih * i / 4;
    g.beginPath(); g.moveTo(pad.l, y); g.lineTo(W - pad.r, y); g.stroke();
    g.fillText(String(100 - i * 25), 4, y + 3);
  }

  if (!hist || hist.length < 2) {
    g.fillStyle = isLight ? 'rgba(15,23,42,.4)' : 'rgba(255,255,255,.25)';
    g.font = '12px sans-serif';
    g.fillText('采集中…（每分钟一个点）', W / 2 - 60, H / 2);
    return;
  }

  const n = hist.length;
  const X = i => pad.l + iw * i / (n - 1);
  const Y = v => pad.t + ih * (1 - Math.max(0, Math.min(100, v)) / 100);

  const cs = getComputedStyle(document.documentElement);
  const C1 = cs.getPropertyValue('--a1').trim() || '#00d4aa';
  const C2 = cs.getPropertyValue('--a2').trim() || '#6366f1';
  const C3 = cs.getPropertyValue('--a3').trim() || '#f59e0b';
  [[  'load', C1, true], ['mem', C2, false], ['disk', C3, false]]
  .forEach(([key, color, fill]) => {
    const pts = hist.map((h, i) => [X(i), Y(h[key] || 0)]);
    if (fill) {
      const grd = g.createLinearGradient(0, pad.t, 0, pad.t + ih);
      grd.addColorStop(0, C1 + '4d');
      grd.addColorStop(1, C1 + '00');
      g.beginPath();
      g.moveTo(pts[0][0], pad.t + ih);
      pts.forEach(p => g.lineTo(p[0], p[1]));
      g.lineTo(pts[n - 1][0], pad.t + ih);
      g.closePath();
      g.fillStyle = grd; g.fill();
    }
    g.beginPath();
    pts.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])));
    g.strokeStyle = color; g.lineWidth = 2; g.lineJoin = 'round'; g.stroke();
  });

  g.fillStyle = isLight ? 'rgba(15,23,42,.45)' : 'rgba(255,255,255,.3)';
  g.font = '10px sans-serif';
  g.fillText(fmtTime(hist[0].t), pad.l, H - 6);
  g.fillText(fmtTime(hist[n - 1].t), W - pad.r - 32, H - 6);
}

/* ---------------- 配置文件 ---------------- */
async function loadFiles() {
  const d = await api('/api/files');
  const box = $('#fileList');
  if (!d.ok || !d.items || !d.items.length) {
    box.innerHTML = '<div class="empty">没有可编辑文件</div>';
    return;
  }
  box.innerHTML = d.items.map(f => `
    <div class="file-item" data-path="${escapeHtml(f.path)}">
      <div class="item-name">${escapeHtml(f.path)}</div>
      <div class="item-desc">${escapeHtml(f.desc || '')} · ${f.kb}KB</div>
    </div>`).join('');
  $$('#fileList .file-item').forEach(el => {
    el.addEventListener('click', () => openFile(el.dataset.path, el));
  });
  if (d.readonly) $('#edWarn').textContent = '只读模式';
}

async function openFile(path, el) {
  $$('#fileList .file-item').forEach(x => x.classList.remove('active'));
  if (el) el.classList.add('active');
  const d = await api('/api/file?path=' + encodeURIComponent(path));
  if (!d.ok) { toast(d.error, true); return; }
  state.file = d;
  state.dirty = false;
  $('#edTitle').textContent = d.path;
  $('#edHint').textContent = `修改于 ${fmtDT(d.mtime)} · ${d.backups.length} 份历史备份`;
  $('#fileEditor').value = d.content;
  $('#edOut').hidden = true;
  updateDirty();
}

function updateDirty() {
  const d = state.file;
  const dirty = d && $('#fileEditor').value !== d.content;
  state.dirty = dirty;
  $('#btnSaveFile').textContent = dirty ? '保存（有未保存改动）' : '保存（自动备份）';
}

$('#fileEditor').addEventListener('input', updateDirty);

$('#btnSaveFile').addEventListener('click', async () => {
  if (!state.file) return toast('先选一个文件', true);
  if (!state.dirty) return toast('没有改动');
  const d = await post('/api/file', {
    path: state.file.path, content: $('#fileEditor').value
  });
  if (!d.ok) { toast(d.error, true); $('#edOut').hidden = false; $('#edOut').textContent = d.error; return; }
  state.file.content = $('#fileEditor').value;
  updateDirty();
  if (d.changed) {
    toast('已保存并备份：' + d.backup);
    $('#edOut').hidden = false;
    $('#edOut').textContent = d.diff || '（无差异）';
    if (d.restart_required) markPending();
  } else toast('内容无变化');
});

$('#btnDiff').addEventListener('click', () => {
  if (!state.file) return;
  const cur = $('#fileEditor').value.split('\n');
  const old = state.file.content.split('\n');
  const out = [];
  const max = Math.max(cur.length, old.length);
  for (let i = 0; i < max; i++) {
    if (cur[i] !== old[i]) {
      out.push(`第 ${i + 1} 行`);
      if (old[i] !== undefined) out.push('  - ' + old[i]);
      if (cur[i] !== undefined) out.push('  + ' + cur[i]);
    }
  }
  $('#edOut').hidden = false;
  $('#edOut').textContent = out.length ? out.join('\n') : '编辑器内容与磁盘内容一致';
});

$('#btnBackups').addEventListener('click', async () => {
  if (!state.file) return;
  const d = await api('/api/backups?path=' + encodeURIComponent(state.file.path));
  $('#edOut').hidden = false;
  if (!d.ok || !d.items.length) { $('#edOut').textContent = '暂无备份'; return; }
  $('#edOut').innerHTML = d.items.map(b =>
    `<div class="bk"><span>${escapeHtml(b.name)}</span><span>${b.kb}KB</span>` +
    `<span>${fmtDT(b.mtime)}</span><button class="btn tiny" data-bk="${escapeHtml(b.name)}">回滚</button></div>`
  ).join('');
  $$('#edOut [data-bk]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!confirm(`确认回滚到 ${btn.dataset.bk}？\n当前内容会先自动备份。`)) return;
      const r = await post('/api/rollback', { path: state.file.path, backup: btn.dataset.bk });
      if (r.ok) { toast('已回滚'); openFile(state.file.path); loadAudit(); }
      else toast(r.error, true);
    });
  });
});

function markPending() {
  const p = $('#pendingPill');
  p.hidden = false;
  p.textContent = '有改动待重启生效';
}

/* ---------------- MCP ---------------- */
async function loadMcp() {
  const d = await api('/api/mcp');
  const w = $('#mcpWarn');
  if (d.warn) { w.hidden = false; w.textContent = '⚠ ' + d.warn; } else w.hidden = true;
  const box = $('#mcpList');
  if (!d.ok || !d.servers || !d.servers.length) {
    box.innerHTML = '<div class="empty">还没有接入 MCP 服务器</div>';
    return;
  }
  box.innerHTML = d.servers.map(s => `
    <div class="item">
      <div style="min-width:0">
        <div class="item-name">${escapeHtml(s.name)}
          <span class="tag ${s.enabled ? 'on' : 'off'}">${s.enabled ? '启用' : '禁用'}</span></div>
        <div class="item-desc">${escapeHtml(s.command)} ${escapeHtml(s.args || '')}</div>
        ${s.env_keys.length ? `<div class="item-meta">env: ${s.env_keys.join(', ')}</div>` : ''}
      </div>
      <div class="acts">
        <button class="btn tiny" data-tg="${escapeHtml(s.name)}" data-en="${s.enabled ? 0 : 1}">
          ${s.enabled ? '禁用' : '启用'}</button>
        <button class="btn tiny" data-test="${escapeHtml(s.name)}">测试连接</button>
        <button class="btn tiny danger" data-del="${escapeHtml(s.name)}">删除</button>
      </div>
    </div>`).join('');

  $$('#mcpList [data-tg]').forEach(b => b.addEventListener('click', async () => {
    const r = await post('/api/mcp/toggle', { name: b.dataset.tg, enabled: b.dataset.en === '1' });
    r.ok ? (toast('已更新，可点热加载'), loadMcp()) : toast(r.error, true);
  }));
  $$('#mcpList [data-del]').forEach(b => b.addEventListener('click', async () => {
    if (!confirm('删除 MCP 服务器「' + b.dataset.del + '」？\nconfig.yaml 会自动备份，可回滚。')) return;
    const r = await post('/api/mcp/delete', { name: b.dataset.del });
    r.ok ? (toast('已删除'), loadMcp()) : toast(r.error, true);
  }));
  $$('#mcpList [data-test]').forEach(b => b.addEventListener('click', () => testMcp(b)));
}

$('#btnMcpSave').addEventListener('click', async () => {
  const name = $('#mName').value.trim(), cmd = $('#mCmd').value.trim();
  if (!name || !cmd) return toast('名称和命令必填', true);
  let env = {};
  const raw = $('#mEnv').value.trim();
  if (raw) {
    try { env = JSON.parse(raw); } catch (e) { return toast('环境变量不是合法 JSON', true); }
  }
  const r = await post('/api/mcp', { name, command: cmd, args: $('#mArgs').value.trim(), env });
  if (r.ok) { toast('已保存到 config.yaml'); loadMcp(); markPending(); loadAudit(); }
  else toast(r.error, true);
});

$('#btnReloadMcp').addEventListener('click', async () => {
  const r = await post('/api/mcp/reload', {});
  toast(r.ok ? '热加载完成' : (r.output || r.error || '失败'), !r.ok);
});

/* ---------------- 工作区（文件树浏览器） ---------------- */
async function loadWorkspace() {
  await wsRender('');
}

async function wsRender(rel) {
  state.wsPath = rel;
  $('#wsCrumb').textContent = rel ? '/' + rel : '/';
  const d = await api('/api/workspace?path=' + encodeURIComponent(rel));
  const box = $('#wsTree');
  if (!d.ok) { box.innerHTML = '<div class="empty">' + escapeHtml(d.error || '加载失败') + '</div>'; return; }
  if (d.readonly) $('#wsWarn').textContent = '只读模式（挂载为 :ro），保存会被拒绝';
  const items = d.items || [];
  if (!items.length) { box.innerHTML = '<div class="empty">空目录</div>'; return; }
  box.innerHTML = items.map(f => `
    <div class="file-item ${f.type === 'dir' ? 'is-dir' : ''} ${f.hidden ? 'is-hidden' : ''}"
         data-path="${escapeHtml(f.path)}" data-type="${f.type}">
      <div class="item-name">${f.type === 'dir' ? '▸ ' : '· '}${escapeHtml(f.name)}</div>
      <div class="item-desc">${f.type === 'dir' ? '目录' : (f.kb + 'KB')}${f.hidden ? ' · 隐藏' : ''}</div>
    </div>`).join('');
  $$('#wsTree .file-item').forEach(el => {
    el.addEventListener('click', () => {
      if (el.dataset.type === 'dir') wsRender(el.dataset.path);
      else openWsFile(el.dataset.path, el);
    });
  });
}

async function openWsFile(path, el) {
  $$('#wsTree .file-item').forEach(x => x.classList.remove('active'));
  if (el) el.classList.add('active');
  const d = await api('/api/workspace/file?path=' + encodeURIComponent(path));
  if (!d.ok) { toast(d.error, true); return; }
  state.wsFile = d;
  state.wsDirty = false;
  $('#wsTitle').textContent = d.path;
  $('#wsHint').textContent = `修改于 ${fmtDT(d.mtime)} · ${d.backups.length} 份历史备份`;
  $('#wsEditor').value = d.content;
  $('#wsOut').hidden = true;
  updateWsDirty();
}

function updateWsDirty() {
  const d = state.wsFile;
  const dirty = d && $('#wsEditor').value !== d.content;
  state.wsDirty = dirty;
  $('#btnWsSave').textContent = dirty ? '保存（有未保存改动）' : '保存（自动备份）';
}

$('#wsEditor').addEventListener('input', updateWsDirty);

$('#btnWsSave').addEventListener('click', async () => {
  if (!state.wsFile) return toast('先选一个文件', true);
  if (!state.wsDirty) return toast('没有改动');
  const d = await post('/api/workspace/file', {
    path: state.wsFile.path, content: $('#wsEditor').value
  });
  if (!d.ok) { toast(d.error, true); $('#wsOut').hidden = false; $('#wsOut').textContent = d.error; return; }
  state.wsFile.content = $('#wsEditor').value;
  updateWsDirty();
  if (d.changed) {
    toast('已保存并备份：' + d.backup);
    $('#wsOut').hidden = false; $('#wsOut').textContent = d.diff || '（无差异）';
    loadAudit();
  } else toast('内容无变化');
});

$('#btnWsUp').addEventListener('click', async () => {
  const cur = state.wsPath || '';
  if (!cur) return;
  const up = cur.includes('/') ? cur.slice(0, cur.lastIndexOf('/')) : '';
  await wsRender(up);
});

$('#btnWsBackups').addEventListener('click', async () => {
  if (!state.wsFile) return;
  const d = await api('/api/backups?path=' + encodeURIComponent(state.wsFile.path));
  $('#wsOut').hidden = false;
  if (!d.ok || !d.items.length) { $('#wsOut').textContent = '暂无备份'; return; }
  $('#wsOut').innerHTML = d.items.map(b =>
    `<div class="bk"><span>${escapeHtml(b.name)}</span><span>${b.kb}KB</span>` +
    `<span>${fmtDT(b.mtime)}</span><button class="btn tiny" data-bk="${escapeHtml(b.name)}">回滚</button></div>`
  ).join('');
  $$('#wsOut [data-bk]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!confirm(`确认回滚到 ${btn.dataset.bk}？\n当前内容会先自动备份。`)) return;
      const r = await post('/api/rollback', { path: state.wsFile.path, backup: btn.dataset.bk });
      if (r.ok) { toast('已回滚'); openWsFile(state.wsFile.path); loadAudit(); }
      else toast(r.error, true);
    });
  });
});

/* ---------------- MCP 连通测试 ---------------- */
async function testMcp(btn) {
  const name = btn.dataset.test;
  btn.disabled = true; btn.textContent = '测试中…';
  const r = await post('/api/mcp/test', { name });
  btn.disabled = false; btn.textContent = '测试连接';
  const pre = $('#mcpTestOut');
  pre.hidden = false;
  if (!r.ok) { pre.textContent = '请求失败：' + (r.error || ''); toast(r.error, true); return; }
  const out = (r.output || '').trim() || (r.ok ? '（无输出，rc=0）' : '（无输出）');
  pre.textContent = `[${r.ok ? 'OK' : 'FAIL'} rc=${r.rc}] ${name}\n${out}`;
  toast(r.ok ? '连通性测试通过' : '测试失败（见下方输出）', !r.ok);
}

/* ---------------- Provider / env ---------------- */
async function loadProviders() {
  const d = await api('/api/providers');
  if (!d.ok) return;
  $('#provGrid').innerHTML = Object.entries(d.items).map(([k, v]) => `
    <label class="prov" data-k="${k}">
      <input type="radio" name="prov" value="${k}">
      <div class="prov-name">${escapeHtml(v.label)}</div>
      <div class="prov-model">${escapeHtml(v.model)}</div>
      <div class="prov-tip">${escapeHtml(v.tip || '')}</div>
    </label>`).join('');
  $$('#provGrid .prov').forEach(el => el.addEventListener('click', () => {
    $$('#provGrid .prov').forEach(x => x.classList.remove('sel'));
    el.classList.add('sel');
    const k = el.dataset.k;
    $('#provTip').textContent = d.items[k].tip || '';
  }));
}

$('#btnProvApply').addEventListener('click', async () => {
  const sel = $('#provGrid .prov.sel');
  if (!sel) return toast('先选一个 Provider', true);
  const r = await post('/api/providers/apply', {
    provider: sel.dataset.k, api_key: $('#provKey').value
  });
  if (!r.ok) return toast(r.error, true);
  $('#provTip').textContent = r.next;
  markPending();
  toast('已写入 .env，还需改 config.yaml 的 model 后重启');
  loadEnv(); loadAudit();
});

async function loadEnv() {
  const d = await api('/api/env');
  const box = $('#envList');
  if (!d.ok || !d.items || !d.items.length) {
    box.innerHTML = '<div class="empty">.env 不存在或为空</div>';
    return;
  }
  box.innerHTML = d.items.map((e, i) => `
    <div class="item env-item">
      <div class="item-name">${escapeHtml(e.key)}
        ${e.secret ? '<span class="tag off">密钥</span>' : ''}</div>
      <input class="env-val" data-k="${escapeHtml(e.key)}"
             value="${escapeHtml(e.value)}" ${e.secret ? 'type="password"' : ''}>
    </div>`).join('') +
    `<div class="ed-bar"><button class="btn" id="btnEnvSave">保存 .env（脱敏项保持不变）</button></div>`;

  $('#btnEnvSave').addEventListener('click', async () => {
    const updates = {};
    $$('#envList .env-val').forEach(inp => { updates[inp.dataset.k] = inp.value; });
    const r = await post('/api/env', { updates });
    if (!r.ok) return toast(r.error, true);
    if (!r.changed) return toast('没有变化（密钥保持原值）');
    toast('已更新：' + r.changed_keys.join(', '));
    markPending(); loadEnv(); loadAudit();
  });
}

/* ---------------- 系统动作 ---------------- */
async function doAction(act, label) {
  if (!confirm(label + ' —— 确认执行？')) return;
  const out = $('#actionOut');
  out.textContent = '执行中…';
  const r = await post('/api/action', { action: act, token: $('#dangerToken').value });
  out.textContent = `$ ${act}\n${'─'.repeat(50)}\n` + (r.output || r.error || '完成');
  toast(r.ok ? label + '完成' : (r.error || label + '失败'), !r.ok);
  loadAudit();
}
$('#btnRestart').addEventListener('click', () => doAction('restart', '重启 Hermes'));
$('#btnUpgrade').addEventListener('click', () => doAction('upgrade', '拉取并升级 Hermes'));

/* ---------------- 技能 ---------------- */
async function loadSkills() {
  const d = await api('/api/skills');
  const box = $('#skillList');
  if (!d.items || !d.items.length) {
    box.innerHTML = '<div class="empty">未发现技能</div>';
    $('#skillHint').textContent = '0 个';
  } else {
    box.innerHTML = d.items.map(s => `
      <div class="item">
        <div style="min-width:0">
          <div class="item-name">${escapeHtml(s.name)}</div>
          ${s.desc ? `<div class="item-desc">${escapeHtml(s.desc)}</div>` : ''}
        </div>
        <div class="acts">
          <button class="btn tiny" data-sk="${escapeHtml(s.name)}" data-en="0">禁用</button>
        </div>
      </div>`).join('');
    $('#skillHint').textContent = d.items.length + ' 个';
    $$('#skillList [data-sk]').forEach(b => b.addEventListener('click', async () => {
      const r = await post('/api/skills/toggle', { name: b.dataset.sk, enable: false });
      r.ok ? (toast('已归档（可恢复）'), loadSkills(), loadArchived()) : toast(r.error, true);
    }));
  }
  loadArchived();
}

async function loadArchived() {
  const d = await api('/api/skills/archived');
  const box = $('#archivedList');
  if (!d.items || !d.items.length) { box.innerHTML = '<div class="empty">无</div>'; return; }
  box.innerHTML = d.items.map(n => `
    <div class="item">
      <div class="item-name">${escapeHtml(n)}</div>
      <div class="acts"><button class="btn tiny" data-ak="${escapeHtml(n)}">恢复</button></div>
    </div>`).join('');
  $$('#archivedList [data-ak]').forEach(b => b.addEventListener('click', async () => {
    const r = await post('/api/skills/toggle', { name: b.dataset.ak, enable: true });
    r.ok ? (toast('已恢复'), loadSkills(), loadArchived()) : toast(r.error, true);
  }));
}

$('#btnSkillInstall').addEventListener('click', async () => {
  const n = $('#skillInstallName').value.trim();
  if (!n) return toast('填技能名', true);
  const r = await post('/api/skills/install', { name: n });
  toast(r.ok ? '安装完成' : (r.output || r.error || '失败').slice(0, 120), !r.ok);
  if (r.ok) { $('#skillInstallName').value = ''; loadSkills(); }
});

/* ---------------- 记忆 ---------------- */
async function loadMemory() {
  const d = await api('/api/memories');
  const box = $('#memList');
  if (!d.items || !d.items.length) { box.innerHTML = '<div class="empty">暂无记忆文件</div>'; return; }
  box.innerHTML = d.items.map(m => `
    <div class="item">
      <div class="item-name">${escapeHtml(m.name)}</div>
      <div class="item-meta">${m.kb} KB</div>
    </div>`).join('');
  const total = d.items.reduce((a, b) => a + b.kb, 0);
  $('#memHint').textContent = `${d.items.length} 个 · 共 ${(total / 1024).toFixed(2)} MB`;
}

/* ---------------- 任务 ---------------- */
async function loadCron() {
  const d = await api('/api/cron');
  const box = $('#cronList');
  if (!d.items || !d.items.length) { box.innerHTML = '<div class="empty">没有定时任务</div>'; return; }
  box.innerHTML = d.items.map(c => `
    <div class="item">
      <div style="min-width:0">
        <div class="item-name">${escapeHtml(c.name)}
          <span class="tag ${c.disabled ? 'off' : 'on'}">${c.disabled ? '已禁用' : '启用'}</span></div>
        <pre class="cron-body">${escapeHtml(c.body)}</pre>
      </div>
      <div class="acts">
        <button class="btn tiny" data-ck="${escapeHtml(c.name)}" data-en="${c.disabled ? 1 : 0}">
          ${c.disabled ? '启用' : '禁用'}</button>
      </div>
    </div>`).join('');
  $$('#cronList [data-ck]').forEach(b => b.addEventListener('click', async () => {
    const r = await post('/api/cron/toggle', { name: b.dataset.ck, enable: b.dataset.en === '1' });
    r.ok ? (toast('已更新'), loadCron(), loadAudit()) : toast(r.error, true);
  }));
}

/* ---------------- 审计 ---------------- */
async function loadAudit() {
  const d = await api('/api/audit');
  const box = $('#auditList');
  if (!d.items || !d.items.length) {
    box.innerHTML = '<div class="empty">还没有任何变更记录</div>';
    return;
  }
  box.innerHTML = d.items.map(a => `
    <div class="item">
      <div style="min-width:0">
        <div class="item-name">${escapeHtml(a.action)}</div>
        <div class="item-desc">${escapeHtml(a.detail || '')}</div>
      </div>
      <div class="item-meta">${escapeHtml(a.time || '')}<br>${escapeHtml(a.actor || '')}</div>
    </div>`).join('');
}

/* ---------------- 对话 ---------------- */
function addMsg(role, text, ms) {
  const flow = $('#chatFlow');
  const el = document.createElement('div');
  el.className = 'msg ' + role;
  const b = document.createElement('div');
  b.className = 'bubble';
  b.textContent = text;
  el.appendChild(b);
  if (ms) {
    const m = document.createElement('div');
    m.className = 'meta';
    m.textContent = (role === 'me' ? '已发送' : '耗时 ') + (ms / 1000).toFixed(1) + 's';
    el.appendChild(m);
  }
  flow.appendChild(el);
  flow.scrollTop = flow.scrollHeight;
  return el;
}

async function send() {
  if (state.busy) return;
  const ta = $('#chatInput');
  const msg = ta.value.trim();
  if (!msg) return;

  addMsg('me', msg);
  ta.value = ''; ta.style.height = 'auto';

  state.busy = true;
  $('#btnSend').disabled = true;

  const useStream = !$('#chkStream') || $('#chkStream').checked;

  if (useStream) {
    await sendStream(msg);
  } else {
    const wait = document.createElement('div');
    wait.className = 'msg ai';
    wait.innerHTML = '<div class="bubble"><span class="thinking"><i></i><i></i><i></i></span></div>';
    $('#chatFlow').appendChild(wait);
    $('#chatFlow').scrollTop = $('#chatFlow').scrollHeight;

    try {
      const d = await post('/api/chat', { message: msg });
      wait.remove();
      if (d.ok) addMsg('ai', d.reply || '（无输出）', d.ms);
      else { addMsg('ai', '执行失败：' + (d.reply || d.error || '未知错误')); toast('Hermes 未返回成功结果', true); }
    } catch (e) {
      wait.remove();
      addMsg('ai', '请求失败：' + e.message);
      toast('对话请求失败', true);
    } finally {
      state.busy = false;
      $('#btnSend').disabled = false;
    }
  }
}

/* ---------------- 流式对话（SSE） ---------------- */
async function sendStream(msg) {
  const flow = $('#chatFlow');
  const el = document.createElement('div');
  el.className = 'msg ai';
  el.innerHTML = '<div class="bubble"><span class="typing-cursor">▋</span></div>';
  flow.appendChild(el);
  flow.scrollTop = flow.scrollHeight;
  const bubble = el.querySelector('.bubble');

  let textBuf = '';
  let ms = 0;

  try {
    const resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg })
    });

    if (!resp.ok) {
      const d = await resp.json().catch(() => ({}));
      bubble.textContent = '执行失败：' + (d.error || 'HTTP ' + resp.status);
      state.busy = false; $('#btnSend').disabled = false;
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop(); // 不完整的行留到下次
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let evt;
        try { evt = JSON.parse(line.slice(6)); } catch { continue; }
        if (evt.type === 'token') {
          textBuf += evt.content || '';
          bubble.innerHTML = escapeHtml(textBuf) + '<span class="typing-cursor">▋</span>';
          flow.scrollTop = flow.scrollHeight;
        } else if (evt.type === 'tool_call') {
          renderToolCall(bubble, evt, false);
          flow.scrollTop = flow.scrollHeight;
        } else if (evt.type === 'tool_result') {
          renderToolCall(bubble, evt, true);
          flow.scrollTop = flow.scrollHeight;
        } else if (evt.type === 'error') {
          textBuf += '\n[错误] ' + (evt.content || '');
          bubble.innerHTML = escapeHtml(textBuf);
        } else if (evt.type === 'done') {
          ms = evt.ms || 0;
        }
      }
    }
    // 去掉光标
    const cur = bubble.querySelector('.typing-cursor');
    if (cur) cur.remove();
    if (!textBuf && !bubble.querySelector('.tool-call')) {
      bubble.textContent = '（无输出）';
    }
    if (ms) {
      const t = document.createElement('span');
      t.className = 'msg-time';
      t.textContent = ` ${ms}ms`;
      el.appendChild(t);
    }
  } catch (e) {
    bubble.textContent = '请求失败：' + e.message;
    toast('流式对话失败', true);
  } finally {
    state.busy = false;
    $('#btnSend').disabled = false;
  }
}

function renderToolCall(bubble, evt, isResult) {
  let card = bubble.querySelector('.tool-call:last-child');
  if (!card || card.dataset.name !== (evt.name || '')) {
    card = document.createElement('div');
    card.className = 'tool-call';
    card.dataset.name = evt.name || '';
    const head = document.createElement('div');
    head.className = 'tc-head';
    head.textContent = '🔧 ' + (evt.name || 'tool');
    card.appendChild(head);
    bubble.appendChild(card);
  }
  if (isResult || evt.result) {
    const r = document.createElement('div');
    r.className = 'tc-result';
    r.textContent = typeof (evt.result || evt.content) === 'string'
      ? (evt.result || evt.content) : JSON.stringify(evt.result || evt.content, null, 2);
    card.appendChild(r);
  } else if (evt.args || evt.content) {
    const a = document.createElement('div');
    a.className = 'tc-args';
    a.textContent = typeof (evt.args || evt.content) === 'string'
      ? (evt.args || evt.content) : JSON.stringify(evt.args || evt.content, null, 2);
    card.appendChild(a);
  }
}

/* ---------------- 仪表盘（官方 iframe 嵌入） ---------------- */
async function loadDashboard() {
  const frame = $('#dashFrame');
  const fallback = $('#dashFallback');
  if (!frame) return;
  // 探测官方后端是否可达
  try {
    const r = await fetch('/proxy/api/status', { headers: { 'Accept': 'application/json' } });
    if (r.ok) {
      frame.src = '/proxy/';
      frame.style.display = 'block';
      fallback.hidden = true;
    } else {
      throw new Error('not ok');
    }
  } catch {
    frame.style.display = 'none';
    fallback.hidden = false;
  }
}

/* ---------------- 事件 ---------------- */

/* 移动端：汉堡菜单 + 遮罩抽屉 */
const _navEl = document.querySelector('.sidebar');
const _scrimEl = document.getElementById('scrim');
function closeNavMobile() {
  if (_navEl) _navEl.classList.remove('open');
  if (_scrimEl) _scrimEl.classList.remove('show');
}
const _btnMenu = document.getElementById('btnMenu');
if (_btnMenu) _btnMenu.addEventListener('click', () => {
  const open = _navEl.classList.toggle('open');
  _scrimEl.classList.toggle('show', open);
});
if (_scrimEl) _scrimEl.addEventListener('click', closeNavMobile);

$('#btnSend').addEventListener('click', send);
$('#chatInput').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
$('#chatInput').addEventListener('input', function () {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 150) + 'px';
});
$$('.chip').forEach(c => {
  c.addEventListener('click', () => { $('#chatInput').value = c.dataset.q; $('#chatInput').focus(); });
});

$('#btnRefresh').addEventListener('click', () => {
  loadOverview();
  if (LOADERS[state.view]) LOADERS[state.view]();
  toast('已刷新');
});

/* ---------------- 活体探测 ---------------- */
$('#btnProbe').addEventListener('click', async (e) => {
  const deep = e.shiftKey;
  const btn = $('#btnProbe');
  btn.disabled = true; btn.textContent = deep ? '深度探测中…' : '探测中…';
  try {
    const d = await post('/api/probe', { deep });
    renderProbe(d);
    toast(d.ok ? `活体探测正常（${(d.ms / 1000).toFixed(1)}s）` : '探测发现问题', !d.ok);
  } catch (err) {
    toast('探测失败：' + err.message, true);
  } finally {
    btn.disabled = false; btn.textContent = '活体探测';
    loadOverview();
  }
});

function renderProbe(d) {
  const panel = $('#probePanel');
  panel.hidden = false;
  $('#probeHint').textContent =
    `${(d.ms / 1000).toFixed(1)}s · ${d.deep ? '深度（含模型连通）' : '轻量（零成本）'}`;
  $('#probeSteps').innerHTML = (d.steps || []).map(s => `
    <div class="pstep ${s.ok ? 'ok' : 'bad'}">
      <span class="pdot"></span>
      <span class="pname">${escapeHtml(s.name)}</span>
      <span class="pdet">${escapeHtml(s.detail || '')}</span>
    </div>`).join('');
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* ---------------- 体检 ---------------- */
async function runScan(kind, btn) {
  const out = $('#scanOut');
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = '运行中…';
  out.textContent = '执行中，请稍候…';
  const d = await post('/api/scan', { kind });
  if (!d.ok) {
    out.textContent = '执行失败：' + (d.error || '未知错误') + (d.hint ? '\n提示：' + d.hint : '');
    toast('巡检失败', true);
  } else {
    out.textContent = `$ bash ${d.name}   (退出码 ${d.rc}，${(d.ms / 1000).toFixed(1)}s)\n` +
                      '─'.repeat(56) + '\n' + d.output;
    $('#scanHint').textContent = `${d.name} · ${(d.ms / 1000).toFixed(1)}s · 退出码 ${d.rc}`;
    toast(d.rc === 0 ? '巡检完成，无异常' : '巡检发现需要关注的问题', d.rc !== 0);
  }
  btn.disabled = false; btn.textContent = label;
}
$('#btnHealth').addEventListener('click', e => runScan('health', e.currentTarget));
$('#btnSec').addEventListener('click', e => runScan('security', e.currentTarget));

window.addEventListener('resize', () => {
  if (state.data) drawChart(state.data.history || []);
});

/* ---------------- 启动 ---------------- */
async function loadConfig() {
  const d = await api('/api/config');
  if (!d.ok) return;
  $('#footMode').textContent = d.mode || '-';
  $('#footDir').textContent = d.hermes_dir || '-';
  $('#footQuota').textContent = fmtMB(d.quota_mb || 0);
  const w = $('#footWrite');
  if (d.readonly) { w.textContent = '只读模式'; w.className = 'warn-text'; }
  else if (!d.writable) { w.textContent = '不可写'; w.className = 'bad-text'; }
  else { w.textContent = '可写'; w.className = 'ok-text'; }
  if (!d.has_yaml) console.warn('缺少 ruamel.yaml，config.yaml 语法校验已跳过');
}

/* ---------------- 启动（鉴权感知） ---------------- */
let _entered = false;
function enterApp() {
  if (_entered) return;
  _entered = true;
  $('#loginScreen').hidden = true;
  loadOverview();
  loadConfig();
  setInterval(loadOverview, 60000);
}

async function boot() {
  const d = await api('/api/overview');
  if (d.need_auth) { showLogin(); return; }
  if (!d.ok) { toast('数据加载失败：' + (d.error || '接口错误'), true); return; }
  enterApp();
}

/* ---------------- 登录 / 改密 / 登出 ---------------- */
function showLogin() {
  $('#loginScreen').hidden = false;
  $('#loginErr').textContent = '';
  setTimeout(() => $('#loginPw').focus(), 50);
}

async function doLogin() {
  const pw = $('#loginPw').value;
  const r = await post('/api/login', { password: pw });
  if (!r.ok) { $('#loginErr').textContent = r.error || '登录失败'; return; }
  $('#loginPw').value = '';
  if (r.must_change) {
    openPwModal(true);
    toast('首次登录，请先修改初始密码');
    return;
  }
  enterApp();
  toast('登录成功');
}

function openPwModal(force) {
  $('#pwModal').hidden = false;
  $('#pwErr').textContent = '';
  $('#pwOld').value = $('#pwNew').value = $('#pwNew2').value = '';
  $('#pwModalTitle').textContent = force ? '修改初始密码（必须）' : '修改登录密码';
  $('#btnPwCancel').style.display = force ? 'none' : '';
  setTimeout(() => (force ? $('#pwNew') : $('#pwOld')).focus(), 50);
}
function closePwModal() { $('#pwModal').hidden = true; }

async function doChangePw() {
  const old = $('#pwOld').value, nw = $('#pwNew').value, nw2 = $('#pwNew2').value;
  if (nw.length < 8) return $('#pwErr').textContent = '新密码至少 8 位';
  if (nw !== nw2) return $('#pwErr').textContent = '两次输入不一致';
  const r = await post('/api/change_password', { old, new: nw });
  if (!r.ok) return $('#pwErr').textContent = r.error || '修改失败';
  closePwModal();
  toast('密码已更新');
  // 强制改密流程：改完才正式进入应用
  if (!$('#loginScreen').hidden) enterApp();
}

async function doLogout() {
  await post('/api/logout');
  location.reload();
}

$('#btnLogin').addEventListener('click', doLogin);
$('#loginPw').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
$('#btnPwSave').addEventListener('click', doChangePw);
$('#btnPwCancel').addEventListener('click', closePwModal);
$('#btnChangePw').addEventListener('click', () => openPwModal(false));
$('#btnLogout').addEventListener('click', doLogout);
$('#btnLogout2').addEventListener('click', doLogout);

/* ---------------- 系统：版本 / 升级 / 自检 ---------------- */
async function loadSystem() {
  const d = await api('/api/version');
  if (!d.ok) return;
  $('#sysVer').textContent = d.version || 'dev';
  $('#sysVerSub').textContent = d.git ? 'git: ' + d.git : '发布版本';
  $('#sysUp').textContent = d.upstream || '—';
  $('#sysUpSub').textContent = d.has_update ? '有新版本可用 ↑' : (d.repo ? '已是最新' : '未配置 UPDATE_REPO');
  $('#sysUp').closest('.card').classList.toggle('warn', !!d.has_update);
  $('#sysAuth').textContent = d.auth ? '启用' : '已关闭';
}

$('#btnDashUpdate').addEventListener('click', async (e) => {
  const btn = e.currentTarget; btn.disabled = true; btn.textContent = '升级中…';
  const r = await post('/api/dash-update', {});
  $('#updOut').textContent = r.ok ? (r.output || '已更新') + '\n\n（正在重启以生效…）'
                                  : '失败：' + (r.error || r.output || '未知');
  if (r.restart) toast('已拉取新代码，正在重启…');
  else toast(r.ok ? '已更新' : '升级失败', !r.ok);
  btn.disabled = false; btn.textContent = '升级工作台（git pull）';
  if (!r.restart) loadSystem();
});

$('#btnHermesUpdate').addEventListener('click', async (e) => {
  const btn = e.currentTarget; btn.disabled = true; btn.textContent = '升级中…';
  const r = await post('/api/hermes', { args: ['update'] });
  $('#updOut').textContent = (r.output || r.error || '无输出');
  toast(r.ok ? 'Hermes 升级指令已执行' : '执行失败', !r.ok);
  btn.disabled = false; btn.textContent = '升级 Hermes';
});

$('#btnDoctor').addEventListener('click', async (e) => {
  const btn = e.currentTarget; btn.disabled = true; btn.textContent = '自检中…';
  const r = await post('/api/doctor', {});
  $('#docOut').textContent = (r.output || r.error || '无输出');
  toast(r.ok ? 'doctor 完成' : 'doctor 发现问题', !r.ok);
  btn.disabled = false; btn.textContent = '运行 hermes doctor';
});

$('#btnScanSec').addEventListener('click', e => runScan('security', e.currentTarget));

/* ---------------- 功能：Hermes 命令台 + 配置开关 ---------------- */
const HERMES_CMDS = [
  ['doctor', '自检 doctor', []],
  ['update', '升级 Hermes', []],
  ['memory consolidate', '整理记忆', []],
  ['memory cleanup', '清理记忆', []],
  ['curator status', '技能治理状态', []],
  ['session list', '会话列表', []],
  ['skills update', '更新全部技能', []],
  ['skills catalog', '技能目录', []],
  ['mcp catalog', 'MCP 目录', []],
  ['tools list', '工具集列表', []],
  ['profile list', '多身份列表', []],
  ['model list', '模型列表', []],
];

async function loadHermes() {
  $('#cmdGrid').innerHTML = HERMES_CMDS.map(([args, label]) =>
    `<button class="btn ghost cmd-btn" data-args="${escapeHtml(args)}">${escapeHtml(label)}</button>`).join('');
  $$('#cmdGrid .cmd-btn').forEach(b => b.addEventListener('click', () => runHermes(b.dataset.args)));
  // 配置开关
  const d = await api('/api/cfg');
  if (!d.ok) { $('#cfgBox').innerHTML = '<div class="empty">读取失败</div>'; return; }
  const v = d.values || {};
  const rows = [
    ['tools.async_enabled', '工具集异步执行', 'bool', v['tools.async_enabled']],
    ['memory.compression.enabled', '长会话自动压缩', 'bool', v['memory.compression.enabled']],
    ['memory.memory_window', '记忆窗口(条)', 'int', v['memory.memory_window']],
    ['memory.top_k', '记忆检索 top_k', 'int', v['memory.top_k']],
    ['memory.retrieval.hybrid_search', '混合检索', 'bool', v['memory.retrieval.hybrid_search']],
    ['approvals.mode', '审批模式(smart/manual)', 'str', v['approvals.mode']],
    ['terminal.backend', '终端后端(local/docker)', 'str', v['terminal.backend']],
    ['worker_pool_size', '工作线程数', 'int', v['worker_pool_size']],
  ];
  $('#cfgBox').innerHTML = rows.map(([path, label, type, val]) => `
    <div class="cfg-row">
      <span class="cfg-name">${escapeHtml(label)}</span>
      <span class="cfg-path">${escapeHtml(path)}</span>
      <span class="cfg-ctl" data-path="${escapeHtml(path)}" data-type="${type}">
        ${type === 'bool'
          ? `<button class="btn tiny ${val ? 'on' : 'off'}" data-bool="${val ? 1 : 0}">${val ? '开' : '关'}</button>`
          : `<input class="cfg-in" value="${escapeHtml(String(val ?? ''))}" placeholder="—">`}
      </span>
    </div>`).join('');
  $$('#cfgBox .cfg-ctl').forEach(box => {
    const path = box.dataset.path, type = box.dataset.type;
    if (type === 'bool') {
      box.querySelector('button').addEventListener('click', async (e) => {
        const nv = e.currentTarget.dataset.bool !== '1';
        const r = await post('/api/cfg', { path, value: nv });
        if (!r.ok) return toast(r.error, true);
        e.currentTarget.dataset.bool = nv ? '1' : '0';
        e.currentTarget.textContent = nv ? '开' : '关';
        e.currentTarget.className = 'btn tiny ' + (nv ? 'on' : 'off');
        markPending(); toast('已保存，需重启生效');
      });
    } else {
      const inp = box.querySelector('input');
      inp.addEventListener('change', async () => {
        const r = await post('/api/cfg', { path, value: inp.value.trim() });
        if (!r.ok) return toast(r.error, true);
        markPending(); toast('已保存，需重启生效');
      });
    }
  });
  // 网关白名单
  const env = await api('/api/env');
  if (env.ok) {
    const t = (env.items || []).find(x => x.key === 'TELEGRAM_ALLOWED_USERS');
    $('#tgUsers').value = t ? t.value : '';
  }
}

async function runHermes(args) {
  if (typeof args !== 'string') args = $('#hermesArgs').value.trim();
  if (!args) return toast('请输入命令', true);
  const argv = args.split(/\s+/);
  $('#hermesOut').textContent = '执行中：hermes ' + argv.join(' ') + ' …';
  const r = await post('/api/hermes', { args: argv });
  $('#hermesOut').textContent = (r.output || r.error || '无输出');
  toast(r.ok ? '执行完成' : '执行失败/无输出', !r.ok);
}

$('#btnHermesRun').addEventListener('click', () => runHermes());
$('#hermesArgs').addEventListener('keydown', e => { if (e.key === 'Enter') runHermes(); });

$('#btnTgSave').addEventListener('click', async () => {
  const v = $('#tgUsers').value.trim();
  const r = await post('/api/env', { updates: { TELEGRAM_ALLOWED_USERS: v } });
  if (!r.ok) return toast(r.error, true);
  $('#tgHint').textContent = '已保存，需重启 Hermes 生效';
  markPending();
  setTimeout(() => ($('#tgHint').textContent = ''), 4000);
});

boot();


/* ---------------- 主题 ---------------- */
const THEME_KEY = 'hermes-dash-theme';
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  $('#btnTheme').textContent = t === 'light' ? '◐' : '◑';
  if (state.data) drawChart(state.data.history || []);
}
(function () {
  const saved = localStorage.getItem(THEME_KEY) ||
    (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  applyTheme(saved);
})();
$('#btnTheme').addEventListener('click', () => {
  const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
});

/* ---------------- 成本 ---------------- */
const money = v => '¥' + (v || 0).toFixed(v >= 100 ? 1 : 3);
const ktok = n => n >= 1e6 ? (n / 1e6).toFixed(2) + 'M'
  : n >= 1000 ? (n / 1000).toFixed(1) + 'K' : String(n || 0);

async function loadCost() {
  const d = await api('/api/cost');
  if (!d.ok) { toast(d.error, true); return; }
  state.cost = d;

  $('#costCards').innerHTML = [
    ['今日', d.today], ['近 7 天', d.week], ['近 30 天', d.month],
  ].map(([k, v]) => `
    <div class="ccard">
      <div class="k">${k}</div>
      <div class="v">${money(v.cost)}</div>
      <div class="s">${ktok(v.in)} in / ${ktok(v.out)} out · ${v.calls} 次</div>
    </div>`).join('');

  const b = d.budget || {};
  const hasBudget = b.daily || b.monthly;
  $('#budgetHint').textContent = hasBudget
    ? `日预算 ${b.daily || '—'} / 月预算 ${b.monthly || '—'}`
    : '未设置预算（用 BUDGET_DAILY / BUDGET_MONTHLY 环境变量设置）';
  const tag = $('#budgetTag');
  tag.className = 'budget-tag ' + (b.level || 'ok');
  tag.textContent = hasBudget ? `${b.pct}%` : '未设置';
  $('#bBudget').style.width = Math.min(b.pct || 0, 100) + '%';
  $('#bBudget').classList.toggle('hot', (b.pct || 0) >= 80);

  const note = $('#costNote');
  if (d.note) { note.hidden = false; note.textContent = d.note; } else note.hidden = true;

  const rows = d.by_model || [];
  $('#modelHint').textContent = rows.length ? rows.length + ' 个模型' : '—';
  $('#modelTbl').innerHTML = rows.length ? `
    <tr><th>模型</th><th class="num">调用</th><th class="num">输入</th>
        <th class="num">输出</th><th class="num">花费</th></tr>` +
    rows.map(r => `<tr><td>${escapeHtml(r.model)}</td><td class="num">${r.calls}</td>
      <td class="num">${ktok(r.in)}</td><td class="num">${ktok(r.out)}</td>
      <td class="num">${money(r.cost)}</td></tr>`).join('')
    : '<tr><td class="empty">还没有用量数据</td></tr>';

  const days = d.by_day || [];
  const max = Math.max(0.0001, ...days.map(x => x.cost));
  $('#daySpark').innerHTML = days.length ? days.map(x => `
    <i style="height:${Math.max(3, x.cost / max * 100)}%" title="${x.date} ${money(x.cost)}">
      ${days.length <= 16 ? `<span>${x.date}</span>` : ''}</i>`).join('')
    : '<div class="empty">暂无数据</div>';
}

async function loadPricing() {
  const d = await api('/api/cost/pricing');
  if (!d.ok) return toast(d.error, true);
  $('#pricingEditor').value = JSON.stringify(d.pricing || {}, null, 2);
  state.defaultPricing = d.default;
}
$('#btnPricingSave').addEventListener('click', async () => {
  let obj;
  try { obj = JSON.parse($('#pricingEditor').value); }
  catch (e) { return toast('JSON 格式错误：' + e.message, true); }
  const r = await post('/api/cost/pricing', obj);
  r.ok ? toast('价格表已保存') : toast(r.error, true);
});
$('#btnPricingReset').addEventListener('click', async () => {
  if (!confirm('恢复默认价格表？你的校准会丢失。')) return;
  const r = await post('/api/cost/pricing', state.defaultPricing || {});
  r.ok ? (toast('已恢复默认'), loadPricing()) : toast(r.error, true);
});

/* ---------------- 告警渠道（schema 驱动，支持逐条编辑） ---------------- */
const RULE_LABELS = {
  down: '进程停止', quota: '配额 ≥90%',
  errors: '24h 错误 >50', budget: '预算超 80%',
};
let _editingIndex = -1;   // -1 = 新增模式；>=0 = 正在编辑该渠道

// 按渠道类型动态渲染字段
function renderChanFields(type, values) {
  const schema = (state.notifySchema && state.notifySchema[type]) || [];
  const box = $('#chDynamic');
  if (!schema.length) { box.innerHTML = '<div class="empty">该类型无需额外参数</div>'; return; }
  box.innerHTML = schema.map(f => {
    const v = (values && values[f.name] != null) ? values[f.name] : '';
    const disp = f.secret ? (v && String(v).includes('•') ? v : '') : v; // 密钥不回显明文
    const ph = escapeHtml(f.placeholder || '');
    const inpType = f.secret ? 'password' : (f.kind === 'number' ? 'number' : 'text');
    return `<label class="${f.optional ? '' : 'wide'}">${escapeHtml(f.label)}
      <input data-f="${escapeHtml(f.name)}" type="${inpType}"
             placeholder="${ph}" value="${escapeHtml(disp)}"
             ${f.secret ? 'autocomplete="off"' : ''}></label>`;
  }).join('');
}

function collectChanFields(type) {
  // 收集动态表单里的字段值，密钥若仍是脱敏样式（含 •）则保留原值
  const obj = {};
  $$('#chDynamic [data-f]').forEach(inp => {
    const k = inp.dataset.f, v = inp.value;
    if (v !== '' && !v.includes('•')) obj[k] = v;
  });
  return obj;
}

async function loadNotify() {
  const d = await api('/api/notify');
  if (!d.ok) return toast(d.error, true);
  state.notify = d.config;
  state.notifySchema = d.schema ? d.schema.fields : null;

  const sel = $('#chType');
  if (!sel.options.length) {
    sel.innerHTML = Object.entries(d.types)
      .map(([k, v]) => `<option value="${k}">${escapeHtml(v)}</option>`).join('');
  }
  const sync = () => { renderChanFields(sel.value, null); $('#chHint').textContent = ''; };
  sel.onchange = () => { if (_editingIndex < 0) { $('#chName').value = ''; sync(); } };
  if (_editingIndex < 0) sync();

  const chans = (d.config.channels || []);
  $('#chanList').innerHTML = chans.length ? chans.map((c, i) => {
    const fields = (state.notifySchema && state.notifySchema[c.type]) || [];
    const meta = fields.filter(f => c[f.name] != null && !f.secret)
      .map(f => `${escapeHtml(f.label)}: ${escapeHtml(String(c[f.name]).slice(0, 40))}`)
      .concat(c.url ? ['地址已设置'] : []).join(' · ');
    return `
    <div class="chan">
      <div class="chan-top">
        <div>
          <span class="chan-name">${escapeHtml(c.name || c.type)}</span>
          <span class="tag ${c.enabled === false ? 'off' : 'on'}">
            ${c.enabled === false ? '禁用' : '启用'}</span>
        </div>
        <div class="acts">
          <button class="btn tiny" data-en="${i}" data-on="${c.enabled === false ? 1 : 0}">
            ${c.enabled === false ? '启用' : '禁用'}</button>
          <button class="btn tiny" data-edit="${i}">编辑</button>
          <button class="btn tiny danger" data-rm="${i}">删除</button>
        </div>
      </div>
      <div class="item-meta" style="margin-top:6px">${escapeHtml(d.types[c.type] || c.type)}
        ${meta ? ' · ' + meta : ''}</div>
    </div>`;
  }).join('') : '<div class="empty">还没有配置渠道</div>';

  $$('#chanList [data-rm]').forEach(b => b.addEventListener('click', async () => {
    if (!confirm('删除该渠道？')) return;
    state.notify.channels.splice(+b.dataset.rm, 1);
    const r = await post('/api/notify', state.notify);
    r.ok ? (toast('已删除'), loadNotify()) : toast(r.error, true);
  }));
  $$('#chanList [data-en]').forEach(b => b.addEventListener('click', async () => {
    const c = state.notify.channels[+b.dataset.en];
    c.enabled = b.dataset.on === '1';
    const r = await post('/api/notify', state.notify);
    r.ok ? (toast(c.enabled ? '已启用' : '已禁用'), loadNotify()) : toast(r.error, true);
  }));
  $$('#chanList [data-edit]').forEach(b => b.addEventListener('click', () => {
    const i = +b.dataset.edit, c = state.notify.channels[i];
    _editingIndex = i;
    $('#chFormTitle').textContent = '编辑渠道：' + (c.name || c.type);
    $('#chType').value = c.type;
    $('#chName').value = c.name || '';
    renderChanFields(c.type, c);
    $('#btnChanAdd').textContent = '保存修改';
    $('#btnChanCancel').hidden = false;
    $('#chFormTitle').scrollIntoView({ behavior: 'smooth', block: 'center' });
  }));

  const rules = d.config.rules || {};
  $('#ruleBox').innerHTML = Object.entries(RULE_LABELS).map(([k, label]) => `
    <label><input type="checkbox" data-rule="${k}" ${rules[k] !== false ? 'checked' : ''}>
      ${label}</label>`).join('');
  $('#cooldown').value = d.config.cooldown_hours ?? 6;
}

$('#btnChanCancel').addEventListener('click', () => resetChanForm());

function resetChanForm() {
  _editingIndex = -1;
  $('#chFormTitle').textContent = '新增渠道';
  $('#chName').value = '';
  renderChanFields($('#chType').value, null);
  $('#btnChanAdd').textContent = '添加渠道';
  $('#btnChanCancel').hidden = true;
}

$('#btnChanAdd').addEventListener('click', async () => {
  const t = $('#chType').value;
  const name = $('#chName').value.trim() || t;
  const extra = collectChanFields(t);
  const c = Object.assign({ type: t, name, enabled: true }, extra);
  if (!Object.keys(extra).length) return toast('至少填一项参数', true);

  const cfg = state.notify || { channels: [], rules: {}, cooldown_hours: 6 };
  if (_editingIndex >= 0) {
    // 编辑模式：把未在表单中出现的原 secret 字段保留下来
    const old = cfg.channels[_editingIndex] || {};
    for (const f of (state.notifySchema[t] || [])) {
      if (f.secret && extra[f.name] == null && old[f.name] != null) c[f.name] = old[f.name];
    }
    cfg.channels[_editingIndex] = c;
  } else {
    cfg.channels = (cfg.channels || []).filter(x => (x.name || x.type) !== name);
    cfg.channels.push(c);
  }
  const r = await post('/api/notify', cfg);
  if (!r.ok) return toast(r.error, true);
  toast(_editingIndex >= 0 ? '已保存修改' : '渠道已添加');
  resetChanForm();
  loadNotify();
});

$('#btnNotifySave').addEventListener('click', async () => {
  const cfg = state.notify || { channels: [], rules: {}, cooldown_hours: 6 };
  cfg.rules = {};
  $$('#ruleBox [data-rule]').forEach(i => { cfg.rules[i.dataset.rule] = i.checked; });
  cfg.cooldown_hours = parseInt($('#cooldown').value || '6', 10);
  const r = await post('/api/notify', cfg);
  r.ok ? toast('告警配置已保存') : toast(r.error, true);
});

$('#btnNotifyTest').addEventListener('click', async () => {
  const r = await post('/api/notify/test', {});
  if (!r.ok) return toast(r.error || '推送失败', true);
  const bad = (r.results || []).filter(x => !x.ok);
  if (!bad.length) toast(`${r.results.length} 个渠道全部发送成功`);
  else toast('失败：' + bad.map(b => `${b.channel}(${b.msg})`).join('; '), true);
  loadAlertLog();
});

async function loadAlertLog() {
  const d = await api('/api/notify');
  const items = (d.ok && d.alerts) || [];
  $('#alertLog').innerHTML = items.length ? items.map(a => `
    <div class="alert-item">
      <div class="t">${escapeHtml(a.title)}</div>
      <div class="r">${escapeHtml(a.time)} · ${(a.sent || []).map(s =>
        `${escapeHtml(s.ch)} ${s.ok ? '✓' : '✗ ' + escapeHtml(s.msg || '')}`).join(' · ')}</div>
    </div>`).join('') : '<div class="empty">还没有发送过告警</div>';
}

/* ---------------- 对话接口（Hermes 的模型 API） ---------------- */
async function loadChatApi() {
  const d = await api('/api/chatapi');
  if (!d.ok) return toast(d.error, true);
  state.chatApi = d;
  const sel = $('#caProvider');
  sel.innerHTML = Object.entries(d.presets).map(([k, v]) =>
    `<option value="${k}">${escapeHtml(v.label)}</option>`).join('');
  if (d.provider) sel.value = d.provider;
  $('#caModel').value = d.model || '';
  $('#caKey').value = d.key_set ? (d.api_key || '') : '';
  $('#caKey').placeholder = d.key_set ? '已设置，留空保持不变' : '填你的 API Key';
  const isCustom = (d.provider || 'openai') === 'openai';
  $('#caBaseWrap').hidden = !isCustom;
  $('#caBase').value = isCustom ? (d.base_url || '') : '';
  $('#caCurrent').textContent = d.provider
    ? `当前：${escapeHtml((d.presets[d.provider] || {}).label || d.provider)} · ${d.model || '?'}`
    : '尚未配置';
  $('#caTip').textContent = d.provider && d.presets[d.provider]
    ? (d.presets[d.provider].tip || '') : '选择 Provider 后会显示注意事项。';

  $('#caPresets').innerHTML = Object.entries(d.presets).map(([k, v]) => `
    <label class="prov" data-k="${k}">
      <div class="prov-name">${escapeHtml(v.label)}</div>
      <div class="prov-model">${escapeHtml(v.model)}</div>
      <div class="prov-tip">${escapeHtml(v.tip || (v.base_url || ''))}</div>
    </label>`).join('');
  $$('#caPresets .prov').forEach(el => el.addEventListener('click', () => {
    const k = el.dataset.k, p = d.presets[k];
    $('#caProvider').value = k;
    $('#caModel').value = p.model || '';
    $('#caBaseWrap').hidden = k !== 'openai';
    if (k !== 'openai') $('#caBase').value = '';
    $('#caTip').textContent = p.tip || (p.base_url || '');
  }));
}

$('#caProvider').addEventListener('change', () => {
  const k = $('#caProvider').value;
  const p = (state.chatApi && state.chatApi.presets[k]) || {};
  $('#caBaseWrap').hidden = k !== 'openai';
  if (k !== 'openai') $('#caBase').value = '';
  $('#caTip').textContent = p.tip || p.base_url || '';
});

$('#btnChatApiSave').addEventListener('click', async () => {
  const r = await post('/api/chatapi', {
    provider: $('#caProvider').value,
    model: $('#caModel').value.trim(),
    api_key: $('#caKey').value,
    base_url: $('#caBase').value.trim(),
  });
  if (!r.ok) return toast(r.error, true);
  toast('已保存对话接口，需重启 Hermes 生效');
  markPending();
  loadChatApi(); loadAudit();
});
