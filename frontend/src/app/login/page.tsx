"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageShell } from "@/components/layout/PageShell";
import { Button, ErrorNote, Field, InfoNote, Segmented } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { signIn, signUp } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<"analyst" | "responder" | "viewer">("analyst");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await signIn(email, password);
      else await signUp(email, password, name, role);
      router.push("/history");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in.");
      setBusy(false);
    }
  }

  return (
    <PageShell>
      <div className="mx-auto max-w-md pt-6">
        <div className="card p-7">
          <p className="eyebrow">Ranger station</p>
          <h1 className="mt-1 text-2xl font-semibold text-polar-night">{mode === "login" ? "Sign in" : "Create an account"}</h1>
          <p className="mt-1 text-sm text-slate-ice">
            Accounts are optional on a single-user offline install. When required, roles decide what you can do.
          </p>
          <div className="mt-5">
            <Segmented
              value={mode}
              onChange={setMode}
              options={[
                { value: "login", label: "Sign in" },
                { value: "register", label: "Register" },
              ]}
            />
          </div>
          <form onSubmit={submit} className="mt-5 space-y-4">
            {mode === "register" && (
              <Field label="Name">
                <input className="ctl" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
              </Field>
            )}
            <Field label="Email">
              <input className="ctl" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
            </Field>
            <Field label="Password" hint={mode === "register" ? "At least 8 characters." : undefined}>
              <input className="ctl" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} />
            </Field>
            {mode === "register" && (
              <div>
                <span className="mb-1.5 block text-xs font-semibold text-deep-ice">Role</span>
                <Segmented
                  value={role}
                  onChange={setRole}
                  options={[
                    { value: "analyst", label: "Analyst" },
                    { value: "responder", label: "Responder" },
                    { value: "viewer", label: "Viewer" },
                  ]}
                />
                <InfoNote className="mt-3">
                  <b>Analyst</b>: upload, run, calibrate, validate, export. <b>Responder</b>: view scenes, run flood and landing analysis, read briefs, export video.{" "}
                  <b>Viewer</b>: read-only. The very first account is always an analyst.
                </InfoNote>
              </div>
            )}
            {error && <ErrorNote message={error} />}
            <Button type="submit" className="w-full" loading={busy}>
              {mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </form>
        </div>
      </div>
    </PageShell>
  );
}
