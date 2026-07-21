"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  BookOpen, LogOut, Home, Map, GraduationCap, Route,
  Database, SlidersHorizontal, LineChart, Network, Wrench,
  ChevronDown, Hammer, BarChart3,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface NavbarProps {
  user: { id: number; username: string };
  onLogout: () => void;
}

// Trải nghiệm học viên là chính; công cụ quản trị gom vào dropdown
const LEARNER_ITEMS = [
  { href: "/", label: "Trang chủ", icon: Home },
  { href: "/my-plan", label: "Lộ trình", icon: Route },
  { href: "/quiz", label: "Luyện tập", icon: GraduationCap },
  { href: "/knowledge", label: "Tri thức", icon: Map },
  { href: "/stats", label: "Thống kê", icon: BarChart3 },
];

const ADMIN_ITEMS = [
  { href: "/questions", label: "Ngân hàng câu hỏi", icon: Database },
  { href: "/questions/builder", label: "Tạo đề thi", icon: Hammer },
  { href: "/evaluation", label: "Đánh giá hệ thống", icon: LineChart },
  { href: "/architecture", label: "Multi-Agent", icon: Network },
  { href: "/admin/settings", label: "Cấu hình", icon: SlidersHorizontal },
];

export function Navbar({ user, onLogout }: NavbarProps) {
  const pathname = usePathname();
  const [adminOpen, setAdminOpen] = useState(false);
  const adminRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (adminRef.current && !adminRef.current.contains(e.target as Node)) {
        setAdminOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const isActive = (href: string) => {
    if (href === "/quiz" && pathname.startsWith("/results/")) return true;
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(`${href}/`);
  };

  const adminActive = ADMIN_ITEMS.some(({ href }) =>
    href === "/questions"
      ? pathname === "/questions"
      : pathname === href || pathname.startsWith(`${href}/`)
  );

  return (
    <header className="sticky top-0 z-50 w-full border-b border-sky-200/70 bg-gradient-to-r from-sky-50/95 via-cyan-50/95 to-blue-50/95 shadow-sm backdrop-blur supports-[backdrop-filter]:from-sky-50/80 supports-[backdrop-filter]:via-cyan-50/80 supports-[backdrop-filter]:to-blue-50/80">
      <div className="container flex h-14 items-center gap-3">
        {/* Logo */}
        <Link href="/" className="flex shrink-0 items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-600 shadow-sm">
            <BookOpen className="text-white" size={18} />
          </span>
          <span className="hidden font-bold text-lg tracking-tight text-slate-800 sm:inline">KBS</span>
        </Link>

        {/* Nav */}
        <nav className="flex min-w-0 flex-1 items-center justify-center">
          <div className="flex items-center gap-0.5 rounded-full border border-sky-200/80 bg-white/70 p-1 shadow-sm">
            {LEARNER_ITEMS.map(({ href, label, icon: Icon }) => {
              const active = isActive(href);
              return (
                <Link
                  key={href}
                  href={href}
                  title={label}
                  className={cn(
                    "flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium transition-colors",
                    active
                      ? "bg-sky-600 text-white shadow-sm"
                      : "text-slate-600 hover:bg-sky-100/80 hover:text-sky-900"
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="hidden lg:inline">{label}</span>
                </Link>
              );
            })}

            {/* Admin dropdown */}
            <div className="relative" ref={adminRef}>
              <button
                type="button"
                title="Quản trị"
                onClick={() => setAdminOpen((v) => !v)}
                className={cn(
                  "flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium transition-colors",
                  adminActive || adminOpen
                    ? "bg-sky-600 text-white shadow-sm"
                    : "text-slate-600 hover:bg-sky-100/80 hover:text-sky-900"
                )}
              >
                <Wrench className="h-4 w-4 shrink-0" />
                <span className="hidden lg:inline">Quản trị</span>
                <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", adminOpen && "rotate-180")} />
              </button>
              {adminOpen && (
                <div className="absolute right-0 top-full z-50 mt-2 w-56 rounded-xl border border-sky-200/80 bg-white p-1.5 shadow-lg">
                  {ADMIN_ITEMS.map(({ href, label, icon: Icon }) => (
                    <Link
                      key={href}
                      href={href}
                      onClick={() => setAdminOpen(false)}
                      className={cn(
                        "flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors",
                        isActive(href)
                          ? "bg-sky-50 font-medium text-sky-700"
                          : "text-slate-600 hover:bg-slate-50"
                      )}
                    >
                      <Icon className="h-4 w-4" />
                      {label}
                    </Link>
                  ))}
                </div>
              )}
            </div>
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
            <span className="ml-1 hidden xl:inline">Đăng xuất</span>
          </Button>
        </div>
      </div>
    </header>
  );
}
