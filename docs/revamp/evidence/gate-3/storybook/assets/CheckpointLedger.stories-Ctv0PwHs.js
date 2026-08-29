import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{n as t,t as n}from"./CheckpointLedger-BSFDhLul.js";function r(e,t){return{node:e,observedAt:t,stateDelta:{}}}var i,a,o,s,c,l,u,d,f,p,m,h,g;function _(){return(_=e((()=>{t(),i={title:`Patterns/CheckpointLedger`,component:n,args:{checkpoints:[],current:!0}},a=[r(`planner`,1e3),r(`searcher`,2e3),r(`synthesizer`,3e3)],o={args:{checkpoints:[]}},s={args:{checkpoints:[r(`planner`,1e3)]}},c={args:{checkpoints:a}},l={args:{checkpoints:Array.from({length:24},(e,t)=>r(`checkpoint_${t}`,t*1e3))}},u={args:{checkpoints:[r(`synthesizer`,9e3)],current:!0}},d={args:{checkpoints:a,current:!1}},f={args:{checkpoints:[r(`planner`,1e3),r(``,2e3)]}},p={args:{checkpoints:[r(`claim_decomposer`,1e3)]}},m={args:{checkpoints:a},globals:{theme:`dark`}},h={args:{checkpoints:a},globals:{theme:`forced-colors`}},o.parameters={...o.parameters,docs:{...o.parameters?.docs,source:{originalSource:`{
  args: {
    checkpoints: []
  }
}`,...o.parameters?.docs?.source},description:{story:`Nothing observed yet.

The spine passes \`empty="hidden"\` here and lets its own status line say
"No checkpoints observed on this connection"; on its own the ledger says
it, with the qualifier that makes it true.`,...o.parameters?.docs?.description}}},s.parameters={...s.parameters,docs:{...s.parameters?.docs,source:{originalSource:`{
  args: {
    checkpoints: [checkpoint("planner", 1_000)]
  }
}`,...s.parameters?.docs?.source}}},c.parameters={...c.parameters,docs:{...c.parameters?.docs,source:{originalSource:`{
  args: {
    checkpoints: THREE
  }
}`,...c.parameters?.docs?.source}}},l.parameters={...l.parameters,docs:{...l.parameters?.docs,source:{originalSource:`{
  args: {
    checkpoints: Array.from({
      length: 24
    }, (_, index) => checkpoint(\`checkpoint_\${index}\`, index * 1_000))
  }
}`,...l.parameters?.docs?.source},description:{story:`Long enough to pan.

04 §8.3 item 4: the LIST scrolls and the PAGE does not. Set the viewport
to 320 and drag — the reading column stays put, which is the same
property the CLS budget protects when a tick arrives.`,...l.parameters?.docs?.description}}},u.parameters={...u.parameters,docs:{...u.parameters?.docs,source:{originalSource:`{
  args: {
    checkpoints: [checkpoint("synthesizer", 9_000)],
    current: true
  }
}`,...u.parameters?.docs?.source},description:{story:"After a reconnect gap.\n\n`web/contract/sse/reconnect_gap.jsonl` records a `node_completed` for\n`searcher` published while nobody was subscribed. Redis pub/sub keeps no\nbacklog and the stream writes no `id:` line, so it is gone — and this is\nwhat the ledger shows on the NEW connection: what arrived on it, and\nnothing else. `searcher` appears nowhere on this page.",...u.parameters?.docs?.description}}},d.parameters={...d.parameters,docs:{...d.parameters?.docs,source:{originalSource:`{
  args: {
    checkpoints: THREE,
    current: false
  }
}`,...d.parameters?.docs?.source},description:{story:`The same ledger, after the connection that observed it ended.

The ticks are KEPT — they really were observed — and \`current\` is false,
which is what stops the surface implying they describe now (03 §5.4,
"Reconnecting: ticks kept, then a broken rule").`,...d.parameters?.docs?.description}}},f.parameters={...f.parameters,docs:{...f.parameters?.docs,source:{originalSource:`{
  args: {
    checkpoints: [checkpoint("planner", 1_000), checkpoint("", 2_000)]
  }
}`,...f.parameters?.docs?.source},description:{story:'A `node_completed` whose payload carried no usable label.\n\n"not reported", never "unknown". There is no vocabulary to fall back on:\nthe node set is configuration-dependent (`workflow.py:366-430`) and\n`state_delta` is an open scalar map, so absence is reported rather than\nnamed.',...f.parameters?.docs?.description}}},p.parameters={...p.parameters,docs:{...p.parameters?.docs,source:{originalSource:`{
  args: {
    checkpoints: [checkpoint("claim_decomposer", 1_000)]
  }
}`,...p.parameters?.docs?.source},description:{story:`An opaque label from a graph this client has never heard of (H11).`,...p.parameters?.docs?.description}}},m.parameters={...m.parameters,docs:{...m.parameters?.docs,source:{originalSource:`{
  args: {
    checkpoints: THREE
  },
  globals: {
    theme: "dark"
  }
}`,...m.parameters?.docs?.source}}},h.parameters={...h.parameters,docs:{...h.parameters?.docs,source:{originalSource:`{
  args: {
    checkpoints: THREE
  },
  globals: {
    theme: "forced-colors"
  }
}`,...h.parameters?.docs?.source}}},g=[`Empty`,`SingleCheckpoint`,`ThreeCheckpoints`,`Many`,`AfterReconnectGap`,`NotCurrent`,`UnknownNodeLabel`,`OpaqueLabel`,`Dark`,`ForcedColours`]})))()}_();export{u as AfterReconnectGap,m as Dark,o as Empty,h as ForcedColours,l as Many,d as NotCurrent,p as OpaqueLabel,s as SingleCheckpoint,c as ThreeCheckpoints,f as UnknownNodeLabel,g as __namedExportsOrder,i as default};