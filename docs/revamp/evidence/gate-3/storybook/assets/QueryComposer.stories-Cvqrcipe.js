import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./react-Z7gd5LxR.js";import{t as n}from"./jsx-runtime-CadfrxEJ.js";import{n as r,r as i,t as a}from"./VisuallyHidden-BvZkhsza.js";import{n as o,t as s}from"./Button-DQWqKqVB.js";import{c,s as l}from"./errors-Ch6TWljv.js";import{n as ee,r as u,t as d}from"./StatusBanner-DHqsKSvA.js";import{n as f,t as p}from"./Textarea-CW6YHoQX.js";function m(e){return String(Math.trunc(Math.abs(e))).replace(/\B(?=(\d{3})+(?!\d))/g,`,`)}function h(e){return`${m(e)} / ${m(_)}`}function g(e){let t=Math.max(0,Math.trunc(e)-_);return`${m(t)} character${t===1?``:`s`} over the limit. Shorten the question to send it.`}var _,v,y;function b(){return(b=e((()=>{_=8e3,v={eyebrow:`Evidence Workbench`,heading:`What should the literature settle?`,questionLabel:`Research question`,questionPlaceholder:`e.g. How do current systems evaluate faithfulness in retrieval-augmented generation?`,disclosure:`Generating a plan starts a billable run. You review and edit the plan before any arXiv search or paper reading happens.`,submit:`Generate plan`,submitPending:`Generating plan…`,process:[`Question`,`Plan you approve`,`arXiv run`,`Briefing`]},y={followUpLabel:`Follow-up question`,followUpPlaceholder:`e.g. Which of those findings are contested, and what is the strongest case against them?`,emptyQuestion:`Type a question first. Nothing is sent until you do.`,counterLabel:`Question length:`,retained:`The question is still in the box.`,noAutoRetry:`Nothing was sent again on its own — asking again starts a new billable run.`,orphanSentence:`An empty thread was created before this failed.`,orphanAction:`Open the empty thread`,processLabel:`What happens after you ask`,regionLabel:`Ask a research question`}})))()}function x({variant:e=`landing`,value:t,defaultValue:n=``,onValueChange:i,onSubmit:o,pending:c=!1,unreachable:u=null,failure:f=null,orphanThreadHref:m=null,autoFocus:b=!1,className:x}){let w=(0,C.useId)(),T=`${w}-disclosure`,E=`${w}-reason`,[D,O]=(0,C.useState)(n),k=t===void 0?D:t,A=k.length,j=A>_,M=!j&&A>=7200,N=k.trim()===``,P=e===`landing`,F=u===null?j?g(A):N?y.emptyQuestion:null:l(u).sentence,I=u!==null,L=c||F!==null,R=(0,C.useRef)(!1),z=(0,C.useCallback)(()=>{if(R.current||c||u!==null)return;let e=k.trim();e===``||e.length>8e3||(R.current=!0,Promise.resolve(o(e)).finally(()=>{R.current=!1}))},[o,c,k,u]),B=(0,C.useCallback)(e=>{e.preventDefault(),z()},[z]),V=(0,C.useCallback)(e=>{(e.metaKey||e.ctrlKey)&&e.key===`Enter`&&(e.preventDefault(),z())},[z]),H=f===null?null:l(f);return(0,S.jsxs)(`form`,{noValidate:!0,onSubmit:B,"aria-label":y.regionLabel,"data-variant":e,className:[`flex w-full max-w-content flex-col`,P?`gap-6`:`gap-4`,x].filter(Boolean).join(` `),children:[P?(0,S.jsxs)(`header`,{className:`flex flex-col gap-2`,children:[(0,S.jsx)(`p`,{className:`text-ui-xs font-medium uppercase tracking-wide text-ink-muted`,children:v.eyebrow}),(0,S.jsx)(`h1`,{className:`text-balance text-display text-ink`,children:v.heading})]}):null,(0,S.jsx)(p,{label:P?v.questionLabel:y.followUpLabel,placeholder:P?v.questionPlaceholder:y.followUpPlaceholder,rows:P?4:3,value:k,autoFocus:b,onChange:e=>{t===void 0&&O(e.target.value),i?.(e.target.value)},onKeyDown:V,error:j?g(A):void 0,hint:(0,S.jsxs)(S.Fragment,{children:[(0,S.jsx)(r,{children:y.counterLabel}),(0,S.jsx)(`span`,{"data-counter":j?`over`:M?`near`:`within`,className:j?`tabular-nums text-critical-text`:M?`tabular-nums text-review-text`:`tabular-nums`,children:h(A)})]})}),(0,S.jsxs)(`div`,{className:`flex flex-col gap-3`,children:[(0,S.jsx)(`p`,{id:T,className:`text-balance text-ui-sm text-ink-muted`,children:v.disclosure}),(0,S.jsx)(s,{type:`submit`,variant:`primary`,size:`lg`,busy:c,"aria-disabled":L?!0:void 0,"aria-describedby":F===null?T:`${T} ${E}`,className:`self-start`,children:c?v.submitPending:v.submit}),F===null?null:(0,S.jsx)(`p`,{id:E,className:I?`text-ui-sm text-critical-text`:a,children:F})]}),H===null?null:(0,S.jsxs)(ee,{severity:H.severity,word:H.word,sentence:H.sentence,recovery:H.recovery,userTriggered:d.includes(H.severity),actions:m===null?void 0:(0,S.jsx)(`a`,{href:m,className:`text-ui-sm font-medium text-ink underline underline-offset-4`,children:y.orphanAction}),children:[(0,S.jsx)(`p`,{className:`text-ui-sm text-ink-muted`,children:y.retained}),(0,S.jsx)(`p`,{className:`text-ui-sm text-ink-muted`,children:y.noAutoRetry}),m===null?null:(0,S.jsx)(`p`,{className:`text-ui-sm text-ink-muted`,children:y.orphanSentence})]}),P?(0,S.jsx)(`ol`,{"aria-label":y.processLabel,className:`flex flex-wrap items-center gap-x-3 gap-y-1 text-ui-xs text-ink-muted`,children:v.process.map((e,t)=>(0,S.jsxs)(`li`,{className:`flex items-center gap-3`,children:[t===0?null:(0,S.jsx)(`span`,{"aria-hidden":`true`,className:`text-ink-faint`,children:`·`}),e]},e))}):null]})}var S,C,w;function T(){return(T=e((()=>{S=n(),C=t(),u(),o(),f(),i(),b(),c(),w=.9,x.__docgenInfo={description:``,methods:[],displayName:`QueryComposer`,props:{variant:{required:!1,tsType:{name:`union`,raw:`"landing" | "follow-up"`,elements:[{name:`literal`,value:`"landing"`},{name:`literal`,value:`"follow-up"`}]},description:`Defaults to the landing surface.`,defaultValue:{value:`"landing"`,computed:!1}},value:{required:!1,tsType:{name:`string`},description:`Controlled value. Omit for an uncontrolled field.`},defaultValue:{required:!1,tsType:{name:`string`},description:`Initial value of an uncontrolled field.`,defaultValue:{value:`""`,computed:!1}},onValueChange:{required:!1,tsType:{name:`signature`,type:`function`,raw:`(value: string) => void`,signature:{arguments:[{type:{name:`string`},name:`value`}],return:{name:`void`}}},description:``},onSubmit:{required:!0,tsType:{name:`signature`,type:`function`,raw:`(query: string) => void | Promise<void>`,signature:{arguments:[{type:{name:`string`},name:`query`}],return:{name:`union`,raw:`void | Promise<void>`,elements:[{name:`void`},{name:`Promise`,elements:[{name:`void`}],raw:`Promise<void>`}]}}},description:`The ONLY way a question leaves this component.

