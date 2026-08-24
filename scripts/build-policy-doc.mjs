import fs from 'fs';
import path from 'path';

const mdText = fs.readFileSync('src/credit_audit/policy/policy.md', 'utf-8');

// Parse sections: find all headings starting with "## " or "# "
const sections = [];
const lines = mdText.split('\n');
let currentAnchor = null;
let currentTitle = null;
let currentStart = 0;
let currentEnd = 0;
let byteOffset = 0;

// simple parser that finds headings and their byte offsets
const headings = [];
for (let i = 0; i < mdText.length; i++) {
  if (mdText.slice(i, i+3) === '## ') {
    const end = mdText.indexOf('\n', i);
    const line = mdText.slice(i+3, end);
    const match = line.match(/^(\d+(?:\.\d+)*)\s+(.*)$/);
    if (match) {
      headings.push({ anchor: match[1], title: match[2], start: i });
    }
  }
}

for (let j = 0; j < headings.length; j++) {
  const h = headings[j];
  const next = headings[j+1];
  h.end = next ? next.start : mdText.length;
}

const doc = {
  text: mdText,
  sections: headings
};

fs.writeFileSync('web/lib/audit/policy-doc.ts', 
  `export const policyDoc = ${JSON.stringify(doc, null, 2)};\n`
);
console.log("Created policy-doc.ts");
