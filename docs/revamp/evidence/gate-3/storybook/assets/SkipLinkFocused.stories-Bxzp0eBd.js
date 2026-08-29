import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{n,r}from"./recovery-Cnc_dh1b.js";import{i,o as a}from"./threads-iAeM6bq3.js";import{i as o,r as s,t as c}from"./WorkbenchShell-DwuILiWd.js";import{n as l,t as u}from"./NotFound-B3v0gbJx.js";var d,f,p,m,h,g,_,v;function y(){return(y=e((()=>{d=t(),l(),r(),a(),o(),{expect:f,userEvent:p,within:m}=__STORYBOOK_MODULE_TEST__,h=(0,d.jsx)(`ul`,{className:`flex flex-col gap-1 p-3`,children:[`Retrieval-augmented verification`,`Sparse attention survey`].map((e,t)=>(0,d.jsx)(`li`,{children:(0,d.jsx)(`a`,{href:`/c/thread-${t+1}`,className:`ew-focusable block truncate rounded-md px-3 py-2 text-ui-sm text-ink hover:bg-sunken`,children:e})},e))}),g={title:`Shell/SkipLinkFocused`,parameters:{nextjs:{appDirectory:!0}}},_={render:()=>(0,d.jsx)(s,{rail:h,railMode:`expanded`,railCollapsed:!1,children:(0,d.jsx)(u,{heading:n.notFoundHeading,body:n.notFoundBody,actionLabel:n.notFoundAction,actionHref:`/`})}),play:async({canvasElement:e})=>{let t=m(e).getByRole(`link`,{name:i.skipToContent});await f(t).toHaveAttribute(`href`,`#${c}`),await p.tab(),await f(t).toHaveFocus();let r=e.querySelectorAll(`main`);await f(r).toHaveLength(1),await f(r[0]?.id).toBe(c),await f(m(r[0]).getByRole(`heading`,{level:1,name:n.notFoundHeading})).toBeInTheDocument()}},_.parameters={..._.parameters,docs:{..._.parameters?.docs,source:{originalSource:`{
  render: () => <WorkbenchShell rail={RAIL} railMode="expanded" railCollapsed={false}>
      <NotFound heading={ROUTE_ERROR.notFoundHeading} body={ROUTE_ERROR.notFoundBody} actionLabel={ROUTE_ERROR.notFoundAction} actionHref="/" />
    </WorkbenchShell>,
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    const skip = canvas.getByRole("link", {
      name: WORKSPACE.skipToContent
    });
    await expect(skip).toHaveAttribute("href", \`#\${MAIN_ID}\`);

    // First in the DOM, and therefore first in the tab order without a
    // \`tabindex\` anywhere (WO-08 criterion 10).
    await userEvent.tab();
    await expect(skip).toHaveFocus();

    // And the thing it skips to is real, and singular.
    const mains = canvasElement.querySelectorAll("main");
    await expect(mains).toHaveLength(1);
    await expect(mains[0]?.id).toBe(MAIN_ID);

    // The recovery surface's own heading is inside that landmark, which is
    // what makes "skip to content" true on a 404 rather than merely
    // present.
    await expect(within(mains[0] as HTMLElement).getByRole("heading", {
      level: 1,
      name: ROUTE_ERROR.notFoundHeading
    })).toBeInTheDocument();
  }
}`,..._.parameters?.docs?.source}}},v=[`Focused`]})))()}y();export{_ as Focused,v as __namedExportsOrder,g as default};