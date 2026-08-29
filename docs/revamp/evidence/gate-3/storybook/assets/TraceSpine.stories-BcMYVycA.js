import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{n,r}from"./VisuallyHidden-BvZkhsza.js";import{r as i,t as a}from"./marks-CQxAYwh1.js";import{n as ee,r as o}from"./StatusBadge-BZocO7mF.js";import{a as s,c as te,d as c,f as l,h as u,i as d,l as f,m as ne,n as re,o as ie,p as ae,s as oe,t as se,u as p}from"./CheckpointLedger-BSFDhLul.js";import{n as ce,t as le}from"./Disclosure-rpr3v1uS.js";function ue(e){return e===`succeeded`||e===`failed`||e===`cancelled`}function de(e){let{status:t,observation:n,plan:r}=e,i=n.checkpoints.length>0;return t===`submitting`?`submitting`:t===`unavailable`?`expired`:t===`cancelled`?`cancelled`:t===`succeeded`?i?`succeeded`:`historic`:t===`failed`?i?`failed_observed`:`failed_unobserved`:t===`pending_review`||r!==null&&!ue(t)?`awaiting_review`:n.connection===`recycled`?`recycled`:n.connection===`reconnecting`?`reconnecting`:i?`running_observed`:`rejoined`}function fe(e){return e===`observed`||e===`not-observed`}function pe(e,t){let n=h[e],r=t.observation.checkpoints.length>0;return l.map((e,t)=>{let i=n[t],a=t===g&&fe(i)?r?`observed`:`not-observed`:i;return{name:e,status:a,word:m[a]}})}function me(e,t){let n=t.observation.checkpoints,r=n[n.length-1]?.node??null;switch(e){case`submitting`:return f.submitting;case`awaiting_review`:return f.awaitingReview;case`running_observed`:return d.running;case`rejoined`:return t.status===null?d.notReportedYet:f.rejoined;case`reconnecting`:return f.reconnecting;case`recycled`:return f.recycled;case`succeeded`:return m.complete;case`historic`:return f.historic;case`failed_observed`:case`failed_unobserved`:return ne(r);case`cancelled`:return f.cancelled;case`expired`:return ae}}function he(e){let t=de(e),n=e.observation.checkpoints.length,r=_.has(t),i=me(t,e);return{id:t,segments:pe(t,e),ledger:e.observation.checkpoints,announcement:i,detail:r||n>0?oe(n,r?e.secondsSinceLastFrame:null):null,separator:s(i),live:e.observation.connection===`open`,current:e.observation.current}}var m,h,g,_;function v(){return(v=e((()=>{u(),ie(),m={observed:p.observed,live:p.live,"not-observed":p.notObserved,"awaiting-review":p.pendingReview,complete:p.succeeded,failed:p.failed,cancelled:p.cancelled,unavailable:p.expired},h={submitting:[`not-observed`,`not-observed`,`not-observed`,`not-observed`],awaiting_review:[`observed`,`awaiting-review`,`not-observed`,`not-observed`],running_observed:[`observed`,`not-observed`,`observed`,`not-observed`],rejoined:[`observed`,`not-observed`,`not-observed`,`not-observed`],reconnecting:[`observed`,`not-observed`,`observed`,`not-observed`],recycled:[`observed`,`not-observed`,`observed`,`not-observed`],succeeded:[`observed`,`not-observed`,`observed`,`complete`],historic:[`unavailable`,`unavailable`,`unavailable`,`complete`],failed_observed:[`observed`,`not-observed`,`observed`,`failed`],failed_unobserved:[`observed`,`not-observed`,`not-observed`,`failed`],cancelled:[`observed`,`cancelled`,`not-observed`,`not-observed`],expired:[`unavailable`,`unavailable`,`unavailable`,`unavailable`]},g=2,_=new Set([`running_observed`,`rejoined`,`reconnecting`,`recycled`])})))()}function y(...e){return e.filter(e=>!!e).join(` `)}function b({inputs:e,legend:t=`disclosure`,id:r=`trace-spine`,className:i}){let o=`${r}-label`,s=e===null?null:he(e),c=s?.segments??l.map(e=>({name:e,status:`not-observed`,word:m[`not-observed`]}));return(0,S.jsxs)(`section`,{id:r,"aria-labelledby":o,"data-spine-state":s?.id??`none`,"data-live":s?.live===!0?`true`:`false`,className:y(`flex flex-col gap-3`,i),children:[(0,S.jsx)(n,{as:`h2`,id:o,children:d.regionLabel}),(0,S.jsx)(`ol`,{className:`flex flex-wrap items-start gap-x-6 gap-y-3`,children:c.map((e,t)=>(0,S.jsxs)(`li`,{"data-segment":e.name,"data-status":e.status,className:y(`flex min-w-0 flex-col gap-1`,t===w&&`min-w-full flex-1 md:min-w-0`),children:[(0,S.jsxs)(`span`,{className:`flex items-center gap-2 text-ui-sm font-medium text-ink`,children:[(0,S.jsx)(a,{mark:C[e.status],className:ge[e.status]}),(0,S.jsx)(`span`,{"aria-hidden":`true`,children:e.name}),(0,S.jsx)(n,{children:te(e.name,e.word)})]}),(0,S.jsx)(`span`,{"aria-hidden":`true`,className:`text-ui-xs text-ink-muted`,children:e.word}),t===w?(0,S.jsxs)(`div`,{className:`ew-spine-run`,children:[s===null?null:(0,S.jsx)(se,{checkpoints:s.ledger,current:s.current,empty:`hidden`}),(0,S.jsx)(`span`,{"aria-hidden":`true`,"data-spine-part":`void`,"data-current":s?.current===!0?`true`:`false`,className:`ew-spine-void`}),e.status===`not-observed`?null:(0,S.jsx)(`span`,{className:`whitespace-nowrap text-ui-xs text-ink-faint`,children:d.voidWord})]}):null]},e.name))}),(0,S.jsx)(`p`,{className:`text-ui-xs text-ink-faint`,children:d.voidDescription}),s===null?null:(0,S.jsxs)(`p`,{className:`flex flex-wrap items-baseline gap-x-2 gap-y-1 text-ui-sm text-ink`,children:[(0,S.jsx)(`span`,{role:`status`,"data-spine-part":`announcement`,children:s.announcement}),s.detail===null?null:(0,S.jsxs)(`span`,{className:`text-ink-muted`,"data-spine-part":`detail`,children:[(0,S.jsx)(`span`,{"aria-hidden":`true`,children:s.separator}),s.detail]}),s.live?(0,S.jsx)(ee,{severity:`live`,ambient:!0,children:m.live}):null]}),t===`none`?null:t===`open`?(0,S.jsx)(x,{}):(0,S.jsx)(le,{label:d.legendLabel,children:(0,S.jsx)(x,{})})]})}function x(){return(0,S.jsx)(`ul`,{"data-spine-part":`legend`,className:`flex flex-wrap gap-x-6 gap-y-2`,children:c.map(e=>(0,S.jsxs)(`li`,{className:`flex items-center gap-2 text-ui-xs text-ink-muted`,children:[(0,S.jsx)(a,{mark:e.mark}),e.meaning]},e.mark))})}var S,C,ge,w;function T(){return(T=e((()=>{S=t(),o(),ce(),i(),r(),u(),ie(),v(),re(),C={observed:`circle`,live:`ring`,"not-observed":`dashed-rule`,"awaiting-review":`diamond`,complete:`square`,failed:`slashed-square`,cancelled:`hollow-square`,unavailable:`dashed-square`},ge={observed:`text-signature-text`,live:`text-signature-text`,"not-observed":`text-ink-faint`,"awaiting-review":`text-review-text`,complete:`text-signature-text`,failed:`text-critical-text`,cancelled:`text-ink-muted`,unavailable:`text-ink-faint`},w=2,b.__docgenInfo={description:``,methods:[],displayName:`TraceSpine`,props:{inputs:{required:!0,tsType:{name:`union`,raw:`SpineInputs | null`,elements:[{name:`SpineInputs`},{name:`null`}]},description:`03 §5.2's four inputs, or \`null\` when there is no run on screen at all.

\`null\` is not a thirteenth state — it is the absence of one. The spine
renders its four segment names inert and says nothing, which is the
same shape 03 §1.4's landing legend shows before a question is asked.`},legend:{required:!1,tsType:{name:`union`,raw:`"open" | "disclosure" | "none"`,elements:[{name:`literal`,value:`"open"`},{name:`literal`,value:`"disclosure"`},{name:`literal`,value:`"none"`}]},description:`03 §5.3: the legend is "rendered in the UI once per session and
available from a disclosure thereafter". The composing surface owns
that once-per-session decision (WO-20); this prop is how it says so.`,defaultValue:{value:`"disclosure"`,computed:!1}},id:{required:!1,tsType:{name:`string`},description:`Ids are derived from this so a page may hold more than one.`,defaultValue:{value:`"trace-spine"`,computed:!1}},className:{required:!1,tsType:{name:`string`},description:``}}}})))()}function E(e,t){return{node:e,observedAt:t,stateDelta:{}}}function D(e){return{status:null,observation:{checkpoints:[],connection:`closed`,current:!1},plan:null,secondsSinceLastFrame:null,...e}}var O,k,A,j,M,N,P,F,I,L,R,z,B,V,H,U,W,G,K,q,J,Y,X,Z,Q,$,_e;function ve(){return(ve=e((()=>{T(),O={title:`Patterns/TraceSpine`,component:b,parameters:{docs:{description:{component:`Insertion point (no code): per-checkpoint structured evidence would attach as a disclosure inside each ledger entry, behind a versioned backend contract. state_delta is an open scalar map with no schema, so nothing here reads it.`}}},args:{legend:`disclosure`}},k=[E(`planner`,1e3),E(`searcher`,2e3),E(`synthesizer`,3e3)],A=[E(`planner`,1e3)],j={sub_questions:[`Which faithfulness metrics are used for retrieval-augmented systems?`,`How are they validated against human judgement?`],search_queries:[`retrieval augmented generation faithfulness evaluation`]},M={submitting:D({status:`submitting`}),awaiting_review:D({status:`pending_review`,observation:{checkpoints:A,connection:`open`,current:!0},plan:j,secondsSinceLastFrame:4}),running_observed:D({status:`running`,observation:{checkpoints:k,connection:`open`,current:!0},secondsSinceLastFrame:41}),rejoined:D({status:`running`,observation:{checkpoints:[],connection:`open`,current:!1}}),reconnecting:D({status:`running`,observation:{checkpoints:k,connection:`reconnecting`,current:!1},secondsSinceLastFrame:12}),recycled:D({status:`running`,observation:{checkpoints:A,connection:`recycled`,current:!1},secondsSinceLastFrame:60}),succeeded:D({status:`succeeded`,observation:{checkpoints:k,connection:`closed`,current:!1}}),historic:D({status:`succeeded`}),failed_observed:D({status:`failed`,observation:{checkpoints:k,connection:`closed`,current:!1}}),failed_unobserved:D({status:`failed`}),cancelled:D({status:`cancelled`}),expired:D({status:`unavailable`})},N=D({observation:{checkpoints:[],connection:`open`,current:!1}}),P={args:{inputs:null}},F={args:{inputs:N}},I={args:{inputs:M.rejoined}},L={args:{inputs:M.running_observed}},R={args:{inputs:M.reconnecting}},z={args:{inputs:M.recycled}},B={args:{inputs:M.awaiting_review}},V={args:{inputs:D({status:`running`,observation:{checkpoints:A,connection:`open`,current:!0},plan:j,secondsSinceLastFrame:1})}},H={args:{inputs:M.succeeded}},U={args:{inputs:M.historic}},W={args:{inputs:M.failed_unobserved}},G={args:{inputs:M.failed_observed}},K={args:{inputs:M.cancelled}},q={args:{inputs:M.expired}},J={args:{inputs:M.submitting}},Y={args:{inputs:M.running_observed,legend:`open`}},X={args:{inputs:M.running_observed},globals:{theme:`dark`}},Z={args:{inputs:M.failed_observed,legend:`open`},globals:{theme:`forced-colors`}},Q={args:{inputs:M.running_observed},globals:{motion:`reduce`}},$={args:{inputs:M.running_observed},globals:{viewport:{value:`w320`}}},P.parameters={...P.parameters,docs:{...P.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: null
  }
}`,...P.parameters?.docs?.source},description:{story:`No run on screen at all. The shape, and no claim about anything.`,...P.parameters?.docs?.description}}},F.parameters={...F.parameters,docs:{...F.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATUS_NOT_REPORTED
  }
}`,...F.parameters?.docs?.source},description:{story:`§4 state C. "Its status is not reported yet" — never "unknown".`,...F.parameters?.docs?.description}}},I.parameters={...I.parameters,docs:{...I.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.rejoined
  }
}`,...I.parameters?.docs?.source},description:{story:`§2.2 row 12: rejoined after a reload. The run segment is fully dashed.`,...I.parameters?.docs?.description}}},L.parameters={...L.parameters,docs:{...L.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.running_observed
  }
}`,...L.parameters?.docs?.source},description:{story:`§2.2 row 10. Three ticks, then the void, then the sentence about it.`,...L.parameters?.docs?.description}}},R.parameters={...R.parameters,docs:{...R.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.reconnecting
  }
}`,...R.parameters?.docs?.source},description:{story:`§2.2 row 11. Ticks kept; the rule breaks; the ambient pulse stops.`,...R.parameters?.docs?.description}}},z.parameters={...z.parameters,docs:{...z.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.recycled
  }
}`,...z.parameters?.docs?.source},description:{story:`§2.2 row 25. The server recycled the stream; the run did not stop.`,...z.parameters?.docs?.description}}},B.parameters={...B.parameters,docs:{...B.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.awaiting_review
  }
}`,...B.parameters?.docs?.source},description:{story:`§2.2 row 9. The pause, and the one sentence that describes it.`,...B.parameters?.docs?.description}}},V.parameters={...V.parameters,docs:{...V.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: inputs({
      status: "running",
      observation: {
        checkpoints: ONE,
        connection: "open",
        current: true
      },
      plan: PLAN,
      secondsSinceLastFrame: 1
    })
  }
}`,...V.parameters?.docs?.source},description:{story:`The same pause, one poll earlier.

\`plan_ready\` arrives over SSE before the liveness poll has re-read the
status, so the job detail still says \`running\` while a plan is already in
hand. Input 3 is non-null only during the review pause
(\`schemas.py:98-124\`), which makes it as good an authority for the pause
as the status is — and it is the authority that arrives first.`,...V.parameters?.docs?.description}}},H.parameters={...H.parameters,docs:{...H.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.succeeded
  }
}`,...H.parameters?.docs?.source},description:{story:`Watched to the end: the ledger is what this connection saw.`,...H.parameters?.docs?.description}}},U.parameters={...U.parameters,docs:{...U.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.historic
  }
}`,...U.parameters?.docs?.source},description:{story:"D-010: `job.plan = None` is permanent, so history keeps no lineage.",...U.parameters?.docs?.description}}},W.parameters={...W.parameters,docs:{...W.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.failed_unobserved
  }
}`,...W.parameters?.docs?.source},description:{story:`§2.2 row 15, with nothing observed: "Failed." and no attribution.`,...W.parameters?.docs?.description}}},G.parameters={...G.parameters,docs:{...G.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.failed_observed
  }
}`,...G.parameters?.docs?.source},description:{story:`H3: "after the last observed checkpoint", never "failed in".`,...G.parameters?.docs?.description}}},K.parameters={...K.parameters,docs:{...K.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.cancelled
  }
}`,...K.parameters?.docs?.source},description:{story:`§2.2 row 13. The review pause is the only cancellation point there is.`,...K.parameters?.docs?.description}}},q.parameters={...q.parameters,docs:{...q.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.expired
  }
}`,...q.parameters?.docs?.source},description:{story:`§2.2 row 16. Retention, not deletion and not permission (H8).`,...q.parameters?.docs?.description}}},J.parameters={...J.parameters,docs:{...J.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.submitting
  }
}`,...J.parameters?.docs?.source},description:{story:"Submitting: `POST /research` is in flight and no run exists yet.",...J.parameters?.docs?.description}}},Y.parameters={...Y.parameters,docs:{...Y.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.running_observed,
    legend: "open"
  }
}`,...Y.parameters?.docs?.source},description:{story:`The legend 03 §5.3 shows once per session, before it goes behind a toggle.`,...Y.parameters?.docs?.description}}},X.parameters={...X.parameters,docs:{...X.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.running_observed
  },
  globals: {
    theme: "dark"
  }
}`,...X.parameters?.docs?.source}}},Z.parameters={...Z.parameters,docs:{...Z.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.failed_observed,
    legend: "open"
  },
  globals: {
    theme: "forced-colors"
  }
}`,...Z.parameters?.docs?.source},description:{story:`The RC-17 claim: a word and a shape per status, with the hue removed.`,...Z.parameters?.docs?.description}}},Q.parameters={...Q.parameters,docs:{...Q.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.running_observed
  },
  globals: {
    motion: "reduce"
  }
}`,...Q.parameters?.docs?.source},description:{story:"The one that has to look IDENTICAL to `RunningWithCheckpoint` in the\nblind spot, and different only in that the `Live` mark has stopped.",...Q.parameters?.docs?.description}}},$.parameters={...$.parameters,docs:{...$.parameters?.docs,source:{originalSource:`{
  args: {
    inputs: STATES.running_observed
  },
  globals: {
    viewport: {
      value: "w320"
    }
  }
}`,...$.parameters?.docs?.source},description:{story:`320px is the narrowest RC-14 viewport; the spine wraps rather than pans.`,...$.parameters?.docs?.description}}},_e=[`NoJob`,`StatusUnknown`,`RunningNoCheckpoint`,`RunningWithCheckpoint`,`Reconnecting`,`StreamTimeout`,`AwaitingReview`,`AwaitingReviewBeforeThePoll`,`Succeeded`,`SucceededFromHistory`,`Failed`,`FailedAfterCheckpoint`,`Cancelled`,`Unavailable`,`Submitting`,`LegendOpen`,`Dark`,`ForcedColours`,`ReducedMotion`,`Narrow`]})))()}ve();export{B as AwaitingReview,V as AwaitingReviewBeforeThePoll,K as Cancelled,X as Dark,W as Failed,G as FailedAfterCheckpoint,Z as ForcedColours,Y as LegendOpen,$ as Narrow,P as NoJob,R as Reconnecting,Q as ReducedMotion,I as RunningNoCheckpoint,L as RunningWithCheckpoint,F as StatusUnknown,z as StreamTimeout,J as Submitting,H as Succeeded,U as SucceededFromHistory,q as Unavailable,_e as __namedExportsOrder,O as default};