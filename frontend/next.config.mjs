/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async rewrites() {
    // 프록시 타깃 — 클라이언트는 /api(같은 출처)로 호출, 여기서 백엔드로 rewrite.
    // BACKEND_PROXY_TARGET 우선(포트 바꿔 띄울 때), 없으면 기존 동작.
    const apiBase = process.env.BACKEND_PROXY_TARGET ?? process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${apiBase}/:path*` }];
  },
};
export default nextConfig;
