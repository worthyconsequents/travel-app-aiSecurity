"use client";

import { useState } from "react";
import TravelAssistant from "./travel-assistant";

type Hotel = { id: string; name: string; destination: string; price: number; rating: number; theme: string };
const destinations = [
  { city: "Lisbon", country: "Portugal", image: "lisbon.webp", line: "Slow mornings. Sunlit streets.", alt: "A tram on a street in Lisbon" },
  { city: "Kyoto", country: "Japan", image: "kyoto.webp", line: "Quiet corners. A different rhythm.", alt: "Lanterns lighting a Kyoto alley at night" },
  { city: "Vancouver", country: "Canada", image: "vancouver.webp", line: "City days. Mountain air.", alt: "Boats in Vancouver’s Coal Harbour beneath the mountains" },
];
const stayPhotos: Record<string, string> = {
  h01: "h01.webp", h02: "h02.webp", h03: "h03.webp", h04: "h04.webp",
  h05: "h05.webp", h06: "h06.webp", h07: "h07.webp", h08: "h08.webp",
  h09: "h09.webp", h10: "h10.webp", h11: "h11.webp", h12: "h12.webp",
};

type Booking = { id: string; hotel_name: string; status: string; human: string; check_in: string; check_out: string };

export default function Home() {
  const [identity, setIdentity] = useState("");
  const [destination, setDestination] = useState("");
  const [hotels, setHotels] = useState<Hotel[]>([]);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [chatBusy, setChatBusy] = useState(false);

  async function load(person: string, city: string) {
    setBusy(true); setError("");
    try {
      const login = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ identity: person }) });
      if (!login.ok) throw new Error("We couldn’t open your traveler profile. Please try again.");
      const [hotelResponse, bookingResponse] = await Promise.all([fetch(`/api/hotels?destination=${encodeURIComponent(city)}`), fetch("/api/bookings")]);
      if (!hotelResponse.ok || !bookingResponse.ok) throw new Error("We couldn’t load your stays right now. Please try again.");
      const [inventory, trips] = await Promise.all([hotelResponse.json(), bookingResponse.json()]);
      if (inventory.decision !== "ALLOW" || trips.decision !== "ALLOW") throw new Error("We couldn’t access these details. Please try again.");
      setHotels(inventory.result.hotels); setBookings(trips.result.bookings); setIdentity(person);
      return true;
    } catch (e) { setError(e instanceof Error ? e.message : "The request failed."); return false; }
    finally { setBusy(false); }
  }

  return <>
    <div className="notice">Good trips. Less fuss.</div>
    <header><a className="brand" href="/" aria-label="the boring-travel company home"><span className="brand-small">the</span><span>boring-travel<span className="dot">.</span></span><span className="brand-small">company</span></a><nav><a href="#stays">Explore stays</a><a href="#trips">Your trips</a><a href="#about">Our approach</a></nav><a className="account" href="#trips">Your account ↗</a></header>
    <main>
      <section className="hero"><div><p className="eyebrow">LESS PLANNING. MORE BEING THERE.</p><h1>Boring to plan.<br />Anything but to visit.</h1><p className="intro">Discover thoughtful stays in Lisbon, Kyoto, and Vancouver.<br />Great places to stay. One less thing to think about.</p></div><div className="art"><img src="/photos/lisbon.webp" alt="A classic Lisbon tram winding between colorful city buildings" width={1400} height={1800} fetchPriority="high" /><div className="photo-caption"><span>A LITTLE INSPIRATION</span><p>Meet you in Lisbon.</p><span>PORTUGAL · 38.7223° N, 9.1393° W</span></div></div></section>
      <form className="search" onSubmit={e => { e.preventDefault(); void load(identity || "alice", destination); }}><label>Destination<select value={destination} onChange={e => setDestination(e.target.value)}><option value="">All destinations</option><option>Lisbon</option><option>Kyoto</option><option>Vancouver</option></select></label><label>Traveler<select aria-label="Traveler" value={identity || "alice"} disabled={busy || chatBusy} onChange={e => void load(e.target.value, destination)}><option value="alice">Alice Chen</option><option value="bob">Bob Rivera</option></select></label><button disabled={busy || chatBusy}>{busy ? "Exploring…" : "Explore stays ↗"}</button></form>
      {error && <p className="error" role="alert">{error}</p>}
      <section className="destinations" aria-labelledby="destination-heading">
        <div className="section-title"><div><p className="eyebrow">A CHANGE OF SCENERY</p><h2 id="destination-heading">Where will you slow down?</h2></div><p>Three cities. Plenty to discover.</p></div>
        <div className="destination-grid">{destinations.map(place => <button className="destination-card" key={place.city} disabled={busy || chatBusy} onClick={() => { setDestination(place.city); void load(identity || "alice", place.city); document.getElementById("stays")?.scrollIntoView({ behavior: "smooth" }); }} aria-label={`Explore stays in ${place.city}`}>
          <img src={`/photos/${place.image}`} alt={place.alt} width={900} height={1100} loading="lazy" />
          <div className="destination-copy"><span>{place.country}</span><h3>{place.city}</h3><p>{place.line}</p></div><span className="destination-arrow" aria-hidden="true">↗</span>
        </button>)}</div>
      </section>
      <section id="stays"><div className="section-title"><div><p className="eyebrow">PLACES WITH PERSONALITY</p><h2>Somewhere worth staying.</h2></div><p>12 distinctive stays · 3 destinations</p></div>{!identity ? <div className="empty">Somewhere new is calling. Choose your destination and explore our stays.</div> : <div className="cards">{hotels.map(hotel => <article key={hotel.id}><div className="hotel-art"><img src={`/photos/${stayPhotos[hotel.id] || "h01.webp"}`} alt={`Interior inspiration for ${hotel.name}`} width={900} height={600} loading="lazy" /><span className="stay-category">{hotel.destination === "Kyoto" ? "Quiet retreats" : hotel.destination === "Vancouver" ? "City & nature" : "Characterful stays"}</span><span className="rating">★ {hotel.rating.toFixed(1)}</span></div><div className="card-body"><p className="eyebrow">{hotel.destination}</p><h3>{hotel.name}</h3><p className="price">${(hotel.price / 100).toFixed(0)} <span>/ night</span></p></div></article>)}</div>}{identity && hotels.length === 0 && <p className="empty">No stays found for this destination.</p>}</section>
      <section id="trips"><div className="section-title"><div><p className="eyebrow">YOUR OWN LITTLE ESCAPES</p><h2>Your trips.</h2></div><p>{identity ? `${identity === "alice" ? "Alice Chen" : "Bob Rivera"} · your reservations` : "Select a traveler to begin"}</p></div>{bookings.length ? bookings.map(b => <div className="trip" key={b.id}><div><h3>{b.hotel_name}</h3><p>{b.check_in} → {b.check_out}</p></div><span className="pill">{b.status}</span></div>) : <div className="empty">Your next getaway will feel right at home here. Choose your traveler profile to see your reservations.</div>}</section>
      <section id="about" className="about"><div><p className="eyebrow">HAPPILY UNCOMPLICATED</p><h2>We do the boring bit.</h2><p>Finding a place to stay shouldn’t take over your trip. We keep things simple, so you can spend more time looking forward to where you’re going.</p></div><div className="steps"><div><b>01</b><span>Good places, thoughtfully picked</span></div><div><b>02</b><span>The details, all in one place</span></div><div><b>03</b><span>Less searching. More exploring.</span></div></div></section>

    </main><footer><span className="footer-brand">the boring-travel company<span className="dot">.</span></span><span>All the good parts of getting away.</span><span>Lisbon · Kyoto · Vancouver</span></footer>
    <TravelAssistant key={identity || "alice"} traveler={identity || "alice"} ready={Boolean(identity)} locked={busy} onStart={() => load(identity || "alice", destination)} onBusyChange={setChatBusy} />
  </>;
}
