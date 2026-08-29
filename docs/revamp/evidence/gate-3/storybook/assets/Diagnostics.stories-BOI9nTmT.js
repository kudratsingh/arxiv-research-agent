const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["./redact-oH6UdtAB.js","./rolldown-runtime-CsOFd3vK.js"])))=>i.map(i=>d[i]);
import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{n as t,t as n}from"./preload-helper-8jINIF9P.js";import{t as r}from"./react-Z7gd5LxR.js";import{t as i}from"./jsx-runtime-CadfrxEJ.js";import{r as a,t as o}from"./VisuallyHidden-BvZkhsza.js";import{n as s,t as c}from"./Button-DQWqKqVB.js";import{c as l,i as u}from"./errors-Ch6TWljv.js";import{n as d,t as f}from"./ScrollRegion-C-eDDIXG.js";import{n as p,t as m}from"./Disclosure-rpr3v1uS.js";function h(e,t){return`${e} ${e===1?`record`:`records`} held in memory. The last ${t} are kept, and a reload clears them.`}function g(e){return e<=0?null:`${e} older ${e===1?`record`:`records`} fell off the end of the buffer.`}var _,v,y,b,x;function S(){return(S=e((()=>{_={label:`Technical events`,logLabel:`Received frames`,empty:`No frames have been received on this connection.`,copyAction:`Copy diagnostics`,copyNote:`Copies the last 200 frames and the raw error strings to the clipboard. No question text, no briefing text, no headers and no keys, and nothing is sent anywhere.`,copied:`Copied to the clipboard.`},v={caption:`Received frames, run transitions and failures, oldest first.`,scrollLabel:`Diagnostics table`,columns:{time:`Time`,event:`Event`,detail:`Detail`}},y={frame:`frame`,transition:`transition`,connection:`connection`,terminal:`terminal`,failure:`failure`,vital:`web vital`},b={label:`Web vitals`,note:`Measured in this browser and held in memory. Nothing is sent anywhere.`,empty:`No web vitals have been reported yet.`,scrollLabel:`Web vitals table`,columns:{metric:`Metric`,value:`Value`,rating:`Rating`},metric:{LCP:`Largest contentful paint`,INP:`Interaction to next paint`,CLS:`Cumulative layout shift`},rating:{good:`good`,"needs-improvement":`needs improvement`,poor:`poor`}},x={copying:`Copying…`,copyFailed:`Copying to the clipboard failed. Select the rows and copy them by hand.`}})))()}function C(e){let t=new Date(e);return Number.isNaN(t.getTime())?u:t.toISOString().slice(11,23)}function w(e){if(typeof e==`string`)return e;if(typeof e==`number`||typeof e==`boolean`)return String(e);if(e===null)return`null`;if(e===void 0)return`undefined`;try{return JSON.stringify(e)??String(e)}catch{return String(e)}}function T(e){return typeof e==`object`&&!!e&&!Array.isArray(e)}function E(e){let t=[];e.from!==null&&t.push({key:`from`,value:e.from}),e.failureKind!==null&&t.push({key:`failure_kind`,value:e.failureKind});for(let[n,r]of Object.entries(e.detail??{})){if(n===`state_delta`&&T(r)){for(let[e,n]of Object.entries(r))t.push({key:e,value:w(n)});continue}t.push({key:n,value:w(r)})}return t}function D(e){return typeof e==`string`?Object.hasOwn(b.rating,e)?b.rating[e]:e:u}function O(e){return Object.hasOwn(b.metric,e)?b.metric[e]:e}function k({records:e,capacity:t=200,dropped:r=0,showVitals:i=!1,evidence:a,defaultOpen:s=!1,open:l,onOpenChange:u,onCopy:d,id:p,className:S}){let[T,k]=(0,M.useState)(`idle`),F=e.filter(e=>e.kind!==`vital`),I=e.filter(e=>e.kind===`vital`),L=g(r),R=a??[];async function z(){k(`busy`);try{let{diagnosticsJson:i}=await n(async()=>{let{diagnosticsJson:e}=await import(`./redact-oH6UdtAB.js`);return{diagnosticsJson:e}},__vite__mapDeps([0,1]),import.meta.url),a=i({records:e,capacity:t,dropped:r});d===void 0?await navigator.clipboard.writeText(a):await d(a),k(`done`)}catch{k(`failed`)}}return(0,j.jsxs)(m,{id:p,className:S,label:_.label,defaultOpen:s,open:l,onOpenChange:u,panelClassName:`flex flex-col gap-3`,children:[(0,j.jsx)(`p`,{className:`text-ui-xs text-ink-muted`,children:h(e.length,t)}),L===null?null:(0,j.jsx)(`p`,{className:`text-ui-xs text-ink-muted`,children:L}),R.length===0?null:(0,j.jsx)(`dl`,{className:`flex flex-col gap-1`,children:R.map(e=>(0,j.jsxs)(`div`,{className:`flex flex-wrap gap-2`,children:[(0,j.jsx)(`dt`,{className:`font-mono text-mono-sm text-ink-muted`,children:e.label}),(0,j.jsx)(`dd`,{className:`break-words font-mono text-mono-sm text-ink`,"data-present":e.present?`true`:`false`,children:e.value})]},e.label))}),(0,j.jsx)(`div`,{role:`log`,"aria-live":`polite`,"aria-label":_.logLabel,"data-record-count":e.length,children:(0,j.jsx)(f,{label:v.scrollLabel,axis:`both`,className:`max-h-96 rounded-md border border-border-subtle bg-sunken`,children:(0,j.jsxs)(`table`,{className:`w-max min-w-full border-collapse text-left`,children:[(0,j.jsx)(`caption`,{className:o,children:v.caption}),(0,j.jsx)(`thead`,{children:(0,j.jsxs)(`tr`,{className:`border-b border-border-subtle`,children:[(0,j.jsx)(A,{children:v.columns.time}),(0,j.jsx)(A,{children:v.columns.event}),(0,j.jsx)(A,{children:v.columns.detail})]})}),(0,j.jsx)(`tbody`,{children:F.length===0?(0,j.jsx)(`tr`,{children:(0,j.jsx)(`td`,{colSpan:3,className:`px-3 py-3 text-ui-sm text-ink-muted`,children:_.empty})}):F.map(e=>(0,j.jsxs)(`tr`,{"data-kind":e.kind,"data-event":e.event,className:`border-b border-border-subtle align-baseline last:border-b-0`,children:[(0,j.jsx)(`td`,{className:`whitespace-nowrap px-3 py-1 font-mono text-mono-xs text-ink-muted`,children:C(e.at)}),(0,j.jsxs)(`td`,{className:`px-3 py-1`,children:[(0,j.jsx)(`span`,{className:`block text-mono-xs text-ink-muted`,children:y[e.kind]}),(0,j.jsx)(`span`,{className:`font-mono text-mono-sm text-ink`,children:e.event})]}),(0,j.jsx)(`td`,{className:`px-3 py-1`,children:(0,j.jsx)(`span`,{className:`flex flex-wrap gap-x-3 gap-y-1`,children:E(e).map(e=>(0,j.jsxs)(`span`,{className:`font-mono text-mono-xs text-ink`,children:[(0,j.jsx)(`span`,{className:`text-ink-muted`,children:e.key}),(0,j.jsx)(`span`,{className:`text-ink-muted`,children:N}),e.value]},e.key))})})]},e.seq))})]})})}),i?(0,j.jsxs)(`div`,{className:`flex flex-col gap-2`,children:[(0,j.jsx)(`h3`,{className:`text-ui-sm font-medium text-ink`,children:b.label}),(0,j.jsx)(`p`,{className:`text-ui-xs text-ink-muted`,children:b.note}),I.length===0?(0,j.jsx)(`p`,{className:`text-ui-sm text-ink-muted`,children:b.empty}):(0,j.jsx)(f,{label:b.scrollLabel,className:`rounded-md border border-border-subtle bg-sunken`,children:(0,j.jsxs)(`table`,{className:`w-max min-w-full border-collapse text-left`,children:[(0,j.jsx)(`caption`,{className:o,children:b.label}),(0,j.jsx)(`thead`,{children:(0,j.jsxs)(`tr`,{className:`border-b border-border-subtle`,children:[(0,j.jsx)(A,{children:b.columns.metric}),(0,j.jsx)(A,{children:b.columns.value}),(0,j.jsx)(A,{children:b.columns.rating})]})}),(0,j.jsx)(`tbody`,{children:I.map(e=>(0,j.jsxs)(`tr`,{"data-metric":e.event,className:`border-b border-border-subtle last:border-b-0`,children:[(0,j.jsx)(`th`,{scope:`row`,className:`whitespace-nowrap px-3 py-1 text-ui-sm font-normal text-ink`,children:O(e.event)}),(0,j.jsxs)(`td`,{className:`whitespace-nowrap px-3 py-1 font-mono text-mono-sm text-ink`,children:[w(e.detail?.value),w(e.detail?.unit??``)]}),(0,j.jsx)(`td`,{className:`whitespace-nowrap px-3 py-1 text-ui-sm text-ink-muted`,children:D(e.detail?.rating)})]},e.seq))})]})})]}):null,(0,j.jsxs)(`div`,{className:`flex flex-wrap items-center gap-3`,children:[(0,j.jsx)(c,{variant:`secondary`,size:`sm`,onClick:()=>{z()},busy:T===`busy`,children:T===`busy`?x.copying:_.copyAction}),(0,j.jsx)(`p`,{className:`text-ui-xs text-ink-muted`,"data-copy-state":T,children:P[T]})]})]})}function A({children:e}){return(0,j.jsx)(`th`,{scope:`col`,className:`whitespace-nowrap px-3 py-1 text-ui-xs font-medium text-ink-muted`,children:e})}var j,M,N,P;function F(){return(F=e((()=>{j=i(),M=r(),s(),p(),d(),a(),S(),l(),t(),N=`=`,P={idle:_.copyNote,busy:_.copyNote,done:_.copied,failed:x.copyFailed},k.__docgenInfo={description:``,methods:[],displayName:`Diagnostics`,props:{records:{required:!0,tsType:{name:`unknown`},description:`Oldest first, straight off the ring.`},capacity:{required:!1,tsType:{name:`number`},description:`The ring's ceiling, for the retained line.`,defaultValue:{value:`RING_CAPACITY`,computed:!0}},dropped:{required:!1,tsType:{name:`number`},description:`How many the ring has already dropped.`,defaultValue:{value:`0`,computed:!1}},showVitals:{required:!1,tsType:{name:`boolean`},description:"`?debug=perf` (criterion 7). `false` hides the vitals block entirely —\nnot disabled, not empty: absent.",defaultValue:{value:`false`,computed:!1}},evidence:{required:!1,tsType:{name:`unknown`},description:`\`rawErrorEvidence()\`'s labelled rows — RC-16's "one disclosure away".`},defaultOpen:{required:!1,tsType:{name:`boolean`},description:``,defaultValue:{value:`false`,computed:!1}},open:{required:!1,tsType:{name:`boolean`},description:``},onOpenChange:{required:!1,tsType:{name:`signature`,type:`function`,raw:`(open: boolean) => void`,signature:{arguments:[{type:{name:`boolean`},name:`open`}],return:{name:`void`}}},description:``},onCopy:{required:!1,tsType:{name:`signature`,type:`function`,raw:`(json: string) => void | Promise<void>`,signature:{arguments:[{type:{name:`string`},name:`json`}],return:{name:`union`,raw:`void | Promise<void>`,elements:[{name:`void`},{name:`Promise`,elements:[{name:`void`}],raw:`Promise<void>`}]}}},description:`Where the redacted JSON goes. Defaults to the clipboard.

A seam rather than a mock: jsdom has no \`navigator.clipboard\`, and a
story must not need one.`},id:{required:!1,tsType:{name:`string`},description:``},className:{required:!1,tsType:{name:`string`},description:``}}}})))()}function I(e){let t=R++;return{seq:t,at:L+t*1400,jobId:`baseline-running`,phase:`live`,from:null,failureKind:null,detail:null,...e}}var L,R,z,B,V,H,U,W,G,K;function q(){return(q=e((()=>{F(),L=Date.UTC(2026,7,28,9,14,3,120),R=0,z=[I({kind:`transition`,event:`attaching`,phase:`attaching`,from:`idle`}),I({kind:`connection`,event:`open`,from:`opening`}),I({kind:`frame`,event:`job_started`,detail:{job_id:`baseline-running`}}),I({kind:`frame`,event:`node_completed`,detail:{node:`planner`,state_delta:{iteration:0,sub_questions_count:3}}}),I({kind:`frame`,event:`node_completed`,detail:{node:`searcher`,state_delta:{iteration:1,papers_found:9}}}),I({kind:`frame`,event:`job_completed`,detail:{llm_calls:11}}),I({kind:`terminal`,event:`job_completed`,detail:{shape:`live`}}),I({kind:`transition`,event:`reconciling`,phase:`reconciling`,from:`live`})],B={title:`Diagnostics`,component:k,args:{records:z,capacity:200,dropped:0,onCopy:()=>void 0}},V={},H={args:{defaultOpen:!0}},U={args:{defaultOpen:!0,records:[]}},W={args:{defaultOpen:!0,records:[I({kind:`frame`,event:`job_started`,detail:{job_id:`baseline-running`}}),I({kind:`frame`,event:`node_started`,detail:{node:`searcher`}}),I({kind:`frame`,event:`paper_indexed`,detail:{arxiv_id:`2601.00001`,node:`searcher`,score:.71}}),I({kind:`frame`,event:`node_completed`,detail:{node:`claim_decomposer`,state_delta:{claims_extracted:14,decomposition_strategy:`per-sentence`,iteration:1,unreleased_feature_flag:!0}}}),I({kind:`frame`,event:`node_completed`,detail:{node:`searcher`,state_delta:{}}})]}},G={args:{defaultOpen:!0,dropped:3,records:[I({kind:`frame`,event:`job_started`,detail:{job_id:`baseline-running`}}),I({kind:`connection`,event:`reconnecting`,from:`open`}),I({kind:`connection`,event:`open`,from:`reconnecting`}),I({kind:`frame`,event:`stream_timeout`,detail:{reason:`max_duration`,elapsed_sec:900}}),I({kind:`failure`,event:`poll`,failureKind:`upstream_unavailable`,detail:{status:502,error:`upstream returned 502`}})]}},V.parameters={...V.parameters,docs:{...V.parameters?.docs,source:{originalSource:`{}`,...V.parameters?.docs?.source},description:{story:"Criterion 2. The panel is `hidden`, the live region is out of the tree,\nand nothing about a running stream is announced.",...V.parameters?.docs?.description}}},H.parameters={...H.parameters,docs:{...H.parameters?.docs,source:{originalSource:`{
  args: {
    defaultOpen: true
  }
}`,...H.parameters?.docs?.source},description:{story:`The same records, opened. Three columns, panning inside their own box.`,...H.parameters?.docs?.description}}},U.parameters={...U.parameters,docs:{...U.parameters?.docs,source:{originalSource:`{
  args: {
    defaultOpen: true,
    records: []
  }
}`,...U.parameters?.docs?.source},description:{story:`03 §4.5's fourth state: "No frames received on this connection."

The \`<table>\` is still there — the live region's content does not change
shape when it is empty, only its rows.`,...U.parameters?.docs?.description}}},W.parameters={...W.parameters,docs:{...W.parameters?.docs,source:{originalSource:`{
  args: {
    defaultOpen: true,
    records: [record({
      kind: "frame",
      event: "job_started",
      detail: {
        job_id: "baseline-running"
      }
    }), record({
      kind: "frame",
      event: "node_started",
      detail: {
        node: "searcher"
      }
    }), record({
      kind: "frame",
      event: "paper_indexed",
      detail: {
        arxiv_id: "2601.00001",
        node: "searcher",
        score: 0.71
      }
    }), record({
      kind: "frame",
      event: "node_completed",
      detail: {
        node: "claim_decomposer",
        state_delta: {
          claims_extracted: 14,
          decomposition_strategy: "per-sentence",
          iteration: 1,
          unreleased_feature_flag: true
        }
      }
    }), record({
      kind: "frame",
      event: "node_completed",
      detail: {
        node: "searcher",
        state_delta: {}
      }
    })]
  }
}`,...W.parameters?.docs?.source},description:{story:"Criterion 3. Two names outside `SERVER_EVENT_NAMES`, a node label from no\ngraph, and four `state_delta` keys from no vocabulary — all verbatim.",...W.parameters?.docs?.description}}},G.parameters={...G.parameters,docs:{...G.parameters?.docs,source:{originalSource:`{
  args: {
    defaultOpen: true,
    dropped: 3,
    records: [record({
      kind: "frame",
      event: "job_started",
      detail: {
        job_id: "baseline-running"
      }
    }), record({
      kind: "connection",
      event: "reconnecting",
      from: "open"
    }), record({
      kind: "connection",
      event: "open",
      from: "reconnecting"
    }), record({
      kind: "frame",
      event: "stream_timeout",
      detail: {
        reason: "max_duration",
        elapsed_sec: 900
      }
    }), record({
      kind: "failure",
      event: "poll",
      failureKind: "upstream_unavailable",
      detail: {
        status: 502,
        error: "upstream returned 502"
      }
    })]
  }
}`,...G.parameters?.docs?.source},description:{story:`The risk note (03 §2.2 rows 11 and 25). The raw stream note lives here
and nowhere else: a reconnect, a server-side recycle at the duration
ceiling, and the normalized failure kind beside them.`,...G.parameters?.docs?.description}}},K=[`Collapsed`,`Expanded`,`Empty`,`UnknownEvent`,`StreamNote`]})))()}q();export{V as Collapsed,U as Empty,H as Expanded,G as StreamNote,W as UnknownEvent,K as __namedExportsOrder,B as default};