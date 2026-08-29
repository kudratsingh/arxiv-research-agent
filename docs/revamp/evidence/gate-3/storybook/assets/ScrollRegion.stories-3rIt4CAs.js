import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{r as n,t as r}from"./VisuallyHidden-BvZkhsza.js";import{n as i,t as a}from"./ScrollRegion-C-eDDIXG.js";function o(){return(0,c.jsxs)(`table`,{className:`w-max border-collapse text-ui-sm`,children:[(0,c.jsx)(`caption`,{className:r,children:`Retrieval metrics by sub-question`}),(0,c.jsx)(`thead`,{children:(0,c.jsx)(`tr`,{children:u.map(e=>(0,c.jsx)(`th`,{scope:`col`,className:`whitespace-nowrap border border-border-subtle bg-sunken px-3 py-2 text-left font-semibold text-ink`,children:e},e))})}),(0,c.jsx)(`tbody`,{children:d.map(e=>(0,c.jsx)(`tr`,{children:e.map((t,n)=>(0,c.jsx)(`td`,{className:`whitespace-nowrap border border-border-subtle px-3 py-2 text-ink`,children:t},`${e[0]}-${u[n]}`))},e[0]))})]})}function s({heading:e,children:t}){return(0,c.jsxs)(`section`,{className:`flex flex-col gap-3`,children:[(0,c.jsx)(`h2`,{className:`text-ui-xs font-semibold uppercase text-ink-muted`,children:e}),t]})}var c,l,u,d,f,p,m,h,g,_,v,y,b;function x(){return(x=e((()=>{c=t(),i(),n(),l={title:`Primitives/ScrollRegion`,component:a,args:{label:`Retrieval metrics table, scrollable`,children:(0,c.jsx)(o,{})}},u=[`Sub-question`,`Papers found`,`Papers used`,`Faithfulness`,`Coverage`,`Latency (s)`,`Tokens in`,`Tokens out`],d=[[`Sparse attention scaling`,`18`,`6`,`0.92`,`0.81`,`42.1`,`18,204`,`2,910`],[`Kernel fusion on commodity GPUs`,`11`,`4`,`0.88`,`0.74`,`31.7`,`12,880`,`2,140`],[`Long-context evaluation sets`,`23`,`7`,`0.95`,`0.90`,`55.4`,`24,610`,`3,502`]],f={args:{children:(0,c.jsx)(o,{})}},p={args:{label:`Run summary, scrollable`,children:(0,c.jsx)(`p`,{className:`text-ui-sm text-ink`,children:`Nothing here overflows.`})}},m={args:{axis:`both`,label:`Diagnostics frames, scrollable`,className:`max-h-40`,children:(0,c.jsx)(o,{})}},h=()=>(0,c.jsxs)(`div`,{className:`flex flex-col gap-6 p-6`,children:[(0,c.jsx)(s,{heading:`A table wider than the page — the table pans, the page does not`,children:(0,c.jsx)(a,{label:`Retrieval metrics table, scrollable`,children:(0,c.jsx)(o,{})})}),(0,c.jsx)(s,{heading:`Content that fits — still a named, focusable region`,children:(0,c.jsx)(a,{label:`Run summary, scrollable`,children:(0,c.jsx)(`p`,{className:`text-ui-sm text-ink`,children:`Nothing here overflows.`})})}),(0,c.jsx)(s,{heading:`Both axes, for a diagnostics pane taller than its box`,children:(0,c.jsx)(a,{axis:`both`,label:`Diagnostics frames, scrollable`,className:`max-h-40`,children:(0,c.jsx)(o,{})})})]}),g={render:h},_={render:h,globals:{theme:`dark`}},v={render:h,globals:{theme:`forced-colors`}},y={render:h,globals:{motion:`reduce`}},f.parameters={...f.parameters,docs:{...f.parameters?.docs,source:{originalSource:`{
  args: {
    children: <Table />
  }
}`,...f.parameters?.docs?.source}}},p.parameters={...p.parameters,docs:{...p.parameters?.docs,source:{originalSource:`{
  args: {
    label: "Run summary, scrollable",
    children: <p className="text-ui-sm text-ink">Nothing here overflows.</p>
  }
}`,...p.parameters?.docs?.source}}},m.parameters={...m.parameters,docs:{...m.parameters?.docs,source:{originalSource:`{
  args: {
    axis: "both",
    label: "Diagnostics frames, scrollable",
    className: "max-h-40",
    children: <Table />
  }
}`,...m.parameters?.docs?.source}}},g.parameters={...g.parameters,docs:{...g.parameters?.docs,source:{originalSource:`{
  render: AllStatesRender
}`,...g.parameters?.docs?.source}}},_.parameters={..._.parameters,docs:{..._.parameters?.docs,source:{originalSource:`{
  render: AllStatesRender,
  globals: {
    theme: "dark"
  }
}`,..._.parameters?.docs?.source}}},v.parameters={...v.parameters,docs:{...v.parameters?.docs,source:{originalSource:`{
  render: AllStatesRender,
  globals: {
    theme: "forced-colors"
  }
}`,...v.parameters?.docs?.source}}},y.parameters={...y.parameters,docs:{...y.parameters?.docs,source:{originalSource:`{
  render: AllStatesRender,
  globals: {
    motion: "reduce"
  }
}`,...y.parameters?.docs?.source}}},b=[`WideTable`,`NarrowContent`,`BothAxes`,`AllStates`,`Dark`,`ForcedColours`,`ReducedMotion`]})))()}x();export{g as AllStates,m as BothAxes,_ as Dark,v as ForcedColours,p as NarrowContent,y as ReducedMotion,f as WideTable,b as __namedExportsOrder,l as default};