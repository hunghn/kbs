"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { BookOpen, LogOut, LayoutDashboard, Map, GraduationCap, Database, SlidersHorizontal } from "lucide-react";

interface NavbarProps {
  user: { id: number; username: string };
  onLogout: () => void;
}

export function Navbar({ user, onLogout }: NavbarProps) {
  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 items-center">
        <div className="mr-4 flex items-center gap-2">
          <BookOpen className="h-6 w-6 text-primary" />
          <span className="font-bold text-lg">KBS</span>
        </div>

        <nav className="flex items-center gap-4 text-sm ml-4">
          <Link href="/" className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
            <LayoutDashboard className="h-4 w-4" />
            Dashboard
          </Link>
          <Link href="/knowledge" className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
            <Map className="h-4 w-4" />
            Bản đồ tri thức
          </Link>
          <Link href="/quiz" className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
            <GraduationCap className="h-4 w-4" />
            Làm bài
          </Link>
          <Link href="/questions" className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
            <Database className="h-4 w-4" />
            Quản lý câu hỏi
          </Link>
          <Link href="/admin/settings" className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
            <SlidersHorizontal className="h-4 w-4" />
            Admin Config
          </Link>
        </nav>

        <div className="flex-1" />

        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">
            Xin chào, <span className="font-medium text-foreground">{user.username}</span>
          </span>
          <Button variant="ghost" size="sm" onClick={onLogout}>
            <LogOut className="h-4 w-4 mr-1" />
            Đăng xuất
          </Button>
        </div>
      </div>
    </header>
  );
}
