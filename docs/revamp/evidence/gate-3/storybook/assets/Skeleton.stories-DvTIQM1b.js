import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{r as n,t as r}from"./recovery-Cnc_dh1b.js";import{n as i,r as a}from"./VisuallyHidden-BvZkhsza.js";import{o,s}from"./threads-iAeM6bq3.js";import{i as c,r as l}from"./WorkbenchShell-DwuILiWd.js";import{n as u,t as d}from"./Skeleton-cW23yxTh.js";function f({className:e}){return(0,p.jsxs)(`div`,{"aria-busy":`true`,"data-recovery-surface":`loading`,className:[`flex h-full flex-col`,e].filter(Boolean).join(` `),children:[(0,p.jsxs)(`header`,{className:`border-b border-border-subtle px-6 py-4`,children:[(0,p.jsx)(i,{as:`h1`,children:r.loadingHeading}),(0,p.jsx)(d,{width:`24ch`,height:`var(--text-ui-xl-line)`}),(0,p.jsx)(d,{width:`16ch`,height:`var(--text-ui-xs-line)`,className:`mt-05`})]}),(0,p.jsx)(`div`,{className:`min-h-0 flex-1 overflow-hidden px-6 py-5`,children:(0,p.jsx)(d,{lines:10,height:`var(--text-report-body-size)`,label:r.loadingReport})})]})}var p;function m(){return(m=e((()=>{p=t(),u(),a(),n(),f.__docgenInfo={description:``,methods:[],displayName:`ThreadSkeleton`,props:{className:{required:!1,tsType:{name:`string`},description:``}}}})))()}var h,g,_,v,y,b,x,S,C;function w(){return(w=e((()=>{h=t(),m(),n(),o(),c(),{expect:g,within:_}=__STORYBOOK_MODULE_TEST__,v=(0,h.jsx)(`ul`,{className:`flex flex-col gap-1 p-3`,children:[`Retrieval-augmented verification`,`Sparse attention survey`].map((e,t)=>(0,h.jsx)(`li`,{children:(0,h.jsx)(`a`,{href:`/c/thread-${t+1}`,className:`ew-focusable block truncate rounded-md px-3 py-2 text-ui-sm text-ink hover:bg-sunken`,children:e})},e))}),y={title:`Shell/Skeleton`,component:f,parameters:{nextjs:{appDirectory:!0}},render:()=>(0,h.jsx)(l,{rail:v,railMode:`expanded`,railCollapsed:!1,children:(0,h.jsx)(f,{})})},b={play:async({canvasElement:e})=>{let t=_(e);await g(t.getByRole(`heading`,{level:1,name:r.loadingHeading})).toBeInTheDocument();let n=e.querySelector(`[data-recovery-surface="loading"]`);await g(n).not.toBeNull(),await g(n?.getAttribute(`aria-busy`)).toBe(`true`);let i=e.querySelectorAll(`.ew-skeleton`);await g(i.length).toBeGreaterThan(0);for(let e of i)await g(e.getAttribute(`aria-hidden`)).toBe(`true`)}},x={render:()=>(0,h.jsx)(l,{rail:v,railMode:`expanded`,railCollapsed:!1,children:(0,h.jsxs)(`div`,{className:`flex h-full flex-col`,children:[(0,h.jsxs)(`header`,{className:`border-b border-border-subtle px-6 py-4`,children:[(0,h.jsx)(`h1`,{className:`truncate text-ui-xl font-semibold tracking-tight text-ink`,children:`Retrieval-augmented verification`}),(0,h.jsxs)(`p`,{className:`mt-05 text-ui-xs text-ink-muted`,children:[s(3),` · 12 Mar 2026, 09:41`]})]}),(0,h.jsx)(`div`,{className:`min-h-0 flex-1 overflow-y-auto px-6 py-5`,children:(0,h.jsx)(`p`,{className:`max-w-measure text-report-body text-ink`,children:`The briefing arrives into the track the placeholder lines held open, so the reading position does not move when it does.`})})]})})},S={globals:{viewport:{value:`w412`}},render:()=>(0,h.jsx)(l,{rail:v,railMode:`drawer`,children:(0,h.jsx)(f,{})})},b.parameters={...b.parameters,docs:{...b.parameters?.docs,source:{originalSource:`{
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);

    // Criterion 2 holds here too: the surface has an \`h1\`. It is clipped,
    // because the thread's title is exactly what has not arrived — and a
    // heading that is drawn and then replaced is the layout shift this
    // component exists to remove.
    await expect(canvas.getByRole("heading", {
      level: 1,
      name: RECOVERY.loadingHeading
    })).toBeInTheDocument();
    const surface = canvasElement.querySelector('[data-recovery-surface="loading"]');
    await expect(surface).not.toBeNull();
    await expect(surface?.getAttribute("aria-busy")).toBe("true");

    // The bars are hidden from assistive technology: a placeholder read
    // aloud is a stutter of nothing.
    const bars = canvasElement.querySelectorAll(".ew-skeleton");
    await expect(bars.length).toBeGreaterThan(0);
    for (const bar of bars) {
      await expect(bar.getAttribute("aria-hidden")).toBe("true");
    }
  }
}`,...b.parameters?.docs?.source}}},x.parameters={...x.parameters,docs:{...x.parameters?.docs,source:{originalSource:`{
  render: () => <WorkbenchShell rail={RAIL} railMode="expanded" railCollapsed={false}>
      <div className="flex h-full flex-col">
        <header className="border-b border-border-subtle px-6 py-4">
          <h1 className="truncate text-ui-xl font-semibold tracking-tight text-ink">
            Retrieval-augmented verification
          </h1>
          {/*
            The meta line comes from the dictionary's own composer rather
            than from a typed string: "3 turns" is exactly the shape
            \`turnCount\` exists to get right, and a stand-in that hand-types
            it is a stand-in that can drift from the thing it stands in for.
           */}
          <p className="mt-05 text-ui-xs text-ink-muted">
            {turnCount(3)} · 12 Mar 2026, 09:41
          </p>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <p className="max-w-measure text-report-body text-ink">
            The briefing arrives into the track the placeholder lines held
            open, so the reading position does not move when it does.
          </p>
        </div>
      </div>
    </WorkbenchShell>
}`,...x.parameters?.docs?.source},description:{story:"The arrived thread, at the geometry the skeleton reserved. The header's\npadding, its two line boxes and its bottom rule are the ones\n`ThreadSkeleton`'s header holds open; the transcript fills the same\n`min-h-0 flex-1` track the placeholder lines filled.",...x.parameters?.docs?.description}}},S.parameters={...S.parameters,docs:{...S.parameters?.docs,source:{originalSource:`{
  globals: {
    viewport: {
      value: "w412"
    }
  },
  render: () => <WorkbenchShell rail={RAIL} railMode="drawer">
      <ThreadSkeleton />
    </WorkbenchShell>
}`,...S.parameters?.docs?.source},description:{story:`Below 768px, where the rail is absent from the layout entirely.`,...S.parameters?.docs?.description}}},C=[`Loading`,`Loaded`,`Narrow`]})))()}w();export{x as Loaded,b as Loading,S as Narrow,C as __namedExportsOrder,y as default};