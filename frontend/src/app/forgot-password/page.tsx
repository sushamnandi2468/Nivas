"use client";

import { ArrowLeft, ArrowRight, CheckCircle2, Mail, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { FormEvent, useState } from "react";

import { requestPasswordReset } from "@/lib/nivasops-api";

export default function ForgotPasswordPage() {
  const [apiBaseUrl] = useState(
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000",
  );
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (!email.trim() || !email.includes("@")) {
      setError("Please enter a valid email address.");
      return;
    }

    setLoading(true);
    try {
      await requestPasswordReset(apiBaseUrl, email);
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to process password reset.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="property-visual" aria-label="NivasOps password recovery">
        <div className="visual-grid" aria-hidden="true" />
        <div className="brand-lockup">
          <span className="brand-mark"><ShieldCheck size={21} strokeWidth={2.2} /></span>
          <span>NivasOps</span>
        </div>

        <div className="visual-copy">
          <p className="eyebrow"><span className="live-dot" /> Account Security</p>
          <h1>Recover access to<br />your workspace.</h1>
          <p className="visual-description">
            We will send time-bounded password reset instructions to your registered email address.
          </p>
        </div>
      </section>

      <section className="auth-panel">
        <div className="mobile-brand">
          <span className="brand-mark"><ShieldCheck size={19} /></span>
          <span>NivasOps</span>
        </div>

        <div className="auth-content">
          <Link href="/" className="auth-back-link">
            <ArrowLeft size={16} /> Back to sign in
          </Link>

          <div className="auth-heading">
            <p className="section-label">Account Recovery</p>
            <h2>Forgot Password</h2>
            <p>Enter the email address linked to your society account.</p>
          </div>

          {submitted ? (
            <div className="auth-card-success">
              <CheckCircle2 size={36} color="var(--teal)" style={{ margin: "0 auto" }} />
              <h3>Instructions Dispatched</h3>
              <p>
                If your account is eligible, password reset instructions have been sent to{" "}
                <strong>{email}</strong>.
              </p>
              <Link href="/" className="auth-link" style={{ justifyContent: "center" }}>
                Return to Sign In <ArrowRight size={16} />
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} noValidate style={{ marginTop: "24px" }}>
              {error && (
                <div className="auth-card-error" role="alert">
                  <span>{error}</span>
                </div>
              )}

              <label className="field-label" htmlFor="reset-email">Registered Email</label>
              <div className="text-field">
                <Mail size={17} />
                <input
                  id="reset-email"
                  type="email"
                  required
                  autoComplete="email"
                  placeholder="name@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>

              <button className="submit-button" type="submit" disabled={loading}>
                {loading ? "Sending..." : "Send Reset Link"}
                <ArrowRight size={18} />
              </button>
            </form>
          )}

          <div className="auth-links">
            <Link href="/" className="auth-link">
              Remembered your password? Sign in
            </Link>
            <Link href="/activate" className="auth-link">
              Have an invitation token? Activate account
            </Link>
          </div>

          <div className="security-note">
            <ShieldCheck size={17} />
            <p><strong>Protected access</strong><span>Time-bounded token · Rate-limited recovery</span></p>
          </div>
        </div>

        <footer>
          <span>© 2026 NivasOps</span>
          <span>Privacy · Support</span>
        </footer>
      </section>
    </main>
  );
}
