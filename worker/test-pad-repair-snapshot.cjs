// Offline contracts only: never launches PAD, eBIRForms or a submission.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const flow = fs.readFileSync(path.join(root, 'docs/pad-actions/Stage2_Submit_1601EQ.actions.txt'), 'utf8');
const monthly = fs.readFileSync(path.join(root, 'docs/pad-actions/Stage1_Prepare_0619E.actions.txt'), 'utf8');
const resend = "Resend your Tax Return to eBIRForms Online?\n\nClick OK to continue, or Cancel to stop.";
const normal = "Please ensure that you have INTERNET access and a VALID email address is indicated in your tax return.\n\nAre you sure you want to submit?";
for (const literal of [resend, normal]) assert.ok(flow.includes(literal), 'Exact LF confirmation must be preserved');
assert.match(flow, /IF ValidateEnabled = \$'''true''' THEN/);
assert.match(flow, /IF SubmitEnabled <> \$'''true''' THEN/);
assert.ok(flow.indexOf('AttributeValue=> ValidateEnabled') < flow.indexOf('IF ApprovedForSubmission = True THEN'));
assert.ok(flow.includes('ExpectedReturnPeriod = ApprovedReturnPeriod AND ExpectedSavedReturnName = ApprovedSavedReturnName'));
assert.ok(flow.includes('Files[0].FullName <> ApprovedXmlPath'));
assert.ok(flow.includes('Workstation.TakeScreenshot.TakeScreenshotAndSaveToFile'));
assert.match(monthly, /IF PreparationPrintEnabled <> \$'''true''' THEN/);
for (const text of [flow, monthly]) {
  assert.ok(!text.includes('[ControlRepository]'));
  assert.ok(!text.includes('iVBORw0KGgo'), 'Do not publish embedded screenshots');
}
console.log('PASS: confirmation LF, enabled-state guards, approval identity, screenshot and export privacy contracts');
