/* Searchable confirmation PDFs, using the Gmail print layout. */
import PDFDocument from "pdfkit";

/*
 * Blocks and runs.
 *
 * A BIR confirmation is not prose: it is bold headings, single lines of
 * label-and-value, and bulleted lists of payment channels. Flattening it to
 * plain text throws away exactly the structure that makes it readable, so the
 * body is parsed into blocks (a line, or a list item) of runs (a stretch of
 * text, bold or not) and drawn with that structure intact.
 *
 * This is not a general HTML engine. It handles the tags this mail actually
 * uses and ignores the rest, which is the right trade for a mailbox of
 * system-generated government notices.
 */
const BLOCK_END = /^\/(?:p|div|tr|h[1-6]|li|table|ul|ol)$/i;

function decodeEntities(value) {
  return value
    .replace(/&nbsp;/gi, " ")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
    .replace(/&amp;/gi, "&"); // last, so &amp;lt; does not become <
}

/**
 * @returns {{list: boolean, runs: {text: string, bold: boolean}[]}[]} one entry
 *   per rendered line; an entry with no runs is a blank line.
 */
function parseBlocks(html) {
  const source = String(html)
    .replace(/<(script|style|head)[\s\S]*?<\/\1>/gi, "")
    .replace(/<!--[\s\S]*?-->/g, "");

  const blocks = [];
  let current = { list: false, runs: [] };
  let bold = 0;

  const flush = (asList = false) => {
    blocks.push(current);
    current = { list: asList, runs: [] };
  };

  // Walk tags and the text between them in one pass.
  const token = /<\/?([a-z0-9]+)[^>]*>|([^<]+)/gi;
  let match;
  while ((match = token.exec(source)) !== null) {
    const [, tag, text] = match;

    if (text !== undefined) {
      // Tabs are why this exists at all: pdfkit renders a tab as garbage
      // glyphs, and BIR puts one between every label and its value.
      const clean = decodeEntities(text).replace(/[\t\r]+/g, " ").replace(/\n+/g, " ");
      if (clean.trim()) current.runs.push({ text: clean, bold: bold > 0 });
      continue;
    }

    const name = tag.toLowerCase();
    const closing = match[0].startsWith("</");

    if (name === "br") flush(current.list);
    else if (name === "b" || name === "strong") bold += closing ? -1 : 1;
    else if ((name === "ul" || name === "ol") && !closing) {
      if (current.runs.length) flush();
      flush();
    }
    else if (name === "li" && !closing) {
      if (current.runs.length) flush();
      current.list = true;
    }
    else if (BLOCK_END.test(`/${name}`) && closing) flush(false);

    if (bold < 0) bold = 0;
  }
  flush();

  // Collapse runs of blank lines: a mail full of <br><br><br> should not open
  // half a page down.
  const tidied = [];
  for (const block of blocks) {
    const blank = !block.runs.length;
    if (blank && (!tidied.length || !tidied[tidied.length - 1].runs.length)) continue;
    tidied.push(block);
  }
  while (tidied.length && !tidied[tidied.length - 1].runs.length) tidied.pop();
  return tidied;
}

/** Plain-text bodies become one block per line, with the same tab fix. */
function textToBlocks(text) {
  return String(text).replace(/\t/g, " ").split(/\r?\n/).map((line) => {
    const value = line.trim();
    if (!value) return { list: false, runs: [] };
    const bullet = value.match(/^(?:[-*•]|â€¢)\s+(.*)$/);
    if (bullet) return { list: true, runs: [{ text: bullet[1], bold: false }] };
    const bold = /^(This confirms receipt|FOR RETURNS WITH TAX PAYABLE:|Please pay through|Land Bank of the Philippines|DBP PayTax Online|Unionbank of the Philippines|Taxpayer Agent\/ Tax Software Provider-TSP|This is a system-generated email|Bureau of Internal Revenue)/i.test(value);
    return { list: false, runs: [{ text: value, bold }] };
  });
}

/**
 * Reduce an HTML body to readable text. Kept for the caller that needs a
 * string rather than blocks — the reference parser reads the raw body itself.
 */
