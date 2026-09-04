"use client";

/**
 * ThemeToggle — light / dark / system, persisted, applied before paint
 * (WO-08 criterion 8; RC-05's second persisted preference).
 *
 * WHAT THIS COMPONENT DOES NOT DO: apply the theme on load. WO-01's
 * `themeInitScript` already did that, synchronously, in `<head>`, before
 * the first paint — which is the only place a theme can be applied without
 * a flash. This control's job is narrower and worth stating exactly:
 *
 *   1. READ the preference the script resolved, from
 *      `data-theme-preference` on `<html>`. Not from `localStorage`: the
 *      attribute is the script's *output*, so reading it means the control
 *      and the painted page can never disagree, including in a
 *      storage-blocked context where the script fell through to "system".
 *   2. WRITE the user's choice to both attributes and to
 *      `THEME_STORAGE_KEY`, so the next load's pre-paint script finds it.
 *   3. KEEP FOLLOWING THE OS while the preference is "system". The
 *      pre-paint script attaches a `change` listener only when the stored
 *      preference was already "system" at load, so a user who switches
 *      *to* system in this session would otherwise stop tracking the OS
 *      until the next reload.
 *   4. ADOPT a choice made before hydration. The radios are real markup
 *      from first paint, so a click can land while React is still being
 *      parsed; the browser checks the radio and nothing else happens. The
 *      mount effect below reads that back and completes the interaction
 *      rather than leaving the control showing a choice the document
 *      never took (known gap §16).
 *
 * WHY NATIVE RADIOS. Three `<input type="radio">` in a `<fieldset>` give
 * the group its accessible name from `<legend>`, arrow-key navigation, and
 * "one of three" semantics from the platform. The alternative — three
 * buttons in a `role="radiogroup"` with roving tabindex — is code this
 * product would have to write, test and keep correct for no visual gain,
 * since ThemeToggle.css puts the checked state on the label either way.
 *
 * HYDRATION. The server has no `<html>` attribute to read and no storage,
 * so the first render is deliberately "system" — the same default the
 * pre-paint script falls back to. `useSyncExternalStore` then supplies the
 * real preference on the client. Nothing about the *painted theme* depends
 * on this: only which radio shows as checked.
 */

import { useCallback, useEffect, useSyncExternalStore } from "react";

import { VISUALLY_HIDDEN_CLASS } from "@/components/primitives/VisuallyHidden";
import { THEME_CONTROL } from "@/lib/copy/shell";
import {
  THEME_ATTRIBUTE,
  THEME_PREFERENCES,
  THEME_PREFERENCE_ATTRIBUTE,
  THEME_STORAGE_KEY,
  type ThemePreference,
} from "@/lib/tokens";

import "./ThemeToggle.css";

/** The visible word for each preference, from WO-12's dictionary. */
const THEME_LABEL: Record<ThemePreference, string> = {
  light: THEME_CONTROL.light,
  dark: THEME_CONTROL.dark,
  system: THEME_CONTROL.system,
};

const DARK_QUERY = "(prefers-color-scheme: dark)";

/**
 * The radio group's `name`. Named once because the mount effect below reads
 * the group back out of the DOM by it: radios sharing a `name` ARE one group
 * to the platform, so the document-wide query and the rendered markup have to
 * agree by construction rather than by two matching string literals.
 */
const RADIO_GROUP_NAME = "theme-preference";

/* -------------------------------------------------------------------------
 * The store: `data-theme-preference` on the document element.
 *
 * A module-level listener set rather than a `MutationObserver`, because the
 * only writer is `setThemePreference` below and an observer would cost a
 * subscription on every mount to watch for a write this module makes
 * itself.
 * ---------------------------------------------------------------------- */

const listeners = new Set<() => void>();

function subscribe(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange);
  return () => {
    listeners.delete(onStoreChange);
  };
}

function isThemePreference(value: string | null): value is ThemePreference {
  return (THEME_PREFERENCES as readonly string[]).includes(value ?? "");
}

/** The preference the pre-paint script resolved, or "system". */
export function readThemePreference(): ThemePreference {
  if (typeof document === "undefined") return "system";
  const attribute = document.documentElement.getAttribute(
    THEME_PREFERENCE_ATTRIBUTE,
  );
  return isThemePreference(attribute) ? attribute : "system";
}

/**
 * "system" — the value the pre-paint script itself falls back to, and
 * therefore the only honest thing a server render can claim. Exported so a
 * test can pin it: if this ever returned a *theme*, a server-rendered
 * document would assert a choice the user has not made.
 */
export function serverThemePreference(): ThemePreference {
  return "system";
}

