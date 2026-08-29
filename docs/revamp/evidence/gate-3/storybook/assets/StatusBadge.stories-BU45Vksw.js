import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{n,r}from"./marks-CQxAYwh1.js";import{n as i,r as a}from"./StatusBadge-BZocO7mF.js";function o({heading:e,children:t}){return(0,s.jsxs)(`section`,{className:`flex flex-col gap-3`,children:[(0,s.jsx)(`h2`,{className:`text-ui-xs font-semibold uppercase text-ink-muted`,children:e}),(0,s.jsx)(`div`,{className:`flex flex-wrap items-center gap-4`,children:t})]})}var s,c,l,u,d,f,p,m,h,g,_,v,y,b;function x(){return(x=e((()=>{s=t(),r(),a(),c={title:`Primitives/StatusBadge`,component:i,args:{severity:`live`,children:`Live`}},l={args:{severity:`info`,children:`Queued`}},u={args:{severity:`review`,children:`Waiting for your review`}},d={args:{severity:`live`,children:`Live`,ambient:!0}},f={args:{severity:`warning`,children:`Partial metrics`}},p={args:{severity:`critical`,children:`Failed`}},m=[{severity:`live`,word:`observed`,mark:`circle`},{severity:`live`,word:`Live`,mark:`ring`},{severity:`info`,word:`not observed`,mark:`dashed-rule`},{severity:`review`,word:`Waiting for your review`,mark:`diamond`},{severity:`live`,word:`Complete`,mark:`square`},{severity:`critical`,word:`Failed`,mark:`slashed-square`},{severity:`info`,word:`Cancelled`,mark:`hollow-square`},{severity:`info`,word:`No longer available`,mark:`dashed-square`}],h=()=>(0,s.jsxs)(`div`,{className:`flex flex-col gap-6 p-6`,children:[(0,s.jsxs)(o,{heading:`Five severities, quiet`,children:[(0,s.jsx)(i,{severity:`info`,children:`Queued`}),(0,s.jsx)(i,{severity:`review`,children:`Waiting for your review`}),(0,s.jsx)(i,{severity:`live`,ambient:!0,children:`Live`}),(0,s.jsx)(i,{severity:`warning`,children:`Partial metrics`}),(0,s.jsx)(i,{severity:`critical`,children:`Failed`})]}),(0,s.jsxs)(o,{heading:`Five severities, on a surface`,children:[(0,s.jsx)(i,{severity:`info`,emphasis:`surface`,children:`Queued`}),(0,s.jsx)(i,{severity:`review`,emphasis:`surface`,children:`Waiting for your review`}),(0,s.jsx)(i,{severity:`live`,emphasis:`surface`,children:`Live`}),(0,s.jsx)(i,{severity:`warning`,emphasis:`surface`,children:`Partial metrics`}),(0,s.jsx)(i,{severity:`critical`,emphasis:`surface`,children:`Failed`})]}),(0,s.jsx)(o,{heading:`The run states of 03 §3.4 — eight words, eight shapes`,children:m.map(e=>(0,s.jsx)(i,{severity:e.severity,mark:e.mark,children:e.word},e.word))}),(0,s.jsx)(o,{heading:`Every mark in the set`,children:n.map(e=>(0,s.jsx)(i,{severity:`info`,mark:e,children:e},e))})]}),g={render:h},_={render:h,globals:{theme:`dark`}},v={render:h,globals:{theme:`forced-colors`}},y={render:h,globals:{motion:`reduce`}},l.parameters={...l.parameters,docs:{...l.parameters?.docs,source:{originalSource:`{
  args: {
    severity: "info",
    children: "Queued"
  }
}`,...l.parameters?.docs?.source}}},u.parameters={...u.parameters,docs:{...u.parameters?.docs,source:{originalSource:`{
  args: {
    severity: "review",
    children: "Waiting for your review"
  }
}`,...u.parameters?.docs?.source}}},d.parameters={...d.parameters,docs:{...d.parameters?.docs,source:{originalSource:`{
  args: {
    severity: "live",
    children: "Live",
    ambient: true
  }
}`,...d.parameters?.docs?.source}}},f.parameters={...f.parameters,docs:{...f.parameters?.docs,source:{originalSource:`{
  args: {
    severity: "warning",
    children: "Partial metrics"
  }
}`,...f.parameters?.docs?.source}}},p.parameters={...p.parameters,docs:{...p.parameters?.docs,source:{originalSource:`{
  args: {
    severity: "critical",
    children: "Failed"
  }
}`,...p.parameters?.docs?.source}}},g.parameters={...g.parameters,docs:{...g.parameters?.docs,source:{originalSource:`{
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
}`,...v.parameters?.docs?.source},description:{story:`The evidence for criterion 7: the same matrix with the hue removed.`,...v.parameters?.docs?.description}}},y.parameters={...y.parameters,docs:{...y.parameters?.docs,source:{originalSource:`{
  render: AllStatesRender,
  globals: {
    motion: "reduce"
  }
}`,...y.parameters?.docs?.source},description:{story:`The ambient pulse stops; the word "Live" does not move.`,...y.parameters?.docs?.description}}},b=[`Info`,`Review`,`Live`,`Warning`,`Critical`,`AllStates`,`Dark`,`ForcedColours`,`ReducedMotion`]})))()}x();export{g as AllStates,p as Critical,_ as Dark,v as ForcedColours,l as Info,d as Live,y as ReducedMotion,u as Review,f as Warning,b as __namedExportsOrder,c as default};