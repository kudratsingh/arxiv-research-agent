/** @type {import('next').NextConfig} */
const nextConfig = {
  // `standalone` bundles a minimal server + node_modules subset into
  // `.next/standalone/`, which is what the Dockerfile's runtime stage
  // copies. Cuts the runtime image size by roughly 5x versus a full
  // `next start` install.
  output: "standalone",
  reactStrictMode: true,
  // Browser API calls stay same-origin under `/api`. The catch-all
  // route handler resolves API_INTERNAL_BASE at runtime and injects
  // ARXIV_API_KEY server-side, including for SSE and exports.
};

export default nextConfig;
