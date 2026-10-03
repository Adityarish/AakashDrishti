"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { login as apiLogin, me, register as apiRegister } from "./api/survey";
import { setToken } from "./api/http";
import type { AuthUser } from "./sceneTypes";

interface AuthState {
  user: AuthUser | null;
  authenticated: boolean;
  authRequired: boolean;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, name: string, role: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authenticated, setAuthenticated] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const info = await me();
      setUser(info.user);
      setAuthenticated(info.authenticated);
      setAuthRequired(info.auth_required);
    } catch {
      setUser(null);
      setAuthenticated(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      authenticated,
      authRequired,
      loading,
      signIn: async (email, password) => {
        const session = await apiLogin(email, password);
        setToken(session.token);
        await refresh();
      },
      signUp: async (email, password, name, role) => {
        const session = await apiRegister(email, password, name, role);
        setToken(session.token);
        await refresh();
      },
      signOut: () => {
        setToken(null);
        void refresh();
      },
    }),
    [user, authenticated, authRequired, loading, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
