/** @type {import('next').NextConfig} */
const nextConfig = {
  // `standalone` bundles a minimal server + node_modules subset into
  // `.next/standalone/`, which is what the Dockerfile's runtime stage
  // copies. Cuts the runtime image size by roughly 5x versus a full
  // `next start` install.
  output: "standalone",
  reactStrictMode: true,
  // API calls originate in the browser and hit the FastAPI service
  // directly. The Docker compose stack sets NEXT_PUBLIC_API_BASE to
  // http://localhost:8000 (the browser's view of the published port).
  //
  // Server-side fetches (RSC) would need the compose-network URL
  // (http://app:8000), but the demo UI is fully client-rendered so
  // we don't need a rewrites/proxy layer today.
};

export default nextConfig;
