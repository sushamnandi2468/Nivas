"use client";

import { ArrowLeft, ArrowRight, CheckCircle2, LockKeyhole, ShieldCheck, Ticket, UserCheck } from "lucide-react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";

import { activateInvitation } from "@/lib/nivasops-api";

function ActivationForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [apiBaseUrl] = useState(
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000",
  );
  const [societyId, setSocietyId] = useState(searchParams.get("society_id") ?? "");
  const [invitationId, setInvitationId] = useState(searchParams.get("invitation_id") ?? "");
  const [token, setToken] = useState(searchParams.get("token") ?? "");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (!societyId.trim() || !invitationId.trim() || !token.trim()) {
      setError("Please provide your Society ID, Invitation ID, and Invitation Token.");
      return;
    }

    if (password.length < 8) {
      setError("Password must be at least 8 characters long.");
      return;
    }

    if (password !== passwordConfirm) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      await activateInvitation(apiBaseUrl, {
        society_id: societyId.trim(),
        invitation_id: invitationId.trim(),
        token: token.trim(),
        password,
      });
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to activate invitation.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="property-visual" aria-label="NivasOps society activation">
        <div className="visual-grid" aria-hidden="true" />
        <div className="brand-lockup">
          <span className="brand-mark"><ShieldCheck size={21} strokeWidth={2.2} /></span>
          <span>NivasOps</span>
        </div>

        <div className="visual-copy">
          <p className="eyebrow"><span className="live-dot" /> Resident & Staff Activation</p>
          <h1>Join your<br />society workspace.</h1>
          <p className="visual-description">
            Activate your verified membership invitation to access community services, manage helpdesk tickets, and coordinate facility operations.
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
            <p className="section-label">Membership Onboarding</p>
            <h2>Activate Invitation</h2>
            <p>Set a secure password to activate your society membership.</p>
          </div>

          {success ? (
            <div className="auth-card-success">
              <CheckCircle2 size={36} color="var(--teal)" style={{ margin: "0 auto" }} />
              <h3>Account Activated!</h3>
              <p>Your membership has been successfully verified and provisioned.</p>
              <button
                type="button"
                className="submit-button"
                onClick={() => router.push("/")}
              >
                Continue to Sign In <ArrowRight size={18} />
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} noValidate style={{ marginTop: "24px" }}>
              {error && (
                <div className="auth-card-error" role="alert">
                  <span>{error}</span>
                </div>
              )}

              <label className="field-label" htmlFor="society-id">Society ID</label>
              <div className="text-field">
                <Ticket size={17} />
                <input
                  id="society-id"
                  required
                  placeholder="Society UUID"
                  value={societyId}
                  onChange={(e) => setSocietyId(e.target.value)}
                />
              </div>

              <label className="field-label" htmlFor="invitation-id">Invitation ID</label>
              <div className="text-field">
                <UserCheck size={17} />
                <input
                  id="invitation-id"
                  required
                  placeholder="Invitation UUID"
                  value={invitationId}
                  onChange={(e) => setInvitationId(e.target.value)}
                />
              </div>

              <label className="field-label" htmlFor="invitation-token">Invitation Token</label>
              <div className="text-field">
                <ShieldCheck size={17} />
                <input
                  id="invitation-token"
                  required
                  placeholder="64-character token"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                />
              </div>

              <label className="field-label" htmlFor="new-password">Create Password</label>
              <div className="text-field">
                <LockKeyhole size={17} />
                <input
                  id="new-password"
                  type="password"
                  required
                  autoComplete="new-password"
                  placeholder="Minimum 8 characters"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>

              <label className="field-label" htmlFor="confirm-password">Confirm Password</label>
              <div className="text-field">
                <LockKeyhole size={17} />
                <input
                  id="confirm-password"
                  type="password"
                  required
                  autoComplete="new-password"
                  placeholder="Re-enter password"
                  value={passwordConfirm}
                  onChange={(e) => setPasswordConfirm(e.target.value)}
                />
              </div>

              <button className="submit-button" type="submit" disabled={loading}>
                {loading ? "Activating..." : "Activate Membership"}
                <ArrowRight size={18} />
              </button>
            </form>
          )}

          <div className="auth-links">
            <Link href="/" className="auth-link">
              Already have an active account? Sign in
            </Link>
          </div>

          <div className="security-note">
            <ShieldCheck size={17} />
            <p><strong>Protected access</strong><span>Single-use invitation token · Tenant verified</span></p>
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

export default function ActivatePage() {
  return (
    <Suspense fallback={<div style={{ padding: "40px", color: "var(--text-soft)" }}>Loading activation portal...</div>}>
      <ActivationForm />
    </Suspense>
  );
}
