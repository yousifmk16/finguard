import { useState } from "react";
import Icon from "@/components/common/Icon";
import SeverityBadge from "@/components/common/SeverityBadge";
import { useRole } from "@/features/auth/useRole";

interface PolicyRule {
  id: string;
  rule: string;
  scope: string;
  threshold: string;
  severity: "high" | "medium" | "low";
  owner: string;
  hits24h: number;
  active: boolean;
}

const INITIAL_RULES: PolicyRule[] = [
  { id: "POL-001", rule: "Spike > 3x baseline", scope: "all services", threshold: "3.0x", severity: "high", owner: "platform", hits24h: 12, active: true },
  { id: "POL-002", rule: "Sustained drift > 48h", scope: "compute, storage", threshold: "48h window", severity: "high", owner: "platform", hits24h: 3, active: true },
  { id: "POL-003", rule: "New service detected", scope: "all accounts", threshold: "first seen", severity: "medium", owner: "security", hits24h: 1, active: true },
  { id: "POL-004", rule: "Region anomaly", scope: "non-primary regions", threshold: "any spend", severity: "medium", owner: "platform", hits24h: 7, active: true },
  { id: "POL-005", rule: "Weekend spike", scope: "all services", threshold: "1.5x weekday avg", severity: "low", owner: "finops", hits24h: 0, active: false },
  { id: "POL-006", rule: "Budget threshold", scope: "tagged accounts", threshold: "80% budget", severity: "medium", owner: "finops", hits24h: 2, active: true },
  { id: "POL-007", rule: "Idle resource cost", scope: "compute", threshold: "> $50/day idle", severity: "low", owner: "platform", hits24h: 4, active: true },
  { id: "POL-008", rule: "Cross-account transfer", scope: "all accounts", threshold: "any transfer", severity: "high", owner: "security", hits24h: 0, active: false },
];

const EMPTY_RULE: Omit<PolicyRule, "id" | "hits24h"> = {
  rule: "",
  scope: "",
  threshold: "",
  severity: "medium",
  owner: "",
  active: true,
};

export default function PoliciesPage() {
  const { isAdmin } = useRole();
  const [rules, setRules] = useState(INITIAL_RULES);
  const [editing, setEditing] = useState<PolicyRule | null>(null);
  const [adding, setAdding] = useState(false);

  const toggleRule = (id: string) => {
    if (!isAdmin) return;
    setRules((prev) => prev.map((r) => (r.id === id ? { ...r, active: !r.active } : r)));
  };

  const saveEdit = (updated: PolicyRule) => {
    setRules((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
    setEditing(null);
  };

  const saveNew = (draft: Omit<PolicyRule, "id" | "hits24h">) => {
    const nextNum = rules.length + 1;
    const id = `POL-${String(nextNum).padStart(3, "0")}`;
    setRules((prev) => [...prev, { ...draft, id, hits24h: 0 }]);
    setAdding(false);
  };

  const activeCount = rules.filter((r) => r.active).length;

  return (
    <div className="page fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">Policies</h1>
          <div className="page-sub">
            <span className="mono">{activeCount}</span> active rules ·{" "}
            <span className="mono">{rules.length}</span> total
          </div>
        </div>
        {isAdmin && (
          <div className="page-actions">
            <button className="btn" type="button" onClick={() => setAdding(true)}>
              <Icon name="policy" size={14} /> Add rule
            </button>
          </div>
        )}
      </div>

      <div className="table-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th style={{ width: 48 }} />
              <th style={{ width: 80 }}>ID</th>
              <th>RULE</th>
              <th>SCOPE</th>
              <th>THRESHOLD</th>
              <th style={{ width: 80 }}>SEV</th>
              <th>OWNER</th>
              <th className="num">HITS 24H</th>
              <th style={{ width: 70 }}>STATE</th>
              {isAdmin && <th style={{ width: 40 }} />}
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id} style={{ opacity: r.active ? 1 : 0.5 }}>
                <td>
                  <button
                    type="button"
                    className={`toggle ${r.active ? "on" : ""}`}
                    onClick={() => toggleRule(r.id)}
                    disabled={!isAdmin}
                    aria-label={`Toggle ${r.id}`}
                  >
                    <span className="toggle-knob" />
                  </button>
                </td>
                <td className="mono" style={{ color: "var(--text-mute)", fontSize: 11 }}>{r.id}</td>
                <td>{r.rule}</td>
                <td className="mono" style={{ color: "var(--text-mute)", fontSize: 11 }}>{r.scope}</td>
                <td className="mono" style={{ fontSize: 11 }}>{r.threshold}</td>
                <td><SeverityBadge severity={r.severity} /></td>
                <td style={{ color: "var(--text-2)", fontSize: 12 }}>{r.owner}</td>
                <td className="num mono">{r.hits24h}</td>
                <td>
                  <span className="mono" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: "0.04em", color: r.active ? "var(--accent)" : "var(--text-dim)" }}>
                    {r.active ? "ACTIVE" : "OFF"}
                  </span>
                </td>
                {isAdmin && (
                  <td>
                    <button className="btn ghost sm" type="button" onClick={() => setEditing(r)} style={{ padding: "2px 6px" }}>
                      <Icon name="settings" size={13} />
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!isAdmin && (
        <div style={{ padding: "10px 14px", background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: "var(--r-md)", marginTop: 14, fontSize: 12, color: "var(--text-mute)" }}>
          Policy toggles are read-only for analyst accounts. Contact an admin to modify rules.
        </div>
      )}

      {editing && (
        <RuleModal
          title="Edit rule"
          initial={editing}
          onSave={(draft) => saveEdit({ ...editing, ...draft })}
          onClose={() => setEditing(null)}
        />
      )}

      {adding && (
        <RuleModal
          title="Add rule"
          initial={EMPTY_RULE}
          onSave={saveNew}
          onClose={() => setAdding(false)}
        />
      )}
    </div>
  );
}

