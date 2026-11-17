# Web dependency patches for the v20 CI gate

Next and its ESLint configuration are pinned to 16.4.5. Vitest and its V8 coverage package are pinned to 4.1.12. These releases cover the two cited Next caching advisories and both Vitest mocker advisories. [Next root-parameter advisory](https://github.com/vercel/next.js/security/advisories/GHSA-mfr8-8qww-v76h) · [Next nested-cache advisory](https://github.com/vercel/next.js/security/advisories/GHSA-vc7v-qv4w-wrv8) · [Vitest registration advisory](https://github.com/advisories/GHSA-qxg6-89mg-rqv8) · [Vitest Windows advisory](https://github.com/advisories/GHSA-xp26-3454-mjgp)

The lock refresh changes 21 existing installation paths within those release families. npm 10.9.8 failed while rebuilding the previous exact Vitest peer set. The replacement entries use the published npm manifests, tarball URLs, and integrity hashes. A fresh `npm ci` on Node 22.23.2 accepted the full lock with standard peer validation.

## Local checks

- TypeScript, ESLint, and the generated API contract check passed.
- Vitest passed 4,308 tests across 223 files with the composed Reader regression present. Coverage was 98.18% statements, 94.41% branches, 94.17% functions, and 99.52% lines.
- The Next 16.4.5 production build passed the existing route budgets. The tightest workspace route, `/workspace/today`, measured 169,847 bytes against 169,984 bytes, leaving 137 bytes of headroom.

## Remaining audit findings

The existing audit gate exits 1. The npm production tree reports zero high or critical findings. The full tree still reports 23 high entries reachable from development dependencies. All 23 include the Picomatch advisory 1247710. Three also carry advisory IDs from the moderate Glob and Minimatch findings. The registry listed 4.0.7 as Picomatch's latest release on November 17, 2026, and the advisory listed no patched release. The published Glob and Minimatch fixes fall outside the locked consumers' major-version ranges. [Picomatch advisory](https://github.com/advisories/GHSA-fc5q-39xc-vjpf) · [Glob advisory](https://github.com/advisories/GHSA-3g3m-2fjr-6pw4) · [Minimatch advisory](https://github.com/advisories/GHSA-g3hv-75wg-m249)

The inspected CI paths use checkout-defined patterns for Tailwind content, ESLint project roots, Storybook stories, and Vitest coverage and test selection. The app, middleware, components, and library source contain no direct imports of the audited glob matchers. These observations cover the configured build and test inputs.

The standalone build separately contains the Picomatch copy compiled into Next. Vercel's 16.4.5 source manifest declares Picomatch 4.0.1, and the built copy's package metadata omits a version. The inspected runtime image matcher uses patterns from Next configuration and tests request URLs against those patterns. This checkout supplies no custom image patterns. The npm production audit measures the lockfile graph and does not inventory embedded vendor code. [Next 16.4.5 package manifest](https://raw.githubusercontent.com/vercel/next.js/v16.4.5/packages/next/package.json)
