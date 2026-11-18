import { FormEvent, useEffect, useRef, useState } from 'react';
import { AgentErrorPanel, RecommendationCard } from './AgentPresentation';
import { AgentControls, useAgent } from './AgentDiscovery';

export function ChatPage() {
  const agent = useAgent();
  const chat = agent.chat;
  const [draft, setDraft] = useState('');
  const composer = useRef<HTMLTextAreaElement>(null);
  function choosePrompt(value: string) { setDraft(value); composer.current?.focus(); }
  const body = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  useEffect(() => { if (following.current && body.current) body.current.scrollTop = body.current.scrollHeight; }, [chat.turns.length, chat.pending]);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim() || !agent.model || chat.busy || agent.busy) return;
    following.current = true; void chat.send(draft); setDraft('');
  }
  return <>
    <section className="hero chat-hero"><p className="eyebrow">YOUR GAME DISCOVERY COMPANION</p><h1>Let’s find your <em>next game.</em></h1><p className="intro">Tell me what you enjoy. Ask questions, compare suggestions, and explore the player opinions behind them.</p></section>
    <div className="discovery-layout chat-layout">
      <aside className="search-panel chat-sidebar" aria-label="Chat settings"><p className="eyebrow">YOUR SPACE TO EXPLORE</p><h2>A little guidance.<br/>A great next game.</h2><p className="chat-sidebar-copy">Build on every suggestion. Tell Atlas what fits, what doesn’t, and what you want to try next.</p><details className="chat-connection" open={!agent.model}><summary><span>Agent connection</span><span className={`connection-badge ${agent.model ? "connected" : ""}`}>{agent.model ? "Ready" : "Set up"}</span></summary>
        <AgentControls chat initialFilters={{ required_tag: [], excluded_tag: [], genre: [] }}/>
        {agent.error && <AgentErrorPanel message={agent.error} code={agent.failure?.code} requestId={agent.failure?.requestId}/>}</details>
        <button className="secondary" onClick={() => { chat.reset(); setDraft(''); }}>New chat</button>
        <p className="hint">Your conversation stays in this tab while you browse. Reloading clears it. Replies use the local catalog and collected English reviews.</p>
      </aside>
      <section className="chat-panel" aria-label="Game recommendation chat"><div className="chat-toolbar"><div><span className="atlas-avatar" aria-hidden="true">✳</span><div><strong>Steam Atlas</strong><span>Your game discovery companion</span></div></div><span className="chat-session-label">THIS SESSION</span></div><div className="chat-body" ref={body} onScroll={event => { const el = event.currentTarget; following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}>
        {!chat.turns.length && !chat.pending && <div className="welcome-panel chat-welcome"><span className="chat-orbit" aria-hidden="true">✳</span><p className="eyebrow">LESS SEARCHING. MORE PLAYING.</p><h2>What do you feel like playing?</h2><p>Start with a mood, a mechanic, or something you already love.</p>
          <div className="chat-starters">{[['☀', 'Something cozy', 'A cozy farming game with exploration'], ['⚒', 'Better together', 'Co-op survival with base building'], ['✧', 'Lose me in a story', 'A story-rich adventure with less combat']].map(([icon, title, prompt]) => <button key={prompt} className="chat-prompt" onClick={() => choosePrompt(prompt)}><span aria-hidden="true">{icon}</span><strong>{title}</strong><small>{prompt}</small><span className="prompt-arrow" aria-hidden="true">↗</span></button>)}</div>
        </div>}
        <div role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions" className="chat-transcript">
          {chat.turns.map((turn, i) => <div className="chat-turn" key={i}>
            <article className="chat-message chat-user" aria-label="Your message"><strong>You</strong><p>{turn.message}</p></article>
            <article className="chat-message" aria-label="Agent reply"><strong><span className="reply-star" aria-hidden="true">✳</span> Steam Atlas</strong><p>{turn.response.reply}</p>
              <div className="chat-games">{turn.response.results.map(game => <RecommendationCard key={game.appid} game={game} fromChat/>)}</div>
              {turn.response.preferences.length > 0 && <p className="hint">Preferences: {turn.response.preferences.join(' · ')}</p>}
              <details className="hint"><summary>Limitations and sources</summary><ul>{turn.response.limitations.map((value, j) => <li key={j}>{value}</li>)}</ul><p>{turn.response.provider} / {turn.response.model}</p></details>
            </article>
          </div>)}
          {chat.pending && <><article className="chat-message chat-user"><strong>You</strong><p>{chat.pending}</p></article><p role="status" className="chat-thinking"><span className="loading-dot" aria-hidden="true"/>Your agent is exploring…</p></>}
        </div>
        {chat.error && <><AgentErrorPanel message={chat.error} code={chat.errorCode} requestId={chat.requestId}/><p>{chat.failed}</p><button className="secondary" disabled={chat.busy || agent.busy || !agent.model} onClick={() => void chat.send(chat.failed)}>Retry message</button></>}
        {chat.interrupted && <div className="interrupted-message"><p>Your message was interrupted. You can edit it before sending again.</p><button className="secondary" onClick={() => { choosePrompt(chat.interrupted); chat.dismissInterrupted(); }}>Restore message</button></div>}
        </div><div className="chat-compose-area">{chat.turns.length > 0 && !chat.busy && <div className="chat-followups" aria-label="Suggested follow-ups">{["Why this game?", ...(chat.turns[chat.turns.length - 1].response.results.length >= 2 ? ["Compare the first two"] : []), "Less combat"].map(prompt => <button type="button" key={prompt} onClick={() => choosePrompt(prompt)}>{prompt} <span aria-hidden="true">↗</span></button>)}</div>}
        <form className="chat-composer search-form" onSubmit={submit}><label htmlFor="chat-message">Message your game agent</label><div className="search-input"><textarea ref={composer} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} id="chat-message" maxLength={500} rows={2} value={draft} onChange={event => setDraft(event.target.value)} placeholder={agent.model ? "Describe your next adventure…" : "Connect your agent to start exploring…"} required/><button disabled={chat.busy || agent.busy || !agent.model || !agent.key || !draft.trim()}>Send message ↗</button></div><div className="composer-meta"><span>{agent.model ? "Enter to send · Shift + Enter for a new line" : "Choose a provider and model in Agent connection"}</span><span>{draft.length}/500</span></div></form>
        {chat.busy && <button className="secondary" onClick={chat.stop}>Stop waiting</button>}
        <p className="hint chat-privacy">English · Each message can incur provider charges. Stopping ends the wait; the provider may finish an accepted request.</p></div>
      </section>
    </div>
  </>;
}
