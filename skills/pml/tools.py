from datetime import datetime

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "pml_create",
            "description": "Start a new Paid Medical Leave (PML) track for a patient. Creates a patient record and returns the initiation scripts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Patient full name"},
                    "clinician": {"type": "string", "description": "Clinician name (e.g. Dr. Al-Katib)"},
                    "weeks": {"type": "number", "description": "Number of weeks of PML approved"},
                    "has_therapist": {"type": "boolean", "description": "Whether the patient currently has a therapist"},
                    "therapist_name": {"type": "string", "description": "External therapist name (if applicable)"},
                    "therapist_contact": {"type": "string", "description": "External therapist contact info (if applicable)"},
                },
                "required": ["name", "clinician", "weeks"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pml_update",
            "description": "Update a PML patient's record. Can update status, therapist info, ROI status, visit dates, or add notes. Use patient name to find them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Patient name (partial match OK)"},
                    "status": {"type": "string", "description": "New status"},
                    "has_therapist": {"type": "boolean"},
                    "therapist_name": {"type": "string"},
                    "therapist_contact": {"type": "string"},
                    "roi_sent_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "roi_returned": {"type": "boolean"},
                    "visit2_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "forms_completed": {"type": "boolean"},
                    "note": {"type": "string"},
                },
                "required": ["patient_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pml_list",
            "description": "List all PML patients, optionally filtered by status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status_filter": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pml_script",
            "description": "Generate a specific script/message for a PML patient.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string"},
                    "script_name": {"type": "string"},
                },
                "required": ["patient_name", "script_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pml_overdue",
            "description": "List PML patients with overdue ROIs (not returned within specified days).",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "number"},
                },
            },
        },
    },
]


def execute(name, args, ctx):
    mgr = getattr(ctx, "pml", None)
    if mgr is None:
        return "Error: PML manager not initialized"

    try:
        if name == "pml_create":
            p = mgr.create_patient(
                name=args.get("name", ""),
                clinician=args.get("clinician", "Dr. Al-Katib"),
                weeks=int(args.get("weeks", 4)),
                has_therapist=args.get("has_therapist", False),
                therapist_name=args.get("therapist_name", ""),
                therapist_contact=args.get("therapist_contact", ""),
            )
            handoff = mgr.get_script(p["id"], "handoff")
            contact = mgr.get_script(p["id"], "patient_contact")
            return (
                f"PML track created for {p['name']} (id: {p['id']})\n"
                f"Status: Initiated | {p['weeks']} weeks | Clinician: {p['clinician']}\n\n"
                f"--- SCRIPT 1: Clinician Handoff (for Spruce) ---\n{handoff}\n\n"
                f"--- SCRIPT 2: Patient Contact ---\n{contact}"
            )

        if name == "pml_update":
            patient_name = args.get("patient_name", "")
            p = mgr.find_patient_by_name(patient_name)
            if not p:
                return f"Error: No patient found matching '{patient_name}'"
            updates = {}
            for key in ("status", "has_therapist", "therapist_name", "therapist_contact",
                        "roi_sent_date", "roi_returned", "visit2_date", "forms_completed"):
                if key in args:
                    updates[key] = args[key]
            if "note" in args:
                p["notes"].append(f"{datetime.now().strftime('%Y-%m-%d')}: {args['note']}")
            if updates:
                p = mgr.update_patient(p["id"], updates)
            else:
                mgr._save()
            from pml import STATUS_LABELS
            return (
                f"Updated {p['name']}:\n"
                f"  Status: {STATUS_LABELS.get(p['status'], p['status'])}\n"
                f"  Therapist: {'Yes — ' + p.get('therapist_name', '') if p.get('has_therapist') else 'No'}\n"
                f"  ROI: {'Returned' if p.get('roi_returned') else ('Sent ' + (p.get('roi_sent_date') or 'N/A') if p.get('roi_sent_date') else 'Not sent')}\n"
                f"  Visit 2: {p.get('visit2_date') or 'Not scheduled'}\n"
                f"  Forms: {'Completed' if p.get('forms_completed') else 'Pending'}"
            )

        if name == "pml_list":
            status_filter = args.get("status_filter")
            patients = mgr.list_patients(status_filter)
            if not patients:
                return "No PML patients found." + (f" (filter: {status_filter})" if status_filter else "")
            from pml import STATUS_LABELS
            lines = [f"PML Patients ({len(patients)}):"]
            for p in patients:
                roi_info = ""
                if p.get("roi_sent_date") and not p.get("roi_returned"):
                    roi_info = f" | ROI sent {p['roi_sent_date']}"
                elif p.get("roi_returned"):
                    roi_info = " | ROI on file"
                lines.append(
                    f"  - {p['name']} ({p['clinician']}, {p['weeks']}wk) "
                    f"[{STATUS_LABELS.get(p['status'], p['status'])}]{roi_info} "
                    f"(id: {p['id']})"
                )
            summary = mgr.get_pipeline_summary()
            if summary:
                pipeline = " | ".join(f"{STATUS_LABELS.get(s, s)}: {c}" for s, c in summary.items())
                lines.append(f"\nPipeline: {pipeline}")
            return "\n".join(lines)

        if name == "pml_script":
            patient_name = args.get("patient_name", "")
            script_name = args.get("script_name", "")
            p = mgr.find_patient_by_name(patient_name)
            if not p:
                return f"Error: No patient found matching '{patient_name}'"
            script = mgr.get_script(p["id"], script_name)
            return f"--- {script_name.upper()} for {p['name']} ---\n\n{script}"

        if name == "pml_overdue":
            days = int(args.get("days", 5))
            overdue = mgr.get_overdue(days)
            if not overdue:
                return f"No patients with ROIs overdue by {days}+ days."
            lines = [f"Overdue ROIs ({len(overdue)} patients):"]
            for p in overdue:
                lines.append(
                    f"  - {p['name']} — ROI sent {p['roi_sent_date']} "
                    f"({p['days_overdue']} days ago)"
                )
            return "\n".join(lines)

        return f"Unknown PML tool: {name}"
    except Exception as e:
        return f"PML Error: {e}"
