import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{f as n,n as r}from"./tokens-BmyTjNhk.js";import{a as i,c as a,l as o,n as s,o as c,r as l,s as u,t as d}from"./errors-Ch6TWljv.js";import{n as f,r as p}from"./StatusBanner-DHqsKSvA.js";function m({failure:e,userTriggered:t=!1}){return(0,g.jsx)(f,{...u(e),userTriggered:t})}function h({heading:e,children:t}){return(0,g.jsxs)(`section`,{className:`flex flex-col gap-3`,children:[(0,g.jsx)(`h2`,{className:`text-ui-xs font-semibold uppercase text-ink-muted`,children:e}),(0,g.jsx)(`div`,{className:`flex flex-col gap-3`,children:t})]})}var g,_,v,y,b,x,S,C,w,T,E,D,O,k,A,j,M,N,P,F,I,L,R,z,B,V,H,U,W,G,K;function q(){return(q=e((()=>{g=t(),a(),n(),p(),_={title:`Patterns/StatusBanner`,component:f,args:{severity:`critical`,sentence:s.server_error.sentence}},v={unauthorized:{kind:`unauthorized`,status:401,message:``,raw:{detail:`missing_api_key`}},not_found:{kind:`not_found`,status:404,message:``,raw:{detail:`job_not_found`}},conflict:{kind:`conflict`,status:409,state:`running`,message:``,raw:{detail:`job_not_awaiting_review (status=running)`}},rate_limited:{kind:`rate_limited`,status:429,retryAfterSec:60,message:``,raw:{detail:{error:`rate_limited`,key_id:`shared`}}},validation:{kind:`validation`,status:422,fields:[{path:`query`,message:`String should have at most 8000 characters`}],message:``,raw:{detail:[]}},upstream_unavailable:{kind:`upstream_unavailable`,status:502,message:``,raw:{detail:`api_upstream_unavailable`}},proxy_misconfigured:{kind:`proxy_misconfigured`,status:503,message:``,raw:{detail:`api_proxy_misconfigured`}},server_error:{kind:`server_error`,status:500,message:``,raw:null},offline:{kind:`offline`,message:``,raw:TypeError(`Failed to fetch`)},timeout:{kind:`timeout`,message:``,raw:null},cancelled:{kind:`cancelled`,message:``,raw:null},unknown:{kind:`unknown`,status:null,message:``,raw:null}},y=Object.keys(s),b={kind:`rate_limited`,status:429,retryAfterSec:900,limitPerHour:20,message:``,raw:{detail:{error:`rate_limited`,key_id:`shared`,limit_per_hour:20}}},x=Object.keys(r),S={render:()=>(0,g.jsx)(`div`,{className:`flex flex-col gap-3 p-6`,children:x.map(e=>(0,g.jsx)(f,{severity:e,sentence:s.not_found.sentence,recovery:i[e]},e))})},C={...S,globals:{theme:`forced-colors`}},w={...S,globals:{theme:`dark`}},T={render:()=>(0,g.jsxs)(`div`,{className:`flex flex-col gap-6 p-6`,children:[(0,g.jsx)(h,{heading:`User-triggered failure — role=alert`,children:(0,g.jsx)(m,{failure:v.rate_limited,userTriggered:!0})}),(0,g.jsx)(h,{heading:`Became true on its own — ordinary content`,children:(0,g.jsx)(m,{failure:v.not_found})})]})},E={render:()=>(0,g.jsx)(f,{severity:`info`,word:s.not_found.word,mark:`dashed-square`,sentence:s.not_found.sentence,recovery:s.not_found.recovery})},D={render:()=>(0,g.jsx)(m,{failure:v.unauthorized})},O={render:()=>(0,g.jsx)(m,{failure:v.not_found})},k={render:()=>(0,g.jsx)(m,{failure:v.conflict})},A={render:()=>(0,g.jsx)(m,{failure:v.rate_limited,userTriggered:!0})},j={render:()=>(0,g.jsx)(m,{failure:b,userTriggered:!0})},M={render:()=>(0,g.jsx)(m,{failure:v.validation,userTriggered:!0})},N={render:()=>(0,g.jsx)(m,{failure:v.upstream_unavailable})},P={render:()=>(0,g.jsx)(m,{failure:v.upstream_unavailable})},F={render:()=>(0,g.jsx)(m,{failure:v.proxy_misconfigured})},I={render:()=>(0,g.jsx)(m,{failure:v.server_error})},L={render:()=>(0,g.jsx)(m,{failure:v.offline})},R={render:()=>(0,g.jsx)(m,{failure:v.timeout})},z={render:()=>(0,g.jsx)(m,{failure:v.cancelled})},B={render:()=>(0,g.jsx)(m,{failure:v.unknown})},V={render:()=>(0,g.jsx)(`div`,{className:`flex flex-col gap-3 p-6`,children:y.map(e=>(0,g.jsx)(m,{failure:v[e]},e))})},H=`SomeFutureExceptionName: unexpected empty synthesis buffer`,U={render:()=>(0,g.jsx)(`div`,{className:`flex flex-col gap-3 p-6`,children:l.map(e=>{let t=c(e,d[e].sentence);return(0,g.jsx)(f,{severity:`critical`,word:s.server_error.word,sentence:t.sentence,recovery:t.recovery,evidence:o(t.errorType,t.rawError)},e)})})},W={render:()=>{let e=c(`SomeFutureExceptionName`,H);return(0,g.jsx)(f,{severity:`critical`,word:s.server_error.word,sentence:e.sentence,recovery:e.recovery,evidence:o(e.errorType,e.rawError)})}},G={render:()=>{let e=c(null,null);return(0,g.jsx)(f,{severity:`critical`,word:s.server_error.word,sentence:e.sentence,recovery:e.recovery,evidence:o(e.errorType,e.rawError)})}},S.parameters={...S.parameters,docs:{...S.parameters?.docs,source:{originalSource:`{
  render: () => <div className="flex flex-col gap-3 p-6">
      {SEVERITIES.map(severity => <StatusBanner key={severity} severity={severity} sentence={FAILURE_COPY.not_found.sentence} recovery={SEVERITY_WORD[severity]} />)}
    </div>
}`,...S.parameters?.docs?.source}}},C.parameters={...C.parameters,docs:{...C.parameters?.docs,source:{originalSource:`{
  ...Severities,
  globals: {
    theme: "forced-colors"
  }
}`,...C.parameters?.docs?.source},description:{story:`RC-17's claim, with the hue removed: the words and the marks still differ.`,...C.parameters?.docs?.description}}},w.parameters={...w.parameters,docs:{...w.parameters?.docs,source:{originalSource:`{
  ...Severities,
  globals: {
    theme: "dark"
  }
}`,...w.parameters?.docs?.source}}},T.parameters={...T.parameters,docs:{...T.parameters?.docs,source:{originalSource:`{
  render: () => <div className="flex flex-col gap-6 p-6">
      <Section heading="User-triggered failure — role=alert">
        <Failure failure={FAILURES.rate_limited} userTriggered />
      </Section>
      <Section heading="Became true on its own — ordinary content">
        <Failure failure={FAILURES.not_found} />
      </Section>
    </div>
}`,...T.parameters?.docs?.source},description:{story:'The live-region rule (03 §7.3). Only the user-triggered failure is a\n`role="alert"`; the ambient one beside it is ordinary content, and\nneither is a second `role="status"` region.',...T.parameters?.docs?.description}}},E.parameters={...E.parameters,docs:{...E.parameters?.docs,source:{originalSource:`{
  render: () => <StatusBanner severity="info" word={FAILURE_COPY.not_found.word} mark="dashed-square" sentence={FAILURE_COPY.not_found.sentence} recovery={FAILURE_COPY.not_found.recovery} />
}`,...E.parameters?.docs?.source},description:{story:`The mark override, for a state whose shape is not its severity's default.`,...E.parameters?.docs?.description}}},D.parameters={...D.parameters,docs:{...D.parameters?.docs,source:{originalSource:`{
  render: () => <Failure failure={FAILURES.unauthorized} />
}`,...D.parameters?.docs?.source}}},O.parameters={...O.parameters,docs:{...O.parameters?.docs,source:{originalSource:`{
  render: () => <Failure failure={FAILURES.not_found} />
}`,...O.parameters?.docs?.source}}},k.parameters={...k.parameters,docs:{...k.parameters?.docs,source:{originalSource:`{
  render: () => <Failure failure={FAILURES.conflict} />
}`,...k.parameters?.docs?.source}}},A.parameters={...A.parameters,docs:{...A.parameters?.docs,source:{originalSource:`{
  render: () => <Failure failure={FAILURES.rate_limited} userTriggered />
}`,...A.parameters?.docs?.source}}},j.parameters={...j.parameters,docs:{...j.parameters?.docs,source:{originalSource:`{
  render: () => <Failure failure={RATE_LIMITED_WITH_HEADER} userTriggered />
}`,...j.parameters?.docs?.source},description:{story:"The 429 that consumes `Retry-After` and the body's `limit_per_hour`.",...j.parameters?.docs?.description}}},M.parameters={...M.parameters,docs:{...M.parameters?.docs,source:{originalSource:`{
  render: () => <Failure failure={FAILURES.validation} userTriggered />
}`,...M.parameters?.docs?.source}}},N.parameters={...N.parameters,docs:{...N.parameters?.docs,source:{originalSource:`{
  render: () => <Failure failure={FAILURES.upstream_unavailable} />
}`,...N.parameters?.docs?.source}}},P.parameters={...P.parameters,docs:{...P.parameters?.docs,source:{originalSource:`{
  render: () => <Failure failure={FAILURES.upstream_unavailable} />
}`,...P.parameters?.docs?.source},description:{story:`The name §4's state-coverage map uses for row F's 502.`,...P.parameters?.docs?.description}}},F.parameters={...F.parameters,docs:{...F.parameters?.docs,source:{originalSource:`{
  render: () => <Failure failure={FAILURES.proxy_misconfigured} />
}`,...F.parameters?.docs?.source}}},I.parameters={...I.parameters,docs:{...I.parameters?.docs,source:{originalSource:`{
  render: () => <Failure failure={FAILURES.server_error} />
}`,...I.parameters?.docs?.source}}},L.parameters={...L.parameters,docs:{...L.parameters?.docs,source:{originalSource:`{
  render: () => <Failure failure={FAILURES.offline} />
}`,...L.parameters?.docs?.source}}},R.parameters={...R.parameters,docs:{...R.parameters?.docs,source:{originalSource:`{
  render: () => <Failure failure={FAILURES.timeout} />
}`,...R.parameters?.docs?.source}}},z.parameters={...z.parameters,docs:{...z.parameters?.docs,source:{originalSource:`{
  render: () => <Failure failure={FAILURES.cancelled} />
}`,...z.parameters?.docs?.source}}},B.parameters={...B.parameters,docs:{...B.parameters?.docs,source:{originalSource:`{
  render: () => <Failure failure={FAILURES.unknown} />
}`,...B.parameters?.docs?.source}}},V.parameters={...V.parameters,docs:{...V.parameters?.docs,source:{originalSource:`{
  render: () => <div className="flex flex-col gap-3 p-6">
      {KINDS.map(kind => <Failure key={kind} failure={FAILURES[kind]} />)}
    </div>
}`,...V.parameters?.docs?.source},description:{story:`All twelve at once, in the union's order.`,...V.parameters?.docs?.description}}},U.parameters={...U.parameters,docs:{...U.parameters?.docs,source:{originalSource:`{
  render: () => <div className="flex flex-col gap-3 p-6">
      {MAPPED_ERROR_TYPES.map(errorType => {
      const described = describeErrorType(errorType, ERROR_TYPE_COPY[errorType].sentence);
      return <StatusBanner key={errorType} severity="critical" word={FAILURE_COPY.server_error.word} sentence={described.sentence} recovery={described.recovery} evidence={rawErrorEvidence(described.errorType, described.rawError)} />;
    })}
    </div>
}`,...U.parameters?.docs?.source}}},W.parameters={...W.parameters,docs:{...W.parameters?.docs,source:{originalSource:`{
  render: () => {
    const described = describeErrorType("SomeFutureExceptionName", RAW_MESSAGE);
    return <StatusBanner severity="critical" word={FAILURE_COPY.server_error.word} sentence={described.sentence} recovery={described.recovery} evidence={rawErrorEvidence(described.errorType, described.rawError)} />;
  }
}`,...W.parameters?.docs?.source},description:{story:"03 §2.2 row 15 and §8.3's *anything else*: the generic sentence AND the\nraw `error` text, visible without opening anything.",...W.parameters?.docs?.description}}},G.parameters={...G.parameters,docs:{...G.parameters?.docs,source:{originalSource:`{
  render: () => {
    const described = describeErrorType(null, null);
    return <StatusBanner severity="critical" word={FAILURE_COPY.server_error.word} sentence={described.sentence} recovery={described.recovery} evidence={rawErrorEvidence(described.errorType, described.rawError)} />;
  }
}`,...G.parameters?.docs?.source},description:{story:'An `error_type` the backend did not report at all. Still not "unknown".',...G.parameters?.docs?.description}}},K=[`Severities`,`ForcedColours`,`Dark`,`LiveRegions`,`OverriddenMark`,`Unauthorized`,`NotFound`,`Conflict`,`RateLimited`,`RateLimitedRetryAfter`,`Validation`,`UpstreamUnavailable`,`UpstreamDown`,`ProxyMisconfigured`,`ServerError`,`Offline`,`Timeout`,`Cancelled`,`Unknown`,`AllFailures`,`MappedErrorTypes`,`UnmappedErrorType`,`ErrorTypeNotReported`]})))()}q();export{V as AllFailures,z as Cancelled,k as Conflict,w as Dark,G as ErrorTypeNotReported,C as ForcedColours,T as LiveRegions,U as MappedErrorTypes,O as NotFound,L as Offline,E as OverriddenMark,F as ProxyMisconfigured,A as RateLimited,j as RateLimitedRetryAfter,I as ServerError,S as Severities,R as Timeout,D as Unauthorized,B as Unknown,W as UnmappedErrorType,P as UpstreamDown,N as UpstreamUnavailable,M as Validation,K as __namedExportsOrder,_ as default};