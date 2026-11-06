import React, { FormEvent, useEffect, useState } from 'react';
import { Link, Route, Routes, useLocation, useParams, useSearchParams } from 'react-router-dom';
import { Aspect, Facets, Game, get, Insights, SearchResponse } from './api';
import './style.css';
import { FilterPicker } from './FilterPicker';

const example = 'Explore an open world and build a base to survive with friends';
function ErrorMessage({ message }: { message: string }) { return <div className="error" role="alert">{message}</div>; }
function Tags({ values, limit = 5 }: { values: string[]; limit?: number }) { return <div className="tags">{values.slice(0, limit).map((v, i) => <span key={`${v}-${i}`}>{v}</span>)}</div>; }

const methods = [
  ['word2vec', 'Word2Vec · baseline'], ['bm25', 'BM25 · keywords'], ['sentence', 'MiniLM · sentences'],
  ['hybrid_word2vec', 'BM25 + Word2Vec · RRF'], ['hybrid_sentence', 'BM25 + MiniLM · RRF'],
];
export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const query = params.get('q') || '';
  const searchKey = params.toString();
  const [text, setText] = useState(query);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(0);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [facetError, setFacetError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    get<Facets>('filters/', controller.signal).then(setFacets).catch(e => { if (!controller.signal.aborted) setFacetError(e.message); });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    setText(query); setData(null); setError('');
    if (!query) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    const requestParams = new URLSearchParams(searchKey); requestParams.set('limit', '10');
    get<SearchResponse>(`search/?${requestParams}`, controller.signal)
      .then(setData).catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [searchKey, retry]);
  function changeField(field: string, values: string[]) { const next = new URLSearchParams(params); next.delete(field); values.forEach(v => next.append(field, v)); setParams(next); }
  function submit(event: FormEvent) { event.preventDefault(); if (text.trim()) { const next = new URLSearchParams(params); next.set('q', text.trim()); setParams(next); setRetry(v => v + 1); } }
  return <>
    <section className="hero"><p className="eyebrow">YOUR NEXT ADVENTURE STARTS HERE</p><h1>Discover your next <em>great game.</em></h1><p className="intro">Tell us what you love to play. Explore matching games and the player opinions behind them.</p></section><div className="discovery-layout"><aside className="search-panel" aria-label="Search and filters"><div className="panel-heading"><span>Refine your discovery</span><span aria-hidden="true">⌕</span></div>
      <form onSubmit={submit} className="search-form"><label htmlFor="query">What do you feel like playing?</label><div className="search-input"><textarea id="query" rows={3} value={text} onChange={e => setText(e.target.value)} maxLength={500} required placeholder="A cozy farming game with exploration…"/><button type="submit" disabled={loading || !text.trim()}>{loading ? 'Searching…' : 'Find games ↗'}</button></div><p className="hint">Search in English · Compare lexical and semantic retrieval</p></form>
      <button className="example" onClick={() => { const next = new URLSearchParams(params); next.set('q', example); setParams(next); setRetry(v => v + 1); }}>Try: open-world survival with friends <span>↗</span></button>
      <div className="search-controls"><div><label htmlFor="mode">Search method</label><select id="mode" value={params.get('mode') || 'word2vec'} onChange={e => changeField('mode', [e.target.value])}>{methods.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div><p className="hint">Experimental methods are available for comparison. Scores use different scales and are not recommendation probabilities.</p><div className="filter-grid"><FilterPicker field="required_tag" title="Required tags" options={facets?.tags || []} selected={params.getAll('required_tag')} change={v => changeField('required_tag', v)} disabled={!facets}/><FilterPicker field="excluded_tag" title="Excluded tags" options={facets?.tags || []} selected={params.getAll('excluded_tag')} change={v => changeField('excluded_tag', v)} disabled={!facets}/><FilterPicker field="genre" title="Genres" options={facets?.genres || []} selected={params.getAll('genre')} change={v => changeField('genre', v)} disabled={!facets}/></div><p className="hint">All required tags · Any selected genre · No excluded tags. Matches use catalog labels; missing tags do not prove a feature is absent.</p><button type="button" className="example" onClick={() => { const next = new URLSearchParams(params); ['required_tag', 'excluded_tag', 'genre'].forEach(k => next.delete(k)); setParams(next); }}>Clear filters</button>{facetError && <p className="hint" role="status">Filters unavailable: {facetError}</p>}</div>
    </aside><div className="discovery-content">
    {error && <><ErrorMessage message={error}/><button className="secondary" onClick={() => setRetry(v => v + 1)}>Try again</button></>}
    {loading && <p role="status" className="empty loading-state"><span className="loading-dot" aria-hidden="true"/>Exploring the catalog…</p>}
    {data && <section aria-label="Search results"><div className="section-heading"><h2>Your next possibilities</h2><span className="result-count">{data.results.length} matches</span></div><p className="hint">{methods.find(([value]) => value === (data.mode || 'word2vec'))?.[1]}. Scores describe ranking within this method, not quality or recommendation probability.</p>
      {!data.results.length && <p className="empty">{data.message}</p>}
      {data.message && data.results.length > 0 && <p className="hint">{data.message}</p>}
      <div className="results">{data.results.map(game => <Link className="game-card" key={game.appid} to={`/games/${game.appid}`} state={{ search: searchKey }}><div className="card-top"><span className="rank">{String(game.rank).padStart(2, '0')}</span><span className="similarity">{(game.score ?? game.similarity ?? 0).toFixed(game.score_type === 'rrf' ? 4 : 3)} {game.score_type === 'rrf' ? 'RRF score' : game.score_type === 'bm25' ? 'BM25 score' : 'cosine similarity'}</span></div><h3>{game.name}</h3><Tags values={game.genres}/><p className="description">{game.description}</p><div className="card-bottom"><span>{game.review_count ? `${game.review_count.toLocaleString()} collected reviews` : 'No collected reviews'}</span><strong>Explore ↗</strong></div></Link>)}</div>
      {data.unknown_terms.length > 0 && <p className="hint">Words outside the model vocabulary: {data.unknown_terms.slice(0, 20).join(', ')}</p>}
    </section>}
    {!query && <div className="welcome-panel"><p className="eyebrow">LESS SCROLLING. MORE DISCOVERY.</p><h2>Find a world<br/>worth getting lost in.</h2><p>From quiet farming afternoons to survival with friends, start with an idea and make it yours.</p><section className="how"><div><span>01 / DESCRIBE</span><h3>Start with a feeling.</h3><p>A setting, a mechanic, or a way to play. Your words guide the search.</p></div><div><span>02 / DISCOVER</span><h3>Follow the connection.</h3><p>Explore games with descriptions closest to what you have in mind.</p></div><div><span>03 / LOOK CLOSER</span><h3>Weigh both sides.</h3><p>Compare concise strengths and drawbacks, with supporting evidence available when you need it.</p></div></section></div>}
    </div></div>
  </>;
}

