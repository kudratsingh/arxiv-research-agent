import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{n,t as r}from"./Textarea-CW6YHoQX.js";function i({heading:e,children:t}){return(0,a.jsxs)(`section`,{className:`flex max-w-measure flex-col gap-3`,children:[(0,a.jsx)(`h2`,{className:`text-ui-xs font-semibold uppercase text-ink-muted`,children:e}),t]})}var a,o,s,c,l,u,d,f,p,m,h,g,_,v,y,b,x,S;function C(){return(C=e((()=>{a=t(),n(),o=60,s=`How do sparse attention kernels change long-context scaling?`,c=`${s} And what does that cost at inference time on commodity accelerators?`,l={title:`Primitives/Textarea`,component:r,args:{label:`Research question`,placeholder:`Ask a question about ML/AI papers`}},u={},d={args:{defaultValue:s}},f={args:{hint:`One question at a time gets the better plan.`}},p={args:{value:s,limit:o,readOnly:!0}},m={args:{value:c,limit:o,readOnly:!0}},h={args:{value:``,readOnly:!0,error:`Enter a question before submitting.`}},g={args:{disabled:!0,defaultValue:s}},_=()=>(0,a.jsxs)(`div`,{className:`flex flex-col gap-6 p-6`,children:[(0,a.jsx)(i,{heading:`Empty, with a hint`,children:(0,a.jsx)(r,{label:`Research question`,placeholder:`Ask a question about ML/AI papers`,hint:`One question at a time gets the better plan.`})}),(0,a.jsx)(i,{heading:`Within budget`,children:(0,a.jsx)(r,{label:`Research question`,value:s.slice(0,30),limit:o,readOnly:!0})}),(0,a.jsx)(i,{heading:`Near the limit — the counter warns before it refuses`,children:(0,a.jsx)(r,{label:`Research question`,value:s,limit:o,readOnly:!0})}),(0,a.jsx)(i,{heading:`Over the limit — stated, not truncated`,children:(0,a.jsx)(r,{label:`Research question`,value:c,limit:o,readOnly:!0})}),(0,a.jsx)(i,{heading:`Invalid`,children:(0,a.jsx)(r,{label:`Research question`,value:``,readOnly:!0,error:`Enter a question before submitting.`})}),(0,a.jsx)(i,{heading:`Disabled`,children:(0,a.jsx)(r,{label:`Research question`,disabled:!0,defaultValue:s})})]}),v={render:_},y={render:_,globals:{theme:`dark`}},b={render:_,globals:{theme:`forced-colors`}},x={render:_,globals:{motion:`reduce`}},u.parameters={...u.parameters,docs:{...u.parameters?.docs,source:{originalSource:`{}`,...u.parameters?.docs?.source}}},d.parameters={...d.parameters,docs:{...d.parameters?.docs,source:{originalSource:`{
  args: {
    defaultValue: NEAR
  }
}`,...d.parameters?.docs?.source}}},f.parameters={...f.parameters,docs:{...f.parameters?.docs,source:{originalSource:`{
  args: {
    hint: "One question at a time gets the better plan."
  }
}`,...f.parameters?.docs?.source}}},p.parameters={...p.parameters,docs:{...p.parameters?.docs,source:{originalSource:`{
  args: {
    value: NEAR,
    limit: LIMIT,
    readOnly: true
  }
}`,...p.parameters?.docs?.source}}},m.parameters={...m.parameters,docs:{...m.parameters?.docs,source:{originalSource:`{
  args: {
    value: OVER,
    limit: LIMIT,
    readOnly: true
  }
}`,...m.parameters?.docs?.source}}},h.parameters={...h.parameters,docs:{...h.parameters?.docs,source:{originalSource:`{
  args: {
    value: "",
    readOnly: true,
    error: "Enter a question before submitting."
  }
}`,...h.parameters?.docs?.source}}},g.parameters={...g.parameters,docs:{...g.parameters?.docs,source:{originalSource:`{
  args: {
    disabled: true,
    defaultValue: NEAR
  }
}`,...g.parameters?.docs?.source}}},v.parameters={...v.parameters,docs:{...v.parameters?.docs,source:{originalSource:`{
  render: AllStatesRender
}`,...v.parameters?.docs?.source}}},y.parameters={...y.parameters,docs:{...y.parameters?.docs,source:{originalSource:`{
  render: AllStatesRender,
  globals: {
    theme: "dark"
  }
}`,...y.parameters?.docs?.source}}},b.parameters={...b.parameters,docs:{...b.parameters?.docs,source:{originalSource:`{
  render: AllStatesRender,
  globals: {
    theme: "forced-colors"
  }
}`,...b.parameters?.docs?.source}}},x.parameters={...x.parameters,docs:{...x.parameters?.docs,source:{originalSource:`{
  render: AllStatesRender,
  globals: {
    motion: "reduce"
  }
}`,...x.parameters?.docs?.source}}},S=[`Empty`,`Filled`,`WithHint`,`NearLimit`,`OverLimit`,`Invalid`,`Disabled`,`AllStates`,`Dark`,`ForcedColours`,`ReducedMotion`]})))()}C();export{v as AllStates,y as Dark,g as Disabled,u as Empty,d as Filled,b as ForcedColours,h as Invalid,p as NearLimit,m as OverLimit,x as ReducedMotion,f as WithHint,S as __namedExportsOrder,l as default};