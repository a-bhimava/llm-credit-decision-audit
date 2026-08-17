import { AuditStudio } from "@/components/audit-studio";

export const metadata = { title: "Audit Studio", description: "Run a bounded, facts-only synthetic audit." };

export default function AuditPage() {
  return <AuditStudio />;
}
