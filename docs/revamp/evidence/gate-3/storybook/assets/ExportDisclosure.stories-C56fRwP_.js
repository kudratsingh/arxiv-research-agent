import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./react-Z7gd5LxR.js";import{t as n}from"./jsx-runtime-CadfrxEJ.js";import{t as r}from"./react-dom-DohlnDi3.js";import"./primitives-C6B3pA6y.js";import{a as i,i as a,n as o,r as s}from"./styles-B5dROzMd.js";import{n as c,t as l}from"./Disclosure-rpr3v1uS.js";import{i as u,n as d,r as f,t as p}from"./ReportReader-B6BpDFSd.js";import{n as m,r as h,t as g}from"./MetricsStrip-Dvc9K9Yr.js";var _;function v(){return(v=e((()=>{_={label:`Export`,markdown:`Markdown`,pdf:`PDF`,word:`Word`,refused:`There is nothing to export yet: this run produced no briefing.`}})))()}function y(e,t){return`${T}/research/${encodeURIComponent(e)}/export?format=${t}`}function b({jobId:e,hasBriefing:t,refused:n=!1,defaultOpen:r=!1,onOpenChange:a,id:c,className:u}){let d=(0,C.useId)(),f=c??`${d}-export`,p=(0,C.useRef)(null),[m,h]=(0,C.useState)(r);function g(e){h(e),a?.(e)}function v(){document.getElementById(f)?.focus()}function b(e){if(e.key===`Escape`){if(!m)return;e.stopPropagation(),e.preventDefault(),g(!1),v();return}if(e.key!==`ArrowDown`&&e.key!==`ArrowUp`)return;let t=x(p.current);if(t.length===0)return;if(e.preventDefault(),!m){(0,w.flushSync)(()=>{g(!0)});let t=x(p.current);t[e.key===`ArrowDown`?0:t.length-1]?.focus();return}let n=t.indexOf(document.activeElement);if(n===-1){t[e.key===`ArrowDown`?0:t.length-1]?.focus();return}t[(n+(e.key===`ArrowDown`?1:-1)+t.length)%t.length]?.focus()}return n?(0,S.jsx)(`p`,{role:`alert`,className:s(`ew-export__refusal font-ui`,u),children:_.refused}):t?(0,S.jsx)(`div`,{onKeyDown:b,"data-export":`true`,className:s(`ew-export`,u),children:(0,S.jsx)(l,{id:f,label:_.label,open:m,onOpenChange:g,panelClassName:`ew-export__panel`,children:(0,S.jsx)(`ul`,{ref:p,className:`ew-export__list`,children:E.map(t=>(0,S.jsx)(`li`,{children:(0,S.jsx)(`a`,{href:y(e,t),download:!0,"data-export-link":`true`,"data-format":t,className:s(`ew-export__link font-ui`,o,i(`sm`)),children:D[t]})},t))})})}):null}function x(e){return e===null?[]:Array.from(e.querySelectorAll(`a[data-export-link]`))}var S,C,w,T,E,D;function O(){return(O=e((()=>{S=n(),C=t(),w=r(),c(),a(),v(),T=`/api`,E=[`md`,`pdf`,`docx`],D={md:_.markdown,pdf:_.pdf,docx:_.word},b.__docgenInfo={description:``,methods:[],displayName:`ExportDisclosure`,props:{jobId:{required:!0,tsType:{name:`string`},description:`The run whose briefing is exported.`},hasBriefing:{required:!0,tsType:{name:`boolean`},description:"Whether a briefing exists. `false` renders nothing at all (criterion 4).\nStatus is deliberately not a prop — see the header."},refused:{required:!1,tsType:{name:`boolean`},description:`Set once an export attempt has been refused with 409. Renders the
inline explanation in place of the control.`,defaultValue:{value:`false`,computed:!1}},defaultOpen:{required:!1,tsType:{name:`boolean`},description:``,defaultValue:{value:`false`,computed:!1}},onOpenChange:{required:!1,tsType:{name:`signature`,type:`function`,raw:`(open: boolean) => void`,signature:{arguments:[{type:{name:`boolean`},name:`open`}],return:{name:`void`}}},description:`Fired on every open and close, including the ones Escape causes.`},id:{required:!1,tsType:{name:`string`},description:`The trigger's id. Generated when absent.`},className:{required:!1,tsType:{name:`string`},description:``}}}})))()}var k,A,j,M,N,P,F,I,L,R,z,B,V,H,U,W,G,K;function q(){return(q=e((()=>{k=n(),f(),O(),m(),d(),{expect:A,userEvent:j,within:M}=__STORYBOOK_MODULE_TEST__,N=`baseline-succeeded`,P=`baseline-failed-partial`,F=[`# Partial briefing`,``,`The run retained an incomplete synthesis before verification failed.`,``,`## What remains useful`,``,`- Initial retrieval completed.`,`- Final claim verification did not complete.`].join(`
`),I={errorType:`verification_incomplete`,error:`Verification stopped before all claims could be checked.`},L=h({iterations:1,quality_score:null,cost_usd:.18,llm_calls:4,elapsed_sec:36}),R={title:`Patterns/ExportDisclosure`,component:b,args:{jobId:N,hasBriefing:!0},render:e=>(0,k.jsx)(`div`,{className:`max-w-xs p-6`,children:(0,k.jsx)(b,{...e})})},z={},B={args:{defaultOpen:!0}},V={play:async({canvasElement:e})=>{let t=M(e),n=t.getByRole(`button`,{name:`Export`});await j.tab(),await A(n).toHaveFocus(),await j.keyboard(`{Enter}`),await A(n).toHaveAttribute(`aria-expanded`,`true`),await j.keyboard(`{ArrowDown}`),await A(t.getByRole(`link`,{name:`Markdown`})).toHaveFocus(),await j.keyboard(`{ArrowDown}`),await A(t.getByRole(`link`,{name:`PDF`})).toHaveFocus(),await j.keyboard(`{Escape}`),await A(n).toHaveAttribute(`aria-expanded`,`false`),await A(n).toHaveFocus()}},H={args:{hasBriefing:!1}},U={args:{refused:!0}},W={args:{jobId:P,defaultOpen:!0},loaders:[async()=>({renderer:await u()})],render:(e,t)=>(0,k.jsx)(`div`,{className:`p-6`,children:(0,k.jsx)(p,{markdown:F,renderer:t.loaded.renderer,failure:I,actions:(0,k.jsx)(b,{...e}),metrics:(0,k.jsx)(g,{metrics:L})})})},G={args:{defaultOpen:!0},globals:{theme:`dark`}},z.parameters={...z.parameters,docs:{...z.parameters?.docs,source:{originalSource:`{}`,...z.parameters?.docs?.source},description:{story:'At rest: one button, `aria-expanded="false"`, three links out of reach.',...z.parameters?.docs?.description}}},B.parameters={...B.parameters,docs:{...B.parameters?.docs,source:{originalSource:`{
  args: {
    defaultOpen: true
  }
}`,...B.parameters?.docs?.source},description:{story:`The three formats the backend accepts, as ordinary links in flow.`,...B.parameters?.docs?.description}}},V.parameters={...V.parameters,docs:{...V.parameters?.docs,source:{originalSource:`{
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button", {
      name: "Export"
    });

    // Open from the keyboard. A real <button> takes Enter, which is half of
    // why criterion 3 says "a real button" rather than "role=button".
    await userEvent.tab();
    await expect(trigger).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await expect(trigger).toHaveAttribute("aria-expanded", "true");

    // Arrow into the list and along it.
    await userEvent.keyboard("{ArrowDown}");
    await expect(canvas.getByRole("link", {
      name: "Markdown"
    })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    await expect(canvas.getByRole("link", {
      name: "PDF"
    })).toHaveFocus();

    // Escape closes it and returns focus, which is the half a disclosure
    // usually forgets.
    await userEvent.keyboard("{Escape}");
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(trigger).toHaveFocus();
  }
}`,...V.parameters?.docs?.source},description:{story:`Criterion 3, in the browser: open with the keyboard, traverse, dismiss,
and get focus back.`,...V.parameters?.docs?.description}}},H.parameters={...H.parameters,docs:{...H.parameters?.docs,source:{originalSource:`{
  args: {
    hasBriefing: false
  }
}`,...H.parameters?.docs?.source},description:{story:`03 §2.2 row 23, resting: no briefing, so no control. This frame is empty,
and that is the state.`,...H.parameters?.docs?.description}}},U.parameters={...U.parameters,docs:{...U.parameters?.docs,source:{originalSource:`{
  args: {
    refused: true
  }
}`,...U.parameters?.docs?.source},description:{story:`03 §2.2 row 23, after the fact: the proxy answered 409 to an export that
was offered, and the message names the cause instead of the status code.`,...U.parameters?.docs?.description}}},W.parameters={...W.parameters,docs:{...W.parameters?.docs,source:{originalSource:`{
  args: {
    jobId: PARTIAL_JOB_ID,
    defaultOpen: true
  },
  loaders: [async () => ({
    renderer: await loadReportRenderer()
  })],
  render: (args, context) => <div className="p-6">
      <ReportReader markdown={PARTIAL_BRIEFING} renderer={context.loaded.renderer as ReportRenderer} failure={PARTIAL_FAILURE} actions={<ExportDisclosure {...args} />} metrics={<MetricsStrip metrics={PARTIAL_METRICS} />} />
    </div>
}`,...W.parameters?.docs?.source},description:{story:`Criterion 5 — the whole of 03 §2.2 row 14, composed.

The failure is a banner ABOVE a briefing that still renders, export sits
beside the title, and the metrics are attached BENEATH the body. Nothing
in this arrangement knows the run's status: \`export_research\` gates on a
falsy \`result\` alone (\`src/api/routes.py:364-368\`), so the only question
asked here is whether there is a briefing.`,...W.parameters?.docs?.description}}},G.parameters={...G.parameters,docs:{...G.parameters?.docs,source:{originalSource:`{
  args: {
    defaultOpen: true
  },
  globals: {
    theme: "dark"
  }
}`,...G.parameters?.docs?.source},description:{story:`03 §2.2 row 8 — the same control on the dark token set.`,...G.parameters?.docs?.description}}},K=[`Closed`,`Open`,`KeyboardFocus`,`UnavailableNoReport`,`Refused409`,`OnFailedRun`,`Dark`]})))()}q();export{z as Closed,G as Dark,V as KeyboardFocus,W as OnFailedRun,B as Open,U as Refused409,H as UnavailableNoReport,K as __namedExportsOrder,R as default};