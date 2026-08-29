import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{n,o as r}from"./threads-iAeM6bq3.js";import{n as i,t as a}from"./ThreadList-CNPmfk2V.js";import{n as o,t as s}from"./ThreadDrawer-jZpmQqcd.js";var c,l,u,d,f,p,m,h;function g(){return(g=e((()=>{c=t(),i(),r(),o(),{expect:l,screen:u,within:d}=__STORYBOOK_MODULE_TEST__,f={title:`ThreadRail/Drawer`,component:s,args:{open:!1,onOpenChange:()=>{},children:(0,c.jsx)(a,{threads:[{id:`thread-1`,title:`Retrieval-augmented verification`},{id:`thread-2`,title:`Sparse attention survey`}],activeConversationId:`thread-1`})}},p={play:async()=>{await l(u.queryByRole(`dialog`)).toBeNull()}},m={args:{open:!0},parameters:{viewport:{defaultViewport:`w320`}},play:async()=>{let e=await u.findByRole(`dialog`,{name:n.heading});await l(d(e).getByRole(`link`,{name:/Retrieval-augmented/})).toBeVisible(),await l(d(e).queryByRole(`region`)).toBeNull()}},p.parameters={...p.parameters,docs:{...p.parameters?.docs,source:{originalSource:`{
  play: async () => {
    await expect(screen.queryByRole("dialog")).toBeNull();
  }
}`,...p.parameters?.docs?.source},description:{story:`Closed is not "hidden": Radix renders no portal at all, so the drawer's
subtree — and the second copy of the rail it would hold — does not exist.`,...p.parameters?.docs?.description}}},m.parameters={...m.parameters,docs:{...m.parameters?.docs,source:{originalSource:`{
  args: {
    open: true
  },
  parameters: {
    viewport: {
      defaultViewport: "w320"
    }
  },
  play: async () => {
    const dialog = await screen.findByRole("dialog", {
      name: THREAD_RAIL.heading
    });
    // The rail is inside the dialog, and the dialog is the only scroller:
    // no second \`region\` focus stop wrapping it (see ThreadDrawer.tsx).
    await expect(within(dialog).getByRole("link", {
      name: /Retrieval-augmented/
    })).toBeVisible();
    await expect(within(dialog).queryByRole("region")).toBeNull();
  }
}`,...m.parameters?.docs?.source}}},h=[`Closed`,`Open`]})))()}g();export{p as Closed,m as Open,h as __namedExportsOrder,f as default};