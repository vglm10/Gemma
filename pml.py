import json
import os
import uuid
import time
from datetime import datetime, timedelta

PML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pml")
PATIENTS_FILE = os.path.join(PML_DIR, "patients.json")

STATUSES = [
    "initiated",
    "patient_contacted",
    "awaiting_therapist_info",
    "roi_sent",
    "therapy_referral",
    "roi_verified",
    "visit2_ready",
    "forms_completed",
    "active_monitoring",
]

STATUS_LABELS = {
    "initiated": "Initiated",
    "patient_contacted": "Patient Contacted",
    "awaiting_therapist_info": "Awaiting Therapist Info",
    "roi_sent": "ROI Sent",
    "therapy_referral": "Therapy Referral Needed",
    "roi_verified": "ROI Verified",
    "visit2_ready": "Ready for Visit 2",
    "forms_completed": "Forms Completed",
    "active_monitoring": "Active Monitoring",
}

# ─── Script Templates ───────────────────────────────────────────────

SCRIPTS = {
    "handoff": (
        "Patient {patient_name} is approved for {weeks} weeks of PML. "
        "Initiate the Leave Track."
    ),
    "patient_contact": (
        "Hi {patient_name},\n\n"
        "{clinician} has approved your medical leave. Your paperwork will be "
        "completed live during your next appointment.\n\n"
        "As a reminder, maintaining this leave requires active participation in our "
        "sleep, nutrition, and emotional intelligence/therapy program.\n\n"
        "Please reply with your current therapist's name, contact info, and "
        "appointment cadence so we can send a Release of Information (ROI) "
        "prior to your next visit.\n\n"
        "Thank you,\nPsychiatry in Motion"
    ),
    "roi_request": (
        "Dear {therapist_name},\n\n"
        "We are writing to request a Release of Information regarding our mutual "
        "patient, {patient_name}, who is currently on a structured Paid Medical "
        "Leave program under the care of {clinician} at Psychiatry in Motion.\n\n"
        "We are requesting verification that {patient_name} is actively "
        "participating in therapy sessions. We do not require private therapy "
        "notes — only confirmation of active participation and appointment cadence.\n\n"
        "Please complete and return the attached ROI at your earliest convenience.\n\n"
        "Thank you,\nPsychiatry in Motion"
    ),
    "therapy_referral_celine": (
        "Hi {patient_name},\n\n"
        "Since you do not currently have a therapist, our protocol requires you "
        "to establish care to maintain your leave status.\n\n"
        "We highly recommend our in-house specialist, Celine, who works directly "
        "with our clinical team. Her rate is $250/session, and we offer Care Credit "
        "or internal payment plans to make this accessible.\n\n"
        "Shall I book your intake with her, or would you prefer our list of "
        "external insurance-based referrals?"
    ),
    "external_referral": (
        "Hi {patient_name},\n\n"
        "As discussed, here is our list of external therapists who accept insurance "
        "and are experienced with burnout recovery. Please establish care with one "
        "of them and have their office send us a Release of Information so we can "
        "coordinate your recovery plan.\n\n"
        "Please note: your PML forms cannot be signed at your next visit until "
        "the ROI is on file.\n\n"
        "Thank you,\nPsychiatry in Motion"
    ),
    "visit2_reminder": (
        "Hi {patient_name},\n\n"
        "This is a reminder to schedule your follow-up visit to complete your "
        "Paid Medical Leave paperwork. Please note that all PML forms must be "
        "completed live during a clinical session per clinic policy.\n\n"
        "Please call or message us to book your appointment.\n\n"
        "Thank you,\nPsychiatry in Motion"
    ),
    "objection_general": (
        "I completely understand that frequent visits and therapy feel like a lot "
        "right now when you are already exhausted. Our primary goal is your actual "
        "recovery. {clinician} requires this protocol — regular visits, active therapy, "
        "and lifestyle tracking — because it is the clinical standard for getting you well.\n\n"
        "Secondarily, we have to be honest about the insurance company: they demand "
        "continuous proof that you are actively recovering. If we don't track these "
        "markers every 1-2 weeks, they will use that gap to deny the claim, and you "
        "will be left fighting them while trying to heal. We require this cadence to "
        "heal you first, and protect your paycheck second."
    ),
    "objection_financial": (
        "I completely understand the financial stress. Because active therapy is a "
        "mandatory medical requirement to actually heal from this burnout and validate "
        "your Paid Medical Leave, we want to help you find a path that works.\n\n"
        "We have two options:\n"
        "1) We can set you up with Care Credit today to finance your sessions with "
        "Celine, or\n"
        "2) We can provide a list of external clinics that may take your insurance.\n\n"
        "Which option feels more manageable for you right now?"
    ),
    "objection_roi_privacy": (
        "Because {clinician} is legally signing off on your medical inability to work, "
        "our practice requires verified coordination of care to ensure you are getting "
        "the right support.\n\n"
        "We absolutely do not need your private therapy notes; we strictly need the ROI "
        "to confirm you are actively participating in the emotional recovery portion of "
        "your treatment plan. We cannot safely or legally authorize the medical leave "
        "without this verification on file."
    ),
    "objection_just_sign": (
        "To ensure your employer or third-party receives 100% accurate information and "
        "your paycheck is not delayed, clinic policy mandates that all medical leave "
        "paperwork is completed live, together, during a clinical session. This ensures "
        "nothing is missed.\n\n"
        "As noted in the practice policy, form completion is charged at $200/hr without "
        "you around to answer the questions. Shall I book your follow-up for Tuesday or "
        "Thursday to get this completed together?"
    ),
    "objection_refusal": (
        "Psychiatry in Motion is a holistic, active-recovery practice. Our ethical duty "
        "is to help you get better.\n\n"
        "Because you are declining the mandatory therapy and lifestyle protocols required "
        "to heal and maintain Paid Medical Leave under our care, we are unable to "
        "authorize your forms.\n\n"
        "We will gladly maintain your medication management for the next 30 days while "
        "you transition to a clinic that better fits your preferred treatment style, and "
        "I have attached a list of referrals."
    ),
}


