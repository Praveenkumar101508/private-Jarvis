import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "IRA — SupraCloud",
  description: "Private sovereign AI assistant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-[#0d0d0d] text-white antialiased">{children}</body>
    </html>
  );
}
