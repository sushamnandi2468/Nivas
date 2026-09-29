"use client";

import {
  Activity,
  ArrowRight,
  Building2,
  Check,
  Eye,
  EyeOff,
  LockKeyhole,
  Mail,
  ShieldCheck,
  Smartphone,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";

import { loginWithEmailPassword, normalizeApiBaseUrl, WorkspacePersona } from "@/lib/nivasops-api";

type SignInMode = "password" | "otp";

const OTP_LENGTH = 4;
const RESEND_SECONDS = 45;
const STORAGE_KEY = "nivasops.workspace-session";
const SESSION_EVENT = "nivasops-session-change";

export default function Home() {
  const router = useRouter();
  const [mode, setMode] = useState<SignInMode>("password");
  const [apiBaseUrl] = useState(
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000",
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [societyId, setSocietyId] = useState("");
  const [workspacePersona, setWorkspacePersona] = useState<WorkspacePersona>("RESIDENT");
  const [phone, setPhone] = useState("");
  const [otpRequested, setOtpRequested] = useState(false);
  const [otp, setOtp] = useState(() => Array<string>(OTP_LENGTH).fill(""));
  const [secondsRemaining, setSecondsRemaining] = useState(RESEND_SECONDS);
  const [showPassword, setShowPassword] = useState(false);
  const [message, setMessage] = useState("");
  const [isError, setIsError] = useState(false);
  const [loading, setLoading] = useState(false);
  const otpInputs = useRef<Array<HTMLInputElement | null>>([]);

  useEffect(() => {
    if (!otpRequested || secondsRemaining === 0) return;

    const timer = window.setInterval(() => {
      setSecondsRemaining((current) => Math.max(0, current - 1));
    }, 1000);

    return () => window.clearInterval(timer);
  }, [otpRequested, secondsRemaining]);

  const digits = phone.replace(/\D/g, "").slice(0, 10);
  const formattedPhone = digits.replace(/(\d{5})(?=\d)/, "$1 ");

  function selectMode(nextMode: SignInMode) {
    setMode(nextMode);
    setMessage("");
    setIsError(false);
  }

  function requestOtp() {
    if (digits.length !== 10) {
      setMessage("Enter a valid 10-digit mobile number.");
      setIsError(true);
      return;
    }

    setOtpRequested(true);
    setOtp(Array<string>(OTP_LENGTH).fill(""));
    setSecondsRemaining(RESEND_SECONDS);
    setMessage("");
    setIsError(false);
    window.setTimeout(() => otpInputs.current[0]?.focus(), 0);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    setIsError(false);

    if (mode === "otp") {
      if (!otpRequested) {
        requestOtp();
        return;
      }

      if (otp.some((value) => value === "")) {
        setMessage("Enter all four digits from your verification code.");
        setIsError(true);
        return;
      }

      setMessage("SMS Gateway is operating in developer preview mode. Please sign in with your verified Password.");
      setIsError(false);
      return;
    }

    if (!email.trim() || !password) {
      setMessage("Please enter your registered email address and password.");
      setIsError(true);
      return;
    }

    const trimmedSocietyId = societyId.trim();
    const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!trimmedSocietyId) {
      setMessage("Please enter your Society UUID. All workspace requests require an authorized society context.");
      setIsError(true);
      return;
    }
    if (!UUID_REGEX.test(trimmedSocietyId)) {
      setMessage("Please enter a valid 36-character Society UUID (e.g. 11111111-2222-3333-4444-555555555555).");
      setIsError(true);
      return;
    }

    setLoading(true);
    try {
      const normalizedBase = normalizeApiBaseUrl(apiBaseUrl);
      const response = await loginWithEmailPassword(normalizedBase, email, password);
      const sessionPayload = {
        apiBaseUrl: normalizedBase,
        accessToken: response.access,
        societyId: trimmedSocietyId,
        displayName: email.split("@")[0],
        workspacePersona,
      };

      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(sessionPayload));
      window.dispatchEvent(new Event(SESSION_EVENT));

      if (workspacePersona === "FACILITY_MANAGER") {
        router.push("/app/operations");
      } else {
        router.push("/app");
      }
    } catch (err) {
      setIsError(true);
      setMessage(err instanceof Error ? err.message : "Failed to sign in. Please verify your credentials.");
    } finally {
      setLoading(false);
    }
  }

  function updateOtp(index: number, value: string) {
    const digit = value.replace(/\D/g, "").slice(-1);
    setOtp((current) => current.map((item, itemIndex) => (itemIndex === index ? digit : item)));
    setMessage("");
    if (digit && index < OTP_LENGTH - 1) otpInputs.current[index + 1]?.focus();
  }

  function handleOtpKeyDown(index: number, event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Backspace" && !otp[index] && index > 0) {
      otpInputs.current[index - 1]?.focus();
    }
  }

  function handleOtpPaste(value: string) {
    const pastedDigits = value.replace(/\D/g, "").slice(0, OTP_LENGTH).split("");
    if (pastedDigits.length === 0) return;
    setOtp(Array.from({ length: OTP_LENGTH }, (_, index) => pastedDigits[index] ?? ""));
    otpInputs.current[Math.min(pastedDigits.length, OTP_LENGTH) - 1]?.focus();
  }

  return (
    <main className="auth-page">
      <section className="property-visual" aria-label="NivasOps society operations">
        <div className="visual-grid" aria-hidden="true" />
        <div className="brand-lockup">
          <span className="brand-mark"><ShieldCheck size={21} strokeWidth={2.2} /></span>
          <span>NivasOps</span>
        </div>

        <div className="visual-copy">
          <p className="eyebrow"><span className="live-dot" /> Society systems nominal</p>
          <h1>One community.<br />Every operation in view.</h1>
          <p className="visual-description">
            Secure helpdesk, facility response, and resident service coordination for communities that never stand still.
          </p>
          <div className="live-summary" aria-label="Live operations summary">
            <div><Activity size={17} /><span><strong>97.2%</strong> SLA health</span></div>
            <div><Users size={17} /><span><strong>8</strong> teams active</span></div>
            <div><Building2 size={17} /><span><strong>3</strong> societies linked</span></div>
          </div>
        </div>
      </section>

      <section className="auth-panel">
        <div className="mobile-brand">
          <span className="brand-mark"><ShieldCheck size={19} /></span>
          <span>NivasOps</span>
        </div>

        <div className="auth-content">
          <div className="auth-heading">
            <p className="section-label">Secure workspace access</p>
            <h2>Welcome back</h2>
            <p>Sign in using the details registered with your society.</p>
          </div>

          <div className="mode-switch" role="tablist" aria-label="Sign-in method">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "password"}
              className={mode === "password" ? "active" : ""}
              onClick={() => selectMode("password")}
            >
              <Mail size={16} /> Password
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "otp"}
              className={mode === "otp" ? "active" : ""}
              onClick={() => selectMode("otp")}
            >
              <Smartphone size={16} /> Quick OTP
            </button>
          </div>

          <form onSubmit={handleSubmit} noValidate>
            {mode === "password" ? (
              <>
                <label className="field-label" htmlFor="email">Email address</label>
                <div className="text-field">
                  <Mail size={17} />
                  <input
                    key="password-email"
                    id="email"
                    type="email"
                    autoComplete="email"
                    placeholder="name@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>
                <div className="password-label-row">
                  <label className="field-label" htmlFor="password">Password</label>
                  <Link href="/forgot-password" className="auth-link" style={{ fontSize: "0.74rem" }}>
                    Forgot password?
                  </Link>
                </div>
                <div className="text-field">
                  <LockKeyhole size={17} />
                  <input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    placeholder="Enter your password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    title={showPassword ? "Hide password" : "Show password"}
                    onClick={() => setShowPassword((current) => !current)}
                  >
                    {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </div>
                <label className="field-label" htmlFor="workspace-persona">Workspace Destination</label>
                <div className="text-field" style={{ marginBottom: "16px" }}>
                  <select
                    id="workspace-persona"
                    value={workspacePersona}
                    onChange={(e) => setWorkspacePersona(e.target.value as WorkspacePersona)}
                    style={{
                      width: "100%",
                      background: "transparent",
                      color: "var(--text)",
                      border: "none",
                      outline: "none",
                      padding: "0 10px",
                    }}
                  >
                    <option value="RESIDENT" style={{ background: "var(--surface)" }}>Resident Desk</option>
                    <option value="FACILITY_MANAGER" style={{ background: "var(--surface)" }}>Facility Manager Desk</option>
                  </select>
                </div>
                <label className="field-label" htmlFor="society-id">Society UUID <span style={{ color: "var(--brand-primary, #2563eb)" }}>*</span></label>
                <div className="text-field" style={{ marginBottom: "6px" }}>
                  <Building2 size={17} />
                  <input
                    id="society-id"
                    placeholder="e.g. 11111111-2222-3333-4444-555555555555"
                    value={societyId}
                    onChange={(e) => setSocietyId(e.target.value)}
                  />
                </div>
                <p className="field-help" style={{ marginBottom: "16px", fontSize: "0.8rem" }}>
                  Tenant operations and resident requests require a verified Society UUID.
                </p>
              </>
            ) : (
              <>
                <label className="field-label" htmlFor="mobile-number">Registered mobile number</label>
                <div className={`phone-field ${message && digits.length !== 10 ? "field-error" : ""}`}>
                  <span className="country-code" aria-label="India country code">IN&nbsp;&nbsp;+91</span>
                  <input
                    key="otp-mobile"
                    id="mobile-number"
                    inputMode="numeric"
                    autoComplete="tel-national"
                    placeholder="98765 43210"
                    value={formattedPhone}
                    disabled={otpRequested}
                    onChange={(event) => {
                      setPhone(event.target.value);
                      setMessage("");
                    }}
                    aria-describedby="phone-help form-message"
                  />
                  {digits.length === 10 && <Check className="valid-icon" size={17} aria-label="Valid number" />}
                </div>
                <p id="phone-help" className="field-help">We will send a single-use 4-digit code.</p>

                {otpRequested && (
                  <div className="otp-section">
                    <div className="otp-header">
                      <div>
                        <span className="field-label">Verification code</span>
                        <p>Sent to +91 {formattedPhone}</p>
                      </div>
                      <button type="button" className="edit-number" onClick={() => setOtpRequested(false)}>Edit number</button>
                    </div>
                    <div className="otp-inputs" onPaste={(event) => {
                      event.preventDefault();
                      handleOtpPaste(event.clipboardData.getData("text"));
                    }}>
                      {otp.map((value, index) => (
                        <input
                          key={index}
                          ref={(element) => { otpInputs.current[index] = element; }}
                          aria-label={`Verification digit ${index + 1}`}
                          inputMode="numeric"
                          autoComplete={index === 0 ? "one-time-code" : "off"}
                          maxLength={1}
                          value={value}
                          onChange={(event) => updateOtp(index, event.target.value)}
                          onKeyDown={(event) => handleOtpKeyDown(index, event)}
                        />
                      ))}
                    </div>
                    <div className="otp-meta">
                      <span className="linked-badge"><Building2 size={14} /> 2 societies linked</span>
                      {secondsRemaining > 0 ? (
                        <span>Resend in 00:{secondsRemaining.toString().padStart(2, "0")}</span>
                      ) : (
                        <button type="button" onClick={requestOtp}>Resend code</button>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}

            {message && (
              <p
                id="form-message"
                className="form-message"
                style={{ color: isError ? "var(--danger)" : "var(--teal)" }}
                role="status"
              >
                {message}
              </p>
            )}

            <button className="submit-button" type="submit" disabled={loading}>
              {loading
                ? "Verifying..."
                : mode === "otp" && !otpRequested
                ? "Send verification code"
                : "Sign In to Workspace"}
              <ArrowRight size={18} />
            </button>
          </form>

          <div className="auth-links">
            <Link href="/activate" className="auth-link">
              Have an invitation token? Activate your account <ArrowRight size={14} />
            </Link>
            <Link href="/app" className="auth-link" style={{ color: "var(--text-muted)", fontSize: "0.76rem" }}>
              Or use local development session bypass
            </Link>
          </div>

          <div className="security-note">
            <ShieldCheck size={17} />
            <p><strong>Protected access</strong><span>Tenant isolated · PBKDF2 secured · Audited sessions</span></p>
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

