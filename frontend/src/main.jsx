import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip } from 'recharts'
import './styles.css'

const api = (path, options) => fetch(path, options).then(async r => {
  if (!r.ok) throw new Error(await r.text())
  return r.json()
})

const pct = (n) => `${(Number(n || 0) * 100).toFixed(1)}%`
const eur = (n) => `€${Number(n || 0).toFixed(2)}`
const fmtDate = (s) => s ? new Date(s + (s.endsWith('Z') ? '' : 'Z')).toLocaleString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : '—'

function Stat({ label, value, sub }) {
  return <div className="stat"><div className="muted">{label}</div><div className="stat-value">{value}</div>{sub && <div className="sub">{sub}</div>}</div>
}

function AdminBar() {
  const [token, setToken] = useState(localStorage.getItem('adminToken') || '')
  const [action, setAction] = useState('')

  async function call(path, method = 'POST') {
    if (!token) return setAction('Vpiši admin token.')
    setAction('Izvajam…')
    try {
      const r = await fetch(path, { method, headers: { 'x-admin-token': token } })
      const j = await r.json()
      setAction(JSON.stringify(j))
    } catch (e) { setAction(String(e)) }
  }

  return <div className="admin-bar">
    <input
      placeholder="Admin token"
      value={token}
      onChange={e => { setToken(e.target.value); localStorage.setItem('adminToken', e.target.value) }}
    />
    <button onClick={() => call('/api/admin/run-cycle')}>Run cycle</button>
    <button onClick={() => call('/api/admin/relink-odds')}>Relink odds</button>
    <button onClick={() => call('/api/admin/clear-predictions')}>Clear predictions</button>
    <button onClick={() => call('/api/admin/odds-check', 'GET')}>Odds check</button>
    <button onClick={() => call('/api/admin/relink-status', 'GET')}>Relink status</button>
    {action && <span className="admin-result">{action}</span>}
  </div>
}

function Overview({ dash, days, setDays, refresh }) {
  const curve = useMemo(() => {
    if (!dash) return []
    let balance = 1000
    const points = [{ name: 'Start', balance }]
    const sorted = [...(dash.recent_bets || [])].reverse()
    sorted.forEach((b, i) => {
      if (b.pnl != null) { balance += Number(b.pnl); points.push({ name: `${i+1}`, balance: Number(balance.toFixed(2)) }) }
    })
    return points
  }, [dash])

  return <>
    <div className="toolbar-row">
      <select value={days} onChange={e => setDays(Number(e.target.value))}>
        <option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option>
      </select>
      <button onClick={refresh}>Refresh</button>
    </div>
    <section className="stats-grid">
      <Stat label="BANKROLL" value={eur(dash.bankroll)} sub="paper account" />
      <Stat label="P&L" value={eur(dash.pnl)} sub={`${days}-day period`} />
      <Stat label="ROI" value={pct(dash.roi)} sub={`${dash.settled} settled`} />
      <Stat label="WIN RATE" value={pct(dash.win_rate)} sub={`${dash.wins} wins`} />
      <Stat label="AVG EDGE" value={pct(dash.avg_edge)} sub={`${dash.bets} total bets`} />
      <Stat label="OPEN EXPOSURE" value={eur(dash.open_exposure)} sub="risk currently open" />
    </section>
    <section className="grid-two">
      <div className="panel">
        <div className="panel-head">
          <div><h2>Bankroll curve</h2><span>Based on settled paper bets</span></div>
          <strong>{eur(dash.bankroll)}</strong>
        </div>
        <div className="chart">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={curve}>
              <XAxis dataKey="name" hide />
              <YAxis hide domain={['dataMin - 20', 'dataMax + 20']} />
              <Tooltip />
              <Area type="monotone" dataKey="balance" strokeWidth={2} fillOpacity={0.18} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="panel">
        <div className="panel-head">
          <div><h2>Zadnje stave</h2><span>Zadnjih 8 paper stav</span></div>
          <strong>{(dash.recent_bets || []).length}</strong>
        </div>
        <div className="mini-list">
          {(dash.recent_bets || []).slice(0, 8).map(b => (
            <div key={b.id} className="mini-row">
              <b>{b.selection}</b>
              <span>{b.market}</span>
              <span>{Number(b.odds).toFixed(2)}</span>
              <span className="edge">{pct(b.edge)}</span>
            </div>
          ))}
          {!dash.recent_bets?.length && <div className="empty">Ni stav še.</div>}
        </div>
      </div>
    </section>
  </>
}

