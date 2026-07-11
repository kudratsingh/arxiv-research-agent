import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "arxiv-research-agent",
  description:
    "Multi-agent research assistant for ML/AI papers. LangGraph + Claude with supervisor loop, faithfulness verifier, eval harness, FastAPI + SSE, Docker + Redis + Postgres.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
