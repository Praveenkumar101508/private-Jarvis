import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "IRA",
  description: "Private Sovereign AI Assistant",
  applicationName: "IRA",
  appleWebApp: {
    capable: true,
    title: "IRA",
    statusBarStyle: "black-translucent",
  },
  formatDetection: {
    telephone: false,
  },
  manifest: "/manifest.json",
  // Fix #100: apple-touch-icon omitted here — iOS Safari requires PNG.
  // Generate icon-192x192.png / icon-512x512.png from the SVGs and add them
  // back via <link rel="apple-touch-icon" href="/icons/icon-192x192.png" />.
  icons: {},
};

export const viewport: Viewport = {
  themeColor: "#0a0a0a",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        {/* PWA / Add-to-Home-Screen tags */}
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-title" content="IRA" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        {/*
          Fix #100: apple-touch-icon links removed — iOS Safari silently
          ignores SVG apple-touch-icons and falls back to a screenshot.
          To restore: generate icon-180x180.png from the SVG and add:
            <link rel="apple-touch-icon" href="/icons/icon-180x180.png" />
        */}
      </head>
      <body className={`${inter.className} bg-neutral-950 text-white antialiased`}>
        {children}
      </body>
    </html>
  );
}
