import { useEffect, useRef, useState } from 'react';
import { AgentContext, AgentRequestError, ChatResponse, ChatTurn, agentPost } from './api';

export function useChatSession(provider: string, model: string, key: string) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [pending, setPending] = useState('');
  const [failed, setFailed] = useState('');
  const [error, setError] = useState('');
  const [errorCode, setErrorCode] = useState('');
  const [requestId, setRequestId] = useState<string>();
  const [interrupted, setInterrupted] = useState('');
  const active = useRef<AbortController | null>(null);
  const pendingText = useRef('');
  const version = useRef(0);
  const context = useRef<AgentContext>({ preferences: [], latest_query: '', previous_appids: [] });
  function stop() {
    if (active.current) setInterrupted(pendingText.current);
    version.current++; active.current?.abort(); active.current = null;
    setPending('');
  }
  function reset() {
    stop(); setTurns([]); setFailed(''); setError(''); setErrorCode(''); setRequestId(undefined); setInterrupted('');
    context.current = { preferences: [], latest_query: '', previous_appids: [] };
  }
  useEffect(() => () => active.current?.abort(), []);
  async function send(value: string) {
    const message = value.trim();
    if (!message || message.length > 500 || !provider || !model || !key || active.current) return;
    const controller = new AbortController(); active.current = controller;
    pendingText.current = message;
    const generation = ++version.current;
    setPending(message); setFailed(''); setError(''); setErrorCode(''); setRequestId(undefined); setInterrupted('');
    const history = turns.slice(-6).flatMap(turn => [
      { role: 'user', content: turn.message, appids: [] },
      { role: 'assistant', content: turn.response.reply,
        appids: turn.response.results.map(game => game.appid),
        games: turn.response.results.map(game => ({ appid: game.appid, explanation: game.explanation.slice(0, 700) })) },
    ]);
    try {
      const response = await agentPost<ChatResponse>('chat', {
        provider, model, message, history, context: context.current,
      }, key, controller.signal);
      if (generation !== version.current) return;
      context.current = response.context;
      setTurns(previous => [...previous, { message, response }]);
    } catch (e) {
      if (generation !== version.current || controller.signal.aborted) return;
      setFailed(message); setError(e instanceof Error ? e.message : 'Chat request failed.');
      if (e instanceof AgentRequestError) { setErrorCode(e.code); setRequestId(e.requestId); }
    } finally {
      if (generation === version.current) { active.current = null; setPending(''); }
    }
  }
  return { turns, pending, failed, error, errorCode, requestId, interrupted,
    dismissInterrupted: () => setInterrupted(''), busy: !!pending, send, reset, stop };
}
