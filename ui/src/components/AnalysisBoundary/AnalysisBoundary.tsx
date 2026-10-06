import styles from "./AnalysisBoundary.module.css";

// docs/INTERFACE_DESIGN.md section 4's semantic marks, shared with the CLI
// (pgproof.cli.rendering.marks.Mark) so terminal and browser agree on
// vocabulary (section 1, principle 6).
export type Mark = "ok" | "attention" | "failure" | "unavailable";

const GLYPH: Record<Mark, string> = {
  ok: "✓",
  attention: "!",
  failure: "×",
  unavailable: "○",
};

export interface AnalysisBoundaryProps {
  mark: Mark;
  children: string;
}

// "Icons never appear without nearby text" (section 4) — the glyph is
// decorative and hidden from assistive tech; the sentence carries the
// meaning on its own.
export function AnalysisBoundary({ mark, children }: AnalysisBoundaryProps) {
  return (
    <p className={styles.line} data-mark={mark}>
      <span aria-hidden="true" className={styles.glyph}>
        {GLYPH[mark]}
      </span>
      {children}
    </p>
  );
}
