import styles from "./EvidenceLabel.module.css";

// The eight labels docs/INTERFACE_DESIGN.md section 2 requires used
// consistently everywhere a claim's trust level is shown.
export type EvidenceKind =
  | "observed"
  | "user_confirmed"
  | "inferred"
  | "verified_in_fixture"
  | "question"
  | "unresolved"
  | "inconclusive"
  | "rejected";

const LABEL: Record<EvidenceKind, string> = {
  observed: "Observed",
  user_confirmed: "User-confirmed",
  inferred: "Inferred",
  verified_in_fixture: "Verified in fixture",
  question: "Question",
  unresolved: "Unresolved",
  inconclusive: "Inconclusive",
  rejected: "Rejected",
};

export interface EvidenceLabelProps {
  kind: EvidenceKind;
}

// Color is secondary here by construction: the text IS the label (section 3,
// "Color reinforces meaning but never carries meaning alone"), the `data-kind`
// attribute only tints it.
export function EvidenceLabel({ kind }: EvidenceLabelProps) {
  return (
    <span className={styles.label} data-kind={kind}>
      {LABEL[kind]}
    </span>
  );
}
