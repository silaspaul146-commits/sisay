"use client";
/**
 * Staff sign-in with Auth0 (Authorization Code + PKCE, in the browser).
 * Tokens are kept in memory only, never in localStorage: a reload re-checks the Auth0 session and,
 * if the browser blocks that silent check, sends the reviewer through the Auth0 page again
 * (instant when they are still signed in there).
 */
import { Auth0Client, createAuth0Client } from "@auth0/auth0-spa-js";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { apiFetch, ApiError, type Me, type TokenGetter } from "./api";
import { config, missingConfig } from "./config";

type AuthState =
  | { status: "loading" }
  | { status: "misconfigured"; missing: string[] }
  | { status: "not_provisioned" }
  | { status: "error"; message: string }
  | { status: "ready"; me: Me };

type AuthContext = { state: AuthState; getToken: TokenGetter; logout: () => void; can: (p: string) => boolean };

const Ctx = createContext<AuthContext | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  const client = useRef<Auth0Client | null>(null);

  useEffect(() => {
    if (missingConfig.length) {
      setState({ status: "misconfigured", missing: missingConfig });
      return;
    }
    let cancelled = false;
    (async () => {
      const auth0 = await createAuth0Client({
        domain: config.auth0Domain,
        clientId: config.auth0ClientId,
        cacheLocation: "memory",
        authorizationParams: { audience: config.audience, redirect_uri: window.location.origin + "/" },
      });
      client.current = auth0;
      const params = new URLSearchParams(window.location.search);
      if (params.has("code") && params.has("state")) {
        const { appState } = await auth0.handleRedirectCallback<{ returnTo?: string }>();
        window.history.replaceState({}, "", appState?.returnTo ?? "/");
      } else {
        try {
          await auth0.getTokenSilently();
        } catch {
          await auth0.loginWithRedirect({ appState: { returnTo: window.location.pathname + window.location.search } });
          return;
        }
      }
      try {
        const me = await apiFetch<Me>(() => auth0.getTokenSilently(), "/auth/me");
        if (!cancelled) setState({ status: "ready", me });
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) setState({ status: "not_provisioned" });
        else setState({ status: "error", message: err instanceof Error ? err.message : "Sign-in failed." });
      }
    })().catch((err) => !cancelled && setState({ status: "error", message: String(err?.message ?? err) }));
    return () => {
      cancelled = true;
    };
  }, []);

  const getToken = useCallback<TokenGetter>(async () => {
    if (!client.current) throw new ApiError(401, "not_signed_in", "Not signed in yet.");
    return client.current.getTokenSilently();
  }, []);

  const logout = useCallback(() => {
    client.current?.logout({ logoutParams: { returnTo: window.location.origin + "/" } });
  }, []);

  const value = useMemo<AuthContext>(() => ({
    state, getToken, logout,
    can: (p: string) => state.status === "ready" && state.me.permissions.includes(p),
  }), [state, getToken, logout]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthContext {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
