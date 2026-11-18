import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { AgentErrorPanel, RecommendationCard } from './AgentPresentation';
import { AgentRequestError, AgentContext, AgentFilters, AgentResponse, agentPost, get } from './api';
import { useChatSession } from './useChatSession';

const emptyFilters = (): AgentFilters => ({ required_tag: [], excluded_tag: [], genre: [] });
const emptyContext = (): AgentContext => ({ preferences: [], latest_query: '', previous_appids: [] });
function useAgentSession() {
  const [enabled, setEnabled] = useState(false);
  const [provider, setProvider] = useState('');
  const [key, setKey] = useState('');
  const [models, setModels] = useState<{ id: string; label: string }[]>([]);
  const [model, setModel] = useState('');
  const chat = useChatSession(provider, model, key);
  const [filters, setFilters] = useState<AgentFilters>(emptyFilters);
  const [context, setContext] = useState<AgentContext>(emptyContext);
  const [result, setResult] = useState<AgentResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [failure, setFailure] = useState<AgentRequestError | null>(null);
  const active = useRef<AbortController | null>(null);
  const generation = useRef(0);
  function cancel() { generation.current++; active.current?.abort(); active.current = null; setBusy(false); }
  useEffect(() => () => active.current?.abort(), []);
  function reset() { cancel(); setResult(null); setContext(emptyContext()); setError(''); setFailure(null); setFilters(emptyFilters()); }
  function disable() { reset(); chat.reset(); setKey(''); setProvider(''); setModels([]); setModel(''); setEnabled(false); }
  function changeProvider(value: string) { reset(); chat.reset(); setProvider(value); setKey(''); setModels([]); setModel(''); }
  function changeKey(value: string) { cancel(); chat.reset(); setKey(value); setModels([]); setModel(''); setError(''); setFailure(null); }
  function changeModel(value: string) { cancel(); chat.stop(); setModel(value); setError(''); setFailure(null); }
  function updateFilters(value: AgentFilters) { cancel(); setFilters(value); setError(''); setFailure(null); }
  async function request<T>(path: string, body: unknown): Promise<T | null> {
    cancel(); const version = generation.current;
    const controller = new AbortController(); active.current = controller;
    setBusy(true); setError(''); setFailure(null);
    try {
      const value = await agentPost<T>(path, body, key, controller.signal);
      if (generation.current !== version) return null;
      return value;
    } catch (e) {
      if (generation.current === version && !controller.signal.aborted) {
        setError(e instanceof Error ? e.message : 'Agent request failed.');
        if (e instanceof AgentRequestError) setFailure(e);
      }
      return null;
    } finally { if (generation.current === version) { setBusy(false); active.current = null; } }
  }
  async function loadModels() {
    chat.stop();
    setModels([]); setModel('');
    const data = await request<{ models: { id: string; label: string }[] }>('models', { provider });
    if (data) { setModels(data.models); if (!data.models.length) setError('No supported models are available for this key.'); }
  }
  async function run(query: string, refinement = false) {
    if (!query.trim() || !model || !key || busy) return;
    const data = await request<AgentResponse>('discover', { provider, model, query: query.trim(), filters,
      context: refinement ? context : emptyContext() });
    if (data) { setResult(data); setContext(data.context); setFilters(data.filters); }
  }
  return { enabled, enable: (value: AgentFilters) => { setFilters(value); setEnabled(true); }, disable,
    provider, changeProvider, key, changeKey, models, model, changeModel, filters, updateFilters,
    context, result, busy, error, failure, reset, loadModels, run, chat };
}
type Session = ReturnType<typeof useAgentSession>;
const AgentSession = createContext<Session | null>(null);
export function AgentProvider({ children }: { children: React.ReactNode }) {
  const session = useAgentSession();
  return <AgentSession.Provider value={session}>{children}</AgentSession.Provider>;
}
export function useAgent() {
  const session = useContext(AgentSession);
  if (!session) throw new Error('AgentProvider is required');
  return session;
}

