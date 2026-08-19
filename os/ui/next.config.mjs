/** @type {import('next').NextConfig} */
const nextConfig = {
  // Local-only management surface: no image optimization service, no telemetry
  // surprises, nothing that phones home. The filesystem is the database.
  images: { unoptimized: true },
};

export default nextConfig;
