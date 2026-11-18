import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import { App } from './App';
import { AgentResponse } from './api';

afterEach(() => vi.restoreAllMocks());
const key = 'development-secret-key';
const filters = { required_tag: ['Co-op'], excluded_tag: [], genre: [] };
const game = { appid: 10, name: 'Island Builders', description: 'Explore an island.', genres: ['Adventure'], user_tags: ['Co-op'], steam_url: 'https://store.steampowered.com/app/10/', review_count: 0, recommended_count: 0 };
const response: AgentResponse = {
  status: 'ready', query: 'island', message: 'A match for exploration.', mode: 'bm25', filters,
  results: [{ ...game, rank: 1, score: 1.2, score_type: 'bm25', similarity: null,
    explanation: 'Explore an island.', references: [{ kind: 'catalog', field: 'description', review_id: '', excerpt: 'Explore an island.' }], insight_status: 'no_reviews' }],
  preferences: ['Exploration'], limitations: ['Player opinions are sampled.'],
  context: { preferences: ['Exploration'], latest_query: 'island', previous_appids: [10] },
  actions: ['Searched bm25'], elapsed_ms: 100, provider: 'openai', model: 'gpt-6-luna', usage: {},
};
function setup(discover: (init?: RequestInit) => Promise<Response> = async () => new Response(JSON.stringify(response))) {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith('agent/providers/')) return new Response(JSON.stringify({ providers: [{ id: 'openai', label: 'OpenAI' }, { id: 'google', label: 'Google' }] }));
    if (url.endsWith('agent/models/')) return new Response(JSON.stringify({ models: [{ id: 'gpt-6-luna', label: 'GPT Luna' }] }));
    if (url.endsWith('agent/discover/')) return discover(init);
    if (url.endsWith('filters/')) return new Response(JSON.stringify({ tags: [{ label: 'Co-op', count: 3 }], genres: [{ label: 'Adventure', count: 1 }] }));
    if (url.includes('insights/')) return new Response(JSON.stringify({ appid: 10, status: 'no_reviews', positive: [], negative: [], collected_review_count: 0, analyzed_review_count: 0, note: '', analysis_version: 'fixture' }));
    return new Response(JSON.stringify(game));
  });
  render(<MemoryRouter><App/></MemoryRouter>);
  return fetcher;
}
async function connect() {
  fireEvent.click(screen.getByRole('checkbox', { name: 'Agent mode' }));
  await screen.findByRole('option', { name: 'OpenAI' });
  fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'openai' } });
  fireEvent.change(screen.getByLabelText('Provider API key'), { target: { value: key } });
  fireEvent.click(screen.getByRole('button', { name: 'Load models' }));
  await screen.findByRole('option', { name: 'GPT Luna' });
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'gpt-6-luna' } });
}
async function discover() {
  fireEvent.change(screen.getByLabelText('What do you feel like playing?'), { target: { value: 'island' } });
  fireEvent.click(screen.getByRole('button', { name: /Find games/ }));
  await screen.findByRole('heading', { name: 'Your agent discoveries' });
}

test('explicit connection and search use header credentials, with no browser persistence or automatic generation', async () => {
  const local = vi.spyOn(Storage.prototype, 'setItem');
  const fetcher = setup();
  await connect();
  expect(screen.getByLabelText('Provider API key')).toHaveAttribute('type', 'password');
  expect(screen.getByText('Selected automatically')).toBeInTheDocument();
  expect(screen.queryByLabelText('Search method')).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([u]) => String(u).includes('discover/'))).toHaveLength(0);
  fireEvent.change(screen.getByLabelText('What do you feel like playing?'), { target: { value: 'island' } });
  expect(fetcher.mock.calls.filter(([u]) => String(u).includes('discover/'))).toHaveLength(0);
  await discover();
  const [, init] = fetcher.mock.calls.find(([u]) => String(u).endsWith('agent/discover/'))!;
  expect(init?.headers).toEqual({ 'Content-Type': 'application/json', 'X-Agent-API-Key': key });
  expect(String(init?.body)).not.toContain(key);
  expect(fetcher.mock.calls.every(([u]) => !String(u).includes(key))).toBe(true);
  expect(local).not.toHaveBeenCalled();
  expect(screen.getByText('View recommendation evidence')).toBeInTheDocument();
});