export function AgentControls({ initialFilters, chat = false }: { initialFilters: AgentFilters; chat?: boolean }) {
  const agent = useAgent();
  const [providers, setProviders] = useState<{ id: string; label: string }[]>([
    { id: 'openai', label: 'OpenAI' }, { id: 'anthropic', label: 'Anthropic' }, { id: 'google', label: 'Google' },
  ]);
  const [providerRetry, setProviderRetry] = useState(0);
  const [providerError, setProviderError] = useState('');
  useEffect(() => {
    if (!agent.enabled && !chat) return;
    const controller = new AbortController();
    setProviderError('');
    get<{ providers: { id: string; label: string }[] }>('agent/providers/', controller.signal)
      .then(data => { if (!controller.signal.aborted && data.providers?.length) setProviders(data.providers); }).catch(() => { if (!controller.signal.aborted) setProviderError('Cannot verify providers with the backend. You can choose a provider now; start Django at the configured backend address before loading models.'); });
    return () => controller.abort();
  }, [agent.enabled, chat, providerRetry]);
  return <section className="agent-controls" aria-label="Agent connection">
    {!chat && <label className="agent-toggle"><input type="checkbox" checked={agent.enabled}
      onChange={e => { setProviderError(''); if (e.target.checked) agent.enable(initialFilters); else agent.disable(); }}/>{' '}Agent mode</label>}
    {(agent.enabled || chat) && <>
      <p className="hint">Uses your API key. Requests incur provider charges and send your query plus relevant catalog and review excerpts to the selected provider. Your key stays in memory and clears on disable or reload.</p>
      {providerError && <div role="alert"><p>{providerError}</p><button type="button" className="secondary" onClick={() => setProviderRetry(value => value + 1)}>Retry provider connection</button></div>}
      <label htmlFor="agent-provider">Provider</label><select id="agent-provider" value={agent.provider} onChange={e => agent.changeProvider(e.target.value)}><option value="">Choose provider</option>{providers.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}</select>
      <label htmlFor="agent-key">Provider API key</label><input id="agent-key" type="password" autoComplete="off" spellCheck={false} value={agent.key} maxLength={512} onChange={e => agent.changeKey(e.target.value)}/>
      <button type="button" className="secondary" onClick={() => void agent.loadModels()} disabled={agent.busy || !agent.provider || !agent.key.trim()}>Load models</button>
      <label htmlFor="agent-model">Model</label><select id="agent-model" value={agent.model} onChange={e => agent.changeModel(e.target.value)}><option value="">Choose model</option>{agent.models.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}</select>
      <p className="hint">Lightweight models are listed first. Choose Flash-Lite, Luna, Mini, or Haiku for shorter waits. Available models depend on your API key.</p>
      <p className="hint">Up to 4 model responses and 6 tool calls, with a 45-second provider-attempt limit and a 180-second request limit by default. Use Reset discovery or Disable agent mode to stop waiting. Temporary provider failures retry up to 5 times; accepted requests may incur charges.</p>
      <div className="agent-buttons">{!chat && <button type="button" className="secondary" onClick={agent.reset}>Reset discovery</button>}<button type="button" className="secondary" onClick={agent.disable}>{chat ? 'Disconnect' : 'Disable agent mode'}</button></div>
    </>}
  </section>;
}

export function AgentResults({ searchKey }: { searchKey: string }) {
  const agent = useAgent();
  const [refinement, setRefinement] = useState('');
  const data = agent.result;
  return <section aria-label="Agent discovery">
    {agent.error && <AgentErrorPanel message={agent.error} code={agent.failure?.code} requestId={agent.failure?.requestId}/>}
    {agent.busy && <p role="status" className="empty">Discovering games…</p>}
    {!data && !agent.busy && <p className="empty">Choose a provider and model, then describe what you feel like playing.</p>}
    {data && <>
      <div className="section-heading"><h2>Your agent discoveries</h2><span>{data.results.length} matches</span></div>
      <p role="status">{data.message}</p>
      <p className="hint">Interpreted preferences: {data.preferences.join(' · ') || 'No additional preferences'}</p>
      <p className="hint">Applied filters: {Object.entries(data.filters).map(([k, v]) => `${k}: ${v.join(', ') || 'none'}`).join(' · ')}</p>
      <p className="hint">{data.actions.join('; ')} · {data.provider} / {data.model} · {(data.elapsed_ms / 1000).toFixed(1)}s</p>
      <ul className="hint">{data.limitations.map((value, i) => <li key={i}>{value}</li>)}</ul>
      <div className="results">{data.results.map(game => <RecommendationCard key={game.appid} game={game} searchKey={searchKey}/>)}</div>
      <form className="agent-refinement" onSubmit={e => { e.preventDefault(); void agent.run(refinement, true); }}><label htmlFor="agent-refinement">Refine your discovery</label><input id="agent-refinement" value={refinement} onChange={e => setRefinement(e.target.value)} maxLength={500}/><button className="secondary" disabled={agent.busy || !agent.model || !refinement.trim()}>Apply refinement</button></form>
      <div className="agent-buttons">{['More exploration', 'Less combat'].map(value => <button className="secondary" type="button" key={value} disabled={agent.busy || !agent.model} onClick={() => void agent.run(value, true)}>{value}</button>)}</div>
    </>}
  </section>;
}
