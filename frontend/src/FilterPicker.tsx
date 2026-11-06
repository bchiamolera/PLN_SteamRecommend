import { useEffect, useRef, useState } from 'react';
import { Facets } from './api';

const key = (value: string) => value.normalize('NFKC').trim().toLocaleLowerCase('en-US');

export function FilterPicker({ field, title, options, selected, change, disabled }: {
  field: string; title: string; options: Facets['tags']; selected: string[];
  change: (values: string[]) => void; disabled: boolean;
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const input = useRef<HTMLInputElement>(null);
  const selectedKeys = new Set(selected.map(key));
  const matches = options.filter(option => !selectedKeys.has(key(option.label)) && key(option.label).includes(key(query)));
  const expanded = open && !disabled;
  const listId = `${field}-options`;

  useEffect(() => {
    if (expanded && active >= 0) document.getElementById(`${field}-option-${active}`)?.scrollIntoView?.({ block: 'nearest' });
  }, [active, expanded, field]);

  function choose(option: Facets['tags'][number]) {
    // Only commit an object supplied by the catalog endpoint, never typed text.
    if (!selectedKeys.has(key(option.label))) change([...selected, option.label]);
    input.current?.focus();
    setQuery(''); setActive(-1); setOpen(false);
  }

  return <div className="filter-picker" onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) { setOpen(false); setActive(-1); }
  }}>
    <label htmlFor={field}>{title}</label>
    <div className="filter-dropdown">
      <div className="filter-input">
        <input ref={input} id={field} role="combobox" aria-autocomplete="list" aria-expanded={expanded}
          aria-controls={listId} aria-activedescendant={expanded && active >= 0 && active < matches.length ? `${field}-option-${active}` : undefined}
          autoComplete="off" value={query} disabled={disabled} placeholder="Search catalog options…"
          onFocus={() => setOpen(true)} onClick={() => setOpen(true)}
          onChange={event => { setQuery(event.target.value); setActive(0); setOpen(true); }}
          onKeyDown={event => {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
              event.preventDefault(); setOpen(true);
              setActive(current => matches.length ? (event.key === 'ArrowDown' ? Math.min(current + 1, matches.length - 1) : Math.max(current - 1, 0)) : -1);
            } else if (event.key === 'Enter') {
              event.preventDefault();
              if (expanded && matches[active]) choose(matches[active]);
            } else if (event.key === 'Escape') { event.preventDefault(); setOpen(false); setActive(-1); }
            else if (event.key === 'Tab') setOpen(false);
          }}/>
        <button type="button" tabIndex={-1} disabled={disabled} aria-label={`Toggle ${title.toLowerCase()} options`}
          onMouseDown={event => event.preventDefault()} onClick={() => { input.current?.focus(); setOpen(!expanded); setActive(-1); }}><span className="select-arrow" aria-hidden="true"/></button>
      </div>
      {expanded && <div className="filter-menu">
        <ul id={listId} role="listbox" aria-label={`${title} options`}>
          {matches.map((option, index) => <li id={`${field}-option-${index}`} key={option.label} role="option" aria-selected={index === active}
            className={index === active ? 'active' : ''} onMouseDown={event => event.preventDefault()}
            onMouseEnter={() => setActive(index)} onClick={() => choose(option)}>
            <span>{option.label}</span><small>{option.count.toLocaleString('en-US')} games</small>
          </li>)}
        </ul>
        {!matches.length && <p role="status">No matching catalog options.</p>}
      </div>}
    </div>
    <div className="filter-chips">{selected.map(label => <button type="button" key={label}
      onClick={() => change(selected.filter(value => value !== label))} aria-label={`Remove ${label} from ${title.toLowerCase()}`}>{label} ×</button>)}</div>
  </div>;
}