type RuleDraft = Omit<PolicyRule, "id" | "hits24h">;

function RuleModal({
  title,
  initial,
  onSave,
  onClose,
}: {
  title: string;
  initial: RuleDraft;
  onSave: (draft: RuleDraft) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<RuleDraft>({ ...initial });
  const [error, setError] = useState("");

  const set = (key: keyof RuleDraft, value: string | boolean) =>
    setForm((f) => ({ ...f, [key]: value }));

  const handleSave = () => {
    if (!form.rule.trim()) { setError("Rule name is required."); return; }
    if (!form.scope.trim()) { setError("Scope is required."); return; }
    if (!form.threshold.trim()) { setError("Threshold is required."); return; }
    if (!form.owner.trim()) { setError("Owner is required."); return; }
    onSave(form);
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "oklch(0 0 0 / 0.6)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200 }} onClick={onClose}>
      <div style={{ background: "var(--surface-1)", border: "1px solid var(--border)", borderRadius: "var(--r-lg)", width: 480, padding: 24, display: "flex", flexDirection: "column", gap: 16 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ fontWeight: 600, fontSize: 14 }}>{title}</div>
          <button type="button" className="btn ghost sm" onClick={onClose} style={{ padding: "2px 8px" }}>✕</button>
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          <Field label="Rule name">
            <input className="input" value={form.rule} onChange={(e) => set("rule", e.target.value)} placeholder="e.g. Spike > 3x baseline" autoFocus />
          </Field>
          <Field label="Scope">
            <input className="input" value={form.scope} onChange={(e) => set("scope", e.target.value)} placeholder="e.g. all services, compute" />
          </Field>
          <Field label="Threshold">
            <input className="input" value={form.threshold} onChange={(e) => set("threshold", e.target.value)} placeholder="e.g. 3.0x, 80% budget" />
          </Field>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="Severity">
              <select className="select" value={form.severity} onChange={(e) => set("severity", e.target.value)}>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </Field>
            <Field label="Owner">
              <input className="input" value={form.owner} onChange={(e) => set("owner", e.target.value)} placeholder="e.g. platform, finops" />
            </Field>
          </div>
          <Field label="Active">
            <button type="button" className={`toggle ${form.active ? "on" : ""}`} onClick={() => set("active", !form.active)}>
              <span className="toggle-knob" />
            </button>
          </Field>
        </div>

        {error && <div style={{ fontSize: 12, color: "var(--sev-high)" }}>{error}</div>}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button type="button" className="btn" onClick={handleSave}>Save</button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "grid", gap: 5 }}>
      <label style={{ fontSize: 11, fontFamily: "var(--mono)", color: "var(--text-mute)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</label>
      {children}
    </div>
  );
}
