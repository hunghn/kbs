"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  BookOpen, LogOut, LayoutDashboard, Map, GraduationCap,
  Database, SlidersHorizontal, LineChart, Network,
} from "lucide-react";

interface NavbarProps {
  user: { id: number; username: string };
  onLogout: () => void;
}

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/knowledge", label: "Tri thức", icon: Map },
  { href: "/quiz", label: "Làm bài", icon: GraduationCap },
  { href: "/questions", label: "Câu hỏi", icon: Database },
  { href: "/evaluation", label: "Đánh giá", icon: LineChart },
  { href: "/architecture", label: "Multi-Agent", icon: Network },
  { href: "/admin/settings", label: "Cấu hình", icon: SlidersHorizontal },
];

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

  return (
    <header className="sticky top-0 z-50 w-full border-b border-sky-200/70 bg-gradient-to-r from-sky-50/95 via-cyan-50/95 to-blue-50/95 shadow-sm backdrop-blur supports-[backdrop-filter]:from-sky-50/80 supports-[backdrop-filter]:via-cyan-50/80 supports-[backdrop-filter]:to-blue-50/80">
      <div className="container flex h-14 items-center gap-3">
        {/* Logo */}
        <Link href="/" className="flex shrink-0 items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-600 shadow-sm">
            <BookOpen className="h-4.5 w-4.5 text-white" size={18} />
          </span>
          <span className="hidden font-bold text-lg tracking-tight text-slate-800 sm:inline">KBS</span>
        </Link>

        {/* Nav */}
        <nav className="flex min-w-0 flex-1 items-center justify-center">
          <div className="flex items-center gap-0.5 rounded-full border border-sky-200/80 bg-white/70 p-1 shadow-sm">
            {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
              const active = isActive(href);
              return (
                <Link
                  key={href}
                  href={href}
                  title={label}
                  className={[
                    "flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium transition-colors",
                    active
                      ? "bg-sky-600 text-white shadow-sm"
                      : "text-slate-600 hover:bg-sky-100/80 hover:text-sky-900",
                  ].join(" ")}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="hidden xl:inline">{label}</span>
                </Link>
              );
            })}
          </div>
        </nav>

        {/* User */}
        <div className="flex shrink-0 items-center gap-2">
          <span
            className="hidden items-center gap-2 rounded-full border border-sky-200/80 bg-white/70 py-1 pl-1 pr-3 text-sm shadow-sm md:flex"
            title={user.username}
          >
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-sky-600 text-xs font-bold text-white">
              {user.username.charAt(0).toUpperCase()}
            </span>
            <span className="max-w-28 truncate font-medium text-slate-700">{user.username}</span>
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={onLogout}
            title="Đăng xuất"
            className="border-sky-200 bg-white/80 px-2.5 text-sky-800 hover:bg-sky-100 hover:text-sky-900"
          >
            <LogOut className="h-4 w-4" />
            <span className="ml-1 hidden lg:inline">Đăng xuất</span>
          </Button>
        </div>
      </div>
    </header>
  );
}
