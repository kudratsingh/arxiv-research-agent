import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{o as n,t as r}from"./threads-iAeM6bq3.js";import{i,n as a,r as o}from"./WorkbenchShell-DwuILiWd.js";import{n as s,t as c}from"./NotFound-B3v0gbJx.js";var l,u,d,f,p,m,h,g;function _(){return(_=e((()=>{l=t(),s(),n(),i(),{expect:u,within:d}=__STORYBOOK_MODULE_TEST__,f=(0,l.jsx)(`ul`,{className:`flex flex-col gap-1 p-3`,children:[`Retrieval-augmented verification`,`Sparse attention survey`].map((e,t)=>(0,l.jsx)(`li`,{children:(0,l.jsx)(`a`,{href:`/c/thread-${t+1}`,className:`ew-focusable block truncate rounded-md px-3 py-2 text-ui-sm text-ink hover:bg-sunken`,children:e})},e))}),p={title:`Shell/NotFoundProduct`,component:c,parameters:{nextjs:{appDirectory:!0}},render:e=>(0,l.jsx)(o,{rail:f,railMode:`expanded`,railCollapsed:!1,children:(0,l.jsx)(c,{...e})}),args:{heading:r.notFoundHeading,body:r.notFoundBody,actionLabel:r.notFoundBackToStart,actionHref:`/`,secondaryLabel:r.notFoundBackToList,secondaryHref:`#${a}`}},m={play:async({canvasElement:e})=>{let t=d(e),n=t.getByRole(`heading`,{level:1,name:r.notFoundHeading});await u(n).toBeInTheDocument();let i=t.getByText(r.notFoundBody);await u(i).toHaveTextContent(/never have existed/i),await u(i).toHaveTextContent(/another principal/i),await u(i.textContent??``).not.toMatch(/deleted/i),await u(i.textContent??``).not.toMatch(/no permission/i),await u(t.getByRole(`link`,{name:r.notFoundBackToStart})).toHaveAttribute(`href`,`/`),await u(t.getByRole(`link`,{name:r.notFoundBackToList})).toHaveAttribute(`href`,`#${a}`)}},h={globals:{viewport:{value:`w412`}},args:{secondaryLabel:void 0,secondaryHref:void 0},render:e=>(0,l.jsx)(o,{rail:f,railMode:`drawer`,children:(0,l.jsx)(c,{...e})})},m.parameters={...m.parameters,docs:{...m.parameters?.docs,source:{originalSource:`{
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);

    // Criterion 2: the heading the baseline does not have.
    const heading = canvas.getByRole("heading", {
      level: 1,
      name: THREAD.notFoundHeading
    });
    await expect(heading).toBeInTheDocument();

    // Criterion 3, on the rendered text rather than on the constant.
    const body = canvas.getByText(THREAD.notFoundBody);
    await expect(body).toHaveTextContent(/never have existed/i);
    await expect(body).toHaveTextContent(/another principal/i);
    await expect(body.textContent ?? "").not.toMatch(/deleted/i);
    await expect(body.textContent ?? "").not.toMatch(/no permission/i);

    // Two routes out, at two different destinations.
    await expect(canvas.getByRole("link", {
      name: THREAD.notFoundBackToStart
    })).toHaveAttribute("href", "/");
    await expect(canvas.getByRole("link", {
      name: THREAD.notFoundBackToList
    })).toHaveAttribute("href", \`#\${RAIL_ID}\`);
  }
}`,...m.parameters?.docs?.source}}},h.parameters={...h.parameters,docs:{...h.parameters?.docs,source:{originalSource:`{
  globals: {
    viewport: {
      value: "w412"
    }
  },
  args: {
    secondaryLabel: undefined,
    secondaryHref: undefined
  },
  render: args => <WorkbenchShell rail={RAIL} railMode="drawer">
      <NotFound {...args} />
    </WorkbenchShell>
}`,...h.parameters?.docs?.source},description:{story:`The same state with only the primary way out — what a surface renders
below 768px, where the rail is absent from the layout and an in-page link
to it would point at nothing.`,...h.parameters?.docs?.description}}},g=[`Default`,`WithoutTheRail`]})))()}_();export{m as Default,h as WithoutTheRail,g as __namedExportsOrder,p as default};