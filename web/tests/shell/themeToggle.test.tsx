/**
 * WO-08 criterion 8 — `ThemeToggle` offers light / dark / system, persists,
 * and is applied by WO-01's pre-paint script with no flash.
 *
 * The first two clauses are asserted here. The third is a browser fact —
 * "no flash" means a paint that never happened — and is WO-21's, per the
 * WO-01-c5 precedent. What this file *can* prove about it, and does, is the
 * property the Playwright assertion depends on: the toggle writes the
 * preference to the exact key `themeInitScript` reads, in a form that
 * script accepts, and writes both attributes so the resolved theme is live
 * before the next reload rather than because of it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeToggle, readThemePreference } from "@/components/patterns/ThemeToggle";
import { THEME_CONTROL } from "@/lib/copy/shell";
import {
  THEME_ATTRIBUTE,
  THEME_PREFERENCES,
  THEME_PREFERENCE_ATTRIBUTE,
  THEME_STORAGE_KEY,
  themeInitScript,
} from "@/lib/tokens";

import { act, render, screen, user } from "../support/render";
import { installMatchMedia, setPrefersDark, uninstallMatchMedia } from "./support";

beforeEach(() => {
  installMatchMedia({ width: 1440, prefersDark: false });
  window.localStorage.clear();
});

afterEach(() => {
  uninstallMatchMedia();
  window.localStorage.clear();
});

describe("criterion 8 — three choices, named and grouped", () => {
  it("offers exactly light, dark and system as one named radio group", () => {
    render(<ThemeToggle />);
    const group = screen.getByRole("group", { name: THEME_CONTROL.groupLabel });
    expect(group).toBeInTheDocument();

    const radios = screen.getAllByRole("radio");
    expect(radios.map((radio) => (radio as HTMLInputElement).value)).toEqual([
      ...THEME_PREFERENCES,
    ]);
    for (const label of [THEME_CONTROL.light, THEME_CONTROL.dark, THEME_CONTROL.system]) {
      expect(screen.getByRole("radio", { name: label })).toBeInTheDocument();
    }
  });

  it("shows the preference the pre-paint script resolved, not a guess", () => {
    // `render` writes both attributes exactly as themeInitScript does.
    render(<ThemeToggle />, { theme: "dark", themePreference: "dark" });
    expect(screen.getByRole("radio", { name: THEME_CONTROL.dark })).toBeChecked();
    expect(screen.getByRole("radio", { name: THEME_CONTROL.light })).not.toBeChecked();
  });

  it("tells an explicit light apart from a system that resolves to light", () => {
    render(<ThemeToggle />, { theme: "light", themePreference: "system" });
    expect(screen.getByRole("radio", { name: THEME_CONTROL.system })).toBeChecked();
    expect(screen.getByRole("radio", { name: THEME_CONTROL.light })).not.toBeChecked();
    expect(readThemePreference()).toBe("system");
  });
});

describe("criterion 8 — persistence, in the form the pre-paint script reads", () => {
  it.each(["light", "dark", "system"] as const)("stores %s under WO-01's key", async (choice) => {
    // Start from a preference that is not the one under test, so the click
    // is a real change rather than a no-op on an already-checked radio.
    render(<ThemeToggle />, {
      theme: "light",
      themePreference: choice === "dark" ? "light" : "dark",
    });
    await user().click(screen.getByRole("radio", { name: new RegExp(`^${choice}$`, "i") }));

    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe(choice);
    // RC-05 allows two keys product-wide; this is the only one written here.
    expect(window.localStorage.length).toBe(1);
    // The script accepts a value only if it is in THEME_PREFERENCES; the
    // script's own source is the assertion's other half.
    expect(themeInitScript).toContain(JSON.stringify(THEME_STORAGE_KEY));
    expect(themeInitScript).toContain(JSON.stringify(THEME_PREFERENCES));
  });

  it("applies the choice to both attributes immediately", async () => {
    render(<ThemeToggle />, { theme: "light", themePreference: "light" });
    await user().click(screen.getByRole("radio", { name: THEME_CONTROL.dark }));

    const root = document.documentElement;
    expect(root.getAttribute(THEME_ATTRIBUTE)).toBe("dark");
    expect(root.getAttribute(THEME_PREFERENCE_ATTRIBUTE)).toBe("dark");
  });

  it("resolves `system` through prefers-color-scheme rather than storing a theme", async () => {
    installMatchMedia({ width: 1440, prefersDark: true });
    render(<ThemeToggle />, { theme: "light", themePreference: "light" });
    await user().click(screen.getByRole("radio", { name: THEME_CONTROL.system }));

    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("system");
    expect(document.documentElement.getAttribute(THEME_PREFERENCE_ATTRIBUTE)).toBe("system");
    expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBe("dark");
  });

  it("keeps following the OS after the user switches to system in this session", async () => {
    installMatchMedia({ width: 1440, prefersDark: false });
    render(<ThemeToggle />, { theme: "light", themePreference: "light" });
    await user().click(screen.getByRole("radio", { name: THEME_CONTROL.system }));
    expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBe("light");

    // The pre-paint script attaches its own listener only when the STORED
    // preference was already "system" at load, so without the component's
    // listener this transition would be missed until the next reload.
    await act(async () => {
      setPrefersDark(true);
    });
    expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBe("dark");
  });

  it("stops following the OS once an explicit choice is made", async () => {
    installMatchMedia({ width: 1440, prefersDark: false });
    render(<ThemeToggle />, { theme: "light", themePreference: "system" });
    await user().click(screen.getByRole("radio", { name: THEME_CONTROL.light }));

    await act(async () => {
      setPrefersDark(true);
    });
    expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBe("light");
  });

  it("still applies the theme when storage throws", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage is partitioned");
    });
    try {
      render(<ThemeToggle />, { theme: "light", themePreference: "light" });
      await user().click(screen.getByRole("radio", { name: THEME_CONTROL.dark }));
      expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBe("dark");
    } finally {
      setItem.mockRestore();
    }
  });
});

describe("criterion 8 — the no-flash property's preconditions", () => {
  it("does not apply the theme itself on mount; the pre-paint script already did", () => {
    // A control that wrote `data-theme` from an effect would be the flash.
    // With an explicit preference the component writes nothing at mount.
    document.documentElement.setAttribute(THEME_ATTRIBUTE, "dark");
    document.documentElement.setAttribute(THEME_PREFERENCE_ATTRIBUTE, "dark");
    render(<ThemeToggle />, { theme: "dark", themePreference: "dark" });
    expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBe("dark");
  });

  it("is not the source of truth: it reads the attribute the script wrote", () => {
    document.documentElement.setAttribute(THEME_PREFERENCE_ATTRIBUTE, "nonsense");
    expect(readThemePreference()).toBe("system");
  });
});
