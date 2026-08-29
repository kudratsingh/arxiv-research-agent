import{n as e}from"./rolldown-runtime-CsOFd3vK.js";import{t}from"./jsx-runtime-CadfrxEJ.js";import{t as n}from"./IdentitySlot-BjnLwoTT.js";var r,i,a,o,s;function c(){return(c=e((()=>{r=t(),{expect:i}=__STORYBOOK_MODULE_TEST__,a={title:`Shell/IdentitySlot`,component:n},o={render:()=>(0,r.jsx)(`div`,{"data-identity-slot-probe":``,children:(0,r.jsx)(n,{})}),play:async({canvasElement:e})=>{let t=e.querySelector(`[data-identity-slot-probe]`);await i(t).toBeTruthy(),await i(t?.childElementCount).toBe(0),await i(t?.textContent).toBe(``)}},o.parameters={...o.parameters,docs:{...o.parameters?.docs,source:{originalSource:`{
  render: () => <div data-identity-slot-probe="">
      <IdentitySlot />
    </div>,
  play: async ({
    canvasElement
  }) => {
    const probe = canvasElement.querySelector("[data-identity-slot-probe]");
    await expect(probe).toBeTruthy();
    await expect(probe?.childElementCount).toBe(0);
    await expect(probe?.textContent).toBe("");
  }
}`,...o.parameters?.docs?.source},description:{story:`Nothing. Not an avatar, not a placeholder, not a zero-height box with a
border — the slot contributes no element and no text.`,...o.parameters?.docs?.description}}},s=[`Empty`]})))()}c();export{o as Empty,s as __namedExportsOrder,a as default};