function MatchesView() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState(null)

  useEffect(() => {
    api('/api/matches/with-predictions?limit=100')
      .then(setRows).catch(console.error).finally(() => setLoading(false))
  }, [])

  async function openDetail(id) {
    try { setDetail(await api(`/api/matches/${id}`)) } catch (e) { alert(e.message) }
  }

  if (loading) return <div className="loading">Nalagam tekme…</div>

  return <>
    <div className="panel-head"><div><h2>Prihajajoče tekme</h2><span>{rows.length} tekem z napovedmi</span></div></div>
    <div className="table-wrap">
      <table>
        <thead><tr>
          <th>Datum</th><th>Domači</th><th>Gostje</th><th>1</th><th>X</th><th>2</th><th>Kvote</th><th>Stave</th><th></th>
        </tr></thead>
        <tbody>
          {rows.map(m => {
            const home = m.predictions.find(p => p.selection === 'HOME')
            const draw = m.predictions.find(p => p.selection === 'DRAW')
            const away = m.predictions.find(p => p.selection === 'AWAY')
            return <tr key={m.id}>
              <td>{fmtDate(m.kickoff)}</td>
              <td><b>{m.home_team}</b></td>
              <td>{m.away_team}</td>
              <td>{home ? pct(home.probability) : '—'}</td>
              <td>{draw ? pct(draw.probability) : '—'}</td>
              <td>{away ? pct(away.probability) : '—'}</td>
              <td>{m.odds_count}</td>
              <td>{m.bets_count}</td>
              <td><button className="small-btn" onClick={() => openDetail(m.id)}>Odpri</button></td>
            </tr>
          })}
          {!rows.length && <tr><td colSpan="9" className="empty">Ni prihajajočih tekem.</td></tr>}
        </tbody>
      </table>
    </div>
    {detail && <MatchModal detail={detail} onClose={() => setDetail(null)} />}
  </>
}

function PaperBetsView() {
  const [bets, setBets] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api('/api/bets?limit=200')
      .then(setBets).catch(console.error).finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="loading">Nalagam stave…</div>

  return <>
    <div className="panel-head"><div><h2>Paper Bets</h2><span>Vse simulirane stave</span></div></div>
    <div className="table-wrap">
      <table>
        <thead><tr>
          <th>Čas</th><th>Tekma</th><th>Datum tekme</th><th>Izbor</th><th>Trg</th><th>Kvota</th><th>Model</th><th>Edge</th><th>Stake</th><th>Status</th><th>P&L</th>
        </tr></thead>
        <tbody>
          {bets.map(b => {
            const f = b.fixture || {}
            return <tr key={b.id}>
              <td>{b.created_at ? new Date(b.created_at).toLocaleString() : '—'}</td>
              <td>{f.home_team ? <b>{f.home_team} – {f.away_team}</b> : <span className="muted">(ni tekme)</span>}</td>
              <td>{f.kickoff ? fmtDate(f.kickoff) : '—'}</td>
              <td><b>{b.selection}</b></td>
              <td>{b.market}</td>
              <td>{Number(b.odds).toFixed(2)}</td>
              <td>{pct(b.model_probability)}</td>
              <td className="edge">{pct(b.edge)}</td>
              <td>{eur(b.stake)}</td>
              <td><span className={`badge ${String(b.status).toLowerCase()}`}>{b.status}</span></td>
              <td>{b.pnl == null ? '—' : eur(b.pnl)}</td>
            </tr>
          })}
          {!bets.length && <tr><td colSpan="11" className="empty">Ni stav še.</td></tr>}
        </tbody>
      </table>
    </div>
  </>
}

function ModelView({ config }) {
  return <div className="panel">
    <div className="panel-head"><div><h2>Model</h2><span>Poisson + Elo baseline</span></div></div>
    <div className="info-block">
      <h3>Kako deluje</h3>
      <p>Model uporablja kombinacijo dveh pristopov:</p>
      <ul>
        <li><b>Elo rating</b> – ocena moči ekipe glede na zgodovino rezultatov (domači faktor +60).</li>
        <li><b>Poissonova porazdelitev</b> – pričakovani goli ekipe glede na formo (zadnjih 5 tekem), Elo razliko in poškodbe.</li>
      </ul>
      <h3>Trenutne nastavitve</h3>
      <table className="kv-table">
        <tbody>
          <tr><td>MIN_EDGE</td><td><b>{pct(config.min_edge)}</b></td></tr>
          <tr><td>Bankroll</td><td><b>{eur(config.initial_bankroll || 1000)}</b></td></tr>
          <tr><td>Sezona</td><td><b>{config.season}</b></td></tr>
          <tr><td>Lige</td><td><b>{(config.tracked_leagues || []).join(', ')}</b></td></tr>
          <tr><td>Kvote omogočene</td><td><b>{config.odds_enabled ? 'DA' : 'NE'}</b></td></tr>
          <tr><td>Paper trading</td><td><b>{config.paper_trading ? 'DA' : 'NE'}</b></td></tr>
        </tbody>
      </table>
    </div>
  </div>
}

