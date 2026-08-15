import type { Metadata } from "next";

import { Providers } from "@/app/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "FitOps",
  description: "FitOps application frontend.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