function AspectPanel({ title, points, negative }: { title: string; points: Aspect[]; negative?: boolean }) {
  return <section className={`aspect-panel ${negative ? 'negative' : 'positive'}`}>
    <p className="eyebrow">{negative ? '− THE FRICTION' : '+ THE HIGHLIGHTS'}</p>
    <h2>{title}</h2>
    {!points.length && <p className="empty">Not enough recurring evidence for this side.</p>}
    {points.length > 0 && <ul className="aspect-list" aria-label={title}>
      {points.map(point => <li className="aspect" key={point.aspect}>
        <p className="aspect-summary">{point.summary}</p>
        <details><summary>View evidence · {point.support_count} supporting reviews</summary>
          {point.evidence.map(e => <blockquote key={e.review_id}>{e.excerpt}<cite>Collected review · {e.review_id.slice(0, 8)}</cite></blockquote>)}
        </details>
      </li>)}
    </ul>}
  </section>;
}

export function GamePage() {
  const { appid } = useParams();
  const location = useLocation();
  const backTarget = location.state?.search ? `/?${location.state.search}` : location.state?.query ? `/?q=${encodeURIComponent(location.state.query)}` : '/';
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
    <div className="section-heading"><h2>Strengths &amp; drawbacks</h2><span>Local NLP analysis</span></div><p className="hint">{insights.note}</p>
    {insights.status !== 'ready' && <p className="empty">{statuses[insights.status]}</p>}
    <div className="aspect-grid"><AspectPanel title="Positive points" points={insights.positive}/><AspectPanel title="Negative points" points={insights.negative} negative/></div><p className="hint">Analysis: {insights.analysis_version} · Counts reflect supporting reviews, not the number of mentions.</p>
  </>;
}

export function App() { return <><header><Link className="brand" to="/"><span className="brand-icon">✳</span> STEAM ATLAS</Link><nav aria-label="Main navigation"><Link className="nav-link" to="/">Discover</Link><span className="header-note">GAME DISCOVERY / NLP LAB</span></nav></header><main><Routes><Route path="/" element={<SearchPage/>}/><Route path="/games/:appid" element={<GamePage/>}/><Route path="*" element={<p className="empty">Page not found. <Link to="/">Return to discovery</Link></p>}/></Routes></main><footer><span>STEAM ATLAS</span><p>An academic exploration of language, games, and player opinions.<br/>Independent project. Not affiliated with Valve.</p><span>WORD2VEC + LOCAL NLP</span></footer></>; }

