import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./react-Z7gd5LxR.js";import{t as n}from"./jsx-runtime-CadfrxEJ.js";import"./primitives-C6B3pA6y.js";import{n as r,r as i}from"./VisuallyHidden-BvZkhsza.js";import{a,i as o,n as s,r as c}from"./styles-B5dROzMd.js";import{r as l,t as u}from"./marks-CQxAYwh1.js";function d({label:e,labelHidden:t=!1,hint:n,error:i,size:o=`md`,id:l,className:d,required:m,...h}){let g=(0,p.useId)(),_=l??`${g}-input`,v=`${g}-hint`,y=`${g}-error`,b=[n?v:null,i?y:null].filter(Boolean).join(` `)||void 0;return(0,f.jsxs)(`div`,{className:c(`flex flex-col gap-1`,d),children:[(0,f.jsxs)(`label`,{htmlFor:_,className:c(`text-ui-sm font-medium text-ink`,t&&`ew-visually-hidden`),children:[e,m?(0,f.jsx)(`span`,{className:`text-ink-muted`,children:` (required)`}):null]}),(0,f.jsx)(`input`,{...h,id:_,required:m,"aria-invalid":i?!0:void 0,"aria-describedby":b,className:c(`w-full rounded-md border bg-surface px-3 text-ui-base text-ink`,`transition-colors duration-fast ease-standard`,`placeholder:text-ink-faint disabled:cursor-not-allowed disabled:bg-sunken disabled:text-ink-disabled`,s,a(o),i?`border-critical`:`border-border-strong`)}),n?(0,f.jsx)(`p`,{id:v,className:`text-ui-xs text-ink-muted`,children:n}):null,i?(0,f.jsxs)(`p`,{id:y,className:`flex items-center gap-1 text-ui-xs text-critical-text`,children:[(0,f.jsx)(u,{mark:`slashed-square`}),(0,f.jsx)(r,{children:`Error:`}),i]}):null]})}var f,p;function m(){return(m=e((()=>{f=n(),p=t(),l(),o(),i(),d.__docgenInfo={description:``,methods:[],displayName:`Field`,props:{label:{required:!0,tsType:{name:`ReactNode`},description:`Required. A placeholder is not a label.`},labelHidden:{required:!1,tsType:{name:`boolean`},description:`Clip the label rather than drop it — the control stays named.`,defaultValue:{value:`false`,computed:!1}},hint:{required:!1,tsType:{name:`ReactNode`},description:``},error:{required:!1,tsType:{name:`ReactNode`},description:`Truthy switches the control into its invalid presentation.`},size:{required:!1,tsType:{name:`unknown[number]`,raw:`(typeof CONTROL_SIZES)[number]`},description:``,defaultValue:{value:`"md"`,computed:!1}},id:{required:!1,tsType:{name:`string`},description:``}},composes:[`Omit`]}})))()}function h({heading:e,children:t}){return(0,g.jsxs)(`section`,{className:`flex max-w-measure flex-col gap-3`,children:[(0,g.jsx)(`h2`,{className:`text-ui-xs font-semibold uppercase text-ink-muted`,children:e}),t]})}var g,_,v,y,b,x,S,C,w,T,E,D,O,k;function A(){return(A=e((()=>{g=n(),m(),_={title:`Primitives/Field`,component:d,args:{label:`Thread title`,placeholder:`Attention mechanisms`}},v={},y={args:{hint:`Shown in the thread rail. 80 characters or fewer.`}},b={args:{required:!0}},x={args:{defaultValue:``,error:`Enter a title before saving.`,hint:`Shown in the thread rail.`}},S={args:{disabled:!0,defaultValue:`Retrieval-augmented generation`}},C={args:{labelHidden:!0,label:`Search threads`,type:`search`,placeholder:`Search threads`}},w=()=>(0,g.jsxs)(`div`,{className:`flex flex-col gap-6 p-6`,children:[(0,g.jsx)(h,{heading:`Default`,children:(0,g.jsx)(d,{label:`Thread title`,placeholder:`Attention mechanisms`})}),(0,g.jsx)(h,{heading:`With a hint, and required`,children:(0,g.jsx)(d,{label:`Thread title`,required:!0,hint:`Shown in the thread rail. 80 characters or fewer.`})}),(0,g.jsx)(h,{heading:`Invalid — mark, then colour, with the word in the message`,children:(0,g.jsx)(d,{label:`Thread title`,error:`Enter a title before saving.`,hint:`Shown in the thread rail.`})}),(0,g.jsx)(h,{heading:`Disabled`,children:(0,g.jsx)(d,{label:`Job id`,disabled:!0,defaultValue:`job_01HX8Z4N2R`})}),(0,g.jsx)(h,{heading:`Clipped label — the control keeps its name`,children:(0,g.jsx)(d,{label:`Search threads`,labelHidden:!0,type:`search`,placeholder:`Search threads`})}),(0,g.jsxs)(h,{heading:`Control heights — 32 / 40 / 44px`,children:[(0,g.jsx)(d,{label:`Small`,size:`sm`}),(0,g.jsx)(d,{label:`Medium`,size:`md`}),(0,g.jsx)(d,{label:`Large`,size:`lg`})]})]}),T={render:w},E={render:w,globals:{theme:`dark`}},D={render:w,globals:{theme:`forced-colors`}},O={render:w,globals:{motion:`reduce`}},v.parameters={...v.parameters,docs:{...v.parameters?.docs,source:{originalSource:`{}`,...v.parameters?.docs?.source}}},y.parameters={...y.parameters,docs:{...y.parameters?.docs,source:{originalSource:`{
  args: {
    hint: "Shown in the thread rail. 80 characters or fewer."
  }
}`,...y.parameters?.docs?.source}}},b.parameters={...b.parameters,docs:{...b.parameters?.docs,source:{originalSource:`{
  args: {
    required: true
  }
}`,...b.parameters?.docs?.source}}},x.parameters={...x.parameters,docs:{...x.parameters?.docs,source:{originalSource:`{
  args: {
    defaultValue: "",
    error: "Enter a title before saving.",
    hint: "Shown in the thread rail."
  }
}`,...x.parameters?.docs?.source}}},S.parameters={...S.parameters,docs:{...S.parameters?.docs,source:{originalSource:`{
  args: {
    disabled: true,
    defaultValue: "Retrieval-augmented generation"
  }
}`,...S.parameters?.docs?.source}}},C.parameters={...C.parameters,docs:{...C.parameters?.docs,source:{originalSource:`{
  args: {
    labelHidden: true,
    label: "Search threads",
    type: "search",
    placeholder: "Search threads"
  }
}`,...C.parameters?.docs?.source}}},T.parameters={...T.parameters,docs:{...T.parameters?.docs,source:{originalSource:`{
  render: AllStatesRender
}`,...T.parameters?.docs?.source}}},E.parameters={...E.parameters,docs:{...E.parameters?.docs,source:{originalSource:`{
  render: AllStatesRender,
  globals: {
    theme: "dark"
  }
}`,...E.parameters?.docs?.source}}},D.parameters={...D.parameters,docs:{...D.parameters?.docs,source:{originalSource:`{
  render: AllStatesRender,
  globals: {
    theme: "forced-colors"
  }
}`,...D.parameters?.docs?.source}}},O.parameters={...O.parameters,docs:{...O.parameters?.docs,source:{originalSource:`{
  render: AllStatesRender,
  globals: {
    motion: "reduce"
  }
}`,...O.parameters?.docs?.source}}},k=[`Default`,`WithHint`,`Required`,`Invalid`,`Disabled`,`LabelHidden`,`AllStates`,`Dark`,`ForcedColours`,`ReducedMotion`]})))()}A();export{T as AllStates,E as Dark,v as Default,S as Disabled,D as ForcedColours,x as Invalid,C as LabelHidden,O as ReducedMotion,b as Required,y as WithHint,k as __namedExportsOrder,_ as default};