test('refinements preserve context and inferred filters; changing filters is not a paid action', async () => {
  const fetcher = setup(); await connect(); await discover();
  fireEvent.click(screen.getByRole('button', { name: 'Less combat' }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([u]) => String(u).includes('discover/'))).toHaveLength(2));
  const calls = fetcher.mock.calls.filter(([u]) => String(u).includes('discover/'));
  expect(JSON.parse(String(calls[1][1]?.body))).toMatchObject({ query: 'Less combat', filters, context: response.context });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Less combat' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Remove Co-op from required tags' }));
  expect(fetcher.mock.calls.filter(([u]) => String(u).includes('discover/'))).toHaveLength(2);
  fireEvent.change(screen.getByLabelText('Refine your discovery'), { target: { value: 'More puzzles' } });
  fireEvent.click(screen.getByRole('button', { name: 'Apply refinement' }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([u]) => String(u).includes('discover/'))).toHaveLength(3));
});

test('details navigation preserves discovery and key; reset retains connection and disable clears it', async () => {
  setup(); await connect(); await discover();
  fireEvent.click(screen.getByRole('link', { name: 'Island Builders' }));
  await screen.findByRole('heading', { name: 'Positive points' });
  fireEvent.click(screen.getByRole('link', { name: /Discover games/ }));
  expect(await screen.findByRole('heading', { name: 'Your agent discoveries' })).toBeInTheDocument();
  expect(screen.getByLabelText('Provider API key')).toHaveValue(key);
  fireEvent.click(screen.getByRole('button', { name: 'Reset discovery' }));
  expect(screen.queryByRole('heading', { name: 'Your agent discoveries' })).not.toBeInTheDocument();
  expect(screen.getByLabelText('Provider API key')).toHaveValue(key);
  expect(screen.getByLabelText('Model')).toHaveValue('gpt-6-luna');
  fireEvent.click(screen.getByRole('button', { name: 'Disable agent mode' }));
  expect(screen.getByLabelText('Search method')).toHaveValue('word2vec');
  fireEvent.click(screen.getByRole('checkbox', { name: 'Agent mode' }));
  expect(screen.getByLabelText('Provider API key')).toHaveValue('');
  expect(screen.getByLabelText('Model')).toHaveValue('');
});

test('provider changes and a fresh mount clear credentials', async () => {
  setup(); await connect();
  fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'google' } });
  expect(screen.getByLabelText('Provider API key')).toHaveValue('');
  expect(screen.getByLabelText('Model')).toHaveValue('');
});

test('reset invalidates a pending discovery even when transport ignores abort', async () => {
  let resolve!: (value: Response) => void;
  setup(() => new Promise(r => { resolve = r; })); await connect();
  fireEvent.change(screen.getByLabelText('What do you feel like playing?'), { target: { value: 'island' } });
  fireEvent.click(screen.getByRole('button', { name: /Find games/ }));
  await screen.findByText('Discovering games…');
  fireEvent.click(screen.getByRole('button', { name: 'Reset discovery' }));
  await act(async () => resolve(new Response(JSON.stringify(response))));
  expect(screen.queryByRole('heading', { name: 'Your agent discoveries' })).not.toBeInTheDocument();
});

test('provider failures are shown without automatically retrying', async () => {
  const fetcher = setup(async () => new Response(JSON.stringify({ code: 'rate_limit', detail: 'Provider quota reached.' }), { status: 429 }));
  await connect();
  fireEvent.change(screen.getByLabelText('What do you feel like playing?'), { target: { value: 'island' } });
  fireEvent.click(screen.getByRole('button', { name: /Find games/ }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Provider quota reached.');
  expect(fetcher.mock.calls.filter(([u]) => String(u).includes('discover/'))).toHaveLength(1);
});
