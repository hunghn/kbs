"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { BookOpen, LogOut, LayoutDashboard, Map, GraduationCap, Database, SlidersHorizontal } from "lucide-react";

interface NavbarProps {
  user: { id: number; username: string };
  onLogout: () => void;
}

export function Navbar({ user, onLogout }: NavbarProps) {
  const pathname = usePathname();

  const isActive = (href: string) => {
    if (href === "/quiz" && pathname.startsWith("/results/")) {
      return true;
    }
    if (href === "/") {
      return pathname === "/";
    }
    return pathname === href || pathname.startsWith(`${href}/`);
  };

  const linkClass = (href: string) => {
    const active = isActive(href);
    return [
      "flex items-center gap-1 rounded-full px-3 py-1.5 transition-colors",
      active
        ? "bg-sky-600 text-white shadow-sm"
        : "text-slate-600 hover:bg-sky-100/80 hover:text-sky-900",
    ].join(" ");
  };

  return (
    <header className="sticky top-0 z-50 w-full border-b border-sky-200/70 bg-gradient-to-r from-sky-50/95 via-cyan-50/95 to-blue-50/95 shadow-sm backdrop-blur supports-[backdrop-filter]:from-sky-50/80 supports-[backdrop-filter]:via-cyan-50/80 supports-[backdrop-filter]:to-blue-50/80">
      <div className="container flex h-16 items-center">
        <div className="mr-4 flex items-center gap-2">
          <BookOpen className="h-6 w-6 text-sky-700" />
          <span className="font-bold text-lg text-slate-800">KBS</span>
        </div>

        <nav className="ml-4 flex items-center gap-1 rounded-full border border-sky-200/80 bg-white/70 px-2 py-1 text-sm shadow-sm">
          <Link href="/" className={linkClass("/")}>
            <LayoutDashboard className="h-4 w-4" />
            Dashboard
          </Link>
          <Link href="/knowledge" className={linkClass("/knowledge")}>
            <Map className="h-4 w-4" />
            Bản đồ tri thức
          </Link>
          <Link href="/quiz" className={linkClass("/quiz")}>
            <GraduationCap className="h-4 w-4" />
            Làm bài
          </Link>
          <Link href="/questions" className={linkClass("/questions")}>
            <Database className="h-4 w-4" />
            Quản lý câu hỏi
          </Link>
          <Link href="/admin/settings" className={linkClass("/admin/settings")}>
            <SlidersHorizontal className="h-4 w-4" />
            Admin Config
          </Link>
        </nav>

        <div className="flex-1" />

        <div className="flex items-center gap-3">
          <span className="text-sm text-slate-600">
            Xin chào, <span className="font-semibold text-slate-800">{user.username}</span>
          </span>
          <Button variant="outline" size="sm" onClick={onLogout} className="border-sky-200 bg-white/80 text-sky-800 hover:bg-sky-100 hover:text-sky-900">
            <LogOut className="h-4 w-4 mr-1" />
            Đăng xuất
          </Button>
        </div>
      </div>
    </header>
  );
}
