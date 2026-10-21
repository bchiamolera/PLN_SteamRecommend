export interface Game {
  appid: number; name: string; description: string; genres: string[]; user_tags: string[];
  steam_url: string; review_count: number; recommended_count: number;
}
export interface SearchResult extends Game { rank: number; similarity: number }
export interface SearchResponse {
  query: string; results: SearchResult[]; known_terms: string[]; unknown_terms: string[]; message: string;
}
export interface Evidence { review_id: string; excerpt: string }
export interface Aspect { aspect: string; support_count: number; evidence: Evidence[] }
export interface Insights {
  appid: number; analysis_version: string;
  status: 'ready' | 'not_prepared' | 'no_reviews' | 'insufficient_evidence';
  collected_review_count: number; analyzed_review_count: number;
  positive: Aspect[]; negative: Aspect[]; note: string;
}

export async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try { response = await fetch(`/api/v1/${path}`, { signal }); }
  catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw new Error('Cannot reach the backend. Start Django on localhost:8000 and try again.');
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
