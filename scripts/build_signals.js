const fs = require('fs');

const data = JSON.parse(fs.readFileSync('src/credit_audit/interventions/data/demographic_signals.json', 'utf8'));
fs.writeFileSync('web/lib/audit/interventions/signals_data.ts', `export const demographicSignals = ${JSON.stringify(data, null, 2)} as const;\n`);
