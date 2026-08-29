import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{n,r,t as i}from"./MetricsStrip-Dvc9K9Yr.js";var a,o,s,c,l,u,d,f,p,m,h;function g(){return(g=e((()=>{a=t(),n(),o=r({iterations:2,quality_score:.86,cost_usd:.42,llm_calls:11,elapsed_sec:60}),s=r({iterations:1,quality_score:null,cost_usd:.18,llm_calls:4,elapsed_sec:36}),c=r({}),l={title:`Patterns/MetricsStrip`,component:i,args:{metrics:o},render:e=>(0,a.jsx)(`div`,{className:`max-w-2xl p-6`,children:(0,a.jsx)(i,{...e})})},u={args:{metrics:o}},d={args:{metrics:c}},f={args:{metrics:s}},p={args:{metrics:s},globals:{theme:`dark`}},m={args:{metrics:s},globals:{theme:`forced-colors`}},u.parameters={...u.parameters,docs:{...u.parameters?.docs,source:{originalSource:`{
  args: {
    metrics: SUCCEEDED
  }
}`,...u.parameters?.docs?.source},description:{story:`The five real fields, mono numerals, no dash and therefore no legend.`,...u.parameters?.docs?.description}}},d.parameters={...d.parameters,docs:{...d.parameters?.docs,source:{originalSource:`{
  args: {
    metrics: NONE
  }
}`,...d.parameters?.docs?.source},description:{story:`Criterion 2 at full strength: five em dashes and one visible explanation.
The rows stay — a strip that hid its missing fields would let the reader
think the run reported four numbers instead of none.`,...d.parameters?.docs?.description}}},f.parameters={...f.parameters,docs:{...f.parameters?.docs,source:{originalSource:`{
  args: {
    metrics: PARTIAL
  }
}`,...f.parameters?.docs?.source},description:{story:`03 §2.2 row 14's numbers: one field missing, four paid for.`,...f.parameters?.docs?.description}}},p.parameters={...p.parameters,docs:{...p.parameters?.docs,source:{originalSource:`{
  args: {
    metrics: PARTIAL
  },
  globals: {
    theme: "dark"
  }
}`,...p.parameters?.docs?.source},description:{story:`03 §2.2 row 8 — the same strip on the dark token set.`,...p.parameters?.docs?.description}}},m.parameters={...m.parameters,docs:{...m.parameters?.docs,source:{originalSource:`{
  args: {
    metrics: PARTIAL
  },
  globals: {
    theme: "forced-colors"
  }
}`,...m.parameters?.docs?.source},description:{story:`The dash survives without colour. \`--color-ink-muted\` is the only thing
separating a missing number from a present one visually, and 03 §3.4 says
colour may never be the sole carrier — here it is not, because the word
"dash" is spelled out in the legend and "not reported" is in the
accessibility tree.`,...m.parameters?.docs?.description}}},h=[`AllPresent`,`AllNull`,`PartialFailureMetrics`,`Dark`,`ForcedColours`]})))()}g();export{d as AllNull,u as AllPresent,p as Dark,m as ForcedColours,f as PartialFailureMetrics,h as __namedExportsOrder,l as default};