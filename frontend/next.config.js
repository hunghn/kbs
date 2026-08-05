/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    // Mặc định proxy của Next ngắt request sau 30s (socket hang up / 500).
    // Dựng đề nháp và sinh câu hỏi phải chờ LLM lâu hơn thế; backend đã tự
    // giới hạn ~140s nên đặt trần proxy cao hơn để backend là bên trả lời.
    proxyTimeout: 180_000,
  },

  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
