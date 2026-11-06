import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { FilterPicker } from './FilterPicker';

const options = [{ label: 'Co-op', count: 20 }, { label: 'Zombies', count: 10 }];
function setup(selected: string[] = []) {
  const change = vi.fn();
  render(<FilterPicker field="tags" title="Tags" options={options} selected={selected} change={change} disabled={false}/>);
  return { input: screen.getByRole('combobox', { name: 'Tags' }), change };
}

test('opens registered options, searches case-insensitively, and commits a catalog selection', () => {
  const { input, change } = setup();
  fireEvent.focus(input);
  expect(screen.getAllByRole('option')).toHaveLength(2);
  fireEvent.change(input, { target: { value: 'CO-' } });
  expect(screen.getAllByRole('option')).toHaveLength(1);
  fireEvent.click(screen.getByRole('option', { name: /Co-op/ }));
  expect(change).toHaveBeenCalledWith(['Co-op']);
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
});

test('arbitrary input cannot create a filter', () => {
  const { input, change } = setup();
  fireEvent.change(input, { target: { value: 'Not registered' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(screen.getByRole('status')).toHaveTextContent('No matching catalog options');
  expect(change).not.toHaveBeenCalled();
});

test('supports keyboard selection and Escape without duplicates', () => {
  const { input, change } = setup(['co-op']);
  fireEvent.focus(input);
  expect(screen.getAllByRole('option')).toHaveLength(1);
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(change).toHaveBeenCalledWith(['co-op', 'Zombies']);
  fireEvent.focus(input);
  fireEvent.keyDown(input, { key: 'Escape' });
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
});

test('closes when focus leaves the picker', () => {
  const { input } = setup();
  fireEvent.focus(input);
  fireEvent.blur(input, { relatedTarget: null });
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
});
