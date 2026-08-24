import fs from 'fs';
const text = fs.readFileSync('web/lib/audit/policy.ts', 'utf-8');
const importLine = `import { policyDoc } from "./policy-doc";\n`;
const replaced = text.replace('} as const;', '} as const;\n\n(policy as any).doc = policyDoc;\n');
fs.writeFileSync('web/lib/audit/policy.ts', importLine + replaced);
