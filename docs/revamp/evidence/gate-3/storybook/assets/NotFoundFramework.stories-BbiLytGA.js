import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{n,r}from"./recovery-Cnc_dh1b.js";import{i,r as a}from"./WorkbenchShell-DwuILiWd.js";import{n as o,t as s}from"./NotFound-B3v0gbJx.js";var c,l,u,d,f,p,m,h;function g(){return(g=e((()=>{c=t(),o(),r(),i(),{expect:l,within:u}=__STORYBOOK_MODULE_TEST__,d=(0,c.jsx)(`ul`,{className:`flex flex-col gap-1 p-3`,children:[`Retrieval-augmented verification`,`Sparse attention survey`].map((e,t)=>(0,c.jsx)(`li`,{children:(0,c.jsx)(`a`,{href:`/c/thread-${t+1}`,className:`ew-focusable block truncate rounded-md px-3 py-2 text-ui-sm text-ink hover:bg-sunken`,children:e})},e))}),f={title:`Shell/NotFoundFramework`,component:s,parameters:{nextjs:{appDirectory:!0}},render:e=>(0,c.jsx)(a,{rail:d,railMode:`expanded`,railCollapsed:!1,children:(0,c.jsx)(s,{...e})}),args:{heading:n.notFoundHeading,body:n.notFoundBody,actionLabel:n.notFoundAction,actionHref:`/`}},p={play:async({canvasElement:e})=>{let t=u(e);await l(t.getByRole(`heading`,{level:1,name:n.notFoundHeading})).toBeInTheDocument(),await l(t.getByRole(`navigation`,{name:`Threads`})).toBeInTheDocument();let r=t.getByRole(`link`,{name:n.notFoundAction});await l(r).toHaveAttribute(`href`,`/`)}},m={globals:{viewport:{value:`w412`}},render:e=>(0,c.jsx)(a,{rail:d,railMode:`drawer`,children:(0,c.jsx)(s,{...e})})},p.parameters={...p.parameters,docs:{...p.parameters?.docs,source:{originalSource:`{
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);

    // The \`h1\` the framework default does not give the product. (Next's own
    // 404 has an \`h1\` reading "404"; what it has no version of is a heading
    // that says what happened, in a document with landmarks.)
    await expect(canvas.getByRole("heading", {
      level: 1,
      name: ROUTE_ERROR.notFoundHeading
    })).toBeInTheDocument();

    // The rail, intact — the whole difference from the baseline screenshot.
    await expect(canvas.getByRole("navigation", {
      name: "Threads"
    })).toBeInTheDocument();
    const action = canvas.getByRole("link", {
      name: ROUTE_ERROR.notFoundAction
    });
    await expect(action).toHaveAttribute("href", "/");
  }
}`,...p.parameters?.docs?.source},description:{story:'Criterion 1, as a rendered assertion: a real `h1`, the rail still there,\nand "Start a new question" as the primary action.',...p.parameters?.docs?.description}}},m.parameters={...m.parameters,docs:{...m.parameters?.docs,source:{originalSource:`{
  globals: {
    viewport: {
      value: "w412"
    }
  },
  render: args => <WorkbenchShell rail={RAIL} railMode="drawer">
      <NotFound {...args} />
    </WorkbenchShell>
}`,...m.parameters?.docs?.source},description:{story:`Below 768px the rail is not rendered at all (WO-08's structural repair),
so this is the state where "the rail intact" is not available and the
primary action carries the whole recovery. It is still one \`h1\` and still
inside \`<main>\`.`,...m.parameters?.docs?.description}}},h=[`Default`,`Narrow`]})))()}g();export{p as Default,m as Narrow,h as __namedExportsOrder,f as default};