function DataView() {
  return <div className="panel">
    <div className="panel-head"><div><h2>Data</h2><span>Upravljanje podatkov</span></div></div>
    <div className="info-block">
      <h3>Viri podatkov</h3>
      <ul>
        <li><b>Football-Data.org</b> – tekme, ekipe, rezultati (5 glavnih lig + sezona 2025 in 2026).</li>
        <li><b>The Odds API</b> – kvote stavnic (EPL).</li>
      </ul>
      <h3>Ročne akcije</h3>
      <p>Gumbe najdeš v zgornji vrstici (Admin bar). Za dodajanje novih tekem uporabi backfill prek PowerShella:</p>
      <pre>Invoke-RestMethod -Uri ".../api/admin/backfill?competition_code=PL&season=2026" -Method Post -Headers @{{"x-admin-token"="TVOJ_TOKEN"}}</pre>
    </div>
  </div>
}

function SettingsView({ config }) {
  return <div className="panel">
    <div className="panel-head"><div><h2>Settings</h2><span>Trenutne nastavitve sistema</span></div></div>
    <div className="info-block">
      <table className="kv-table">
        <tbody>
          {Object.entries(config).map(([k, v]) => (
            <tr key={k}><td>{k}</td><td><b>{Array.isArray(v) ? v.join(', ') : String(v)}</b></td></tr>
          ))}
        </tbody>
      </table>
      <p className="muted" style={{marginTop: 16}}>
        Spremembe se naredijo v Render Environment (Save Changes). Sistem se bo samodejno ponovno zagnal.
      </p>
    </div>
  </div>
}

function MatchModal({ detail, onClose }) {
  const f = detail.fixture
  return <div className="modal-backdrop" onClick={onClose}>
    <div className="modal" onClick={e => e.stopPropagation()}>
      <div className="modal-head">
        <div>
          <h2>{f.home_team} vs {f.away_team}</h2>
          <span>{fmtDate(f.kickoff)} · {f.status}{f.minute ? ` ${f.minute}'` : ''}</span>
        </div>
        <button onClick={onClose}>×</button>
      </div>
      <div className="prob-grid">
        <div><span>HOME</span><b>{pct(detail.model.home)}</b></div>
        <div><span>DRAW</span><b>{pct(detail.model.draw)}</b></div>
        <div><span>AWAY</span><b>{pct(detail.model.away)}</b></div>
      </div>
      <div className="confidence">Model: {detail.model.name} · confidence {pct(detail.model.confidence)}</div>
      <h3>Kvote (zadnjih 30)</h3>
      <div className="odds-list">
        {detail.odds.length ? detail.odds.map((o, i) => (
          <div key={i}>
            <span>{o.bookmaker}</span>
            <span>{o.market}</span>
            <b>{o.selection}</b>
            <strong>{Number(o.odds).toFixed(2)}</strong>
          </div>
        )) : <div className="empty">Ni kvot.</div>}
      </div>
    </div>
  </div>
}

function App() {
  const [view, setView] = useState('overview')
  const [dash, setDash] = useState(null)
  const [config, setConfig] = useState({})
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(true)

  async function refresh() {
    setLoading(true)
    try {
      const [d, c] = await Promise.all([api(`/api/dashboard?days=${days}`), api('/api/config')])
      setDash(d); setConfig(c)
    } finally { setLoading(false) }
  }

  useEffect(() => { refresh() }, [days])

  useEffect(() => {
    const t = setInterval(refresh, 60000)
    return () => clearInterval(t)
  }, [days])

  const nav = [
    { key: 'overview', label: 'Overview' },
    { key: 'matches', label: 'Matches' },
    { key: 'bets', label: 'Paper Bets' },
    { key: 'model', label: 'Model' },
    { key: 'data', label: 'Data' },
    { key: 'settings', label: 'Settings' },
  ]

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">FE</span>
        <div><b>Football Edge</b><small>paper engine v0.1</small></div>
      </div>
      <nav>
        {nav.map(n => (
          <a key={n.key} className={view === n.key ? 'active' : ''} onClick={() => setView(n.key)}>
            {n.label}
          </a>
        ))}
      </nav>
      <div className="side-note"><div className="dot"></div> Paper trading only</div>
    </aside>

    <main className="main">
      <header className="topbar">
        <div>
          <h1>Trading dashboard</h1>
          <p>Model probabilities → market odds → edge → paper stake</p>
        </div>
      </header>

      <AdminBar />

      {loading || !dash ? <div className="loading">Nalagam…</div> : <>
        {view === 'overview' && <Overview dash={dash} days={days} setDays={setDays} refresh={refresh} />}
        {view === 'matches' && <MatchesView />}
        {view === 'bets' && <PaperBetsView />}
        {view === 'model' && <ModelView config={config} />}
        {view === 'data' && <DataView />}
        {view === 'settings' && <SettingsView config={config} />}
      </>}
    </main>
  </div>
}

createRoot(document.getElementById('root')).render(<App />)