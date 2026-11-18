import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import { App } from './App';
import { ChatResponse } from './api';

afterEach(() => vi.restoreAllMocks());

test('provider selection remains available when backend discovery fails and can reconnect', async () => {
  let offline = true;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
    if (offline) throw new TypeError('Network unavailable');
    return new Response(JSON.stringify({ providers: [{ id: 'google', label: 'Google' }] }));
  });
  render(<MemoryRouter initialEntries={['/chat']}><App/></MemoryRouter>);
  await screen.findByRole('alert');
  fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'google' } });
  expect(screen.getByLabelText('Provider')).toHaveValue('google');
  offline = false;
  fireEvent.click(screen.getByRole('button', { name: 'Retry provider connection' }));
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  expect(screen.getByLabelText('Provider')).toHaveValue('google');
});
const game = { appid: 10, name: 'Island Builders', description: 'Explore an island.', genres: ['Adventure'], user_tags: ['Co-op'], steam_url: 'https://store.steampowered.com/app/10/', review_count: 0, recommended_count: 0 };
const response: ChatResponse = {
  kind: 'recommendations', status: 'ready', query: 'island', reply: 'Try this island adventure.', message: 'Try this island adventure.',
  mode: 'bm25', filters: { required_tag: [], excluded_tag: [], genre: [] },
  results: [{ ...game, rank: 1, score: 1, score_type: 'bm25', similarity: null,
    explanation: 'Explore an island.', references: [{ kind: 'catalog', field: 'description', review_id: '', excerpt: 'Explore an island.' }], insight_status: 'no_reviews' }],
  preferences: ['Exploration'], context: { preferences: ['Exploration'], latest_query: 'island', previous_appids: [10] },
  limitations: ['Prices unavailable.'], actions: [], elapsed_ms: 10, provider: 'openai', model: 'gpt-6-luna', usage: {},
};
function setup(reply: (init?: RequestInit) => Promise<Response> = async () => new Response(JSON.stringify(response))) {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith('agent/providers/')) return new Response(JSON.stringify({ providers: [{ id: 'openai', label: 'OpenAI' }, { id: 'google', label: 'Google' }] }));
    if (url.endsWith('agent/models/')) return new Response(JSON.stringify({ models: [{ id: 'gpt-6-luna', label: 'GPT Luna' }, { id: 'gpt-5.4-mini', label: 'GPT Mini' }] }));
    if (url.endsWith('agent/chat/')) return reply(init);
    if (url.endsWith('filters/')) return new Response(JSON.stringify({ tags: [], genres: [] }));
    if (url.includes('insights/')) return new Response(JSON.stringify({ status: 'no_reviews', positive: [], negative: [], note: '', analysis_version: 'fixture', analyzed_review_count: 0 }));
    return new Response(JSON.stringify(game));
  });
  const view = render(<MemoryRouter initialEntries={['/chat']}><App/></MemoryRouter>);
  return { fetcher, ...view };
}
async function connect() {
  await screen.findByRole('option', { name: 'OpenAI' });
  fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'openai' } });
  fireEvent.change(screen.getByLabelText('Provider API key'), { target: { value: 'private-key' } });
  fireEvent.click(screen.getByRole('button', { name: 'Load models' }));
  await screen.findByRole('option', { name: 'GPT Luna' });
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'gpt-6-luna' } });
}
function send(message = 'island') {
  fireEvent.change(screen.getByLabelText('Message your game agent'), { target: { value: message } });
  fireEvent.click(screen.getByRole('button', { name: /Send message/ }));
}
const chatCalls = (fetcher: ReturnType<typeof setup>['fetcher']) => fetcher.mock.calls.filter(([url]) => String(url).endsWith('agent/chat/'));

test('sequential turns send bounded history and context, with header-only credentials and no persistence', async () => {
  const storage = vi.spyOn(Storage.prototype, 'setItem');
  const { fetcher } = setup(); await connect();
  expect(chatCalls(fetcher)).toHaveLength(0);
  send(); await screen.findByText(response.reply);
  send('Why this game?');
  await waitFor(() => expect(screen.getAllByText(response.reply)).toHaveLength(2));
  const calls = chatCalls(fetcher);
  expect(calls).toHaveLength(2);
  const init = calls[1][1] as RequestInit;
  expect(init.headers).toEqual({ 'Content-Type': 'application/json', 'X-Agent-API-Key': 'private-key' });
  expect(JSON.parse(String(init.body))).toMatchObject({ message: 'Why this game?', context: response.context,
    history: [{ role: 'user', content: 'island', appids: [] }, { role: 'assistant', content: response.reply, appids: [10] }] });
  expect(init.body).not.toContain('private-key');
  expect(JSON.parse(String(init.body)).history[1].games).toEqual([{ appid: 10, explanation: 'Explore an island.' }]);
  expect(storage).not.toHaveBeenCalled();
});

