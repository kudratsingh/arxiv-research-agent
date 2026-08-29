import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{_ as n,c as r,d as i,f as a,g as o,l as s,m as c,p as l,s as u,u as d}from"./tokens-BmyTjNhk.js";import"./primitives-C6B3pA6y.js";import{n as f,r as p,t as m}from"./recovery-Cnc_dh1b.js";import{i as h,r as g}from"./WorkbenchShell-DwuILiWd.js";var _;function v(){return(v=e((()=>{_={documentTitle:`The workbench could not be drawn`,heading:`The workbench could not be drawn`,body:`The failure reached above the whole workbench, so its frame — the header, the thread rail, the theme control — is not on this screen. Reloading this address is the only recovery from here.`,detail:`Nothing the research service already accepted is affected. This page never held the work itself.`,action:`Reload this page`,referenceLabel:`Reference`}})))()}function y({digest:e,onReload:t}){return(0,b.jsx)(`div`,{style:x,"data-recovery-surface":`global-error`,children:(0,b.jsxs)(`main`,{style:S,children:[(0,b.jsx)(`h1`,{style:C,children:_.heading}),(0,b.jsx)(`p`,{style:w,children:_.body}),(0,b.jsx)(`p`,{style:T,children:_.detail}),e===void 0||e===``?null:(0,b.jsxs)(`p`,{style:E,"data-error-digest":``,children:[_.referenceLabel,`: `,e]}),(0,b.jsx)(`button`,{type:`button`,style:D,onClick:t,children:_.action})]})})}var b,x,S,C,w,T,E,D;function O(){return(O=e((()=>{b=t(),v(),x={colorScheme:`light dark`,background:`Canvas`,color:`CanvasText`,minHeight:`100vh`,boxSizing:`border-box`,padding:`48px 24px`,fontSize:`16px`,lineHeight:1.5},S={margin:`0 auto`,maxWidth:`60ch`,display:`flex`,flexDirection:`column`,gap:`16px`,alignItems:`flex-start`},C={margin:0,fontSize:`24px`,lineHeight:1.25,fontWeight:600},w={margin:0},T={margin:0},E={margin:0,fontSize:`14px`,wordBreak:`break-all`},D={background:`ButtonFace`,color:`ButtonText`,border:`1px solid ButtonBorder`,borderRadius:`6px`,minHeight:`44px`,padding:`0 16px`,font:`inherit`,fontWeight:500,cursor:`pointer`},y.__docgenInfo={description:``,methods:[],displayName:`GlobalErrorSurface`,props:{digest:{required:!1,tsType:{name:`string`},description:"`error.digest`, when the runtime produced one."},onReload:{required:!0,tsType:{name:`signature`,type:`function`,raw:`() => void`,signature:{arguments:[],return:{name:`void`}}},description:"Reloads the document. The boundary's own `reset()` cannot help here."}}}})))()}function k({heading:e,body:t,actionLabel:n,onReset:r,digest:i,digestLabel:a,digestRecovery:o,className:s}){return(0,A.jsxs)(`div`,{"data-recovery-surface":`route-error`,className:[`mx-auto flex h-full max-w-content flex-col justify-center gap-4 px-6 py-10`,s].filter(Boolean).join(` `),children:[(0,A.jsx)(`h1`,{className:`text-ui-xl font-semibold tracking-tight text-ink`,children:e}),(0,A.jsx)(`p`,{className:`max-w-measure text-balance text-ui-base text-ink-muted`,children:t}),i===void 0||i===``?null:(0,A.jsxs)(`div`,{className:`flex flex-col gap-1 rounded-md border border-border-subtle bg-sunken p-3`,children:[(0,A.jsxs)(`dl`,{className:`flex flex-wrap items-baseline gap-2`,children:[(0,A.jsx)(`dt`,{className:`font-mono text-mono-sm text-ink-muted`,children:a}),(0,A.jsx)(`dd`,{className:`break-all font-mono text-mono-sm text-ink`,"data-error-digest":``,children:i})]}),(0,A.jsx)(`p`,{className:`text-ui-xs text-ink-muted`,children:o})]}),(0,A.jsx)(`div`,{className:`mt-2 flex flex-wrap items-center gap-3`,children:(0,A.jsx)(`button`,{type:`button`,onClick:r,"data-route-error-reset":``,className:j,children:n})})]})}var A,j;function M(){return(M=e((()=>{A=t(),p(),j=`ew-focusable ew-target ew-target--md inline-flex items-center justify-center rounded-md border border-transparent bg-primary px-4 text-ui-base font-medium text-primary-on transition-colors duration-fast ease-standard hover:bg-primary-strong`,k.__docgenInfo={description:``,methods:[],displayName:`RouteError`,props:{heading:{required:!0,tsType:{name:`string`},description:"The `h1`. Criterion 2: every recovery surface renders exactly one."},body:{required:!0,tsType:{name:`string`},description:``},actionLabel:{required:!0,tsType:{name:`string`},description:"The `reset` control's label."},onReset:{required:!0,tsType:{name:`signature`,type:`function`,raw:`() => void`,signature:{arguments:[],return:{name:`void`}}},description:"Next's `reset()`. Re-renders the segment; sends nothing."},digest:{required:!1,tsType:{name:`string`},description:"`error.digest`, when the runtime produced one."},digestLabel:{required:!0,tsType:{name:`string`},description:`The digest row's label.`},digestRecovery:{required:!0,tsType:{name:`string`},description:`What the digest is for. Rendered only when there is a digest.`},className:{required:!1,tsType:{name:`string`},description:``}}}})))()}function N({children:e}){return(0,P.jsx)(g,{rail:R,railMode:`expanded`,railCollapsed:!1,children:e})}var P,F,I,L,R,z,B,V,H,U,W;function G(){return(G=e((()=>{P=t(),O(),M(),v(),p(),a(),h(),{expect:F,fn:I,within:L}=__STORYBOOK_MODULE_TEST__,R=(0,P.jsx)(`ul`,{className:`flex flex-col gap-1 p-3`,children:[`Retrieval-augmented verification`,`Sparse attention survey`].map((e,t)=>(0,P.jsx)(`li`,{children:(0,P.jsx)(`a`,{href:`/c/thread-${t+1}`,className:`ew-focusable block truncate rounded-md px-3 py-2 text-ui-sm text-ink hover:bg-sunken`,children:e})},e))}),z=Object.fromEntries([...new Set(Array.from(JSON.stringify([u,r,s,d,i,l,c,o,n]).matchAll(/--[a-z0-9-]+/g),e=>e[0]))].map(e=>[e,`initial`])),B={title:`Shell/ErrorBoundary`,parameters:{nextjs:{appDirectory:!0}}},V={render:()=>(0,P.jsx)(N,{children:(0,P.jsx)(k,{heading:f.errorHeading,body:f.errorBody,actionLabel:f.errorAction,onReset:I(),digestLabel:m.referenceLabel,digestRecovery:m.referenceRecovery})}),play:async({canvasElement:e})=>{let t=L(e);await F(t.getByRole(`heading`,{level:1,name:f.errorHeading})).toBeInTheDocument(),await F(t.getByRole(`navigation`,{name:`Threads`})).toBeInTheDocument(),await F(t.queryByText(m.referenceLabel)).toBeNull()}},H={render:()=>(0,P.jsx)(N,{children:(0,P.jsx)(k,{heading:m.threadErrorHeading,body:m.threadErrorBody,actionLabel:f.errorAction,onReset:I(),digest:`3f1c9ad0c2b74e6a`,digestLabel:m.referenceLabel,digestRecovery:m.referenceRecovery})}),play:async({canvasElement:e})=>{let t=L(e);await F(t.getByRole(`heading`,{level:1,name:m.threadErrorHeading})).toBeInTheDocument(),await F(t.getByText(`3f1c9ad0c2b74e6a`)).toBeInTheDocument(),await F(t.getByText(m.referenceLabel)).toBeInTheDocument()}},U={render:()=>(0,P.jsx)(`div`,{style:z,"data-tokens-unset":``,children:(0,P.jsx)(y,{digest:`3f1c9ad0c2b74e6a`,onReload:I()})}),play:async({canvasElement:e})=>{let t=L(e);await F(t.getByRole(`heading`,{level:1,name:_.heading})).toBeInTheDocument(),await F(t.getByRole(`button`,{name:_.action})).toBeInTheDocument();let n=e.querySelector(`[data-recovery-surface="global-error"]`);await F(n).not.toBeNull(),await F(n?.querySelectorAll(`[class]`).length).toBe(0),await F(n?.hasAttribute(`class`)).toBe(!1),await F(n?.getAttribute(`style`)??``).not.toBe(``)}},V.parameters={...V.parameters,docs:{...V.parameters?.docs,source:{originalSource:`{
  render: () => <InShell>
      <RouteError heading={ROUTE_ERROR.errorHeading} body={ROUTE_ERROR.errorBody} actionLabel={ROUTE_ERROR.errorAction} onReset={fn()} digestLabel={RECOVERY.referenceLabel} digestRecovery={RECOVERY.referenceRecovery} />
    </InShell>,
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", {
      level: 1,
      name: ROUTE_ERROR.errorHeading
    })).toBeInTheDocument();
    await expect(canvas.getByRole("navigation", {
      name: "Threads"
    })).toBeInTheDocument();
    // No digest was passed, so no evidence row is invented for it.
    await expect(canvas.queryByText(RECOVERY.referenceLabel)).toBeNull();
  }
}`,...V.parameters?.docs?.source},description:{story:"`app/(workspace)/error.tsx`: the shell is still there, and still works.",...V.parameters?.docs?.description}}},H.parameters={...H.parameters,docs:{...H.parameters?.docs,source:{originalSource:`{
  render: () => <InShell>
      <RouteError heading={RECOVERY.threadErrorHeading} body={RECOVERY.threadErrorBody} actionLabel={ROUTE_ERROR.errorAction} onReset={fn()} digest="3f1c9ad0c2b74e6a" digestLabel={RECOVERY.referenceLabel} digestRecovery={RECOVERY.referenceRecovery} />
    </InShell>,
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", {
      level: 1,
      name: RECOVERY.threadErrorHeading
    })).toBeInTheDocument();
    await expect(canvas.getByText("3f1c9ad0c2b74e6a")).toBeInTheDocument();
    await expect(canvas.getByText(RECOVERY.referenceLabel)).toBeInTheDocument();
  }
}`,...H.parameters?.docs?.source},description:{story:"`app/(workspace)/c/[id]/error.tsx`, with the server's correlation hash.\nThe digest is labelled, in mono, under the sentence — never the sentence.",...H.parameters?.docs?.description}}},U.parameters={...U.parameters,docs:{...U.parameters?.docs,source:{originalSource:`{
  render: () => <div style={TOKENS_UNSET} data-tokens-unset="">
      <GlobalErrorSurface digest="3f1c9ad0c2b74e6a" onReload={fn()} />
    </div>,
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", {
      level: 1,
      name: GLOBAL_ERROR.heading
    })).toBeInTheDocument();
    await expect(canvas.getByRole("button", {
      name: GLOBAL_ERROR.action
    })).toBeInTheDocument();
    const surface = canvasElement.querySelector<HTMLElement>('[data-recovery-surface="global-error"]');
    await expect(surface).not.toBeNull();

    // No class anywhere in the subtree: no Tailwind utility, therefore no
    // custom property, therefore nothing the missing token sheet could have
    // taken away.
    await expect(surface?.querySelectorAll("[class]").length).toBe(0);
    await expect(surface?.hasAttribute("class")).toBe(false);
    // It does style itself — with inline declarations only.
    await expect(surface?.getAttribute("style") ?? "").not.toBe("");
  }
}`,...U.parameters?.docs?.source},description:{story:"`app/global-error.tsx` — no shell, no stylesheet, no token.\n\nThe surface is built out of CSS system colours (`Canvas`, `CanvasText`,\n`ButtonFace`) and inline styles, so it renders the same whether or not\nthe token sheet loaded. The play function proves the load-bearing half of\nthat rather than asserting it: not one element in the subtree carries a\n`class`, which is the only way a Tailwind utility — and therefore a\n`var(--…)` — could get in.",...U.parameters?.docs?.description}}},W=[`Workspace`,`Thread`,`Global`]})))()}G();export{U as Global,H as Thread,V as Workspace,W as __namedExportsOrder,B as default};