function htmlToText(html) {
  return String(html)
    // Anything scripted or styled contributes no readable text.
    .replace(/<(script|style|head)[\s\S]*?<\/\1>/gi, "")
    .replace(/<!--[\s\S]*?-->/g, "")
    // Structural tags become the line breaks a reader expects.
    .replace(/<\/(p|div|tr|h[1-6]|li|table)>/gi, "\n")
    .replace(/<br\s*\/?>/gi, "\n")
    // BIR confirmations list the ePayment channels as <li>; without a marker
    // the items read as unrelated lines.
    .replace(/<li\b[^>]*>/gi, "• ")
    // Table cells run together otherwise.
    .replace(/<\/t[dh]>/gi, "  ")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function bodyText(message) {
  if (message.text && message.text.trim()) return message.text.trim();
  if (message.html) return htmlToText(message.html);
  return "(no message body)";
}

/*
 * A BIR submission already has a name, and it is the one the accountants search
 * for. Two shapes appear in this mailbox:
 *
 *   eBIRForms  "File name: 010243153000-0619E-082026.xml"
 *   eSubmission "ACKNOWLEDGEMENT RECEIPT NUMBER: 20260904-V783748"
 *
 * Both are matched against the body rather than the subject, which is identical
 * across hundreds of these mails and so identifies nothing.
 */
// The .xml is required and greedy on purpose. Made optional, the match ends at
// the first hyphen and "010243153000-0619E-082026" is filed as "010243153000",
// which loses the form and the period — the parts that identify the return.
const BIR_FILE_NAME = /File\s*name\s*[:\-]\s*([^\s<>"']{6,150})\.xml\b/i;
// Same line without the extension, for any variant that omits it.
const BIR_FILE_NAME_BARE = /File\s*name\s*[:\-]\s*([A-Za-z0-9][A-Za-z0-9._-]{5,150})/i;
const ACK_NUMBER = /ACKNOWLEDGE?MENT\s+RECEIPT\s+NUMBER\s*[:\-]\s*([A-Za-z0-9-]{6,60})/i;

/** Windows-illegal characters, and the spacing a share tolerates badly. */
function safeStem(value) {
  return String(value)
    .replace(/[\\/:*?"<>|]/g, "-")
    // eslint-disable-next-line no-control-regex
    .replace(/[\x00-\x1f]/g, "")
    .replace(/\s+/g, " ")
    .replace(/^[\s.]+|[\s.]+$/g, "")
    .slice(0, 150)
    .trim();
}

/**
 * The name a saved email is offered under. The BIR reference wins where the
 * email carries one; everything else falls back to a date-led name, which at
 * least sorts sensibly in a client folder.
 */
export function suggestName(message) {
  const text = bodyText(message);
  const reference = text.match(BIR_FILE_NAME)
    || text.match(ACK_NUMBER)
    || text.match(BIR_FILE_NAME_BARE);
  if (reference) {
    const stem = safeStem(reference[1]);
    if (stem) return `${stem}.pdf`;
  }
  const date = (message.date || new Date().toISOString()).slice(0, 10);
  const subject = safeStem(message.subject || "email") || "email";
  return `${date} ${subject}.pdf`;
}

const BODY_SIZE = 10;
const LEFT = 27;
// Gmail's print view keeps the rule close to the page edge, then insets the
// message body beneath the metadata.
const BODY_LEFT = 47;

function gmailLogo(doc) {
  // Vector artwork stays sharp when the PDF is printed or zoomed.
  doc.save().lineWidth(6).lineCap("round");
  doc.moveTo(30, 63).lineTo(30, 46).stroke("#4285f4");
  doc.moveTo(52, 63).lineTo(52, 46).stroke("#34a853");
  doc.moveTo(30, 46).lineTo(41, 54).lineTo(52, 46).stroke("#ea4335");
  doc.moveTo(30, 46).lineTo(30, 50).stroke("#c5221f");
  doc.moveTo(52, 46).lineTo(52, 50).stroke("#fbbc04");
  doc.restore();
  doc.font("Helvetica").fontSize(23).fillColor("#333333").text("Gmail", 65, 44);
}

function drawBlock(doc, block, width) {
  const left = BODY_LEFT + (block.list ? 24 : 0);
  doc.font("Helvetica").fontSize(BODY_SIZE).fillColor("black");
  if (doc.y + 12 > doc.page.height - doc.page.margins.bottom) doc.addPage();
  if (block.list) doc.text("•", left - 12, doc.y, { lineBreak: false });
  block.runs.forEach((run, index) => {
    doc.font(run.bold ? "Helvetica-Bold" : "Helvetica");
    doc.text(run.text, index === 0 ? left : undefined, undefined, {
      width: width - (left - LEFT), continued: index < block.runs.length - 1,
      lineGap: 0
    });
  });
}

/** Render the original message content inside a Gmail-style print header. */
export function renderMessagePdf(message, options = {}) {
  return new Promise((resolve, reject) => {
    const printedAt = options.printedAt || new Date();
    const timeZone = options.timeZone || "Asia/Manila";
    const subject = message.subject || "(no subject)";
    const doc = new PDFDocument({
      // The filed return is Legal size (8.5 x 14 in). Keep the receipt on
      // the same sheet so the merged package has one consistent page format.
      size: "LEGAL", bufferPages: true,
      margins: { top: 36, bottom: 36, left: LEFT, right: LEFT },
      info: { Title: subject, Author: message.from || "", CreationDate: printedAt }
    });
    const chunks = [];
    doc.on("data", chunk => chunks.push(chunk));
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);
    const width = doc.page.width - LEFT * 2;
    const rule = y => doc.moveTo(LEFT, y).lineTo(LEFT + width, y)
      .lineWidth(0.6).strokeColor("#888888").stroke();

    gmailLogo(doc);
    // Display names come from message metadata or optional mailbox configuration.
    const accountName = options.accountName ?? process.env.GMAIL_PRINT_ACCOUNT_NAME;
    const account = accountName && message.to && !message.to.includes("<")
      ? `${accountName} <${message.to}>` : message.to || "";
    doc.font("Helvetica-Bold").fontSize(10).fillColor("black")
      .text(account, 190, 50, { width: width - 163, align: "right" });
    rule(Math.max(84, doc.y + 12));
    doc.font("Helvetica-Bold").fontSize(14).text(subject, LEFT, Math.max(92, doc.y + 20), { width });
    doc.font("Helvetica").fontSize(10).text("1 message", LEFT, doc.y, { width });
    const separatorY = doc.y + 5;
    rule(separatorY);
    const metaY = separatorY + 7;
    const sender = String(message.from || "");
    const senderParts = sender.match(/^(.*?)\s*(<[^>]+>)$/);
    const senderName = senderParts ? senderParts[1].replace(/^['"]|['"]$/g, "") : sender;
    if (senderParts) {
      doc.font("Helvetica-Bold").text(senderName, LEFT, metaY, { width: width * 0.62, continued: true });
      doc.font("Helvetica").text(` ${senderParts[2]}`, { continued: false });
    } else doc.font("Helvetica-Bold").fontSize(10).text(sender, LEFT, metaY, { width: width * 0.62 });
    const senderBottom = doc.y;
    if (message.date && Number.isFinite(new Date(message.date).getTime())) {
      const date = new Date(message.date);
      const day = date.toLocaleDateString("en-US", {
        weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone
      });
      const time = date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone });
      doc.font("Helvetica").fontSize(10).text(`${day} at ${time}`, LEFT + width * 0.64, metaY,
        { width: width * 0.36, align: "right" });
    }
    doc.font("Helvetica").fontSize(10).text(`To: ${message.to || ""}`, LEFT,
      Math.max(senderBottom, doc.y), { width });
    doc.y += 12;

    const blocks = message.html ? parseBlocks(message.html) : textToBlocks(message.text || "(no message body)");
    for (const block of blocks) {
      if (!block.runs.length) doc.y += 11;
      else drawBlock(doc, block, width);
    }
    if (message.attachments?.length) {
      doc.y += 12;
      drawBlock(doc, { list: false, runs: [{ text: "Attachments", bold: true }] }, width);
      for (const attachment of message.attachments) {
        drawBlock(doc, { list: true, runs: [{ text: attachment.filename, bold: false }] }, width);
      }
    }

    const count = doc.bufferedPageRange().count;
    const stamp = printedAt.toLocaleString("en-US", {
      month: "numeric", day: "numeric", year: "2-digit", hour: "numeric", minute: "2-digit", timeZone
    });
    const messageUrl = message.id ? `https://mail.google.com/mail/u/0/#all/${encodeURIComponent(message.threadId || message.id)}` : "";
    for (let page = 0; page < count; page++) {
      doc.switchToPage(page);
      doc.font("Helvetica").fontSize(8).fillColor("black");
      doc.text(stamp, 16, 14, { lineBreak: false });
      doc.text(`Gmail - ${subject}`, 190, 14, { width: 300, height: 12, ellipsis: true });
      doc.text(messageUrl, 16, doc.page.height - 21,
        { width: width - 20, height: 10, ellipsis: true, lineBreak: false });
      doc.text(`${page + 1}/${count}`, doc.page.width - 40, doc.page.height - 21, { lineBreak: false });
    }
    doc.end();
  });
}
