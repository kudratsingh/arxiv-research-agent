import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{a as n,f as r,o as i,r as a}from"./tokens-BmyTjNhk.js";import{n as o,r as s}from"./shell-Cj-7KxQe.js";import{n as c,t as l}from"./ThemeToggle-D2yyPDpB.js";function u(e){return t=>(document.documentElement.setAttribute(n,e),(0,d.jsx)(t,{}))}var d,f,p,m,h,g,_,v,y,b,x;function S(){return(S=e((()=>{d=t(),s(),r(),c(),{expect:f,userEvent:p}=__STORYBOOK_MODULE_TEST__,m={title:`Patterns/ThemeToggle`,component:l,decorators:[e=>(0,d.jsx)(`div`,{className:`flex items-center gap-4 bg-canvas p-6`,children:(0,d.jsx)(e,{})})]},h={globals:{theme:`light`}},g={globals:{theme:`dark`}},_={decorators:[u(`system`)]},v={decorators:[u(`light`)],play:async({canvas:e})=>{await p.click(e.getByRole(`radio`,{name:o.dark})),await f(document.documentElement.getAttribute(a)).toBe(`dark`),await f(document.documentElement.getAttribute(n)).toBe(`dark`),await f(window.localStorage.getItem(i)).toBe(`dark`),window.localStorage.removeItem(i)}},y={play:async({canvasElement:e})=>{let t=e.querySelector(`input[type="radio"][value="dark"]`);t?.focus(),await f(t).toHaveFocus()}},b={globals:{theme:`forced-colors`}},h.parameters={...h.parameters,docs:{...h.parameters?.docs,source:{originalSource:`{
  globals: {
    theme: "light"
  }
}`,...h.parameters?.docs?.source},description:{story:'An explicit light choice: `data-theme-preference="light"`.',...h.parameters?.docs?.description}}},g.parameters={...g.parameters,docs:{...g.parameters?.docs,source:{originalSource:`{
  globals: {
    theme: "dark"
  }
}`,...g.parameters?.docs?.source},description:{story:`An explicit dark choice. The control is legible on the dark canvas.`,...g.parameters?.docs?.description}}},_.parameters={..._.parameters,docs:{..._.parameters?.docs,source:{originalSource:`{
  decorators: [withPreference("system")]
}`,..._.parameters?.docs?.source},description:{story:"Deferring to the OS. Distinguishable from `Light` only because the\nproduct stores the *preference* separately from the resolved theme —\nwhich is the reason `THEME_PREFERENCE_ATTRIBUTE` exists.",..._.parameters?.docs?.description}}},v.parameters={...v.parameters,docs:{...v.parameters?.docs,source:{originalSource:`{
  decorators: [withPreference("light")],
  play: async ({
    canvas
  }) => {
    await userEvent.click(canvas.getByRole("radio", {
      name: THEME_CONTROL.dark
    }));
    await expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBe("dark");
    await expect(document.documentElement.getAttribute(THEME_PREFERENCE_ATTRIBUTE)).toBe("dark");
    await expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    window.localStorage.removeItem(THEME_STORAGE_KEY);
  }
}`,...v.parameters?.docs?.source},description:{story:`Making a choice, which is the one thing a static picture cannot show.

The play function is the mechanism end to end: click, and \`data-theme\`
flips on \`<html>\` — so the canvas behind the control repaints — while the
*preference* is written to WO-01's storage key for the next load's
pre-paint script to find. web/tests/shell/themeToggle.test.tsx asserts
the same contract without a browser.`,...v.parameters?.docs?.description}}},y.parameters={...y.parameters,docs:{...y.parameters?.docs,source:{originalSource:`{
  play: async ({
    canvasElement
  }) => {
    const input = canvasElement.querySelector<HTMLInputElement>('input[type="radio"][value="dark"]');
    input?.focus();
    await expect(input).toHaveFocus();
  }
}`,...y.parameters?.docs?.source},description:{story:"The focus ring, on the label rather than on the clipped input.\n\nThe same honest caveat SkipLink's `Focused` story carries: `:focus-visible`\nis granted for a keyboard-initiated focus, and a scripted `.focus()` may\nnot qualify. The story proves the input takes focus and that the ring has\nsomewhere to land; a Tab is what paints it.",...y.parameters?.docs?.description}}},b.parameters={...b.parameters,docs:{...b.parameters?.docs,source:{originalSource:`{
  globals: {
    theme: "forced-colors"
  }
}`,...b.parameters?.docs?.source}}},x=[`Light`,`Dark`,`System`,`Switching`,`KeyboardFocus`,`ForcedColours`]})))()}S();export{g as Dark,b as ForcedColours,y as KeyboardFocus,h as Light,v as Switching,_ as System,x as __namedExportsOrder,m as default};