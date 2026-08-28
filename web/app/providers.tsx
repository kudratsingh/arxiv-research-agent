"use client";

// The client-side provider tree (04-ARCHITECTURE.md §4.1).
//
// **Not mounted yet, on purpose.** `app/layout.tsx` belongs to WO-08,
// which is writing it concurrently, so this file exports the wiring and
// WO-08 (and WO-20, for the workspace segment) does the mounting:
//
//     import { Providers } from "@/app/providers";
//     …
//     <body>
//       <Providers>{children}</Providers>
//     </body>
//
// `Providers` is the seam that keeps that edit a one-time change: the
// job machine's `JobRunProvider` and anything else that needs to wrap the
// tree joins it here rather than in the layout.
//
// Until something mounts it, TanStack Query is not in any route's chunk
// union — which is why `npm run budgets` does not move in the PR that
// adds the library (R-11 / RC-01). The ~13 KB gzip lands on `/` when
// WO-20 route-loads it, and WO-23's check is what will price it.

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
