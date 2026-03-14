"use client";

import { useState, useEffect, useCallback } from "react";
import { authAPI } from "@/lib/api";
import { Navbar } from "@/components/layout/navbar";
import { LoginForm } from "@/components/auth/login-form";
import { Dashboard } from "@/components/dashboard/dashboard";

export default function HomePage() {
  const [user, setUser] = useState<{ id: number; username: string } | null>(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = useCallback(async () => {
    const token = localStorage.getItem("kbs_token");
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      const me = await authAPI.me();
      setUser(me);
    } catch {
      localStorage.removeItem("kbs_token");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const handleLogin = (token: string) => {
    localStorage.setItem("kbs_token", token);
    checkAuth();
  };

  const handleLogout = () => {
    localStorage.removeItem("kbs_token");
    setUser(null);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary" />
      </div>
    );
  }

  if (!user) {
    return <LoginForm onLogin={handleLogin} />;
  }

  return (
    <div className="min-h-screen">
      <Navbar user={user} onLogout={handleLogout} />
      <Dashboard />
    </div>
  );
}