Called with the trimmed question. A returned promise is what the
duplicate-submit guard waits on, so an async caller — every real one —
gets the guard for the whole flight rather than for one tick.`},pending:{required:!1,tsType:{name:`boolean`},description:`A submission is in flight. Renders 03 §1.4's pending label.`,defaultValue:{value:`false`,computed:!1}},unreachable:{required:!1,tsType:{name:`union`,raw:`ApiFailure | null`,elements:[{name:`ApiFailure`},{name:`null`}]},description:`The research service is known to be unreachable (03 §2.2 row 4).
Refuses submit and attaches \`describeFailure()\`'s sentence as the
reason. Note this is NOT the same thing as \`failure\`: this one became
true on its own and is ordinary content, that one is something the
user just did and is announced.`,defaultValue:{value:`null`,computed:!1}},failure:{required:!1,tsType:{name:`union`,raw:`ApiFailure | null`,elements:[{name:`ApiFailure`},{name:`null`}]},description:`The submission that failed (03 §2.2 row 17). The question is kept.`,defaultValue:{value:`null`,computed:!1}},orphanThreadHref:{required:!1,tsType:{name:`union`,raw:`string | null`,elements:[{name:`string`},{name:`null`}]},description:`H7: where the thread that was created before the submission failed
lives. \`null\` when no thread was created, which is the ordinary case
for a follow-up.`,defaultValue:{value:`null`,computed:!1}},autoFocus:{required:!1,tsType:{name:`boolean`},description:``,defaultValue:{value:`false`,computed:!1}},className:{required:!1,tsType:{name:`string`},description:``}}}})))()}var E,D,O,k,A,j,M,N,P,F,I,L,R,z,B,V,H,U,W,G,K,q,J,Y,X,Z,Q;function $(){return($=e((()=>{E=n(),b(),T(),D=`How do current systems evaluate faithfulness in retrieval-augmented generation, and which of those measures survive a change of retriever?`,O=D.repeat(Math.ceil(_*w/138)).slice(0,_-40),k=D.repeat(Math.ceil((_+200)/138)).slice(0,_+137),A={kind:`rate_limited`,status:429,retryAfterSec:900,limitPerHour:20,message:``,raw:{detail:{error:`rate_limited`,key_id:`shared`,limit_per_hour:20}}},j={kind:`unauthorized`,status:401,message:``,raw:{detail:`missing_api_key`}},M={kind:`upstream_unavailable`,status:502,message:``,raw:{detail:`api_upstream_unavailable`}},N={kind:`proxy_misconfigured`,status:503,message:``,raw:{detail:`api_proxy_misconfigured`}},P={kind:`validation`,status:422,fields:[{path:`query`,message:`String should have at most 8000 characters`}],message:``,raw:{detail:[]}},F={title:`Features/QueryComposer`,component:x,args:{variant:`landing`,onSubmit:()=>void 0},decorators:[e=>(0,E.jsx)(`div`,{className:`w-full max-w-content p-6`,children:(0,E.jsx)(e,{})})]},I={},L={args:{value:D}},R={args:{value:O}},z={args:{value:k}},B={args:{value:D,pending:!0}},V={args:{value:D,unreachable:M}},H={args:{value:D,failure:A}},U={args:{value:D,failure:j}},W={args:{value:D,failure:M}},G={args:{value:D,failure:N}},K={args:{value:D,failure:P}},q={args:{value:D,failure:A,orphanThreadHref:`/c/9f1c0d3e-0f3a-4f5f-9a1c-1b2c3d4e5f60`}},J={args:{variant:`follow-up`,value:D}},Y={args:{value:D},globals:{theme:`dark`}},X={args:{value:D,failure:A},globals:{theme:`forced-colors`}},Z={args:{value:D},globals:{viewport:{value:`w320`}}},I.parameters={...I.parameters,docs:{...I.parameters?.docs,source:{originalSource:`{}`,...I.parameters?.docs?.source},description:{story:`03 §2.2 row 1. The counter is visible at zero characters (criterion 2).`,...I.parameters?.docs?.description}}},L.parameters={...L.parameters,docs:{...L.parameters?.docs,source:{originalSource:`{
  args: {
    value: QUESTION
  }
}`,...L.parameters?.docs?.source}}},R.parameters={...R.parameters,docs:{...R.parameters?.docs,source:{originalSource:`{
  args: {
    value: NEAR
  }
}`,...R.parameters?.docs?.source},description:{story:`The counter warns before the bound, in the review hue.`,...R.parameters?.docs?.description}}},z.parameters={...z.parameters,docs:{...z.parameters?.docs,source:{originalSource:`{
  args: {
    value: OVER
  }
}`,...z.parameters?.docs?.source},description:{story:`Over 8,000. Submit is refused client-side, the counter is critical, the
field is \`aria-invalid\`, and the text is still all there — the primitive
refuses rather than truncating.`,...z.parameters?.docs?.description}}},B.parameters={...B.parameters,docs:{...B.parameters?.docs,source:{originalSource:`{
  args: {
    value: QUESTION,
    pending: true
  }
}`,...B.parameters?.docs?.source},description:{story:"`POST /research` is in flight: 03 §1.4's pending label, click refused.",...B.parameters?.docs?.description}}},V.parameters={...V.parameters,docs:{...V.parameters?.docs,source:{originalSource:`{
  args: {
    value: QUESTION,
    unreachable: UPSTREAM_DOWN
  }
}`,...V.parameters?.docs?.source},description:{story:"03 §2.2 row 4. Not a bare `disabled` button: `aria-disabled` keeps the\ncontrol focusable and `aria-describedby` carries the reason.",...V.parameters?.docs?.description}}},H.parameters={...H.parameters,docs:{...H.parameters?.docs,source:{originalSource:`{
  args: {
    value: QUESTION,
    failure: RATE_LIMITED
  }
}`,...H.parameters?.docs?.source}}},U.parameters={...U.parameters,docs:{...U.parameters?.docs,source:{originalSource:`{
  args: {
    value: QUESTION,
    failure: UNAUTHORIZED
  }
}`,...U.parameters?.docs?.source}}},W.parameters={...W.parameters,docs:{...W.parameters?.docs,source:{originalSource:`{
  args: {
    value: QUESTION,
    failure: UPSTREAM_DOWN
  }
}`,...W.parameters?.docs?.source}}},G.parameters={...G.parameters,docs:{...G.parameters?.docs,source:{originalSource:`{
  args: {
    value: QUESTION,
    failure: PROXY_MISCONFIGURED
  }
}`,...G.parameters?.docs?.source}}},K.parameters={...K.parameters,docs:{...K.parameters?.docs,source:{originalSource:`{
  args: {
    value: QUESTION,
    failure: VALIDATION
  }
}`,...K.parameters?.docs?.source},description:{story:`Row 20: the 422 mapped onto the question field rather than swallowed.`,...K.parameters?.docs?.description}}},q.parameters={...q.parameters,docs:{...q.parameters?.docs,source:{originalSource:`{
  args: {
    value: QUESTION,
    failure: RATE_LIMITED,
    orphanThreadHref: "/c/9f1c0d3e-0f3a-4f5f-9a1c-1b2c3d4e5f60"
  }
}`,...q.parameters?.docs?.source},description:{story:"H7. The thread was created before `POST /research` failed, so it exists,\nit is empty, and it is offered rather than left to be found.",...q.parameters?.docs?.description}}},J.parameters={...J.parameters,docs:{...J.parameters?.docs,source:{originalSource:`{
  args: {
    variant: "follow-up",
    value: QUESTION
  }
}`,...J.parameters?.docs?.source},description:{story:`03 §4.3's compact variant: no display heading, no process strip.`,...J.parameters?.docs?.description}}},Y.parameters={...Y.parameters,docs:{...Y.parameters?.docs,source:{originalSource:`{
  args: {
    value: QUESTION
  },
  globals: {
    theme: "dark"
  }
}`,...Y.parameters?.docs?.source}}},X.parameters={...X.parameters,docs:{...X.parameters?.docs,source:{originalSource:`{
  args: {
    value: QUESTION,
    failure: RATE_LIMITED
  },
  globals: {
    theme: "forced-colors"
  }
}`,...X.parameters?.docs?.source}}},Z.parameters={...Z.parameters,docs:{...Z.parameters?.docs,source:{originalSource:`{
  args: {
    value: QUESTION
  },
  globals: {
    viewport: {
      value: "w320"
    }
  }
}`,...Z.parameters?.docs?.source},description:{story:`RC-14's narrowest width: the disclosure stays above the button.`,...Z.parameters?.docs?.description}}},Q=[`Empty`,`Filled`,`NearLimit`,`OverLimit`,`Submitting`,`Unreachable`,`RateLimited`,`Unauthorized`,`UpstreamDown`,`ProxyMisconfigured`,`Validation`,`FailedWithOrphanThread`,`FollowUp`,`Dark`,`ForcedColours`,`Narrow`]})))()}$();export{Y as Dark,I as Empty,q as FailedWithOrphanThread,L as Filled,J as FollowUp,X as ForcedColours,Z as Narrow,R as NearLimit,z as OverLimit,G as ProxyMisconfigured,H as RateLimited,B as Submitting,U as Unauthorized,V as Unreachable,W as UpstreamDown,K as Validation,Q as __namedExportsOrder,F as default};