class PMLManager:
    def __init__(self):
        os.makedirs(PML_DIR, exist_ok=True)
        self._patients = []
        self._load()

    def _load(self):
        if os.path.exists(PATIENTS_FILE):
            try:
                with open(PATIENTS_FILE, "r") as f:
                    self._patients = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._patients = []

    def _save(self):
        with open(PATIENTS_FILE, "w") as f:
            json.dump(self._patients, f, indent=2)

    def create_patient(self, name, clinician, weeks, has_therapist=False,
                       therapist_name="", therapist_contact=""):
        patient = {
            "id": uuid.uuid4().hex[:8],
            "name": name,
            "clinician": clinician,
            "weeks": weeks,
            "created": datetime.now().strftime("%Y-%m-%d"),
            "status": "initiated",
            "has_therapist": has_therapist,
            "therapist_name": therapist_name,
            "therapist_contact": therapist_contact,
            "roi_sent_date": None,
            "roi_returned": False,
            "visit2_date": None,
            "forms_completed": False,
            "notes": [f"{datetime.now().strftime('%Y-%m-%d')}: PML initiated, {weeks} weeks"],
        }
        self._patients.append(patient)
        self._save()
        return patient

    def get_patient(self, patient_id):
        for p in self._patients:
            if p["id"] == patient_id:
                return p
        return None

    def find_patient_by_name(self, name):
        name_lower = name.lower()
        for p in self._patients:
            if name_lower in p["name"].lower():
                return p
        return None

    def update_patient(self, patient_id, updates):
        for p in self._patients:
            if p["id"] == patient_id:
                for k, v in updates.items():
                    if k in p:
                        p[k] = v
                if "notes" not in updates:
                    note = f"{datetime.now().strftime('%Y-%m-%d')}: Updated"
                    if "status" in updates:
                        note += f" — status → {STATUS_LABELS.get(updates['status'], updates['status'])}"
                    p["notes"].append(note)
                self._save()
                return p
        return None

    def advance_status(self, patient_id):
        p = self.get_patient(patient_id)
        if not p:
            return None
        current_idx = STATUSES.index(p["status"]) if p["status"] in STATUSES else -1
        if current_idx < len(STATUSES) - 1:
            new_status = STATUSES[current_idx + 1]
            # Skip therapy_referral if patient has therapist, skip roi_sent if no therapist
            if new_status == "therapy_referral" and p.get("has_therapist"):
                new_status = "roi_sent"
            elif new_status == "roi_sent" and not p.get("has_therapist"):
                new_status = "therapy_referral"
            return self.update_patient(patient_id, {"status": new_status})
        return p

    def delete_patient(self, patient_id):
        before = len(self._patients)
        self._patients = [p for p in self._patients if p["id"] != patient_id]
        if len(self._patients) < before:
            self._save()
            return True
        return False

    def list_patients(self, status_filter=None):
        if status_filter:
            return [p for p in self._patients if p["status"] == status_filter]
        return list(self._patients)

    def get_overdue(self, days=5):
        overdue = []
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        for p in self._patients:
            if p["status"] == "roi_sent" and not p["roi_returned"]:
                if p.get("roi_sent_date") and p["roi_sent_date"] <= cutoff:
                    days_ago = (datetime.now() - datetime.strptime(p["roi_sent_date"], "%Y-%m-%d")).days
                    overdue.append({**p, "days_overdue": days_ago})
        return overdue

    def get_script(self, patient_id, script_name):
        p = self.get_patient(patient_id)
        if not p:
            return "Error: Patient not found"
        template = SCRIPTS.get(script_name)
        if not template:
            return f"Error: Unknown script '{script_name}'. Available: {', '.join(SCRIPTS.keys())}"
        return template.format(
            patient_name=p["name"],
            clinician=p.get("clinician", "Dr. Al-Katib"),
            weeks=p.get("weeks", 4),
            therapist_name=p.get("therapist_name", "[Therapist]"),
        )

    def get_scripts_for_status(self, patient_id):
        p = self.get_patient(patient_id)
        if not p:
            return {}
        status = p["status"]
        scripts = {}
        if status == "initiated":
            scripts["handoff"] = "Clinician → Admin handoff message"
            scripts["patient_contact"] = "Admin → Patient booking & therapy audit"
        elif status in ("patient_contacted", "awaiting_therapist_info"):
            if p.get("has_therapist"):
                scripts["roi_request"] = "ROI request to external therapist"
            else:
                scripts["therapy_referral_celine"] = "In-house referral (Celine)"
                scripts["external_referral"] = "External referral list"
        elif status in ("roi_sent", "therapy_referral"):
            scripts["visit2_reminder"] = "Visit 2 scheduling reminder"
        elif status == "roi_verified":
            scripts["visit2_reminder"] = "Visit 2 scheduling reminder"
        # Objection scripts always available
        scripts["objection_general"] = "General pushback response"
        scripts["objection_financial"] = "Financial pushback response"
        scripts["objection_roi_privacy"] = "ROI/privacy pushback response"
        scripts["objection_just_sign"] = "Just sign it pushback response"
        scripts["objection_refusal"] = "Outright refusal response"
        return scripts

    def get_pipeline_summary(self):
        counts = {}
        for p in self._patients:
            s = p["status"]
            counts[s] = counts.get(s, 0) + 1
        return counts

    def get_checklist(self, patient_id):
        p = self.get_patient(patient_id)
        if not p:
            return None
        return {
            "has_therapist_info": bool(p.get("has_therapist") and p.get("therapist_name")),
            "roi_on_file": p.get("roi_returned", False),
            "therapy_confirmed": p.get("has_therapist", False) or p["status"] in ("therapy_referral", "roi_verified"),
            "visit2_scheduled": bool(p.get("visit2_date")),
            "forms_completed": p.get("forms_completed", False),
            "ready_for_visit2": p.get("roi_returned", False) or p["status"] in ("roi_verified", "visit2_ready"),
        }
