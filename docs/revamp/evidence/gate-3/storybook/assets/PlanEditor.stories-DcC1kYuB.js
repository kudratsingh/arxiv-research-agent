const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["./PlanEditorFields-CXR9IfLM.js","./rolldown-runtime-CsOFd3vK.js","./react-Z7gd5LxR.js","./jsx-runtime-CadfrxEJ.js","./Button-DQWqKqVB.js","./primitives-C6B3pA6y.js","./primitives-RmCPfk8v.css","./styles-B5dROzMd.js","./Textarea-CW6YHoQX.js","./VisuallyHidden-BvZkhsza.js","./marks-CQxAYwh1.js","./tokens-BmyTjNhk.js","./schema-BXd7mzUz.js"])))=>i.map(i=>d[i]);
import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{n as t,t as n}from"./preload-helper-8jINIF9P.js";import{t as r}from"./react-Z7gd5LxR.js";import{t as i}from"./jsx-runtime-CadfrxEJ.js";import{n as a,t as o}from"./Button-DQWqKqVB.js";import{n as s,t as c}from"./Skeleton-cW23yxTh.js";import{n as l,r as u}from"./StatusBadge-BZocO7mF.js";import{c as d,o as f}from"./errors-Ch6TWljv.js";import{n as p,r as m}from"./StatusBanner-DHqsKSvA.js";import{a as h,f as g,m as _}from"./schema-BXd7mzUz.js";function v({plan:e,status:t=`editing`,initialDraft:n,issues:r=[],staleCause:i=`resolved_elsewhere`,onReview:a,onRefetch:s,className:c}){let u=(0,x.useId)(),d=`${u}-heading`,m=`${u}-arxiv-hint`,h=t===`stale`,_=JSON.stringify([e.sub_questions,e.search_queries]),v=(0,x.useRef)(!1);(0,x.useEffect)(()=>{if(!h){v.current=!1;return}v.current||(v.current=!0,s?.())},[h,s]);let C=i===`hitl_timeout`,w=f(`hitl_timeout`),T=h?null:t===`resolving`?g.resolving:t===`submitting`||t===`cancelling`?g.sending:g.status;return(0,b.jsxs)(`section`,{"aria-labelledby":d,"data-surface":`plan-editor`,"data-status":t,className:[`flex flex-col gap-4 rounded-lg border border-review bg-review-surface p-5`,c].filter(Boolean).join(` `),children:[(0,b.jsxs)(`div`,{className:`flex flex-wrap items-center justify-between gap-2`,children:[(0,b.jsx)(`h2`,{id:d,className:`text-ui-lg font-semibold text-ink`,children:g.heading}),(0,b.jsx)(l,{severity:`review`,emphasis:`surface`,children:g.statusWord})]}),(0,b.jsx)(`p`,{className:`text-ui-sm text-ink`,children:g.intro}),T===null?null:(0,b.jsx)(`p`,{"data-testid":`plan-status-line`,className:`text-ui-sm text-ink-muted`,children:T}),h?(0,b.jsx)(p,{severity:`warning`,userTriggered:!0,sentence:C?w.sentence:g.conflict,recovery:C?w.recovery:g.conflictRecovery,actions:(0,b.jsx)(o,{variant:`primary`,size:`md`,"data-primary":`true`,onClick:()=>s?.(),children:g.refresh})}):(0,b.jsx)(x.Suspense,{fallback:(0,b.jsx)(y,{}),children:(0,b.jsx)(S,{plan:e,status:t,initialDraft:n,issues:r,onReview:a,arxivHintId:m},_)})]})}function y(){return(0,b.jsxs)(`div`,{className:`grid gap-6 md:grid-cols-2`,"data-testid":`plan-editor-loading`,children:[(0,b.jsx)(c,{lines:4,height:`var(--size-control-height-lg)`,label:g.heading}),(0,b.jsx)(c,{lines:4,height:`var(--size-control-height-lg)`})]})}var b,x,S;function C(){return(C=e((()=>{b=i(),x=r(),a(),s(),u(),d(),_(),m(),t(),S=(0,x.lazy)(()=>n(()=>import(`./PlanEditorFields-CXR9IfLM.js`),__vite__mapDeps([0,1,2,3,4,5,6,7,8,9,10,11,12]),import.meta.url)),v.__docgenInfo={description:``,methods:[],displayName:`PlanEditor`,props:{plan:{required:!0,tsType:{name:`Plan`},description:"The server's plan — `JobDetail.plan` or a `plan_ready` frame."},status:{required:!1,tsType:{name:`union`,raw:`| "editing"
| "submitting"
| "cancelling"
| "resolving"
| "stale"`,elements:[{name:`literal`,value:`"editing"`},{name:`literal`,value:`"submitting"`},{name:`literal`,value:`"cancelling"`},{name:`literal`,value:`"resolving"`},{name:`literal`,value:`"stale"`}]},description:``,defaultValue:{value:`"editing"`,computed:!1}},initialDraft:{required:!1,tsType:{name:`PlanDraft`},description:"The working copy to open with. Defaults to `plan`. Exists so the\n`Edited` state is reachable by props rather than by a scripted\ninteraction, and so a caller can restore a draft."},issues:{required:!1,tsType:{name:`unknown`},description:`A 422 that still arrived. Mapped onto rows, never a page-level banner.`,defaultValue:{value:`[]`,computed:!1}},staleCause:{required:!1,tsType:{name:`union`,raw:`"resolved_elsewhere" | "hitl_timeout"`,elements:[{name:`literal`,value:`"resolved_elsewhere"`},{name:`literal`,value:`"hitl_timeout"`}]},description:``,defaultValue:{value:`"resolved_elsewhere"`,computed:!1}},onReview:{required:!0,tsType:{name:`signature`,type:`function`,raw:`(request: ReviewRequest) => void`,signature:{arguments:[{type:{name:`ReviewRequest`},name:`request`}],return:{name:`void`}}},description:"Send the decision. Called with `approve`, `revise` (always with a plan)\nor `cancel`, and never called at all when the client bounds refuse."},onRefetch:{required:!1,tsType:{name:`signature`,type:`function`,raw:`() => void`,signature:{arguments:[],return:{name:`void`}}},description:"Read the run again. Called on entering `stale`, and by the control."},className:{required:!1,tsType:{name:`string`},description:``}}}})))()}async function w(e){return k(()=>e.getByRole(`button`,{name:e=>e===g.approve||e===g.revise}),{timeout:4e3})}var T,E,D,O,k,A,j,M,N,P,F,I,L,R,z,B,V,H,U,W,G;function K(){return(K=e((async()=>{T=i(),_(),h(),C(),t(),{expect:E,fn:D,userEvent:O,waitFor:k,within:A}=__STORYBOOK_MODULE_TEST__,j={title:`Patterns/PlanEditor`,component:v,decorators:[e=>(0,T.jsx)(`main`,{className:`mx-auto max-w-content p-gutter-narrow`,children:(0,T.jsx)(e,{})})],args:{plan:{sub_questions:[`Which verification architectures are currently used?`,`How is evidence provenance preserved?`,`What evaluation methods detect unsupported claims?`],search_queries:[`retrieval augmented claim verification`,`evidence provenance language model`,`unsupported claim detection evaluation`]},onReview:D(),onRefetch:D()}},await n(()=>import(`./PlanEditorFields-CXR9IfLM.js`),__vite__mapDeps([0,1,2,3,4,5,6,7,8,9,10,11,12]),import.meta.url),M={play:async({canvasElement:e})=>{let t=A(e);await E(await w(t)).toHaveAccessibleName(g.approve),await E(t.getAllByRole(`button`,{name:g.approve})).toHaveLength(1)}},N={args:{initialDraft:{subQuestions:[`Which verification architectures are currently used?`,`Which of them have been evaluated outside their own paper?`],searchQueries:[`retrieval augmented claim verification`,`evidence provenance language model`,`unsupported claim detection evaluation`]}},play:async({args:e,canvasElement:t})=>{let n=await w(A(t));await E(n).toHaveAccessibleName(g.revise),await O.click(n),await k(()=>E(e.onReview).toHaveBeenCalledWith(E.objectContaining({action:`revise`})))}},P={args:{plan:{sub_questions:[],search_queries:[]}},play:async({canvasElement:e})=>{let t=A(e);await w(t),await E(t.getByText(g.noSubQuestions)).toBeInTheDocument(),await E(t.getByText(g.noArxivQueries)).toBeInTheDocument()}},F={args:{plan:{sub_questions:Array.from({length:20},(e,t)=>`Sub-question ${t+1}`),search_queries:[`retrieval augmented claim verification`]}},play:async({canvasElement:e})=>{let t=A(e);await w(t),await E(t.getByRole(`button`,{name:`Add sub-question`})).toBeDisabled(),await E(t.getByRole(`button`,{name:`Add arXiv query`})).toBeEnabled()}},I={args:{plan:{sub_questions:[`Which verification architectures are currently used?`],search_queries:[`retrieval augmented claim verification`]},initialDraft:{subQuestions:[`x`.repeat(501)],searchQueries:[`retrieval augmented claim verification`]}},play:async({args:e,canvasElement:t})=>{let n=A(t);await O.click(await w(n)),await E(await n.findByText(/1 character over the limit/)).toBeVisible(),await E(e.onReview).not.toHaveBeenCalled(),await E(n.getByLabelText(`Sub-question 1`).value).toHaveLength(501)}},L={args:{plan:{sub_questions:[`x`.repeat(500)],search_queries:[`arxiv query at a normal length`]}},play:async({canvasElement:e})=>{let t=A(e);await w(t),await E(t.getByText(`500 / 500`)).toBeInTheDocument()}},R={args:{status:`submitting`},play:async({canvasElement:e})=>{let t=await w(A(e));await E(t).toHaveAttribute(`aria-busy`,`true`),await E(t).toBeEnabled()}},z={args:{status:`cancelling`},play:async({canvasElement:e})=>{let t=A(e);await w(t),await E(t.getByRole(`button`,{name:g.cancel})).toBeDisabled()}},B={args:{status:`resolving`},play:async({canvasElement:e})=>{let t=A(e);await w(t),await E(t.getByTestId(`plan-status-line`)).toHaveTextContent(g.resolving)}},V={args:{status:`stale`},play:async({args:e,canvasElement:t})=>{let n=A(t),r=await n.findByRole(`alert`);await E(r).toHaveTextContent(g.conflict),await k(()=>E(e.onRefetch).toHaveBeenCalled()),await E(n.getByRole(`button`,{name:g.refresh})).toBeEnabled()}},H={args:{status:`stale`,staleCause:`hitl_timeout`},play:async({canvasElement:e})=>{let t=await A(e).findByRole(`alert`);await E(t).toHaveTextContent(/not reviewed in time/i),await E(t.textContent??``).not.toMatch(/\b\d+\s*(?:minutes?|seconds?)\b/i)}},U={args:{issues:[{path:`plan.search_queries.1`,message:`String should have at most 500 characters`,type:`string_too_long`}]},play:async({canvasElement:e})=>{let t=A(e);await w(t),await k(()=>E(t.getByLabelText(`arXiv query 2`)).toHaveAttribute(`aria-invalid`,`true`)),await E(t.getByLabelText(`arXiv query 1`)).not.toHaveAttribute(`aria-invalid`)}},W={play:async({canvasElement:e})=>{let t=A(e);await w(t);let n=t.getByLabelText(`arXiv query 1`),r=t.getByLabelText(`Sub-question 1`);await E(n).toHaveAccessibleDescription(E.stringContaining(`verbatim`)),await E(r).not.toHaveAccessibleDescription(E.stringContaining(`verbatim`)),await E(getComputedStyle(n).fontFamily).not.toBe(getComputedStyle(r).fontFamily)}},M.parameters={...M.parameters,docs:{...M.parameters?.docs,source:{originalSource:`{
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    // Unedited: one control, reading "Approve plan", and no second approve
    // beside it. 03 §7.2's focus-on-removal rule is driven in
    // \`web/tests/plan/PlanEditor.test.tsx\`, which walks all three of its
    // cases; repeating one of them here would only buy a slower story.
    await expect(await form(canvas)).toHaveAccessibleName(PLAN.approve);
    await expect(canvas.getAllByRole("button", {
      name: PLAN.approve
    })).toHaveLength(1);
  }
}`,...M.parameters?.docs?.source}}},N.parameters={...N.parameters,docs:{...N.parameters?.docs,source:{originalSource:`{
  args: {
    initialDraft: {
      subQuestions: ["Which verification architectures are currently used?", "Which of them have been evaluated outside their own paper?"],
      searchQueries: ["retrieval augmented claim verification", "evidence provenance language model", "unsupported claim detection evaluation"]
    }
  },
  play: async ({
    args,
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    const primary = await form(canvas);
    // The same control, relabelled — and it sends \`revise\`, with the plan.
    await expect(primary).toHaveAccessibleName(PLAN.revise);
    await userEvent.click(primary);
    await waitFor(() => expect(args.onReview).toHaveBeenCalledWith(expect.objectContaining({
      action: "revise"
    })));
  }
}`,...N.parameters?.docs?.source}}},P.parameters={...P.parameters,docs:{...P.parameters?.docs,source:{originalSource:`{
  args: {
    plan: {
      sub_questions: [],
      search_queries: []
    }
  },
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    await form(canvas);
    await expect(canvas.getByText(PLAN.noSubQuestions)).toBeInTheDocument();
    await expect(canvas.getByText(PLAN.noArxivQueries)).toBeInTheDocument();
  }
}`,...P.parameters?.docs?.source}}},F.parameters={...F.parameters,docs:{...F.parameters?.docs,source:{originalSource:`{
  args: {
    plan: {
      sub_questions: Array.from({
        length: MAX_PLAN_ITEMS
      }, (_, index) => \`Sub-question \${index + 1}\`),
      search_queries: ["retrieval augmented claim verification"]
    }
  },
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    await form(canvas);
    // The cap is \`MAX_PLAN_ITEMS\` (\`schemas.py:26\`), refused in the form.
    await expect(canvas.getByRole("button", {
      name: "Add sub-question"
    })).toBeDisabled();
    await expect(canvas.getByRole("button", {
      name: "Add arXiv query"
    })).toBeEnabled();
  }
}`,...F.parameters?.docs?.source},description:{story:`One column at \`MAX_PLAN_ITEMS\`, beside one that is not.

Both columns at the cap would be forty controlled fields plus an axe pass
per story, which is slow enough to be flaky and shows nothing the pair
below does not: the state is "this list is full", and having the other
column open is what proves the refusal is per-list rather than global.`,...F.parameters?.docs?.description}}},I.parameters={...I.parameters,docs:{...I.parameters?.docs,source:{originalSource:`{
  args: {
    plan: {
      sub_questions: ["Which verification architectures are currently used?"],
      search_queries: ["retrieval augmented claim verification"]
    },
    initialDraft: {
      subQuestions: ["x".repeat(MAX_PLAN_ITEM_LEN + 1)],
      searchQueries: ["retrieval augmented claim verification"]
    }
  },
  play: async ({
    args,
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await form(canvas));
    await expect(await canvas.findByText(/1 character over the limit/)).toBeVisible();
    await expect(args.onReview).not.toHaveBeenCalled();
    await expect((canvas.getByLabelText("Sub-question 1") as HTMLTextAreaElement).value).toHaveLength(MAX_PLAN_ITEM_LEN + 1);
  }
}`,...I.parameters?.docs?.source},description:{story:`One character past the bound — the refusal, not a truncation.

The pair with \`ItemAtMaxLength\`: 500 characters submit, 501 do not, and
the 501st is still on screen afterwards. Criterion 3 is that the request
is never made, and the play below is where that is visible rather than
merely asserted in a unit test.`,...I.parameters?.docs?.description}}},L.parameters={...L.parameters,docs:{...L.parameters?.docs,source:{originalSource:`{
  args: {
    plan: {
      sub_questions: ["x".repeat(MAX_PLAN_ITEM_LEN)],
      search_queries: ["arxiv query at a normal length"]
    }
  },
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    await form(canvas);
    // Exactly at the bound is valid; the counter states it and refuses
    // nothing. One more character is the refusal, and it truncates neither.
    await expect(canvas.getByText(\`\${MAX_PLAN_ITEM_LEN} / \${MAX_PLAN_ITEM_LEN}\`)).toBeInTheDocument();
  }
}`,...L.parameters?.docs?.source}}},R.parameters={...R.parameters,docs:{...R.parameters?.docs,source:{originalSource:`{
  args: {
    status: "submitting"
  },
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    const primary = await form(canvas);
    // Busy, not disabled: the control keeps focus and the tab order rather
    // than vanishing under the user's hands mid-submission.
    await expect(primary).toHaveAttribute("aria-busy", "true");
    await expect(primary).toBeEnabled();
  }
}`,...R.parameters?.docs?.source}}},z.parameters={...z.parameters,docs:{...z.parameters?.docs,source:{originalSource:`{
  args: {
    status: "cancelling"
  },
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    await form(canvas);
    await expect(canvas.getByRole("button", {
      name: PLAN.cancel
    })).toBeDisabled();
  }
}`,...z.parameters?.docs?.source}}},B.parameters={...B.parameters,docs:{...B.parameters?.docs,source:{originalSource:`{
  args: {
    status: "resolving"
  },
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    await form(canvas);
    await expect(canvas.getByTestId("plan-status-line")).toHaveTextContent(PLAN.resolving);
  }
}`,...B.parameters?.docs?.source},description:{story:`The 200 that does not mean resumed (\`schemas.py:141-160\`).

Not one of the ten the card names, and it is here anyway: \`resolving\` is
the state criterion 6 is about, and a state nobody can look at is a state
nobody reviews.`,...B.parameters?.docs?.description}}},V.parameters={...V.parameters,docs:{...V.parameters?.docs,source:{originalSource:`{
  args: {
    status: "stale"
  },
  play: async ({
    args,
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    const alert = await canvas.findByRole("alert");
    await expect(alert).toHaveTextContent(PLAN.conflict);
    // It refetches rather than dead-ending — on arrival, and again on demand.
    await waitFor(() => expect(args.onRefetch).toHaveBeenCalled());
    await expect(canvas.getByRole("button", {
      name: PLAN.refresh
    })).toBeEnabled();
  }
}`,...V.parameters?.docs?.source}}},H.parameters={...H.parameters,docs:{...H.parameters?.docs,source:{originalSource:`{
  args: {
    status: "stale",
    staleCause: "hitl_timeout"
  },
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    const alert = await canvas.findByRole("alert");
    // The mapped \`error_type\` sentence, and still no countdown anywhere:
    // \`api_hitl_timeout_sec\` is server configuration, not an API field.
    await expect(alert).toHaveTextContent(/not reviewed in time/i);
    await expect(alert.textContent ?? "").not.toMatch(/\\b\\d+\\s*(?:minutes?|seconds?)\\b/i);
  }
}`,...H.parameters?.docs?.source}}},U.parameters={...U.parameters,docs:{...U.parameters?.docs,source:{originalSource:`{
  args: {
    issues: [{
      path: "plan.search_queries.1",
      message: "String should have at most 500 characters",
      type: "string_too_long"
    }]
  },
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    await form(canvas);
    // On the row FastAPI named, and on no other — the baseline mapped
    // nothing at all.
    await waitFor(() => expect(canvas.getByLabelText("arXiv query 2")).toHaveAttribute("aria-invalid", "true"));
    await expect(canvas.getByLabelText("arXiv query 1")).not.toHaveAttribute("aria-invalid");
  }
}`,...U.parameters?.docs?.source}}},W.parameters={...W.parameters,docs:{...W.parameters?.docs,source:{originalSource:`{
  play: async ({
    canvasElement
  }) => {
    const canvas = within(canvasElement);
    await form(canvas);
    const arxiv = canvas.getByLabelText("arXiv query 1");
    const prose = canvas.getByLabelText("Sub-question 1");
    await expect(arxiv).toHaveAccessibleDescription(expect.stringContaining("verbatim"));
    await expect(prose).not.toHaveAccessibleDescription(expect.stringContaining("verbatim"));
    // The faces really differ in the rendered result, not only in a class.
    await expect(getComputedStyle(arxiv).fontFamily).not.toBe(getComputedStyle(prose).fontFamily);
  }
}`,...W.parameters?.docs?.source},description:{story:`The two families side by side, which is the decision to look at.

Sub-questions are prose in the UI face and may be rewritten freely; arXiv
queries are literal strings in the utility (mono) face and are sent
verbatim. If the typeface distinction ever falls, the \`aria-describedby\`
hint under the arXiv column is the only thing carrying it — which is why
this story asserts the hint as well as the face.`,...W.parameters?.docs?.description}}},G=[`Default`,`Edited`,`EmptyLists`,`MaxItems`,`OverLimitRefused`,`ItemAtMaxLength`,`Submitting`,`SubmittingCancel`,`Resolving`,`Conflict409`,`HitlTimedOut`,`Validation422`,`TwoFamilies`]})))()}await K();export{V as Conflict409,M as Default,N as Edited,P as EmptyLists,H as HitlTimedOut,L as ItemAtMaxLength,F as MaxItems,I as OverLimitRefused,B as Resolving,R as Submitting,z as SubmittingCancel,W as TwoFamilies,U as Validation422,G as __namedExportsOrder,j as default};