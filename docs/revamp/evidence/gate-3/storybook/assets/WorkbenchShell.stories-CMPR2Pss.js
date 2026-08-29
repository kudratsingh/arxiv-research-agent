import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{f as n,t as r}from"./tokens-BmyTjNhk.js";import{n as i,o as a}from"./threads-iAeM6bq3.js";import{i as o,r as s}from"./WorkbenchShell-DwuILiWd.js";function c(){return(0,u.jsxs)(`aside`,{className:`flex h-full w-rail shrink-0 flex-col bg-surface`,children:[(0,u.jsx)(`div`,{className:`p-3`,children:(0,u.jsx)(`button`,{type:`button`,className:`ew-focusable ew-target ew-target--sm w-full rounded-md border border-border-strong bg-surface px-3 text-ui-sm font-medium text-ink`,children:`+ New conversation`})}),(0,u.jsx)(`p`,{className:`px-3 pb-2 text-ui-xs font-semibold uppercase tracking-wide text-ink-faint`,children:`Recent`}),(0,u.jsx)(`ul`,{className:`flex flex-col gap-1 px-2`,children:[`Retrieval-augmented verification`,`Sparse attention survey`,`Eval harness drift`].map((e,t)=>(0,u.jsx)(`li`,{children:(0,u.jsx)(`a`,{href:`/c/thread-${t+1}`,className:`ew-focusable block truncate rounded-md px-3 py-2 text-ui-sm text-ink hover:bg-sunken`,children:e})},e))})]})}function l(){return(0,u.jsxs)(`div`,{className:`flex h-full flex-col gap-4 overflow-y-auto p-6`,children:[(0,u.jsx)(`h1`,{className:`text-ui-xl font-semibold text-ink`,children:`Retrieval-augmented verification`}),(0,u.jsxs)(`p`,{className:`max-w-measure text-ui-sm text-ink-muted`,children:[`The route renders here, inside the shell’s single`,(0,u.jsx)(`code`,{className:`font-mono`,children:` <main id="main">`}),`. In M1 that is still the existing landing page or conversation thread, rendered unmodified.`]})]})}var u,d,f,p,m,h,g,_,v,y,b,x,S,C,w,T;function E(){return(E=e((()=>{u=t(),a(),n(),o(),{expect:d,screen:f,userEvent:p,waitFor:m}=__STORYBOOK_MODULE_TEST__,h={title:`Shell/WorkbenchShell`,component:s,parameters:{nextjs:{appDirectory:!0}},args:{rail:(0,u.jsx)(c,{}),children:(0,u.jsx)(l,{})}},g={args:{railMode:`expanded`,railCollapsed:!1}},_={args:{railMode:`expanded`,railCollapsed:!0}},v={args:{railMode:`expanded`},beforeEach:()=>(window.localStorage.setItem(r,`0`),()=>window.localStorage.removeItem(r)),play:async({canvas:e})=>{await p.click(e.getByRole(`button`,{name:i.collapse})),await d(e.getByRole(`button`,{name:i.expand})).toBeInTheDocument(),await d(window.localStorage.getItem(r)).toBe(`1`)}},y={args:{railMode:`drawer`}},b={args:{railMode:`drawer`,defaultDrawerOpen:!0},play:async()=>{await m(()=>{d(f.getByRole(`dialog`,{name:i.heading})).toBeInTheDocument()})}},x={args:{railMode:`expanded`,railCollapsed:!1,offline:!0}},S={args:{railMode:`compact`}},C={args:{...g.args},globals:{theme:`dark`}},w={args:{...g.args},globals:{theme:`forced-colors`}},g.parameters={...g.parameters,docs:{...g.parameters?.docs,source:{originalSource:`{
  args: {
    railMode: "expanded",
    railCollapsed: false
  }
}`,...g.parameters?.docs?.source},description:{story:`≥1024px, the persistent 260px rail. The default the server renders.`,...g.parameters?.docs?.description}}},_.parameters={..._.parameters,docs:{..._.parameters?.docs,source:{originalSource:`{
  args: {
    railMode: "expanded",
    railCollapsed: true
  }
}`,..._.parameters?.docs?.source},description:{story:`≥1024px with the persisted collapse preference set: the 56px icon strip.`,..._.parameters?.docs?.description}}},v.parameters={...v.parameters,docs:{...v.parameters?.docs,source:{originalSource:`{
  args: {
    railMode: "expanded"
  },
  // Before the render, not inside the play: the shell reads the preference
  // while it renders, so clearing it afterwards would be too late.
  beforeEach: () => {
    window.localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, "0");
    return () => window.localStorage.removeItem(RAIL_COLLAPSED_STORAGE_KEY);
  },
  play: async ({
    canvas
  }) => {
    await userEvent.click(canvas.getByRole("button", {
      name: THREAD_RAIL.collapse
    }));
    await expect(canvas.getByRole("button", {
      name: THREAD_RAIL.expand
    })).toBeInTheDocument();
    await expect(window.localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe("1");
  }
}`,...v.parameters?.docs?.source},description:{story:`The collapse toggle, and the preference it writes.

This story deliberately omits \`railCollapsed\`, so the shell reads the real
\`localStorage\` key — RC-05's second and last persisted preference. The
play function is the only place the *write* is demonstrated rather than
described; web/tests/shell/shell.test.tsx asserts the same thing without a
browser.`,...v.parameters?.docs?.description}}},y.parameters={...y.parameters,docs:{...y.parameters?.docs,source:{originalSource:`{
  args: {
    railMode: "drawer"
  }
}`,...y.parameters?.docs?.source},description:{story:`Below 768px. The rail is not in the layout at all (04 §8.3 item 1) — the
only way to it is the labelled header button.`,...y.parameters?.docs?.description}}},b.parameters={...b.parameters,docs:{...b.parameters?.docs,source:{originalSource:`{
  args: {
    railMode: "drawer",
    defaultDrawerOpen: true
  },
  play: async () => {
    // \`screen\`, not \`canvas\`: Radix portals the dialog to \`document.body\`,
    // outside the story's canvas element. The drawer's module is lazy (it
    // carries Radix), so the dialog is one microtask behind first render.
    await waitFor(() => {
      expect(screen.getByRole("dialog", {
        name: THREAD_RAIL.heading
      })).toBeInTheDocument();
    });
  }
}`,...b.parameters?.docs?.source},description:{story:`The drawer as an APG modal dialog. Focus is trapped inside it, Escape
closes it, and focus returns to the trigger — asserted in
web/tests/shell/drawer.test.tsx, because a story is a picture.`,...b.parameters?.docs?.description}}},x.parameters={...x.parameters,docs:{...x.parameters?.docs,source:{originalSource:`{
  args: {
    railMode: "expanded",
    railCollapsed: false,
    offline: true
  }
}`,...x.parameters?.docs?.source},description:{story:`Offline. The shell states it and does not announce it: 03 §7.3 allows
exactly two live regions product-wide and both are spoken for, so the
announcement is WO-12's StatusBanner rather than a third.`,...x.parameters?.docs?.description}}},S.parameters={...S.parameters,docs:{...S.parameters?.docs,source:{originalSource:`{
  args: {
    railMode: "compact"
  }
}`,...S.parameters?.docs?.source},description:{story:`768–1023px: the 56px icon strip, every control named.`,...S.parameters?.docs?.description}}},C.parameters={...C.parameters,docs:{...C.parameters?.docs,source:{originalSource:`{
  args: {
    ...RailExpanded.args
  },
  globals: {
    theme: "dark"
  }
}`,...C.parameters?.docs?.source}}},w.parameters={...w.parameters,docs:{...w.parameters?.docs,source:{originalSource:`{
  args: {
    ...RailExpanded.args
  },
  globals: {
    theme: "forced-colors"
  }
}`,...w.parameters?.docs?.source}}},T=[`RailExpanded`,`RailCollapsed`,`RailCollapseToggle`,`DrawerClosed`,`DrawerOpen`,`Offline`,`IconStrip`,`Dark`,`ForcedColours`]})))()}E();export{C as Dark,y as DrawerClosed,b as DrawerOpen,w as ForcedColours,S as IconStrip,x as Offline,v as RailCollapseToggle,_ as RailCollapsed,g as RailExpanded,T as __namedExportsOrder,h as default};