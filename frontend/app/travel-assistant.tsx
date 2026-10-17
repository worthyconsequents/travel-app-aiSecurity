"use client";

import { useEffect, useRef, useState } from "react";

type Stay = { id: string; name: string; destination: string; price: number; rating: number };
type Trip = { hotel_name: string; check_in: string; check_out: string; status: string };
type Message = { id: number; role: "assistant" | "user"; text: string; stays?: Stay[]; bookings?: Trip[] };
type Props = {
  traveler: string;
  ready: boolean;
  locked: boolean;
  onStart: () => Promise<boolean>;
  onBusyChange: (busy: boolean) => void;
};
const welcome: Message = {
  id: 0,
  role: "assistant",
  text: "Hello. A little less planning starts here. I can find stays, share hotel details, or help you check your trips.",
};
const prompts = ["Find stays in Lisbon", "Explore Kyoto", "Show my trips"];
const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export default function TravelAssistant({ traveler, ready, locked, onStart, onBusyChange }: Props) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([welcome]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const launcher = useRef<HTMLButtonElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const request = useRef<AbortController | null>(null);
  const nextId = useRef(1);
  const name = traveler === "bob" ? "Bob" : "Alice";

  useEffect(() => () => { request.current?.abort(); onBusyChange(false); }, [onBusyChange]);
  useEffect(() => { if (open && !sending && !locked) input.current?.focus(); }, [open, sending, locked]);
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [messages, sending, open]);

  function close() { setOpen(false); launcher.current?.focus(); }

  async function send(text: string) {
    const message = text.trim();
    if (!message || message.length > 2000 || sending || locked) return;
    const controller = new AbortController();
    request.current = controller;
    setSending(true); onBusyChange(true); setDraft("");
    setMessages(current => [...current.slice(-23), { id: nextId.current++, role: "user", text: message }]);
    try {
      if (!ready && !await onStart()) throw new Error("profile");
      if (controller.signal.aborted) return;
      const response = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }), signal: controller.signal,
      });
      if (!response.ok) throw new Error("unavailable");
      const result = await response.json();
      // Another browser tab may have changed the shared session cookie.
      // Discard any response for a different traveler, including its result cards.
      if (result.traveler !== traveler) throw new Error("profile");
      if (typeof result.message !== "string") throw new Error("unavailable");
      if (!controller.signal.aborted) setMessages(current => [...current, {
        id: nextId.current++, role: "assistant", text: result.message,
        stays: Array.isArray(result.stays) ? result.stays : [],
        bookings: Array.isArray(result.bookings) ? result.bookings : [],
      }]);
    } catch (error) {
      if (!controller.signal.aborted) {
        const profile = error instanceof Error && error.message === "profile";
        setMessages(current => [...(profile ? [welcome] : current), {
          id: nextId.current++, role: "assistant",
          text: profile
            ? "Your traveler profile changed. Choose your traveler above and explore stays to reconnect."
            : "I couldn’t reach your travel details just now. Please try your message again in a moment.",
        }]);
        setDraft(message);
      }
    } finally {
      if (!controller.signal.aborted) { setSending(false); onBusyChange(false); input.current?.focus(); }
    }
  }

  return <div className="travel-chat">
    {open && <section className="chat-panel" role="dialog" aria-modal="false" aria-labelledby="chat-title" onKeyDown={e => { if (e.key === "Escape") close(); }}>
      <div className="chat-header">
        <div className="chat-avatar" aria-hidden="true">b.</div>
        <div><h2 id="chat-title">Your travel assistant</h2><p>A little help getting away · {name}</p></div>
        <button className="chat-close" type="button" onClick={close} aria-label="Close travel assistant">×</button>
      </div>
      <div className="chat-toolbar"><span>Good trips. Less fuss.</span><button type="button" disabled={sending} onClick={() => { setMessages([welcome]); setDraft(""); input.current?.focus(); }}>New chat ↺</button></div>
      <div className="chat-log" ref={log} role="log" aria-label="Travel conversation" aria-live="polite" aria-relevant="additions" aria-busy={sending}>
        {messages.map(item => <div className={`chat-message ${item.role}`} key={item.id}>
          <span className="chat-speaker">{item.role === "user" ? "You" : "Travel assistant"}</span>
          <p>{item.text}</p>
          {!!item.stays?.length && <div className="chat-stays">{item.stays.map(stay => <div className="chat-stay" key={stay.id}>
            <img src={`/photos/${/^h(?:0[1-9]|1[0-2])$/.test(stay.id) ? stay.id : "h01"}.webp`} alt="" width={68} height={76} loading="lazy" />
            <div><span className="chat-city">{stay.destination} · ★ {stay.rating.toFixed(1)}</span><h3>{stay.name}</h3><span className="chat-rate">{money.format(stay.price / 100)} <small>/ night</small></span>
              <button type="button" disabled={sending || locked} onClick={() => void send(`Tell me about ${stay.id}`)} aria-label={`Details for ${stay.name}`}>More about this stay ↗</button>
            </div>
          </div>)}</div>}
          {item.bookings?.map((trip, index) => <div className="chat-trip" key={`${trip.hotel_name}-${index}`}><h3>{trip.hotel_name}</h3><p>{trip.check_in} → {trip.check_out}</p><span>{trip.status}</span></div>)}
        </div>)}
        {sending && <p className="chat-thinking" role="status">Checking the details<span aria-hidden="true">…</span></p>}
      </div>
      <div className="chat-suggestions" aria-label="Suggested questions">{prompts.map(prompt => <button key={prompt} type="button" disabled={sending || locked} onClick={() => void send(prompt)}>{prompt} ↗</button>)}</div>
      <form className="chat-compose" onSubmit={e => { e.preventDefault(); void send(draft); }}>
        <label className="sr-only" htmlFor="travel-message">Message your travel assistant</label>
        <textarea id="travel-message" ref={input} rows={2} value={draft} maxLength={2000} disabled={sending || locked} placeholder="Where would you like to go?" onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(draft); } }} />
        <button type="submit" disabled={sending || locked || !draft.trim()} aria-label="Send message">↑</button>
      </form>
      <p className="chat-note">For finding stays and checking trips. Listed rates in USD.</p>
    </section>}
    <button ref={launcher} type="button" className="chat-launcher" aria-expanded={open} aria-haspopup="dialog" onClick={() => open ? close() : setOpen(true)}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H5l-4 3 1.7-6.1A8.5 8.5 0 1 1 21 11.5Z" /><path d="M7 10h8M7 14h5" /></svg>
      {open ? "Close assistant" : "A little travel help"}
    </button>
  </div>;
}
