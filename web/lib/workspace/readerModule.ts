export type ReaderContentComponent = typeof import("@/components/workspace/ReaderContent").default;

/** Cache code only; item, principal, version and draft state stay in the view. */
export function createReaderModuleLoader(importer: () => Promise<{ default: ReaderContentComponent }>) {
  let content: ReaderContentComponent | null = null;
  let pending: Promise<ReaderContentComponent> | null = null;
  return {
    peek: () => content,
    load: () => {
      if (content) return Promise.resolve(content);
      if (!pending) pending = importer().then(module => {
        content = module.default;
        return content;
      }).finally(() => { pending = null; });
      return pending;
    },
  };
}

export const readerModule = createReaderModuleLoader(() => import("@/components/workspace/ReaderContent"));
