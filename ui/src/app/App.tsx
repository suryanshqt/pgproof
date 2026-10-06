import { useState } from "react";
import { AnalysisBoundary } from "../components/AnalysisBoundary/AnalysisBoundary";
import type { EvidenceKind } from "../components/EvidenceLabel/EvidenceLabel";
import { EvidenceLabel } from "../components/EvidenceLabel/EvidenceLabel";
import { MetricRule } from "../components/MetricRule/MetricRule";
import { StateNotice } from "../components/StateNotice/StateNotice";
import styles from "./App.module.css";

type Theme = "system" | "light" | "dark";
type Density = "balanced" | "compact";

const EVIDENCE_KINDS: EvidenceKind[] = [
  "observed",
  "user_confirmed",
  "inferred",
  "verified_in_fixture",
  "question",
  "unresolved",
  "inconclusive",
  "rejected",
];

const SPACE_SCALE = [1, 2, 3, 4, 5, 6, 7, 8] as const;

// The fixture gallery docs/PR_ROADMAP.md FE-01 asks for: every token and
// primitive rendered together so visual QA has a real page to screenshot,
// without building the product screens FE-02 onward own.
export function App() {
  const [theme, setTheme] = useState<Theme>("system");
  const [density, setDensity] = useState<Density>("balanced");

  return (
    <div
      className={styles.page}
      data-theme={theme === "system" ? undefined : theme}
      data-density={density === "balanced" ? undefined : density}
    >
      <header className={styles.header}>
        <h1>pgproof fixture gallery</h1>
        <div className={styles.controls}>
          <label>
            Theme
            <select value={theme} onChange={(event) => setTheme(event.target.value as Theme)}>
              <option value="system">System</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </label>
          <label>
            Density
            <select
              value={density}
              onChange={(event) => setDensity(event.target.value as Density)}
            >
              <option value="balanced">Balanced</option>
              <option value="compact">Compact</option>
            </select>
          </label>
        </div>
      </header>

      <main className={styles.main}>
        <section aria-labelledby="typography-heading">
          <h2 id="typography-heading">Typography</h2>
          <h1>Heading 1</h1>
          <h2>Heading 2</h2>
          <p>
            Body text in the system sans stack. Code, SQL, and identifiers use{" "}
            <code>the system monospace stack</code>.
          </p>
          <p className="pgp-tabular-nums">Comparison figures: 86.2 ms vs 14.3 ms</p>
        </section>

        <section aria-labelledby="space-heading">
          <h2 id="space-heading">Space scale</h2>
          <div className={styles.swatchRow}>
            {SPACE_SCALE.map((step) => (
              <div key={step} className={styles.spaceSwatch}>
                <div
                  className={styles.spaceBox}
                  style={{ width: `var(--space-${step})`, height: `var(--space-${step})` }}
                />
                <span>space.{step}</span>
              </div>
            ))}
          </div>
        </section>

        <section aria-labelledby="evidence-heading">
          <h2 id="evidence-heading">Evidence labels</h2>
          <div className={styles.labelRow}>
            {EVIDENCE_KINDS.map((kind) => (
              <EvidenceLabel key={kind} kind={kind} />
            ))}
          </div>
        </section>

        <section aria-labelledby="metrics-heading">
          <h2 id="metrics-heading">Metric rules</h2>
          <MetricRule count={2} label="required correctness decisions" />
          <MetricRule count={4} label="questions material context missing" />
          <MetricRule count={0} label="verified improvements" />
        </section>

        <section aria-labelledby="boundary-heading">
          <h2 id="boundary-heading">Analysis boundary</h2>
          <AnalysisBoundary mark="ok">Reconstructed provisional design</AnalysisBoundary>
          <AnalysisBoundary mark="attention">
            3 relationships exist only in ORM code
          </AnalysisBoundary>
          <AnalysisBoundary mark="unavailable">
            Runtime query behavior not inspected
          </AnalysisBoundary>
          <AnalysisBoundary mark="failure">Migration stopped at revision 91ca21</AnalysisBoundary>
        </section>

        <section aria-labelledby="state-heading">
          <h2 id="state-heading">Interaction states</h2>
          <div className={styles.stateStack}>
            <StateNotice kind="pristine" title="No run yet">
              Run <code>pgproof review .</code> to produce the first artifacts.
            </StateNotice>
            <StateNotice kind="empty" title="No recommendations">
              The rule engine found nothing to report for this schema.
            </StateNotice>
            <StateNotice kind="partial" title="Partial analysis">
              Runtime capture was not approved; only static evidence is shown.
            </StateNotice>
            <StateNotice kind="failure" title="Migration failed">
              PostgreSQL rejected revision 91ca21. No partial schema was analysed.
            </StateNotice>
          </div>
        </section>
      </main>
    </div>
  );
}
