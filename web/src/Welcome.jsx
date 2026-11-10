// The way in: an account, or a guest workspace in one press.
//
// Either way the visitor gets a workspace of their own, so a correction or an
// upload is theirs and nobody else's. A guest is not a lesser mode -- it is
// the same workspace without a name -- because a judge given the link should
// be one press from the model, not a form away from it.

import { useEffect, useState } from "react";
import { account } from "./App.jsx";
import "./showcase.css";

const BACKDROP = "/projects/AB_Fourplex_01_Technical_Design_Package/cover.jpg";

export default function Welcome({ onSignedIn }) {
  const [mode, setMode] = useState("guest"); // guest | signin | signup
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [cover, setCover] = useState(false);

  useEffect(() => {
    const img = new Image();
    img.onload = () => setCover(true);
    img.src = BACKDROP;
  }, []);

  async function go(path, body) {
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await account(path, body));
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  function submit(e) {
    e.preventDefault();
    if (!name.trim() || !password) {
      setError("Enter a name and a password.");
      return;
    }
    go(mode === "signup" ? "/auth/signup" : "/auth/login", {
      username: name,
      password,
    });
  }

  const form = mode !== "guest";

  return (
    <div className="sc sc-welcome">
      <div
        className={`sc-backdrop${cover ? " has-cover" : ""}`}
        style={cover ? { backgroundImage: `url(${BACKDROP})` } : undefined}
        aria-hidden="true"
      />
      <div className="sc-veil" aria-hidden="true" />

      <main className="wl">
        <div className="wl-brand">
          <span className="sc-logo" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="18" height="18">
              <path d="M4 7h16M4 12h16M4 17h10" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" fill="none" />
            </svg>
          </span>
          <b>ecarbon</b>
        </div>
        <h1>Embodied carbon, read from the drawings</h1>
        <p className="wl-lede">
          A vector PDF plan set in. A bill of quantities that cites the sheet
          every number came from, and an A1–A3 carbon figure, out.
        </p>

        <section className="glass wl-card" aria-label="Open a workspace">
          {!form ? (
            <>
              <button
                className="sc-btn sc-btn-primary wl-guest"
                onClick={() => go("/auth/guest")}
                disabled={busy}
              >
                {busy ? "Opening…" : "Continue as a guest"}
              </button>
              <div className="wl-or"><span>or</span></div>
              <div className="wl-pair">
                <button className="glass sc-btn" onClick={() => setMode("signin")}>
                  Sign in
                </button>
                <button className="glass sc-btn" onClick={() => setMode("signup")}>
                  Create an account
                </button>
              </div>
            </>
          ) : (
            <form onSubmit={submit} noValidate>
              <div className="sc-seg wl-tabs" role="tablist">
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === "signin"}
                  className={mode === "signin" ? "is-on" : ""}
                  onClick={() => { setMode("signin"); setError(null); }}
                >
                  Sign in
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === "signup"}
                  className={mode === "signup" ? "is-on" : ""}
                  onClick={() => { setMode("signup"); setError(null); }}
                >
                  Create an account
                </button>
              </div>
              <label className="wl-field" htmlFor="wl-name">
                <span>Name</span>
                <input
                  id="wl-name"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck="false"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoFocus
                />
                {mode === "signup" && <em>3 to 32 letters, numbers, dashes or underscores</em>}
              </label>
              <label className="wl-field" htmlFor="wl-password">
                <span>Password</span>
                <input
                  id="wl-password"
                  type="password"
                  autoComplete={mode === "signup" ? "new-password" : "current-password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                {mode === "signup" && <em>At least 6 characters</em>}
              </label>
              {error && (
                <p className="wl-error" role="alert">
                  {error}
                </p>
              )}
              <button className="sc-btn sc-btn-primary wl-submit" type="submit" disabled={busy}>
                {busy ? "One moment…" : mode === "signup" ? "Create account" : "Sign in"}
              </button>
              <button type="button" className="sc-link wl-back" onClick={() => { setMode("guest"); setError(null); }}>
                Continue as a guest instead
              </button>
            </form>
          )}
          {!form && error && (
            <p className="wl-error" role="alert">
              {error}
            </p>
          )}
        </section>

        <p className="wl-note">
          Corrections and uploads stay in your own workspace; nobody else sees
          them. Accounts are held on this server and clear when it restarts.
          The bundled plan sets are always here.
        </p>
      </main>
    </div>
  );
}
