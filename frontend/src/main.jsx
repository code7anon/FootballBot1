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

function Stat({ label, value, sub }) {
  return <div className="stat"><div className="muted">{label}</div><div className="stat-value">{value}</div>{sub && <div className="sub">{sub}</div>}</div>
}

function App() {
  const [dash, setDash] = useState(null)
  const [matches, setMatches] = useState([])
  const [detail, setDetail] = useState(null)
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(true)
  const [action, setAction] = useState('')

  async function refresh() {
    setLoading(true)
    try {
      const [d, m] = await Promise.all([api(`/api/dashboard?days=${days}`), api('/api/matches')])
      setDash(d); setMatches(m)
    } finally { setLoading(false) }
  }

  useEffect(() => { refresh() }, [days])
  useEffect(() => {
    const t = setInterval(refresh, 60000)
    return () => clearInterval(t)
  }, [days])

  async function runCycle() {
    const token = window.prompt('Admin token (only needed when ADMIN_TOKEN is configured):')
    setAction('Running cycle…')
    try {
      const res = await api('/api/admin/run-cycle', { method: 'POST', headers: { 'x-admin-token': token || '' } })
      setAction(JSON.stringify(res.details))
      await refresh()
    } catch (e) { setAction(e.message) }
  }

  async function openMatch(id) {
    setDetail(await api(`/api/matches/${id}`))
  }

  const curve = useMemo(() => {
    if (!dash) return []
    const base = 1000
    let balance = base
    const sorted = [...(dash.recent_bets || [])].reverse()
    const points = [{ name: 'Start', balance }]
    sorted.forEach((b, i) => { if (b.pnl != null) { balance += Number(b.pnl); points.push({ name: `${i+1}`, balance: Number(balance.toFixed(2)) }) } })
    return points
  }, [dash])

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">FE</span><div><b>Football Edge</b><small>paper engine v0.1</small></div></div>
      <nav><a className="active">Overview</a><a>Matches</a><a>Paper Bets</a><a>Model</a><a>Data</a><a>Settings</a></nav>
      <div className="side-note"><div className="dot"></div> Paper trading only</div>
    </aside>

    <main className="main">
      <header className="topbar"><div><h1>Trading dashboard</h1><p>Model probabilities → market odds → edge → paper stake</p></div><div className="toolbar"><select value={days} onChange={e => setDays(Number(e.target.value))}><option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option></select><button onClick={refresh}>Refresh</button><button className="primary" onClick={runCycle}>Run cycle</button></div></header>
      {action && <div className="notice">{action}</div>}
      {loading || !dash ? <div className="loading">Loading system…</div> : <>
      <section className="stats-grid">
        <Stat label="BANKROLL" value={eur(dash.bankroll)} sub="paper account" />
        <Stat label="P&L" value={eur(dash.pnl)} sub={`${days}-day period`} />
        <Stat label="ROI" value={pct(dash.roi)} sub={`${dash.settled} settled`} />
        <Stat label="WIN RATE" value={pct(dash.win_rate)} sub={`${dash.wins} wins`} />
        <Stat label="AVG EDGE" value={pct(dash.avg_edge)} sub={`${dash.bets} total bets`} />
        <Stat label="OPEN EXPOSURE" value={eur(dash.open_exposure)} sub="risk currently open" />
      </section>

      <section className="grid-two">
        <div className="panel"><div className="panel-head"><div><h2>Bankroll curve</h2><span>Based on settled paper bets</span></div><strong>{eur(dash.bankroll)}</strong></div><div className="chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={curve}><XAxis dataKey="name" hide/><YAxis hide domain={['dataMin - 20','dataMax + 20']}/><Tooltip/><Area type="monotone" dataKey="balance" strokeWidth={2} fillOpacity={0.18}/></AreaChart></ResponsiveContainer></div></div>
        <div className="panel"><div className="panel-head"><div><h2>Today's matches</h2><span>Tracked fixtures in database</span></div><strong>{matches.length}</strong></div><div className="match-list">{matches.length === 0 ? <div className="empty">No fixtures cached. Run a collector cycle.</div> : matches.slice(0, 12).map(m => <button className="match-row" key={m.id} onClick={() => openMatch(m.id)}><div className="time">{new Date(m.kickoff + 'Z').toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</div><div className="teams"><b>{m.home_team}</b><span>{m.away_team}</span></div><div className="score">{m.home_goals ?? '-'} : {m.away_goals ?? '-'}</div><div className={`status ${m.status === 'NS' ? '' : 'live'}`}>{m.status}{m.minute ? ` ${m.minute}'` : ''}</div></button>)}</div></div>
      </section>

      <section className="panel"><div className="panel-head"><div><h2>Recent paper bets</h2><span>Every decision is logged for later calibration</span></div></div><div className="table-wrap"><table><thead><tr><th>Time</th><th>Selection</th><th>Market</th><th>Odds</th><th>Model</th><th>Edge</th><th>Stake</th><th>Status</th><th>P&L</th></tr></thead><tbody>{(dash.recent_bets || []).slice(0, 25).map(b => <tr key={b.id}><td>{new Date(b.created_at).toLocaleString()}</td><td><b>{b.selection}</b></td><td>{b.market}</td><td>{b.odds.toFixed(2)}</td><td>{pct(b.model_probability)}</td><td className="edge">{pct(b.edge)}</td><td>{eur(b.stake)}</td><td><span className={`badge ${String(b.status).toLowerCase()}`}>{b.status}</span></td><td>{b.pnl == null ? '—' : eur(b.pnl)}</td></tr>)}{!dash.recent_bets?.length && <tr><td colSpan="9" className="empty">No paper bets yet.</td></tr>}</tbody></table></div></section>
      </>}
    </main>

    {detail && <div className="modal-backdrop" onClick={() => setDetail(null)}><div className="modal" onClick={e => e.stopPropagation()}><div className="modal-head"><div><h2>{detail.fixture.home_team} vs {detail.fixture.away_team}</h2><span>{detail.fixture.kickoff.replace('T',' ').slice(0,16)} UTC · {detail.fixture.status}</span></div><button onClick={() => setDetail(null)}>×</button></div><div className="prob-grid"><div><span>HOME</span><b>{pct(detail.model.home)}</b></div><div><span>DRAW</span><b>{pct(detail.model.draw)}</b></div><div><span>AWAY</span><b>{pct(detail.model.away)}</b></div></div><div className="confidence">Model: {detail.model.name} · confidence {pct(detail.model.confidence)}</div><h3>Latest odds</h3><div className="odds-list">{detail.odds.length ? detail.odds.map((o,i) => <div key={i}><span>{o.bookmaker}</span><span>{o.market}</span><b>{o.selection}</b><strong>{Number(o.odds).toFixed(2)}</strong></div>) : <div className="empty">No odds snapshots stored.</div>}</div></div></div>}
  </div>
}

createRoot(document.getElementById('root')).render(<App />)
