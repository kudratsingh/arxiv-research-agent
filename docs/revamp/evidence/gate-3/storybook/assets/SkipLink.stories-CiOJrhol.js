import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{n,t as r}from"./SkipLink-B98brSJA.js";function i({targetId:e=`main`,label:t}){return(0,a.jsxs)(`div`,{className:`flex flex-col gap-4 p-6`,children:[(0,a.jsx)(r,{targetId:e,children:t}),(0,a.jsx)(`header`,{className:`rounded-md border border-border-subtle bg-surface p-4 text-ui-sm text-ink`,children:`Header — the skip link comes before this in the tab order.`}),(0,a.jsxs)(`main`,{id:e,className:`rounded-md border border-border-subtle bg-surface p-4`,children:[(0,a.jsx)(`h2`,{className:`text-ui-lg font-semibold text-ink`,children:`Main`}),(0,a.jsxs)(`p`,{className:`text-ui-sm text-ink-muted`,children:[`The link points here. In the product this is WO-08’s single`,(0,a.jsx)(`code`,{className:`font-mono`,children:` <main id="main">`}),`.`]})]})]})}var a,o,s,c,l,u,d,f,p,m;function h(){return(h=e((()=>{a=t(),n(),{expect:o}=__STORYBOOK_MODULE_TEST__,s={title:`Primitives/SkipLink`,component:r},c={render:()=>(0,a.jsx)(i,{})},l={render:()=>(0,a.jsx)(i,{}),play:async({canvasElement:e})=>{let t=e.querySelector(`a`);t?.focus(),await o(t).toHaveFocus()}},u={render:()=>(0,a.jsx)(i,{targetId:`report`,label:`Skip to the report`})},d={render:()=>(0,a.jsx)(i,{}),globals:{theme:`dark`}},f={render:()=>(0,a.jsx)(i,{}),globals:{theme:`forced-colors`}},p={render:()=>(0,a.jsx)(i,{}),globals:{motion:`reduce`}},c.parameters={...c.parameters,docs:{...c.parameters?.docs,source:{originalSource:`{
  render: () => <Page />
}`,...c.parameters?.docs?.source},description:{story:`Clipped, which is what it looks like almost all of the time.`,...c.parameters?.docs?.description}}},l.parameters={...l.parameters,docs:{...l.parameters?.docs,source:{originalSource:`{
  render: () => <Page />,
  play: async ({
    canvasElement
  }) => {
    const link = canvasElement.querySelector("a");
    link?.focus();
    await expect(link).toHaveFocus();
  }
}`,...l.parameters?.docs?.source}}},u.parameters={...u.parameters,docs:{...u.parameters?.docs,source:{originalSource:`{
  render: () => <Page targetId="report" label="Skip to the report" />
}`,...u.parameters?.docs?.source},description:{story:"A route whose main region is named something else. The target really\nexists in the story, because axe's `skip-link` rule checks that it does.",...u.parameters?.docs?.description}}},d.parameters={...d.parameters,docs:{...d.parameters?.docs,source:{originalSource:`{
  render: () => <Page />,
  globals: {
    theme: "dark"
  }
}`,...d.parameters?.docs?.source}}},f.parameters={...f.parameters,docs:{...f.parameters?.docs,source:{originalSource:`{
  render: () => <Page />,
  globals: {
    theme: "forced-colors"
  }
}`,...f.parameters?.docs?.source}}},p.parameters={...p.parameters,docs:{...p.parameters?.docs,source:{originalSource:`{
  render: () => <Page />,
  globals: {
    motion: "reduce"
  }
}`,...p.parameters?.docs?.source}}},m=[`Default`,`Focused`,`CustomTarget`,`Dark`,`ForcedColours`,`ReducedMotion`]})))()}h();export{u as CustomTarget,d as Dark,c as Default,l as Focused,f as ForcedColours,p as ReducedMotion,m as __namedExportsOrder,s as default};