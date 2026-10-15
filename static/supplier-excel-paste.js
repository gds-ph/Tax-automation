(() => {
 const api=window.supplierPasteRows; if(!api)return;
 const {rows,deleted,update,formatBase,list,total}=api;
 const status=document.getElementById('supplier-paste-status');
 list.addEventListener('paste',event=>{
  const input=event.target.closest('input');
  if(!input||input.readOnly||!input.name)return;
  const text=event.clipboardData?.getData('text/plain')||'';
  if(!/[\t\r\n]/.test(text))return;
  event.preventDefault();
  try {
   const cells=window.eqExcelPaste.parse(text);
   const field=input.name.replace(/^rows-\d+-/,'');
   const editable=['payee','tin','atc','base','reference'];
   if(!editable.includes(field))return;
   let fields;
   if(cells[0].length===1)fields=[field];
   else if(field==='payee'&&cells[0].length===7)fields=['payee','tin','atc','base',null,null,'reference'];
   else if(field==='payee'&&cells[0].length===5)fields=editable;
   else throw Error('Paste one column into its matching field, or 5 or 7 columns starting in Supplier / payee.');
   if(cells.some(row=>/^(total|registered name|supplier \/ payee)$/i.test(row[0].trim())))throw Error('Exclude the header and Total row. No cells were changed.');
   const visible=rows().filter(r=>!r.hidden&&!deleted(r).checked);
   const start=visible.indexOf(input.closest('[data-transaction]'));
   if(start<0)return;
   const needed=Math.max(0,cells.length-(visible.length-start));
   const reusable=rows().filter(r=>r.hidden&&!deleted(r).checked);
   if(Number(total.value)+Math.max(0,needed-reusable.length)>100)throw Error('This paste exceeds the 100-row editor limit. Use Excel import for larger batches. No cells were changed.');
   cells.forEach(values=>values.forEach((value,index)=>{
    const name=fields[index];if(!name)return;
    if(value.trim().length>{payee:200,tin:17,atc:5,base:24,reference:300}[name])throw Error('A pasted '+name+' exceeds its field limit. No cells were changed.');
   }));
   for(let i=0;i<needed;i++){
    let row=reusable.shift();
    if(!row){
     const index=Number(total.value), t=document.createElement('template');
     t.innerHTML=document.getElementById('transaction-template').innerHTML.replaceAll('__prefix__',String(index));
     list.append(t.content);total.value=index+1;row=rows().at(-1);
    }
    row.hidden=false;visible.push(row);
   }
   update();
   cells.forEach((values,offset)=>values.forEach((value,index)=>{
    const name=fields[index];if(!name)return;
    const target=visible[start+offset].querySelector('[name$="-'+name+'"]');
    target.value=value.trim();target.dispatchEvent(new Event('input',{bubbles:true}));
    if(name==='base')formatBase(target);
    if(name==='atc')target.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
   }));
   status.textContent=cells.length+' row(s) pasted for the selected month. Review before saving.'+(fields.length===7?' Excel rates and withholding were ignored; the app calculates them.':'');
  } catch(error){status.textContent=error.message;}
  status.hidden=false;
 });
})();
