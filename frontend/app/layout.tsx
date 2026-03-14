import type { Metadata } from "next";
import "./globals.css";
import "katex/dist/katex.min.css";

export const metadata: Metadata = {
  title: "KBS - Hệ thống Kiểm tra Tri thức",
  description: "Hệ thống quản lý và kiểm tra tri thức thông minh dựa trên IRT",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi">
      <body className="min-h-screen bg-background antialiased">
        {children}
      </body>
    </html>
  );
}
