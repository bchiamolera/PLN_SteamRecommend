import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import { App } from './App';

afterEach(() => vi.restoreAllMocks());
const game = { appid: 10, name: 'Island Builders', description: 'Explore an island with friends.', genres: ['Adventure'], user_tags: [], steam_url: 'https://store.steampowered.com/app/10/', review_count: 3, recommended_count: 2 };
const insight = { appid: 10, analysis_version: 'aspects-clauses-v1', status: 'ready', collected_review_count: 3, analyzed_review_count: 3, positive: [{ aspect: 'graphics', support_count: 2, evidence: [{ review_id: 'review-1', excerpt: 'The graphics are beautiful.' }] }], negative: [], note: 'Recurring observations in collected reviews.' };

test('search → game → supporting review', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input);
    const body = url.includes('search/') ? { query: 'island', results: [{ ...game, rank: 1, similarity: .8 }], known_terms: ['island'], unknown_terms: [], message: '' } : url.includes('insights/') ? insight : game;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  render(<MemoryRouter><App/></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('What do you feel like playing?'), { target: { value: 'island' } });
  fireEvent.click(screen.getByRole('button', { name: /Find games/ }));
  fireEvent.click(await screen.findByRole('link', { name: /Island Builders/ }));
  expect(await screen.findByRole('heading', { name: 'Players praise' })).toBeInTheDocument();
  fireEvent.click(screen.getByText('Read supporting excerpts'));
  expect(screen.getByText('The graphics are beautiful.')).toBeVisible();
});

test('backend failure is actionable and retry is available', async () => {
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('network'));
  render(<MemoryRouter initialEntries={['/?q=island']}><App/></MemoryRouter>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Start Django');
  expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
});

test('unknown query words show an empty state', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ query: 'xyz', results: [], unknown_terms: ['xyz'], known_terms: [], message: 'No searchable words found.' })));
  render(<MemoryRouter initialEntries={['/?q=xyz']}><App/></MemoryRouter>);
  expect(await screen.findByText('No searchable words found.')).toBeInTheDocument();
});

test('unprepared game insights show coverage without fabricated points', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => new Response(JSON.stringify(String(input).includes('insights/') ? { ...insight, status: 'not_prepared', positive: [], analyzed_review_count: 0 } : game)));
  render(<MemoryRouter initialEntries={['/games/10']}><App/></MemoryRouter>);
  await waitFor(() => expect(screen.getByText('Review insights have not been prepared for this game yet.')).toBeInTheDocument());
  expect(screen.queryByText('The graphics are beautiful.')).not.toBeInTheDocument();
});
