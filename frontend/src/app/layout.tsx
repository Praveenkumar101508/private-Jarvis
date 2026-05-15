import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "IRA — Intelligent Responsive Assistant",
  description: "Your warm, multilingual AI assistant with an Indian female persona",
  icons: { icon: "/favicon.ico" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Noto+Sans+Devanagari:wght@400;500&display=swap" rel="stylesheet" />
      </head>
      <body className="bg-ira-warm min-h-screen font-sans antialiased">{children}</body>
    </html>
  );
}
