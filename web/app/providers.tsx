"use client";

// The client-side provider tree (04-ARCHITECTURE.md §4.1).
//
// MOUNTED PER ROUTE, NOT AT THE ROOT, AND THAT IS A BUDGET DECISION.
// WO-20 landed the mounts: `QueryProvider` is wrapped around the routes that
// actually read through TanStack Query — `app/(learn)/layout.tsx` and
// `app/(workspace)/c/[id]/page.tsx` — so the library is charged to those
// chunk unions and not to `/`, which is the tighter of the two gated rows.
// The measurement is in `app/layout.tsx`'s note above `<body>`.
//
// `Providers` is the composite for the day the whole tree needs wrapping, and
// nothing mounts it yet. It exists so that edit stays one line in the layout
// rather than a new provider in every route file.

import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { createQueryClient } from "@/lib/queries/client";

export interface QueryProviderProps {
  children: ReactNode;
  /**
   * An existing client. Left undefined in the app — one client is created
   * per browser session and kept in state, never in a module constant,
   * so a server render cannot leak one request's cache into another's.
   */
  client?: QueryClient;
}

/** The TanStack Query wiring, and nothing else. */
export function QueryProvider({
  children,
  client,
}: QueryProviderProps): React.ReactElement {
  const [ownClient] = useState(createQueryClient);
  return (
    <QueryClientProvider client={client ?? ownClient}>
      {children}
    </QueryClientProvider>
  );
}

export interface ProvidersProps {
  children: ReactNode;
  client?: QueryClient;
}

/**
 * Everything the client tree needs, as one component for the layout to
 * mount. Today that is the query client; later providers compose here.
 */
export function Providers({
  children,
  client,
}: ProvidersProps): React.ReactElement {
  return <QueryProvider client={client}>{children}</QueryProvider>;
}
