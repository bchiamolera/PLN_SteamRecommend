import { Link } from 'react-router-dom';
import { ChatGame } from './api';

const advice: Record<string, string> = {
  quota_exhausted: 'Check your provider billing or quota before sending again.',
  authentication: 'Check the API key and its permissions in Agent connection.',
  deadline: 'The time limit was reached. Try a shorter or more specific request.',
  artifacts_unavailable: 'Check local data preparation and ordinary search before retrying.',
  invalid_model_output: 'Try clarifying your requirements or choosing another model.',
};

export function AgentErrorPanel({ message, code = '', requestId }: { message: string; code?: string; requestId?: string }) {
  return <div className="error" role="alert"><p>{message}</p>{advice[code] && <p>{advice[code]}</p>}
    {requestId && <small>Request reference: {requestId}</small>}</div>;
}

export function RecommendationCard({ game, fromChat = false, searchKey = '' }: { game: ChatGame; fromChat?: boolean; searchKey?: string }) {
  const state = fromChat ? { fromChat: true } : { search: searchKey };
  const status = game.insight_status === 'ready' ? 'Review evidence available' :
    game.insight_status === 'no_reviews' ? 'No collected reviews' :
    game.insight_status === 'insufficient_evidence' ? 'Insufficient recurring review evidence' : 'Review evidence not prepared or inspected';
  return <article className="game-card agent-card">
    {!fromChat && game.score !== undefined && <div className="card-top"><span className="rank">{String(game.rank).padStart(2, '0')}</span><span className="similarity">{game.score.toFixed(game.score_type === 'rrf' ? 4 : 3)} {game.score_type === 'rrf' ? 'RRF score' : game.score_type === 'bm25' ? 'BM25 score' : 'cosine similarity'}</span></div>}
    <h3><Link to={`/games/${game.appid}`} state={state}>{game.name}</Link></h3>
    <div className="tags">{game.genres.slice(0, 3).map(genre => <span key={genre}>{genre}</span>)}</div>
    <p>{game.explanation}</p><p className="hint evidence-availability">{status}</p>
    <details><summary>View recommendation evidence</summary>{game.references.map((ref, i) => <blockquote key={i}>{ref.excerpt}<cite>{ref.kind === 'catalog' ? `Catalog · ${ref.field}` : `Collected review · ${ref.review_id.slice(0, 8)}`}</cite></blockquote>)}</details>
    <Link className="example" to={`/games/${game.appid}`} state={state}>Explore game ↗</Link>
  </article>;
}
