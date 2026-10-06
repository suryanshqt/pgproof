import styles from "./MetricRule.module.css";

export interface MetricRuleProps {
  count: number;
  label: string;
}

// docs/INTERFACE_DESIGN.md section 5: "required/open/verified/unresolved
// counts as quiet ruled metrics" — a number plus a label, never a colorful
// card or a fabricated score.
export function MetricRule({ count, label }: MetricRuleProps) {
  return (
    <div className={styles.rule}>
      <span className={`${styles.count} pgp-tabular-nums`}>{count}</span>
      <span className={styles.label}>{label}</span>
    </div>
  );
}
