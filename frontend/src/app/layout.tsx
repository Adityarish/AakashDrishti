import type { Metadata } from "next";
import { Space_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import "@designcodeio/threeui/style.css";
import { AuthProvider } from "@/lib/auth";

const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AakashDrishti",
  icons: { icon: "/favi.png", shortcut: "/favi.png", apple: "/favi.png" },
  description:
    "AakashDrishti -- single-view satellite/aerial image to building heights, calibrated 3D terrain, and disaster-management insight. Built for ISRO Department of Space, Smart India Hackathon 2026, Problem Statement 26175.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${spaceGrotesk.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
