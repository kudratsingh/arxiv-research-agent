const NAVIGATION_REQUEST = "arxiv:workspace-navigation-request";

/** Explicit navigation shares the same draft/pending-write veto as real links. */
export function allowWorkspaceNavigation(href: string): boolean {
  return document.dispatchEvent(new CustomEvent(NAVIGATION_REQUEST, { cancelable: true, detail: { href } }));
}

export function blockWorkspaceNavigation(onBlocked: () => void): () => void {
  const block = (event: Event) => { event.preventDefault(); onBlocked(); };
  document.addEventListener(NAVIGATION_REQUEST, block);
  return () => document.removeEventListener(NAVIGATION_REQUEST, block);
}