test('game details and discover navigation preserve chat; new chat retains connection', async () => {
  setup(); await connect(); send(); await screen.findByText(response.reply);
  fireEvent.click(screen.getByRole('link', { name: 'Island Builders' }));
  await screen.findByRole('heading', { name: 'Positive points' });
  fireEvent.click(screen.getByRole('link', { name: '← Back to chat' }));
  expect(await screen.findByText(response.reply)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: 'Discover' }));
  fireEvent.click(screen.getByRole('link', { name: 'Chat' }));
  expect(screen.getByText(response.reply)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'New chat' }));
  expect(screen.queryByText(response.reply)).not.toBeInTheDocument();
  expect(screen.getByLabelText('Provider API key')).toHaveValue('private-key');
  expect(screen.getByLabelText('Model')).toHaveValue('gpt-6-luna');
});

test('only six completed exchanges are sent while the visible transcript remains complete', async () => {
  const { fetcher } = setup(); await connect();
  for (let i = 0; i < 8; i++) {
    send(`message ${i}`);
    await waitFor(() => expect(screen.getAllByText(response.reply)).toHaveLength(i + 1));
  }
  const calls = chatCalls(fetcher);
  const body = JSON.parse(String(calls[7][1]?.body));
  expect(body.history).toHaveLength(12);
  expect(body.history[0].content).toBe('message 1');
  expect(screen.getByText('message 0')).toBeInTheDocument();
});

test('provider failure retries explicitly without duplicating transcript', async () => {
  let count = 0;
  const { fetcher } = setup(async () => ++count === 1
    ? new Response(JSON.stringify({ detail: 'Quota reached.' }), { status: 429 })
    : new Response(JSON.stringify(response)));
  await connect(); send();
  expect(await screen.findByRole('alert')).toHaveTextContent('Quota reached.');
  expect(chatCalls(fetcher)).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Retry message' }));
  await screen.findByText(response.reply);
  expect(screen.getAllByText('island')).toHaveLength(1);
  expect(chatCalls(fetcher)).toHaveLength(2);
});

test('one pending message, cancellation, and late responses after reset', async () => {
  let resolve!: (value: Response) => void;
  const { fetcher } = setup(() => new Promise(r => { resolve = r; }));
  await connect(); send();
  expect(await screen.findByRole('status')).toHaveTextContent('Your agent is exploring');
  send('another'); expect(chatCalls(fetcher)).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Stop waiting' }));
  fireEvent.click(screen.getByRole('button', { name: 'New chat' }));
  await act(async () => resolve(new Response(JSON.stringify(response))));
  expect(screen.queryByText(response.reply)).not.toBeInTheDocument();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

test('model change retains completed turns; provider change, disconnect, and reload clear them', async () => {
  const { unmount } = setup(); await connect(); send(); await screen.findByText(response.reply);
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'gpt-5.4-mini' } });
  expect(screen.getByText(response.reply)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'google' } });
  expect(screen.queryByText(response.reply)).not.toBeInTheDocument();
  expect(screen.getByLabelText('Provider API key')).toHaveValue('');
  await connect(); send(); await screen.findByText(response.reply);
  fireEvent.click(screen.getByRole('button', { name: 'Disconnect' }));
  expect(screen.queryByText(response.reply)).not.toBeInTheDocument();
  unmount(); setup();
  expect(screen.getByLabelText('Provider API key')).toHaveValue('');
  expect(screen.queryByText(response.reply)).not.toBeInTheDocument();
});

test('interrupted messages can be restored for editing without sending automatically', async () => {
  const { fetcher } = setup(() => new Promise(() => {})); await connect(); send('A quiet island game');
  await screen.findByRole('status');
  fireEvent.click(screen.getByRole('button', { name: 'Stop waiting' }));
  fireEvent.click(screen.getByRole('button', { name: 'Restore message' }));
  expect(screen.getByLabelText('Message your game agent')).toHaveValue('A quiet island game');
  expect(chatCalls(fetcher)).toHaveLength(1);
});

test('evidence availability is visible and comparison suggestions require two games', async () => {
  setup(); await connect(); send(); await screen.findByText(response.reply);
  expect(screen.getByText('No collected reviews')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Compare the first two/ })).not.toBeInTheDocument();
});

test('quota failures preserve the error code and request reference for actionable feedback', async () => {
  setup(async () => new Response(JSON.stringify({ code: 'quota_exhausted', detail: 'Quota exhausted.', request_id: 'safe-reference' }), { status: 429 }));
  await connect(); send();
  expect(await screen.findByRole('alert')).toHaveTextContent('Check your provider billing or quota');
  expect(screen.getByRole('alert')).toHaveTextContent('safe-reference');
});
