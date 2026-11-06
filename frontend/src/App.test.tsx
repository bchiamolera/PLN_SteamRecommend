import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import { App } from './App';

afterEach(() => vi.restoreAllMocks());
const game = { appid: 10, name: 'Island Builders', description: 'Explore an island with friends.', genres: ['Adventure'], user_tags: [], steam_url: 'https://store.steampowered.com/app/10/', review_count: 3, recommended_count: 2 };
const facets = { tags: [{ label: 'Co-op', count: 2 }, { label: 'Zombies', count: 1 }], genres: [{ label: 'Adventure', count: 2 }] };
const insight = { appid: 10, analysis_version: 'aspects-clauses-v1', status: 'ready', collected_review_count: 3, analyzed_review_count: 3, positive: [{ aspect: 'graphics', summary: 'Visual presentation is a recurring strength.', support_count: 2, evidence: [{ review_id: 'review-1', excerpt: 'The graphics are beautiful.' }] }], negative: [{ aspect: 'graphics', summary: 'Visual presentation is a recurring drawback.', support_count: 2, evidence: [{ review_id: 'review-2', excerpt: 'The graphics are terrible.' }] }], note: 'Recurring observations in collected reviews.' };

test('search → game → positive and negative bullets → optional evidence', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input);
    const body = url.includes('filters/') ? facets : url.includes('search/') ? { query: 'island', results: [{ ...game, rank: 1, similarity: .8, score: .8, score_type: 'cosine' }], known_terms: ['island'], unknown_terms: [], message: '' } : url.includes('insights/') ? insight : game;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  render(<MemoryRouter><App/></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('What do you feel like playing?'), { target: { value: 'island' } });
  fireEvent.click(screen.getByRole('button', { name: /Find games/ }));
  fireEvent.click(await screen.findByRole('link', { name: /Island Builders/ }));
  expect(await screen.findByRole('heading', { name: 'Positive points' })).toBeInTheDocument();
  const positives = screen.getByRole('list', { name: 'Positive points' });
  const negatives = screen.getByRole('list', { name: 'Negative points' });
  expect(within(positives).getByRole('listitem')).toHaveTextContent('Visual presentation is a recurring strength.');
  expect(within(negatives).getByRole('listitem')).toHaveTextContent('Visual presentation is a recurring drawback.');
  expect(screen.getByText('The graphics are beautiful.')).not.toBeVisible();
  expect(screen.getByText('The graphics are terrible.')).not.toBeVisible();
  fireEvent.click(within(positives).getByText('View evidence · 2 supporting reviews'));
  expect(screen.getByText('The graphics are beautiful.')).toBeVisible();
});

test('backend failure is actionable and retry is available', async () => {
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('network'));
  render(<MemoryRouter initialEntries={['/?q=island']}><App/></MemoryRouter>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Start Django');
  expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
});

test('unknown query words show an empty state', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => new Response(JSON.stringify(String(input).includes('filters/') ? facets : { query: 'xyz', results: [], unknown_terms: ['xyz'], known_terms: [], message: 'No searchable words found.' })));
  render(<MemoryRouter initialEntries={['/?q=xyz']}><App/></MemoryRouter>);
  expect(await screen.findByText('No searchable words found.')).toBeInTheDocument();
});

test('method and filters survive details navigation and RRF has its own score label', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input);
    const body = url.includes('filters/') ? facets : url.includes('search/') ? { query: 'island', mode: 'hybrid_sentence', results: [{ ...game, rank: 1, similarity: null, score: .025, score_type: 'rrf' }], known_terms: [], unknown_terms: [], message: '' } : url.includes('insights/') ? insight : game;
    return new Response(JSON.stringify(body));
  });
  render(<MemoryRouter initialEntries={['/?q=island&mode=hybrid_sentence&required_tag=Co-op&genre=Adventure']}><App/></MemoryRouter>);
  expect(await screen.findByText('0.0250 RRF score')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: /Island Builders/ }));
  fireEvent.click(await screen.findByRole('link', { name: /Discover games/ }));
  expect(await screen.findByRole('combobox', { name: 'Search method' })).toHaveValue('hybrid_sentence');
  expect(screen.getByRole('button', { name: 'Remove Co-op from required tags' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Remove Adventure from genres' })).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => String(url).includes('required_tag=Co-op') && String(url).includes('mode=hybrid_sentence'))).toBe(true);
});

test('catalog autocomplete adds and clears strict filters', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => new Response(JSON.stringify(String(input).includes('filters/') ? facets : { results: [], unknown_terms: [], known_terms: [], message: 'No matching games.' })));
  render(<MemoryRouter><App/></MemoryRouter>);
  await waitFor(() => expect(screen.getByLabelText('Required tags')).toBeEnabled());
  fireEvent.change(screen.getByLabelText('Required tags'), { target: { value: 'co-op' } });
  fireEvent.click(screen.getByRole('option', { name: /Co-op/ }));
  expect(screen.getByRole('button', { name: 'Remove Co-op from required tags' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
  expect(screen.queryByRole('button', { name: 'Remove Co-op from required tags' })).not.toBeInTheDocument();
});

test('unprepared game insights show coverage without fabricated points', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => new Response(JSON.stringify(String(input).includes('insights/') ? { ...insight, status: 'not_prepared', positive: [], analyzed_review_count: 0 } : game)));
  render(<MemoryRouter initialEntries={['/games/10']}><App/></MemoryRouter>);
  await waitFor(() => expect(screen.getByText('Review insights have not been prepared for this game yet.')).toBeInTheDocument());
  expect(screen.queryByText('The graphics are beautiful.')).not.toBeInTheDocument();
});
