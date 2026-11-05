import { describe, expect, it } from "vitest";
import { commandForKey, GLOBAL_COMMANDS, KEY_SEQUENCE_TIMEOUT, PAGE_COMMANDS, ROUTE_COMMANDS } from "@/lib/workspace/commands";

function key(key: string, overrides: Partial<Parameters<typeof commandForKey>[0]> = {}) {
  return { key, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false,
    defaultPrevented: false, isComposing: false, target: document.body, timeStamp: 100, ...overrides };
}
const none = { command: null, sequence: null };
describe("workspace command vocabulary", () => {
  it("has distinct page, route and global names without UI dispatch", () => {
    const names = [...PAGE_COMMANDS, ...Object.keys(ROUTE_COMMANDS), ...GLOBAL_COMMANDS];
    expect(new Set(names).size).toBe(names.length);
    expect(ROUTE_COMMANDS["go-sources"]).toBe("/workspace/operations");
    expect(PAGE_COMMANDS).toContain("time-15");
  });
  it.each([
    ["j", "next"], ["k", "prev"], ["o", "open"], ["s", "save"], ["d", "dismiss"],
    ["z", "snooze"], ["u", "undo"], ["ArrowRight", "next"], ["ArrowLeft", "prev"], ["Enter", "open"],
    ["/", "focus-composer"], ["?", "shortcuts"], ["[", "toggle-sidebar"],
    ["1", "label-useful"], ["2", "label-maybe"], ["3", "label-irrelevant"],
  ])("maps %s to %s", (pressed, command) => {
    expect(commandForKey(key(pressed))).toEqual({ command, sequence: null });
  });
  it.each(["t", "r", "l", "i", "s", "v"])("resolves g then %s", (pressed) => {
    const first = commandForKey(key("g"));
    expect(first).toEqual({ command: null, sequence: { key: "g", at: 100 } });
    expect(commandForKey(key(pressed, { timeStamp: 100 + KEY_SEQUENCE_TIMEOUT }), first.sequence).command)
      .toBe(({ t: "go-today", r: "go-radar", l: "go-library", i: "go-interests", s: "go-sources", v: "go-review" })[pressed]);
  });
  it("expires, clears, or restarts sequences without swallowing standalone actions", () => {
    const sequence = { key: "g" as const, at: 100 };
    expect(commandForKey(key("l", { timeStamp: 1101 }), sequence)).toEqual(none);
    expect(commandForKey(key("l", { timeStamp: 99 }), sequence)).toEqual(none);
    expect(commandForKey(key("j"), sequence).command).toBe("next");
    expect(commandForKey(key("x"), sequence)).toEqual(none);
    expect(commandForKey(key("g", { timeStamp: 200 }), sequence).sequence).toEqual({ key: "g", at: 200 });
    expect(commandForKey(key("J", { shiftKey: true }))).toEqual(none);
    expect(commandForKey(key("?", { shiftKey: true })).command).toBe("shortcuts");
  });
});

describe("native keyboard ownership", () => {
  it.each([{ defaultPrevented: true }, { isComposing: true }, { altKey: true }, { ctrlKey: true }, { metaKey: true }])(
    "ignores consumed/composing/modified action %j", (flags) => expect(commandForKey(key("s", flags))).toEqual(none));
  it.each(["input", "textarea", "select", "div[contenteditable=true]", "div[contenteditable='']"])(
    "protects field %s except Escape and palette", (selector) => {
      const holder = document.createElement("div");
      holder.innerHTML = selector.startsWith("div") ? `<div contenteditable="true"><span>edit</span></div>` : `<${selector}></${selector}>`;
      const target = holder.querySelector("span") ?? holder.firstElementChild!;
      expect(commandForKey(key("s", { target }))).toEqual(none);
      expect(commandForKey(key("Escape", { target })).command).toBe("escape");
      expect(commandForKey(key("k", { target, metaKey: true })).command).toBe("command-palette");
    });
  it("allows noneditable descendants, handles non-element targets, and supports Ctrl+K", () => {
    const target = document.createElement("div"); target.contentEditable = "false";
    expect(commandForKey(key("s", { target })).command).toBe("save");
    expect(commandForKey(key("s", { target: null })).command).toBe("save");
    expect(commandForKey(key("Enter", { target: null }))).toEqual(none);
    expect(commandForKey(key("K", { ctrlKey: true })).command).toBe("command-palette");
    expect(commandForKey(key("k", { ctrlKey: true, altKey: true }))).toEqual(none);
    expect(commandForKey(key("k", { ctrlKey: true, shiftKey: true }))).toEqual(none);
    expect(commandForKey(key("s", { metaKey: true, altKey: true }))).toEqual(none);
  });
  it.each(["button", "a", "summary", "span role='radio'", "span role='tab'", "div tabindex='0'"])(
    "leaves Enter and arrows native inside %s", (tag) => {
      const holder = document.createElement("div");
      holder.innerHTML = `<${tag}><span>nested</span></${tag.split(" ")[0]}>`;
      const target = holder.querySelector("span:last-child")!;
      for (const pressed of ["Enter", "ArrowLeft", "ArrowRight"]) expect(commandForKey(key(pressed, { target }))).toEqual(none);
    });
  it("allows navigation on the stage or bar containers themselves", () => {
    const main = document.createElement("main"); main.id = "main";
    const bar = document.createElement("div"); bar.className = "ws-bar";
    expect(commandForKey(key("Enter", { target: main })).command).toBe("open");
    expect(commandForKey(key("ArrowRight", { target: bar })).command).toBe("next");
  });
  it.each(["Enter", "ArrowRight", "ArrowLeft"])("leaves Shift+%s native even on the stage", (pressed) => {
    const main = document.createElement("main"); main.id = "main";
    expect(commandForKey(key(pressed, { target: main, shiftKey: true }))).toEqual(none);
    expect(commandForKey(key(pressed, { shiftKey: true }))).toEqual(none);
  });
  it.each(["dialog open", "div role='dialog' aria-modal='true'"])("respects open %s ownership", (tag) => {
    const holder = document.createElement("div");
    holder.innerHTML = `<${tag}><button>action</button></${tag.split(" ")[0]}>`;
    const target = holder.querySelector("button")!;
    expect(commandForKey(key("j", { target }))).toEqual(none);
    expect(commandForKey(key("k", { target, metaKey: true }))).toEqual(none);
    expect(commandForKey(key("Escape", { target })).command).toBe("escape");
    holder.firstElementChild!.setAttribute("data-workspace-palette", "");
    expect(commandForKey(key("k", { target, metaKey: true })).command).toBeNull();
    for (const value of ["s", "d", "j", "1", "2", "3", "g"]) {
      expect(commandForKey(key(value, { target })).command).toBeNull();
    }
  });
});