/** Resolve a preference to the value that goes on `data-theme`. */
function resolve(preference: ThemePreference): "light" | "dark" {
  if (preference !== "system") return preference;
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

/**
 * Write the preference everywhere it is read from: both attributes (what
 * the stylesheet and Tailwind's `dark:` variant key off) and storage (what
 * the next load's pre-paint script reads).
 *
 * Storage is wrapped in try/catch for the same reason `themeInitScript` is:
 * `localStorage` throws outright in a partitioned context, and the failure
 * mode has to be "the theme does not persist", never "the toggle throws".
 */
export function setThemePreference(preference: ThemePreference): void {
  const element = document.documentElement;
  element.setAttribute(THEME_ATTRIBUTE, resolve(preference));
  element.setAttribute(THEME_PREFERENCE_ATTRIBUTE, preference);
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    /* Storage-blocked: the choice applies to this document and no further. */
  }
  for (const listener of listeners) listener();
}

export interface ThemeToggleProps {
  className?: string;
}

export function ThemeToggle({ className }: ThemeToggleProps): React.ReactElement {
  const preference = useSyncExternalStore(
    subscribe,
    readThemePreference,
    serverThemePreference,
  );

  // Item 3 in the header: keep tracking the OS for as long as the user's
  // preference is "system". Re-resolving writes `data-theme` only; the
  // stored preference stays "system", which is the whole point.
  useEffect(() => {
    if (preference !== "system") return;
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia(DARK_QUERY);
    const apply = (): void => {
      document.documentElement.setAttribute(THEME_ATTRIBUTE, resolve("system"));
    };
    apply();
    if (!query.addEventListener) return;
    query.addEventListener("change", apply);
    return () => {
      query.removeEventListener("change", apply);
    };
  }, [preference]);

  // Item 4 in the header: adopt a choice the user made BEFORE hydration.
  //
  // Between first paint and hydration the radios are live markup with no
  // React attached. A click on a label checks its radio natively — the
  // browser does that, not React — and `onChange` below is not there to
  // hear it, so without this the choice is dropped and never recovered:
  // the control sits showing "Dark" while `data-theme` stays light and
  // storage stays empty. That is the whole of gap §16, and it is a defect
  // for any visitor whose bundle lands late, not only for a test.
  //
  // WHAT MAKES THIS SAFE TO RUN ON EVERY MOUNT. The value that arrives in
  // the server markup is `serverThemePreference()`, so a checked radio
  // holding anything else can only have been checked by the user. Adopting
  // is skipped when the checked radio already agrees with the live
  // preference (nothing happened) and when it is the server's own default
  // (React has not re-rendered from the client snapshot yet). Both guards
  // are value comparisons rather than assumptions about when React's
  // `useSyncExternalStore` re-render lands relative to this effect, which
  // is deliberately not an ordering this component gets to depend on.
  //
  // WHY IT IS DECLARED AFTER THE `system` EFFECT AND NOT BEFORE IT. Both run
  // in declaration order on the mount commit, and that one writes
  // `data-theme` on the hydration pass because `preference` is still the
  // server snapshot there — the defect `e2e/theme.spec.ts` declares with
  // `test.fail`, which is not this change's to fix. Declared first, the
  // adopted choice would be applied and then immediately overwritten.
  //
  // THE ONE CASE IT CANNOT SEE, recorded rather than left to be discovered:
  // a pre-hydration click on the option the server already rendered as
  // checked. It changes no DOM state and fires no `change` event, so
  // nothing distinguishes it from no click at all.
  useEffect(() => {
    const chosen =
      document.querySelector<HTMLInputElement>(
        `input[name="${RADIO_GROUP_NAME}"]:checked`,
      )?.value ?? null;
    if (!isThemePreference(chosen)) return;
    if (chosen === readThemePreference() || chosen === serverThemePreference())
      return;
    setThemePreference(chosen);
  }, []);

  const onChange = useCallback((next: ThemePreference) => {
    setThemePreference(next);
  }, []);

  return (
    <fieldset
      className={[
        // `min-w-0` because a fieldset's default `min-width: min-content`
        // would stop it shrinking inside the header's flex row.
        "flex min-w-0 items-center rounded-md border border-border-subtle p-1",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      data-theme-toggle=""
    >
      {/* The group's accessible name. Clipped rather than absent: a
          fieldset with no legend is an unnamed group. */}
      <legend className={VISUALLY_HIDDEN_CLASS}>{THEME_CONTROL.groupLabel}</legend>

      {THEME_PREFERENCES.map((option) => (
        <label key={option} className="ew-theme-option">
          <input
            type="radio"
            name={RADIO_GROUP_NAME}
            value={option}
            checked={preference === option}
            onChange={() => onChange(option)}
            className={VISUALLY_HIDDEN_CLASS}
          />
          <span className="block rounded-sm px-2 py-1 text-ui-xs font-medium text-ink-muted">
            {THEME_LABEL[option]}
          </span>
        </label>
      ))}
    </fieldset>
  );
}
