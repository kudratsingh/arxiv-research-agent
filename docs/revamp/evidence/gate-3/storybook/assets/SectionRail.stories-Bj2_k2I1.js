import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{a as n,n as r,r as i,t as a}from"./SectionRail-DMEDKcS9.js";var o,s,c,l,u,d,f,p,m,h,g,_,v;function y(){return(y=e((()=>{o=t(),n(),r(),s=[{id:`what-the-field-measures`,text:`What the field measures`,level:2},{id:`where-the-disagreement-is`,text:`Where the disagreement is`,level:2},{id:`limits`,text:`Limits`,level:2}],c=[{id:`what-the-field-measures`,text:`What the field measures`,level:2},{id:`automatic-metrics`,text:`Automatic metrics`,level:3},{id:`human-protocols`,text:`Human protocols`,level:3},{id:`where-the-disagreement-is`,text:`Where the disagreement is`,level:2},{id:`unsupported-but-correct`,text:`Unsupported but correct`,level:3},{id:`supported-but-wrong`,text:`Supported but wrong`,level:3},{id:`limits`,text:`Limits`,level:2}],l=Array.from({length:18},(e,t)=>{let n=t+1;return{id:`section-${n}`,text:`${c[t%c.length]?.text??`Section`} ${n}`,level:t%3==0?2:3}}),u={title:`Patterns/SectionRail`,component:a,args:{headings:s,label:i.railLabel},render:e=>(0,o.jsx)(`div`,{className:`p-6`,children:(0,o.jsx)(a,{...e})})},d={args:{headings:[]}},f={args:{headings:s}},p={args:{headings:c}},m={args:{headings:l},render:e=>(0,o.jsxs)(`div`,{className:`flex gap-8 p-6`,children:[(0,o.jsx)(a,{...e}),(0,o.jsx)(`div`,{className:`h-[160vh] flex-1 rounded-md border border-border-subtle bg-sunken`})]})},h={args:{headings:c,activeId:`human-protocols`}},g={args:{headings:c,activeId:`human-protocols`},globals:{theme:`dark`}},_={args:{headings:c,activeId:`human-protocols`},globals:{theme:`forced-colors`}},d.parameters={...d.parameters,docs:{...d.parameters?.docs,source:{originalSource:`{
  args: {
    headings: []
  }
}`,...d.parameters?.docs?.source},description:{story:`Criterion 4: a heading-free report leaves the rail absent, not shelled.`,...d.parameters?.docs?.description}}},f.parameters={...f.parameters,docs:{...f.parameters?.docs,source:{originalSource:`{
  args: {
    headings: SHORT
  }
}`,...f.parameters?.docs?.source}}},p.parameters={...p.parameters,docs:{...p.parameters?.docs,source:{originalSource:`{
  args: {
    headings: DEEP
  }
}`,...p.parameters?.docs?.source},description:{story:"`h3` entries indent under the `h2` they follow; the tag is the depth.",...p.parameters?.docs?.description}}},m.parameters={...m.parameters,docs:{...m.parameters?.docs,source:{originalSource:`{
  args: {
    headings: LONG
  },
  render: args => <div className="flex gap-8 p-6">
      <SectionRail {...args} />
      <div className="h-[160vh] flex-1 rounded-md border border-border-subtle bg-sunken" />
    </div>
}`,...m.parameters?.docs?.source},description:{story:`The sticky state. The rail pins itself at 1280px and up (03 §7.5), so the
frame below is tall enough to scroll and the viewport toolbar's 1440
option is where the behaviour is visible.`,...m.parameters?.docs?.description}}},h.parameters={...h.parameters,docs:{...h.parameters?.docs,source:{originalSource:`{
  args: {
    headings: DEEP,
    activeId: "human-protocols"
  }
}`,...h.parameters?.docs?.source},description:{story:'`aria-current="location"`, plus a rule and full-strength ink (03 §3.4).',...h.parameters?.docs?.description}}},g.parameters={...g.parameters,docs:{...g.parameters?.docs,source:{originalSource:`{
  args: {
    headings: DEEP,
    activeId: "human-protocols"
  },
  globals: {
    theme: "dark"
  }
}`,...g.parameters?.docs?.source}}},_.parameters={..._.parameters,docs:{..._.parameters?.docs,source:{originalSource:`{
  args: {
    headings: DEEP,
    activeId: "human-protocols"
  },
  globals: {
    theme: "forced-colors"
  }
}`,..._.parameters?.docs?.source},description:{story:`The current section survives without its hue: the rule and weight carry it.`,..._.parameters?.docs?.description}}},v=[`Absent`,`ShortList`,`DeepNesting`,`LongSticky`,`ActiveHeading`,`Dark`,`ForcedColours`]})))()}y();export{d as Absent,h as ActiveHeading,g as Dark,p as DeepNesting,_ as ForcedColours,m as LongSticky,f as ShortList,v as __namedExportsOrder,u as default};