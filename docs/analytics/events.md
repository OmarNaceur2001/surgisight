# Surgical Event Detection Rules and Conflict Precedence

## 1. Overview
The SurgiSight Analytics Engine (M5) extracts critical surgical milestones from synchronized 1 Hz phase timelines and tool presence streams. Because multi-modal predictions may occasionally conflict, this specification defines the evidence sources and explicit precedence rules for resolving discrepancies.

## 2. Milestone Definitions

| Event Type | Canonical Phase | Primary Evidence | Secondary Evidence |
|---|---|---|---|
| `calot_dissection_start` | `P2` | Phase P2 entry timestamp | Grasper + Hook/Bipolar active |
| `first_clip` | `P3` | Clipper presence $\ge 0.50$ (or detection box) | Phase P3 active |
| `cystic_duct_cut` | `P3` | Scissors presence $\ge 0.50$ following `first_clip` | Phase P3 active |
| `gallbladder_dissection_start` | `P4` | Phase P4 entry timestamp | Hook/Bipolar active without Clipper |
| `gallbladder_in_bag` | `P5` / `P6` | SpecimenBag presence $\ge 0.50$ | Phase P5/P6 active |
| `gallbladder_retraction` | `P7` | Phase P7 entry timestamp | SpecimenBag exit, Grasper retraction |

## 3. Discrepancy Resolution & Precedence Rules (Non-Negotiable P5)

Under principle **P5 (Uncertainty display)**, the system **never silently reconciles conflicting signals**.

### Conflict Scenario A: Tool Activity Outside Canonical Phase
- **Case**: A high-confidence instrument activation occurs before or after its expected phase (e.g. Clipper presence $\ge 0.85$ at $t = 501\text{s}$ while Phase P2 is classified until $t = 520\text{s}$).
- **Resolution**:
  1. Emit the milestone event at timestamp $t = 501\text{s}$.
  2. Flag the event as `uncertain: true`.
  3. Include explanatory evidence: `"Clipper presence detected (p=0.85) at t=501s while phase classification indicates P2 (Calot triangle dissection). Discrepancy flagged for human review."`
  4. Lower confidence score to reflect temporal ambiguity.

### Conflict Scenario B: Tool Flicker / Brief Drops
- **Case**: An instrument drops to 0.0 for 1 frame (e.g. smoke or occlusion) then reappears.
- **Resolution**: Apply two-threshold hysteresis ($T_{\text{high}} = 0.60$, $T_{\text{low}} = 0.35$, minimum run length 2 seconds). Single-second dropouts do not fragment the operational event.

### Conflict Scenario C: Unobserved Milestones
- **Case**: An event (e.g. cystic duct cut) has no qualifying evidence throughout the recording.
- **Resolution**: The milestone is omitted from the events list. No fabricated or assumed default timestamps are ever produced.
