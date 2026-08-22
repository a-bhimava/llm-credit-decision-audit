const yaml = require('js-yaml');
const fs = require('fs');

const data = yaml.load(fs.readFileSync('src/credit_audit/reasons/lexicon.yaml', 'utf8'));
fs.writeFileSync('web/lib/audit/lexicon.ts', `export const lexicon = ${JSON.stringify(data, null, 2)} as const;\n`);
