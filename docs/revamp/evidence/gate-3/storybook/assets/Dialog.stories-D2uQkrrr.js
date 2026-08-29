import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{n,t as r}from"./Button-DQWqKqVB.js";import{n as i,r as a,t as o}from"./Dialog-Cg5BMiD7.js";var s,c,l,u,d,f,p,m,h,g,_;function v(){return(v=e((()=>{s=t(),n(),a(),c={title:`Primitives/Dialog`,component:o,args:{title:`Delete this thread?`}},l=(0,s.jsxs)(s.Fragment,{children:[(0,s.jsx)(i,{asChild:!0,children:(0,s.jsx)(r,{variant:`secondary`,children:`Keep thread`})}),(0,s.jsx)(i,{asChild:!0,children:(0,s.jsx)(r,{variant:`critical`,children:`Delete thread`})})]}),u={args:{trigger:(0,s.jsx)(r,{variant:`critical`,children:`Delete thread`}),description:`The thread, its jobs and its reports are removed. This cannot be undone.`,footer:l}},d={args:{defaultOpen:!0,description:`The thread, its jobs and its reports are removed. This cannot be undone.`,footer:l}},f={args:{defaultOpen:!0,tone:`critical`,description:`The thread, its jobs and its reports are removed. This cannot be undone.`,footer:l}},p={args:{defaultOpen:!0,title:`Export unavailable`,children:`There is no report to export yet. Run the query first.`}},m={args:{...d.args},globals:{theme:`dark`}},h={args:{...d.args},globals:{theme:`forced-colors`}},g={args:{...d.args},globals:{motion:`reduce`}},u.parameters={...u.parameters,docs:{...u.parameters?.docs,source:{originalSource:`{
  args: {
    trigger: <Button variant="critical">Delete thread</Button>,
    description: "The thread, its jobs and its reports are removed. This cannot be undone.",
    footer: CONFIRM_FOOTER
  }
}`,...u.parameters?.docs?.source},description:{story:`The only story with a trigger: closed, so nothing is aria-hidden.`,...u.parameters?.docs?.description}}},d.parameters={...d.parameters,docs:{...d.parameters?.docs,source:{originalSource:`{
  args: {
    defaultOpen: true,
    description: "The thread, its jobs and its reports are removed. This cannot be undone.",
    footer: CONFIRM_FOOTER
  }
}`,...d.parameters?.docs?.source}}},f.parameters={...f.parameters,docs:{...f.parameters?.docs,source:{originalSource:`{
  args: {
    defaultOpen: true,
    tone: "critical",
    description: "The thread, its jobs and its reports are removed. This cannot be undone.",
    footer: CONFIRM_FOOTER
  }
}`,...f.parameters?.docs?.source},description:{story:'`tone="critical"` tints the title; the words still carry the meaning.',...f.parameters?.docs?.description}}},p.parameters={...p.parameters,docs:{...p.parameters?.docs,source:{originalSource:`{
  args: {
    defaultOpen: true,
    title: "Export unavailable",
    children: "There is no report to export yet. Run the query first."
  }
}`,...p.parameters?.docs?.source},description:{story:"No description: Radix's `aria-describedby` is cleared rather than dangling.",...p.parameters?.docs?.description}}},m.parameters={...m.parameters,docs:{...m.parameters?.docs,source:{originalSource:`{
  args: {
    ...Open.args
  },
  globals: {
    theme: "dark"
  }
}`,...m.parameters?.docs?.source}}},h.parameters={...h.parameters,docs:{...h.parameters?.docs,source:{originalSource:`{
  args: {
    ...Open.args
  },
  globals: {
    theme: "forced-colors"
  }
}`,...h.parameters?.docs?.source}}},g.parameters={...g.parameters,docs:{...g.parameters?.docs,source:{originalSource:`{
  args: {
    ...Open.args
  },
  globals: {
    motion: "reduce"
  }
}`,...g.parameters?.docs?.source},description:{story:"The `ew-enter` fade is removed outright; the dialog is simply there.",...g.parameters?.docs?.description}}},_=[`Closed`,`Open`,`CriticalTone`,`TitleOnly`,`Dark`,`ForcedColours`,`ReducedMotion`]})))()}v();export{u as Closed,f as CriticalTone,m as Dark,h as ForcedColours,d as Open,g as ReducedMotion,p as TitleOnly,_ as __namedExportsOrder,c as default};