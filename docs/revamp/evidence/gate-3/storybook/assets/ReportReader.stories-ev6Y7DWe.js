import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{i as n,n as r,r as i,t as a}from"./ReportReader-B6BpDFSd.js";function o(e){return e.loaded.renderer}var s,c,l,u,d,f,p,m,h,g,_,v,y,b,x,S,C,w,T,E;function D(){return(D=e((()=>{s=t(),i(),r(),c=[`Retrieval-augmented systems are evaluated on answer accuracy far more`,`often than on whether the answer is *supported* by what was retrieved.`,``,`Three of the eleven papers read here separate the two.`].join(`
`),l=`# Faithfulness in retrieval-augmented generation((Eleven papers, read end to end. The through-line is that *faithfulness*(and *accuracy* are measured as if they were one quantity, and they are(not.((## What the field measures today((Answer-level exact match dominates. It rewards a system that guessed(correctly from parametric memory exactly as much as one that read the(retrieved passage.((### Automatic metrics((Entailment-based scoring is the most common substitute, and it inherits(the entailment model's own failure modes.((### Human protocols((Annotator agreement on **support** is consistently lower than agreement(on correctness — which is itself the finding.((## Where the disagreement is((Two camps: one treats unsupported-but-correct as a pass, the other as a(failure. Nothing reconciles them.((### Unsupported but correct((> An answer the retrieval did not license is a coincidence, not a result.((## What is missing((1. A claim-level benchmark that survives paraphrase.(2. A protocol that reports support and accuracy separately.(3. Any agreement on what counts as a citation.((## Limits((The sample is arXiv-only and English-only, and stops at the retrieval(date of this run.`.split(`(`).join(`
`),u=[`## Benchmarks compared`,``,`The columns are wider than the reading column on purpose: this is the`,`SC 1.4.10 case.`,``,`| Benchmark | Claim-level | Paraphrase-robust | Human protocol published | Annotator agreement | Licence |`,`| --- | --- | --- | --- | --- | --- |`,`| Alpha-Verify | yes | partial | yes | 0.71 | CC BY 4.0 |`,`| BetaSupport | no | no | no | not reported | research only |`,`| GammaCite | yes | yes | yes | 0.64 | CC BY-SA 4.0 |`,`| DeltaGround | partial | no | yes | 0.58 | Apache 2.0 |`,``,`## Reading the table`,``,`Only two of the four report agreement at all.`].join(`
`),d=[`## Reproducing the scoring pass`,``,"The verifier is a single call per extracted claim; `--strict` is what",`turns an unsupported claim into a failure rather than a warning.`,``,"```bash",`python -m src.eval.faithfulness --input runs/2601.jsonl --strict --report out/faithfulness-report.json --max-claims 512`,"```",``,`Its output is one record per claim:`,``,"```json",`{"claim_id": "c-014", "supported": false, "evidence": [], "source": "arXiv:2601.00001"}`,"```"].join(`
`),f=[`# Partial briefing`,``,`The run retained an incomplete synthesis before verification failed.`,``,`## What remains useful`,``,`- Initial retrieval completed.`,`- Final claim verification did not complete.`].join(`
`),p={errorType:`verification_incomplete`,error:`Verification stopped before all claims could be checked.`},m={title:`Patterns/ReportReader`,component:a,loaders:[async()=>({renderer:await n()})],args:{markdown:c,renderer:null},render:(e,t)=>(0,s.jsx)(`div`,{className:`p-6`,children:(0,s.jsx)(a,{...e,renderer:o(t)})})},h={args:{markdown:``}},g={args:{markdown:c}},_={args:{markdown:l}},v={args:{markdown:u}},y={args:{markdown:d}},b={args:{markdown:f,failure:p}},x={args:{markdown:``,failure:p}},S={args:{markdown:l},render:e=>(0,s.jsx)(`div`,{className:`p-6`,children:(0,s.jsx)(a,{...e,renderer:null})})},C={args:{markdown:l,activeHeadingId:`where-the-disagreement-is`}},w={args:{markdown:u},globals:{theme:`dark`}},T={args:{markdown:f,failure:p},globals:{theme:`forced-colors`}},h.parameters={...h.parameters,docs:{...h.parameters?.docs,source:{originalSource:`{
  args: {
    markdown: ""
  }
}`,...h.parameters?.docs?.source},description:{story:`No briefing yet. Not a spinner, not a card with nothing in it.`,...h.parameters?.docs?.description}}},g.parameters={...g.parameters,docs:{...g.parameters?.docs,source:{originalSource:`{
  args: {
    markdown: SHORT
  }
}`,...g.parameters?.docs?.source}}},_.parameters={..._.parameters,docs:{..._.parameters?.docs,source:{originalSource:`{
  args: {
    markdown: LONG_WITH_HEADINGS
  }
}`,..._.parameters?.docs?.source},description:{story:`Long enough that the section rail earns its place.`,..._.parameters?.docs?.description}}},v.parameters={...v.parameters,docs:{...v.parameters?.docs,source:{originalSource:`{
  args: {
    markdown: WITH_WIDE_TABLE
  }
}`,...v.parameters?.docs?.source},description:{story:`Criterion 6: the table pans inside a labelled region; the page does not.`,...v.parameters?.docs?.description}}},y.parameters={...y.parameters,docs:{...y.parameters?.docs,source:{originalSource:`{
  args: {
    markdown: WITH_CODE_BLOCKS
  }
}`,...y.parameters?.docs?.source},description:{story:"Criterion 7's other half — `code` and `pre` on the token surfaces.",...y.parameters?.docs?.description}}},b.parameters={...b.parameters,docs:{...b.parameters?.docs,source:{originalSource:`{
  args: {
    markdown: PARTIAL,
    failure: PARTIAL_FAILURE
  }
}`,...b.parameters?.docs?.source},description:{story:"Criterion 1 / H5 / D-010 ruling 2. The failure is a banner ABOVE a\nbriefing that still renders, and the raw `error_type` sits under it\nunedited (RC-16). `ReportView.tsx:13-27` returns before this content.",...b.parameters?.docs?.description}}},x.parameters={...x.parameters,docs:{...x.parameters?.docs,source:{originalSource:`{
  args: {
    markdown: "",
    failure: PARTIAL_FAILURE
  }
}`,...x.parameters?.docs?.source},description:{story:`03 §2.2 row 15: failed, and there is genuinely nothing to show.`,...x.parameters?.docs?.description}}},S.parameters={...S.parameters,docs:{...S.parameters?.docs,source:{originalSource:`{
  args: {
    markdown: LONG_WITH_HEADINGS
  },
  render: args => <div className="p-6">
      <ReportReader {...args} renderer={null} />
    </div>
}`,...S.parameters?.docs?.source},description:{story:`The pipeline has not resolved yet. A still skeleton — 03 §3.7.`,...S.parameters?.docs?.description}}},C.parameters={...C.parameters,docs:{...C.parameters?.docs,source:{originalSource:`{
  args: {
    markdown: LONG_WITH_HEADINGS,
    activeHeadingId: "where-the-disagreement-is"
  }
}`,...C.parameters?.docs?.source},description:{story:`A heading the reader is currently at, marked in the rail.`,...C.parameters?.docs?.description}}},w.parameters={...w.parameters,docs:{...w.parameters?.docs,source:{originalSource:`{
  args: {
    markdown: WITH_WIDE_TABLE
  },
  globals: {
    theme: "dark"
  }
}`,...w.parameters?.docs?.source},description:{story:`03 §2.2 row 8 — the same layout on the dark token set.`,...w.parameters?.docs?.description}}},T.parameters={...T.parameters,docs:{...T.parameters?.docs,source:{originalSource:`{
  args: {
    markdown: PARTIAL,
    failure: PARTIAL_FAILURE
  },
  globals: {
    theme: "forced-colors"
  }
}`,...T.parameters?.docs?.source},description:{story:`The same, with the hue taken away entirely (RC-17).`,...T.parameters?.docs?.description}}},E=[`Empty`,`Short`,`LongWithHeadings`,`WithWideTable`,`WithCodeBlocks`,`PartialFromFailedRun`,`FailedWithNoBriefing`,`Loading`,`ActiveSection`,`Dark`,`ForcedColours`]})))()}D();export{C as ActiveSection,w as Dark,h as Empty,x as FailedWithNoBriefing,T as ForcedColours,S as Loading,_ as LongWithHeadings,b as PartialFromFailedRun,g as Short,y as WithCodeBlocks,v as WithWideTable,E as __namedExportsOrder,m as default};