/** Public build-time configuration (inlined by Next.js). Nothing here is secret. */
export const config = {
  apiBase: (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, ""),
  auth0Domain: process.env.NEXT_PUBLIC_AUTH0_DOMAIN ?? "",
  auth0ClientId: process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID ?? "",
  audience: process.env.NEXT_PUBLIC_AUTH0_AUDIENCE ?? "",
};

export const missingConfig = (Object.entries(config) as [string, string][])
  .filter(([, v]) => !v)
  .map(([k]) => k);
