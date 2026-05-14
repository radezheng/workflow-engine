import { KeyboardEvent, useEffect, useState } from 'react';
import { Bot, Check, LoaderCircle, Send, Sparkles } from 'lucide-react';
import type { AIAssistContext, AIAssistMessage, AIAssistTarget, AIProvider } from '../../api';
import { getAIProviders, requestAIAssist } from '../../api';

type AIAssistPanelProps = {
  target: AIAssistTarget;
  draft: Record<string, unknown>;
  context?: AIAssistContext;
  disabled: boolean;
  onApplyDraft: (draft: Record<string, unknown>) => void;
};

export function AIAssistPanel({ target, draft, context = {}, disabled, onApplyDraft }: AIAssistPanelProps) {
  const [open, setOpen] = useState(false);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [provider, setProvider] = useState('');
  const [messages, setMessages] = useState<AIAssistMessage[]>([]);
  const [input, setInput] = useState('');
  const [pendingDraft, setPendingDraft] = useState<Record<string, unknown> | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    let active = true;
    void getAIProviders()
      .then((items) => {
        if (!active) return;
        setProviders(items);
        setProvider((current) => current || items[0]?.name || '');
      })
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : String(caught));
      });
    return () => { active = false; };
  }, [open]);

  async function submit() {
    const prompt = input.trim();
    if (!prompt || !provider) return;
    const nextMessages = [...messages, { role: 'user' as const, content: prompt }];
    setMessages(nextMessages);
    setInput('');
    setBusy(true);
    setError('');
    try {
      const response = await requestAIAssist(provider, target, nextMessages, draft, context);
      setMessages([...nextMessages, { role: 'assistant', content: response.message }]);
      setPendingDraft(response.draft);
      setReady(response.ready);
      if (response.ready) {
        onApplyDraft(response.draft);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  function handleClose() {
    setOpen(false);
    setError('');
  }

  function handleApply() {
    if (!pendingDraft) return;
    onApplyDraft(pendingDraft);
    setReady(true);
  }

  function handleInputKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      void submit();
    }
  }

  if (!open) {
    return (
      <button type="button" className="secondary-button" disabled={disabled} onClick={() => setOpen(true)} title="AI Assist">
        <Sparkles size={15} />
        AI Assist
      </button>
    );
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="ai-assist-modal" role="dialog" aria-modal="true" aria-label="AI Assist">
        <div className="ai-assist-header">
          <span><Bot size={15} /> AI Assist</span>
          <button type="button" className="secondary-button" disabled={busy} onClick={handleClose}>Close</button>
        </div>
        <select value={provider} onChange={(event) => setProvider(event.target.value)} disabled={busy || !providers.length} title="AI provider">
          {!providers.length && <option value="">No providers</option>}
          {providers.map((item) => (
            <option key={item.name} value={item.name}>{item.name} · {item.model}</option>
          ))}
        </select>
        <div className="ai-chat-log">
          {!messages.length && <p className="empty-state">{providers.length ? 'Describe what you want.' : 'Configure ai_providers in hwe.config.yaml.'}</p>}
          {messages.map((message, index) => (
            <article key={`${message.role}-${index}`} className={`ai-chat-message ${message.role}`}>
              {message.content}
            </article>
          ))}
          {busy && <article className="ai-chat-message assistant loading" role="status"><LoaderCircle size={14} /> Processing...</article>}
        </div>
        {pendingDraft && !ready && <div className="ai-draft-status" role="status">Waiting for enough information before applying to the form.</div>}
        {ready && <div className="ai-draft-status ready" role="status">Draft applied to the form.</div>}
        {error && <div className="inline-error" role="status">{error}</div>}
        <div className="ai-chat-form">
          <textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={handleInputKeyDown} rows={4} disabled={busy || disabled || !provider} placeholder={busy ? 'AI is processing...' : undefined} autoFocus />
          <div className="form-actions">
            <button type="button" className="secondary-button" disabled={busy || !pendingDraft} onClick={handleApply} title="Apply draft">
              <Check size={15} />
              Apply
            </button>
            <button type="button" className="primary-button" disabled={busy || disabled || !provider || !input.trim()} onClick={() => void submit()} title="Send">
              {busy ? <LoaderCircle className="spin-icon" size={15} /> : <Send size={15} />}
              {busy ? 'Processing' : 'Send'}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}