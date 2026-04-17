---
name: pml
description: Paid Medical Leave patient tracking for the clinic workflow. Disabled by default.
version: 0.1
emoji: "🩺"
requires:
  bins: []
  env: []
  python: []
tools_module: tools.py
auth:
  kind: none
---

# pml

Internal skill for tracking patients moving through the clinic's Paid Medical
Leave workflow. Use only when the user explicitly asks about PML patients or
scripts. Disabled by default; the user must turn it on in the Skills panel.

## Tools

- `pml_create(name, clinician, weeks, has_therapist?, therapist_name?, therapist_contact?)`
  — start a new PML track. Returns the handoff and patient-contact scripts.
- `pml_update(patient_name, [status | has_therapist | therapist_name | therapist_contact |
  roi_sent_date | roi_returned | visit2_date | forms_completed | note])` — update a patient.
  Patient name is a partial match.
- `pml_list(status_filter?)` — list patients, optionally filtered by status.
- `pml_script(patient_name, script_name)` — generate a specific message template.
  Script names: `handoff`, `patient_contact`, `roi_request`, `therapy_referral_celine`,
  `external_referral`, `visit2_reminder`, and the `objection_*` scripts.
- `pml_overdue(days?)` — list patients whose ROI has been outstanding for N+ days
  (default 5).

## Usage

- Match patients by the name the user gives you — partial match is fine.
- Status values: `initiated`, `patient_contacted`, `awaiting_therapist_info`,
  `roi_sent`, `therapy_referral`, `roi_verified`, `visit2_ready`, `forms_completed`,
  `active_monitoring`.
- Dates are `YYYY-MM-DD`.
- The output of every tool is a formatted string — surface it back to the user
  without rewriting unless they ask for a different format.
