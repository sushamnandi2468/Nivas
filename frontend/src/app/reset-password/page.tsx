"use client";

import { ArrowLeft, ArrowRight, CheckCircle2, LockKeyhole, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";

import { confirmPasswordReset } from "@/lib/nivasops-api";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [apiBaseUrl] = useState(
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000",
  );
  const [token, setToken] = useState(searchParams.get("token") ?? "");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (!token.trim()) {
      setError("Please provide the password reset token from your email.");
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
      await confirmPasswordReset(apiBaseUrl, {
        token: token.trim(),
        password,
      });
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset password.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="property-visual" aria-label="NivasOps password reset">
        <div className="visual-grid" aria-hidden="true" />
        <div className="brand-lockup">
          <span className="brand-mark"><ShieldCheck size={21} strokeWidth={2.2} /></span>
          <span>NivasOps</span>
        </div>

        <div className="visual-copy">
          <p className="eyebrow"><span className="live-dot" /> Security Verification</p>
          <h1>Reset your<br />account password.</h1>
          <p className="visual-description">
            Choose a strong, unique password to secure your society operations profile.
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
            <p className="section-label">Password Reset</p>
            <h2>Create New Password</h2>
            <p>Enter your reset token and your new password.</p>
          </div>

          {success ? (
            <div className="auth-card-success">
              <CheckCircle2 size={36} color="var(--teal)" style={{ margin: "0 auto" }} />
              <h3>Password Updated</h3>
              <p>Your password has been securely reset. You can now sign in with your new credentials.</p>
              <button
                type="button"
                className="submit-button"
                onClick={() => router.push("/")}
              >
                Sign In Now <ArrowRight size={18} />
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} noValidate style={{ marginTop: "24px" }}>
              {error && (
                <div className="auth-card-error" role="alert">
                  <span>{error}</span>
                </div>
              )}

              <label className="field-label" htmlFor="reset-token">Reset Token</label>
              <div className="text-field">
                <ShieldCheck size={17} />
                <input
                  id="reset-token"
                  required
                  placeholder="Reset token from email"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                />
              </div>

              <label className="field-label" htmlFor="new-password">New Password</label>
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

              <label className="field-label" htmlFor="confirm-new-password">Confirm New Password</label>
              <div className="text-field">
                <LockKeyhole size={17} />
                <input
                  id="confirm-new-password"
                  type="password"
                  required
                  autoComplete="new-password"
                  placeholder="Re-enter new password"
                  value={passwordConfirm}
                  onChange={(e) => setPasswordConfirm(e.target.value)}
                />
              </div>

              <button className="submit-button" type="submit" disabled={loading}>
                {loading ? "Updating..." : "Update Password"}
                <ArrowRight size={18} />
              </button>
            </form>
          )}

          <div className="auth-links">
            <Link href="/" className="auth-link">
              Back to Sign In
            </Link>
          </div>

          <div className="security-note">
            <ShieldCheck size={17} />
            <p><strong>Protected access</strong><span>Single-use token · Session revocation enforced</span></p>
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

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div style={{ padding: "40px", color: "var(--text-soft)" }}>Loading password reset portal...</div>}>
      <ResetPasswordForm />
    </Suspense>
  );
}
