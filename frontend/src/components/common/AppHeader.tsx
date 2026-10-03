"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const NAV_LINKS = [
  { href: "/", label: "Home" },
  { href: "/dashboard", label: "Dashboard" },
  { href: "/history", label: "History" },
  { href: "/map", label: "Map" },
  { href: "/expedition/new", label: "Advanced Run" },
];

export function AppHeader() {
  const pathname = usePathname();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <header
      className={`sticky top-0 z-50 px-4 transition-all duration-500 ease-out ${
        scrolled ? "pt-2" : "pt-4 sm:px-6 lg:px-8"
      }`}
    >
      <div
        className={`glass-panel glass-panel-strong mx-auto flex items-center justify-between gap-4 rounded-[16px] shadow-lg shadow-black/5 transition-all duration-500 ease-out ${
          scrolled ? "h-[52px] max-w-5xl px-5" : "h-14 max-w-6xl px-6"
        }`}
      >
        <Link href="/" className="flex shrink-0 items-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/logo.png"
            alt="AakashDrishti logo"
            className={`w-auto object-contain transition-all duration-500 ${scrolled ? "h-11" : "h-12"}`}
          />
        </Link>

        <nav className={`hidden items-center md:flex ${scrolled ? "gap-0.5" : "gap-1"}`}>
          {NAV_LINKS.map((link) => {
            const active = link.href === "/" ? pathname === "/" : pathname?.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`rounded-lg px-3 py-1.5 text-sm font-bold transition-colors ${
                  active
                    ? "bg-primary/15 text-primary"
                    : "text-black hover:bg-black/5 hover:text-primary"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
