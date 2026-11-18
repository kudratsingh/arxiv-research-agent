# Required CI audit decision — inactive, unresolved

The provider/evaluation repair and the dependency audit are separate gates. The existing C4 audit currently fails on23 propagated development entries with one direct high root, Picomatch npm1247710, for which the recorded registry/advisory inspection found no patched release. Next16.4.5 and Vitest4.1.12 patch available issues without changing audit thresholds. Glob/minimatch moderate roots are also visible below where their IDs propagate.

Automatic approval review rejected writing these entries to the checked-in exception allowlist because accepting the risk was outside the current offline evaluation authorization. **No exception was installed.** The audit failure must remain visible; exact-head CI cannot be called all-green while this job fails. No provider or count contact is authorized by this document.

The safer current action is to keep the gate failing and the live continuation disabled. An owner may later decide whether to accept a narrowly dated, exact-path dev-only exception through the existing C4 mechanism, or wait for a compatible upstream fix. Such a decision must explicitly acknowledge that it accepts an unresolved risk; it is not a security repair. The existing production high/critical zero gate and every new/stale-advisory check would remain. Arbitrary untrusted glob patterns/configuration/checkouts are outside the scoped justification.

Next also ships a separate compiled Picomatch copy outside npm’s dependency graph. Its configured image patterns are not populated by this application, but zero high/critical in the npm production report is not a guarantee about vendored code. No owner service, deployment or active security policy was changed. See [the dependency investigation](WEB-DEPENDENCY-PATCH-v20.md).

## Exact reported chains for review

| Package | Exact advisory IDs | Registered dev path |
|---|---|---|
| @next/eslint-plugin-next | 1247710 | eslint-config-next > @next/eslint-plugin-next |
| @rollup/pluginutils | 1247710 | @storybook/nextjs-vite > @storybook/react-vite > @rollup/pluginutils |
| @storybook/addon-vitest | 1247710 | @storybook/addon-vitest |
| @storybook/nextjs-vite | 1244013, 1244623, 1247710 | @storybook/nextjs-vite |
| @storybook/react-vite | 1244013, 1244623, 1247710 | @storybook/nextjs-vite > @storybook/react-vite |
| @typescript-eslint/typescript-estree | 1244623, 1247710 | eslint-config-next > typescript-eslint > @typescript-eslint/typescript-estree |
| @vitejs/plugin-react | 1247710 | @vitejs/plugin-react |
| @vitest/coverage-v8 | 1247710 | @vitest/coverage-v8 |
| anymatch | 1247710 | tailwindcss > chokidar > anymatch |
| chokidar | 1247710 | tailwindcss > chokidar |
| eslint-config-next | 1247710 | eslint-config-next |
| eslint-import-resolver-typescript | 1247710 | eslint-config-next > eslint-import-resolver-typescript |
| fast-glob | 1247710 | tailwindcss > fast-glob |
| fdir | 1247710 | vitest > tinyglobby > fdir |
| micromatch | 1247710 | tailwindcss > micromatch |
| picomatch | 1247710 | vitest > picomatch |
| readdirp | 1247710 | tailwindcss > chokidar > readdirp |
| sucrase | 1247710 | tailwindcss > sucrase |
| tailwindcss | 1247710 | tailwindcss |
| tinyglobby | 1247710 | vitest > tinyglobby |
| vite | 1247710 | @storybook/nextjs-vite > vite |
| vite-plugin-storybook-nextjs | 1247710 | @storybook/nextjs-vite > vite-plugin-storybook-nextjs |
| vitest | 1247710 | vitest |

These are review data, not an executable allowlist or approval. Raw npm reports, verified dependency paths, observed versions and rejected-action evidence remain in permanent private custody. Any future policy change and exact-head CI result must be recorded before paid activation.
