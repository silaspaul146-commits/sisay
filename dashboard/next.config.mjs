/** Static export: the dashboard is plain files on a static host; all data comes from the API. */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
