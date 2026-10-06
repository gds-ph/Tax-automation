import PDFDocument from 'pdfkit';
let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  try {
    const {data: d, amounts} = JSON.parse(input);
    const doc = new PDFDocument({size: 'A4', margin: 24, info: {Title: '1601C draft layout sample'}});
    doc.pipe(process.stdout);
    const x = 24, w = 547;
    function box(y, h, title, value, bx=x, bw=w) {
      doc.rect(bx,y,bw,h).fillAndStroke('#f2f2f2','#333');
      doc.fillColor('#111').font('Helvetica').fontSize(7).text(title,bx+5,y+4,{width:bw-10});
      doc.font('Helvetica-Bold');
      let size=9;
      while(size>4 && doc.fontSize(size).heightOfString(String(value),{width:bw-10})>h-18) size-=0.5;
      doc.fontSize(size).text(String(value),bx+5,y+16,{width:bw-10});
    }
    function band(y, text) {
      doc.rect(x,y,w,17).fillAndStroke('#ddd','#222');
      doc.fillColor('#111').font('Helvetica-Bold').fontSize(9).text(text,x,y+4,{width:w,align:'center'});
    }
    doc.fillColor('#a32626').fontSize(10).text('DRAFT SAMPLE — NOT FOR FILING',x,22,{width:w,align:'center'});
    doc.fillColor('#111').font('Helvetica-Bold').fontSize(23).text('1601-C',x,45);
    doc.font('Helvetica').fontSize(8).text('January 2018 layout reference',x,73);
    doc.font('Helvetica-Bold').fontSize(14).text('Monthly Remittance Return',165,44,{width:400,align:'center'});
    doc.fontSize(11).text('of Income Taxes Withheld on Compensation',165,65,{width:400,align:'center'});
    box(94,36,'1 For the month (MM/YYYY)',`${String(d.month).padStart(2,'0')}/${d.year}`,x,130);
    box(94,36,'2 Amended?',d.amended,154,100); box(94,36,'3 Taxes withheld?',d.withheld,254,110);
    box(94,36,'4 Sheets',d.sheets,364,95); box(94,36,'5 ATC',d.atc,459,112);
    band(130,'PART I — BACKGROUND INFORMATION');
    box(147,34,'6 Taxpayer Identification Number',d.tin,x,420);box(147,34,'7 RDO code',d.rdo,444,127);
    box(181,38,"8 Withholding agent's name",d.name);
    box(219,52,'9 Registered address',d.address,x,445);box(219,52,'9A ZIP code',d.zip,469,102);
    box(271,34,'10 Contact number',d.phone,x,260);box(271,34,'11 Category of withholding agent',d.category,284,287);
    box(305,34,'12 Email address',d.email);
    box(339,36,'13 Availing of tax relief?',d.relief,x,200);box(339,36,'13A If yes, specify',d.relief_details,224,347);
    band(375,'PART II — COMPUTATION OF TAX');
    let y=392;
    for (const [n,label] of Object.entries(amounts)) {
      doc.rect(x,y,w,20).fillAndStroke(Number(n)%2 ? '#f3f3f3':'#fff','#aaa');
      doc.fillColor('#111').font('Helvetica').fontSize(7).text(`${n}  ${label}`,x+4,y+5,{width:398,height:15});
      doc.rect(435,y+2,132,16).stroke('#888');
      doc.fontSize(9).text(Number(d[`amount_${n}`]).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}),439,y+5,{width:124,align:'right'});
      y+=20;
    }
    doc.font('Helvetica').fontSize(8).fillColor('#a32626').text('Sample of the visible fields through item 31. Amounts are user-entered; totals are not calculated or tax-validated. This is not the complete official return.',x,y+12,{width:w});
    doc.end();
  } catch (error) { console.error('Unable to render sample form'); process.exitCode=1; }
});
