import type { ReactNode } from "react";
import styles from "./StateNotice.module.css";

// docs/INTERFACE_DESIGN.md section 8: every screen explicitly supports a set
// of interaction states. This covers the four with their own visible notice;
// "loading"/"streaming" use StageProgress (not built yet) instead of this.
export type StateKind = "pristine" | "empty" | "partial" | "failure";

export interface StateNoticeProps {
  kind: StateKind;
  title: string;
  children?: ReactNode;
}

// Section 10: "Status changes use polite live regions; failures use alerts."
const ROLE: Record<StateKind, "status" | "alert"> = {
  pristine: "status",
  empty: "status",
  partial: "status",
  failure: "alert",
};

export function StateNotice({ kind, title, children }: StateNoticeProps) {
  return (
    <div
      className={styles.notice}
      data-kind={kind}
      role={ROLE[kind]}
      aria-live={ROLE[kind] === "alert" ? "assertive" : "polite"}
    >
      <p className={styles.title}>{title}</p>
      {children !== undefined && <div className={styles.body}>{children}</div>}
    </div>
  );
}
