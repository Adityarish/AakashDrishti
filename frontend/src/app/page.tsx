"use client";

import Link from "next/link";
import dynamic from "next/dynamic";

/** SylvaLivingWorldScene renders an <iframe srcdoc="..."> that differs between
 * the server-rendered HTML and the client's first render (the library isn't
 * built with Next.js SSR in mind -- confirmed via a real hydration-mismatch
 * error, not a guess). Loading it client-only via next/dynamic (ssr: false)
 * is the correct fix for a third-party component like this: it's simply never
 * part of the server-rendered HTML, so there's nothing for hydration to
 * mismatch against. Dynamically importing the local SylvaScene.tsx wrapper
 * (not the @designcodeio/threeui package directly) -- see that file's comment
 * for why a dynamic import() on the raw package broke the build. */
const SylvaLivingWorldScene = dynamic(() => import("@/components/common/SylvaScene"), { ssr: false });

/** Landing page -- deliberately just the Sylva scene, one line of text, and a
 * CTA. No overlay/scrim/card of any kind: the scene renders exactly as
 * authored, per explicit product decision (see decisions-log.md) -- do not
 * add a darkening gradient back in. The actual product (upload workflow) is
 * a separate route, /dashboard. */
export default function Home() {
  return (
    <div className="relative h-dvh w-full overflow-hidden bg-black">
      <div className="absolute inset-0">
        <SylvaLivingWorldScene variant="living-green" className="h-full w-full" />
      </div>
      <div className="absolute left-6 top-40 z-10 max-w-md sm:left-14 sm:top-48 sm:max-w-2xl">
        <p className="text-5xl font-black tracking-tight text-white [text-shadow:0_2px_14px_rgba(0,0,0,0.75)] sm:text-6xl">
          Aakash Drishti
        </p>
        <p className="mt-3 text-xl font-bold tracking-tight text-white/85 [text-shadow:0_1px_10px_rgba(0,0,0,0.75)] sm:text-2xl">
          Single-View Height Estimation and 3D Flythrough
        </p>
        <Link
          href="/dashboard"
          className="mt-5 inline-flex items-center gap-2 rounded-lg bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground shadow-lg shadow-black/30 transition-colors hover:bg-primary/90"
        >
          Get Started
          <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" stroke="currentColor" strokeWidth={2}>
            <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </Link>
      </div>
    </div>
  );
}
