export interface Game {
  appid: number; name: string; description: string; genres: string[]; user_tags: string[];
  steam_url: string; review_count: number; recommended_count: number;
}
export type SearchMode = 'word2vec' | 'bm25' | 'sentence' | 'hybrid_word2vec' | 'hybrid_sentence';
export interface Facets { tags: { label: string; count: number }[]; genres: { label: string; count: number }[] }
export interface SearchResult extends Game { rank: number; similarity: number | null; score: number; score_type: 'cosine' | 'bm25' | 'rrf' }
export interface SearchResponse {
  query: string; results: SearchResult[]; known_terms: string[]; unknown_terms: string[]; message: string;
  mode: SearchMode; filters: { required_tag: string[]; excluded_tag: string[]; genre: string[] };
}
export interface Evidence { review_id: string; excerpt: string }
export interface Aspect { aspect: string; summary: string; support_count: number; evidence: Evidence[] }
export interface Insights {
  appid: number; analysis_version: string;
  status: 'ready' | 'not_prepared' | 'no_reviews' | 'insufficient_evidence';
  collected_review_count: number; analyzed_review_count: number;
  positive: Aspect[]; negative: Aspect[]; note: string;
}

export interface AgentFilters { required_tag: string[]; excluded_tag: string[]; genre: string[] }
export interface AgentContext { preferences: string[]; latest_query: string; previous_appids: number[] }
export interface AgentReference { kind: 'catalog' | 'review'; field: string; review_id: string; excerpt: string }
export interface AgentResult extends SearchResult { explanation: string; references: AgentReference[]; insight_status: string }
export interface AgentResponse {
  request_id?: string;
  status: 'ready' | 'needs_clarification' | 'no_matches'; query: string; message: string;
  mode: SearchMode | null; results: AgentResult[]; filters: AgentFilters; preferences: string[];
  context: AgentContext; limitations: string[]; actions: string[]; elapsed_ms: number;
  provider: string; model: string; usage: Record<string, number>;
}

export type ChatGame = Omit<AgentResult, 'rank' | 'score' | 'score_type' | 'similarity'> &
  Partial<Pick<AgentResult, 'rank' | 'score' | 'score_type' | 'similarity'>>;
export interface ChatResponse extends Omit<AgentResponse, 'status' | 'results'> {
  status: AgentResponse['status'] | 'answer';
  kind: 'recommendations' | 'answer' | 'needs_clarification' | 'no_matches';
  reply: string;
  results: ChatGame[];
}
export interface ChatTurn { message: string; response: ChatResponse }

export class AgentRequestError extends Error {
  constructor(message: string, public code: string, public requestId?: string) { super(message); }
}

export async function agentPost<T>(path: string, body: unknown, key: string, signal: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1/agent/${path}/`, { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Agent-API-Key': key },
      body: JSON.stringify(body), signal, cache: 'no-store' });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw new Error('Cannot reach the backend. No automatic retry was made.');
  }
  let data;
  try { data = await response.json(); } catch { throw new Error('The backend returned an invalid response.'); }
  if (!response.ok) throw new AgentRequestError(data.detail || 'Agent request failed.', data.code || 'unknown', data.request_id);
  return data as T;
}

export async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try { response = await fetch(`/api/v1/${path}`, { signal }); }
  catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw new Error('Cannot reach the backend. Start Django at the configured backend address and try again.');
  }
  let data;
  try { data = await response.json(); }
  catch { throw new Error('The backend returned an invalid response. Check that Django is running.'); }
  if (!response.ok) {
    const message = data.detail || Object.entries(data).map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(' ') : value}`).join(' ');
    throw new Error(message || `Request failed (${response.status}).`);
  }
  return data as T;
}
