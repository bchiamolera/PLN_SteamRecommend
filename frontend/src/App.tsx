import React, { FormEvent, useEffect, useState } from 'react';
import { Link, Route, Routes, useLocation, useParams, useSearchParams } from 'react-router-dom';
import { Aspect, Game, get, Insights, SearchResponse } from './api';
import './style.css';

const example = 'Explore an open world and build a base to survive with friends';
function ErrorMessage({ message }: { message: string }) { return <div className="error" role="alert">{message}</div>; }
function Tags({ values, limit = 5 }: { values: string[]; limit?: number }) { return <div className="tags">{values.slice(0, limit).map((v, i) => <span key={`${v}-${i}`}>{v}</span>)}</div>; }

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const query = params.get('q') || '';
  const [text, setText] = useState(query);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    setText(query); setData(null); setError('');
    if (!query) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    get<SearchResponse>(`search/?q=${encodeURIComponent(query)}&limit=10`, controller.signal)
      .then(setData).catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [query, retry]);
  function submit(event: FormEvent) { event.preventDefault(); if (text.trim()) { setParams({ q: text.trim() }); setRetry(v => v + 1); } }
  return <>
    <section className="hero"><p className="eyebrow">THE NEXT GAME IS OUT THERE</p><h1>Find your kind<br/>of <em>escape.</em></h1><p className="intro">Describe the world you want to step into. Discover Steam games through their descriptions, then see what players praise and criticize.</p>
      <form onSubmit={submit} className="search-form"><label htmlFor="query">What do you feel like playing?</label><div className="search-input"><input id="query" value={text} onChange={e => setText(e.target.value)} maxLength={500} required placeholder="A cozy farming game with exploration…"/><button type="submit" disabled={loading || !text.trim()}>{loading ? 'Searching…' : 'Find games ↗'}</button></div><p className="hint">Search in English · Word2Vec semantic similarity</p></form>
      <button className="example" onClick={() => { setParams({ q: example }); setRetry(v => v + 1); }}>Try: open-world survival with friends <span>↗</span></button>
    </section>
    {error && <><ErrorMessage message={error}/><button className="secondary" onClick={() => setRetry(v => v + 1)}>Try again</button></>}
    {loading && <p role="status" className="empty">Exploring the catalog…</p>}
    {data && <section aria-label="Search results"><div className="section-heading"><h2>Your next possibilities</h2><span>{data.results.length} matches</span></div><p className="hint">Similarity measures description overlap; it is not a quality score or a recommendation probability.</p>
      {!data.results.length && <p className="empty">{data.message}</p>}
      <div className="results">{data.results.map(game => <Link className="game-card" key={game.appid} to={`/games/${game.appid}`} state={{ query }}><div className="card-top"><span className="rank">{String(game.rank).padStart(2, '0')}</span><span className="similarity">{game.similarity.toFixed(3)} similarity</span></div><h3>{game.name}</h3><Tags values={game.genres}/><p className="description">{game.description}</p><div className="card-bottom"><span>{game.review_count ? `${game.review_count.toLocaleString()} collected reviews` : 'No collected reviews'}</span><strong>Explore ↗</strong></div></Link>)}</div>
      {data.unknown_terms.length > 0 && <p className="hint">Words outside the model vocabulary: {data.unknown_terms.slice(0, 20).join(', ')}</p>}
    </section>}
    {!query && <section className="how"><div><span>01 / DESCRIBE</span><h3>Start with a feeling.</h3><p>A setting, a mechanic, or a way to play. Your words guide the search.</p></div><div><span>02 / DISCOVER</span><h3>Follow the connection.</h3><p>Explore games with descriptions closest to what you have in mind.</p></div><div><span>03 / LOOK CLOSER</span><h3>Hear both sides.</h3><p>Read recurring player observations with the review excerpts behind them.</p></div></section>}
  </>;
}

