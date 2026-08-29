import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{a as n,n as r,o as i,r as a}from"./threads-iAeM6bq3.js";import{n as o,t as s}from"./ThreadList-CNPmfk2V.js";var c,l,u,d,f,p,m,h,g,_,v,y,b,x,S,C;function w(){return(w=e((()=>{c=t(),i(),o(),{expect:l,screen:u,userEvent:d,within:f}=__STORYBOOK_MODULE_TEST__,p=[{id:`thread-1`,title:`Retrieval-augmented verification`},{id:`thread-2`,title:`Sparse attention survey`},{id:`thread-3`,title:`Eval harness drift`}],m={title:`ThreadRail`,component:s,args:{threads:p},decorators:[e=>(0,c.jsx)(`div`,{className:`h-[26rem] w-rail border border-border-subtle bg-surface`,children:(0,c.jsx)(e,{})})],parameters:{docs:{description:{component:`The rail is 260px in the shell (\`--layout-rail-width\`), and a story that
rendered it full-bleed would prove nothing about the one measurement that
matters — a title that has to truncate rather than push the overflow menu
off the edge.`}}}},h={args:{threads:[],loading:!0},play:async({canvasElement:e})=>{let t=f(e);await l(t.getByRole(`list`)).toHaveAttribute(`aria-busy`,`true`),await l(t.getByRole(`heading`,{name:r.heading})).toBeVisible()}},g={args:{threads:[]},play:async({canvasElement:e})=>{await l(f(e).getByText(r.empty)).toBeVisible()}},_={args:{activeConversationId:`thread-2`},play:async({canvasElement:e})=>{let t=f(e).getAllByRole(`button`,{name:/^Thread actions:/});await l(t).toHaveLength(p.length);for(let e of t)await l(e).toBeVisible()}},v={args:{canLoadMore:!0},play:async({canvasElement:e})=>{await l(f(e).getByRole(`button`,{name:r.loadMore})).toBeVisible()}},y={args:{threads:[],notice:{sentence:r.error,recovery:r.errorRecovery,retryLabel:r.retry,onRetry:()=>{}}},play:async({canvasElement:e})=>{let t=f(e);await l(t.getByRole(`alert`)).toHaveTextContent(r.error),await l(t.getByRole(`button`,{name:r.retry})).toBeVisible()}},b={args:{pendingDelete:p[0]},play:async()=>{let e=await u.findByRole(`dialog`),t=n(p[0]?.title??``);await l(f(e).getByText(t.body)).toBeVisible(),await l(f(e).getByRole(`button`,{name:t.confirm})).toBeVisible()}},x={args:{activeConversationId:`thread-1`,attachedJobId:`job-4f2c`},play:async({canvasElement:e})=>{let t=f(e),n=t.getByRole(`link`,{name:/Retrieval-augmented/});await l(n).toHaveAttribute(`href`,`/c/thread-1?job=job-4f2c`),await l(f(n).getByText(a.live)).toBeVisible(),await l(t.getByRole(`link`,{name:/Sparse attention/})).toHaveAttribute(`href`,`/c/thread-2`)}},S={play:async({canvasElement:e})=>{let t=f(e).getAllByRole(`button`,{name:/^Thread actions:/})[0];if(t===void 0)throw TypeError(`no row menu rendered`);t.focus(),await d.keyboard(`{Enter}`);let n=await u.findByRole(`menu`);await l(f(n).getByRole(`menuitem`,{name:a.delete})).toBeVisible()}},h.parameters={...h.parameters,docs:{...h.parameters?.docs,source:{originalSource:`{
  args: {
    threads: [],
    loading: true
  },
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("list")).toHaveAttribute("aria-busy", "true");
    await expect(canvas.getByRole("heading", {
      name: THREAD_RAIL.heading
    })).toBeVisible();
  }
}`,...h.parameters?.docs?.source},description:{story:"03 §2.2 row 2. Three rows at real row height with the chrome already\ndrawn, `aria-busy` on the list, and no spinner anywhere.",...h.parameters?.docs?.description}}},g.parameters={...g.parameters,docs:{...g.parameters?.docs,source:{originalSource:`{
  args: {
    threads: []
  },
  play: async ({
    canvasElement
  }) => {
    await expect(within(canvasElement).getByText(THREAD_RAIL.empty)).toBeVisible();
  }
}`,...g.parameters?.docs?.source},description:{story:`03 §2.2 row 3 — distinct from loading and from the error state.`,...g.parameters?.docs?.description}}},_.parameters={..._.parameters,docs:{..._.parameters?.docs,source:{originalSource:`{
  args: {
    activeConversationId: "thread-2"
  },
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    const menus = canvas.getAllByRole("button", {
      name: /^Thread actions:/
    });
    await expect(menus).toHaveLength(THREADS.length);
    for (const menu of menus) await expect(menu).toBeVisible();
  }
}`,..._.parameters?.docs?.source},description:{story:`The destructive control is in the tab order of every row, at full
opacity, with no pointer event anywhere near it — criterion 2, and the
defect at \`ConversationSidebar.tsx:133\`.`,..._.parameters?.docs?.description}}},v.parameters={...v.parameters,docs:{...v.parameters?.docs,source:{originalSource:`{
  args: {
    canLoadMore: true
  },
  play: async ({
    canvasElement
  }) => {
    await expect(within(canvasElement).getByRole("button", {
      name: THREAD_RAIL.loadMore
    })).toBeVisible();
  }
}`,...v.parameters?.docs?.source},description:{story:'"Load more" appears only when a page came back full (criterion 7). There\nis no page count beside it and no "showing N of M": `GET /conversations`\nreturns a bare array with neither a total nor a `has_more` (03 §2.3).',...v.parameters?.docs?.description}}},y.parameters={...y.parameters,docs:{...y.parameters?.docs,source:{originalSource:`{
  args: {
    threads: [],
    notice: {
      sentence: THREAD_RAIL.error,
      recovery: THREAD_RAIL.errorRecovery,
      retryLabel: THREAD_RAIL.retry,
      onRetry: () => {}
    }
  },
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("alert")).toHaveTextContent(THREAD_RAIL.error);
    await expect(canvas.getByRole("button", {
      name: THREAD_RAIL.retry
    })).toBeVisible();
  }
}`,...y.parameters?.docs?.source},description:{story:"03 §2.2 row 4 — an inline alert at the TOP of the rail, with a Retry that\nre-runs `GET /conversations` and can reach no mutation at all.",...y.parameters?.docs?.description}}},b.parameters={...b.parameters,docs:{...b.parameters?.docs,source:{originalSource:`{
  args: {
    pendingDelete: THREADS[0]
  },
  play: async () => {
    const dialog = await screen.findByRole("dialog");
    const copy = deleteDialog(THREADS[0]?.title ?? "");
    await expect(within(dialog).getByText(copy.body)).toBeVisible();
    await expect(within(dialog).getByRole("button", {
      name: copy.confirm
    })).toBeVisible();
  }
}`,...b.parameters?.docs?.source},description:{story:"03 §2.2 row 24 and §8.2 — the APG modal that replaces `confirm()`, with\nthe ratified sentence. `deletePending` is the eighth rail state\n(*deleting*): the same dialog with its confirm button busy.",...b.parameters?.docs?.description}}},x.parameters={...x.parameters,docs:{...x.parameters?.docs,source:{originalSource:`{
  args: {
    activeConversationId: "thread-1",
    attachedJobId: "job-4f2c"
  },
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    const live = canvas.getByRole("link", {
      name: /Retrieval-augmented/
    });
    await expect(live).toHaveAttribute("href", "/c/thread-1?job=job-4f2c");
    await expect(within(live).getByText(THREAD_ROW.live)).toBeVisible();
    await expect(canvas.getByRole("link", {
      name: /Sparse attention/
    })).toHaveAttribute("href", "/c/thread-2");
  }
}`,...x.parameters?.docs?.source},description:{story:`Criterion 1 / R-02. The attached run's own row keeps \`?job=\` and is the
only row that does — every other row would be pointing the parameter at a
thread that never had that run.`,...x.parameters?.docs?.description}}},S.parameters={...S.parameters,docs:{...S.parameters?.docs,source:{originalSource:`{
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getAllByRole("button", {
      name: /^Thread actions:/
    })[0];
    // \`TypeError\` rather than \`Error\`: this module exports a story called
    // \`Error\`, which shadows the global inside it.
    if (trigger === undefined) throw new TypeError("no row menu rendered");
    trigger.focus();
    await userEvent.keyboard("{Enter}");
    const menu = await screen.findByRole("menu");
    await expect(within(menu).getByRole("menuitem", {
      name: THREAD_ROW.delete
    })).toBeVisible();
  }
}`,...S.parameters?.docs?.source},description:{story:`The overflow menu opened from the keyboard alone — the roving-focus
behaviour RC-09 kept the \`Menu\` primitive for, on the one control in the
product that really is a menu.`,...S.parameters?.docs?.description}}},C=[`Loading`,`Empty`,`Populated`,`PopulatedWithMore`,`Error`,`DeleteConfirm`,`ActiveRunRow`,`RowMenuOpen`]})))()}w();export{x as ActiveRunRow,b as DeleteConfirm,g as Empty,y as Error,h as Loading,_ as Populated,v as PopulatedWithMore,S as RowMenuOpen,C as __namedExportsOrder,m as default};