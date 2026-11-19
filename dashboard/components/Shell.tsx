"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/lib/auth";

const NAV = [
  { href: "/", label: "Needs attention", icon: "M4 6h16 M4 12h16 M4 18h10" },
  { href: "/incidents/", label: "Incidents",
    icon: "M12 21c-5-5.5-7-8.5-7-11.5a7 7 0 0 1 14 0c0 3-2 6-7 11.5z M12 7a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5" },
];

function Logo() {
  return (
    <svg width="30" height="30" viewBox="0 0 72 72" aria-hidden="true">
      <rect width="72" height="72" rx="20" fill="#0B5D5A" />
      <circle cx="36" cy="34" r="17" fill="none" stroke="#fff" strokeWidth="4" opacity="0.45" />
      <circle cx="36" cy="34" r="8" fill="#fff" />
      <path d="M36 51 L36 60" stroke="#fff" strokeWidth="4" strokeLinecap="round" />
    </svg>
  );
}

/** Sidebar + sign-in gate. Pages render only once the reviewer is signed in and provisioned. */
export function Shell({ children }: { children: React.ReactNode }) {
  const { state, logout } = useAuth();
  const path = usePathname();

  if (state.status !== "ready") {
    return (
      <main className="gate">
        <Logo />
        {state.status === "loading" && <p>Signing you in…</p>}
        {state.status === "misconfigured" && (
          <p>This dashboard build is missing settings: {state.missing.join(", ")}. See dashboard/.env.example.</p>
        )}
        {state.status === "not_provisioned" && (
          <>
            <h1>Your account isn&apos;t set up as a reviewer</h1>
            <p>You signed in, but this account has no reviewer access yet. Ask an administrator to grant it.</p>
            <button className="btn btn-secondary" onClick={logout}>Sign out</button>
          </>
        )}
        {state.status === "error" && (
          <>
            <h1>Sign-in didn&apos;t work</h1>
            <p>{state.message}</p>
            {/not authorized to access resource server/i.test(state.message) ? (
              <p className="muted small">An administrator needs to allow this dashboard to use the Sisay API in Auth0
                (APIs → Sisay API → Application Access → Sisay Review → User access: Authorized).</p>
            ) : null}
            <button className="btn btn-secondary" onClick={() => window.location.assign("/")}>Try again</button>
          </>
        )}
      </main>
    );
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><Logo /><span className="wordmark">sisay</span><span className="brand-tag">Review</span></div>
        <nav aria-label="Dashboard">
          {NAV.map((n) => {
            const on = n.href === "/" ? path === "/" : path.startsWith(n.href) || (n.href === "/incidents/" && path.startsWith("/incident"));
            return (
              <Link key={n.href} href={n.href} className={on ? "nav nav-on" : "nav"} aria-current={on ? "page" : undefined}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={n.icon} /></svg>
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="me">
          <span className="avatar" aria-hidden="true">{(state.me.email ?? "R").slice(0, 2).toUpperCase()}</span>
          <span className="me-text"><span className="me-name">{state.me.email ?? "Reviewer"}</span>
            <button className="linklike" onClick={logout}>Sign out</button></span>
        </div>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