function AspectPanel({ title, points, negative }: { title: string; points: Aspect[]; negative?: boolean }) {
  return <section className={`aspect-panel ${negative ? 'negative' : 'positive'}`}><p className="eyebrow">{negative ? '− THE FRICTION' : '+ THE HIGHLIGHTS'}</p><h2>{title}</h2>{!points.length && <p className="empty">Not enough recurring evidence for this side.</p>}{points.map(point => <article className="aspect" key={point.aspect}><div className="section-heading"><h3>{point.aspect}</h3><span>{point.support_count} supporting reviews</span></div><details><summary>Read supporting excerpts</summary>{point.evidence.map(e => <blockquote key={e.review_id}>{e.excerpt}<cite>Collected review · {e.review_id.slice(0, 8)}</cite></blockquote>)}</details></article>)}</section>;
}

export function GamePage() {
  const { appid } = useParams();
  const location = useLocation();
  const backTarget = location.state?.query ? `/?q=${encodeURIComponent(location.state.query)}` : '/';
  const [game, setGame] = useState<Game | null>(null);
  const [insights, setInsights] = useState<Insights | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setGame(null); setInsights(null); setError('');
    Promise.all([get<Game>(`games/${appid}/`, controller.signal), get<Insights>(`games/${appid}/insights/`, controller.signal)])
      .then(([g, i]) => { setGame(g); setInsights(i); })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [appid, retry]);
  if (error) return <><Link to={backTarget} className="back">← Discover games</Link><ErrorMessage message={error}/><button className="secondary" onClick={() => setRetry(v => v + 1)}>Try again</button></>;
  if (!game || !insights) return <p role="status" className="empty">Opening game details…</p>;
  const statuses = { no_reviews: 'No English reviews have been collected for this game.', not_prepared: 'Review insights have not been prepared for this game yet.', insufficient_evidence: 'The collected reviews do not contain enough recurring, unambiguous aspect opinions.', ready: '' };
  return <><Link className="back" to={backTarget}>← Discover games</Link><section className="game-hero"><p className="eyebrow">A CLOSER LOOK · STEAM / {game.appid}</p><h1>{game.name}</h1><Tags values={game.genres} limit={game.genres.length}/><p className="full-description">{game.description}</p>{game.user_tags.length > 0 && <><p className="hint">Player tags</p><Tags values={game.user_tags} limit={game.user_tags.length}/></>}<a className="steam-link" href={game.steam_url} target="_blank" rel="noreferrer">View on Steam ↗</a></section>
    <div className="stats"><div><strong>{game.review_count.toLocaleString()}</strong><span>collected English reviews</span></div><div><strong>{game.recommended_count.toLocaleString()}</strong><span>Steam recommendation votes in this sample</span></div><div><strong>{insights.analyzed_review_count.toLocaleString()}</strong><span>reviews analyzed for aspects</span></div></div>
    <div className="section-heading"><h2>What players are saying</h2><span>Local NLP analysis</span></div><p className="hint">{insights.note}</p>
    {insights.status !== 'ready' && <p className="empty">{statuses[insights.status]}</p>}
    <div className="aspect-grid"><AspectPanel title="Players praise" points={insights.positive}/><AspectPanel title="Players criticize" points={insights.negative} negative/></div><p className="hint">Analysis: {insights.analysis_version} · Counts reflect supporting reviews, not the number of mentions.</p>
  </>;
}

export function App() { return <><header><Link className="brand" to="/"><span className="brand-icon">✳</span> STEAM ATLAS</Link><span className="header-note">GAME DISCOVERY / NLP LAB</span></header><main><Routes><Route path="/" element={<SearchPage/>}/><Route path="/games/:appid" element={<GamePage/>}/><Route path="*" element={<p className="empty">Page not found. <Link to="/">Return to discovery</Link></p>}/></Routes></main><footer><span>STEAM ATLAS</span><p>An academic exploration of language, games, and player opinions.<br/>Independent project. Not affiliated with Valve.</p><span>WORD2VEC + LOCAL NLP</span></footer></>; }

