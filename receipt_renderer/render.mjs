import fs from "node:fs";
import { renderMessagePdf } from "./message-pdf.mjs";

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => input += chunk);
process.stdin.on("end", async () => {
  try {
    const { message, printedAt } = JSON.parse(input);
    const pdf = await renderMessagePdf(message, { printedAt: new Date(printedAt), timeZone: "Asia/Manila" });
    process.stdout.write(pdf);
  } catch (error) {
    console.error(error.stack || error.message || String(error));
    process.exitCode = 1;
  }
});
