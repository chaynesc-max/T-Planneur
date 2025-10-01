import pandas as pd

st.markdown("---")

st.header("📊 Suivi et analyse du planning")

# Bouton pour lever la contrainte des 210h

if "force_mode" not in st.session_state:

    st.session_state.force_mode = False

if st.button("🔓 Lever la contrainte 210h (mode 'À attribuer')"):

    st.session_state.force_mode = not st.session_state.force_mode

if st.session_state.force_mode:

    st.info("⚠️ La contrainte stricte de 210h est désactivée. Les heures manquantes seront marquées comme 'À attribuer'.")

else:

    st.success("✅ La contrainte stricte de 210h est active. Chaque employé doit atteindre exactement 210h.")

# ---- 1. Tableau récap heures par employé ----

recap_data = []

for emp in employees:

    worked_hours = hours_by_employee.get(emp, 0)

    leave_hours = leave_hours_by_employee.get(emp, 0) if 'leave_hours_by_employee' in globals() else 0

    total_hours = worked_hours + leave_hours

    diff_210 = total_hours - 210

    recap_data.append({

        "Employé": emp,

        "Heures travaillées": worked_hours,

        "Heures de congés validés": leave_hours,

        "Total heures comptées": total_hours,

        "Écart vs 210h": diff_210

    })

df_recap = pd.DataFrame(recap_data)

st.subheader("📅 Heures par employé")

st.dataframe(df_recap, use_container_width=True)

# ---- 2. Tableau récap par type de shift ----

shift_summary = []

for emp in employees:

    summary = {

        "Employé": emp,

        "Nuits semaine (lun–jeu)": shift_count[emp]["night_week"] if emp in shift_count else 0,

        "Nuits week-end (ven–dim)": shift_count[emp]["night_weekend"] if emp in shift_count else 0,

        "Jours semaine (lun–ven)": shift_count[emp]["day_week"] if emp in shift_count else 0,

        "Jours week-end (sam–dim)": shift_count[emp]["day_weekend"] if emp in shift_count else 0,

        "Journées courtes": shift_count[emp]["short_day"] if emp in shift_count else 0,

    }

    shift_summary.append(summary)

df_shifts = pd.DataFrame(shift_summary)

st.subheader("⚖️ Répartition des shifts par type")

st.dataframe(df_shifts, use_container_width=True)

# ---- 3. Tableau des blocages ----

logs = []

for emp in employees:

    reasons = []

    if df_recap.loc[df_recap["Employé"] == emp, "Écart vs 210h"].values[0] < 0:

        reasons.append("Manque d'heures planifiées")

    if emp in unavailable_conflicts:  # dictionnaire que tu remplis pendant la planif

        reasons.append("Indisponibilité saisie")

    if emp in rest_conflicts:  # idem

        reasons.append("Repos obligatoire non respecté")

    if emp in quota_conflicts:  # idem

        reasons.append("Quota min/max déjà atteint")

    if not reasons:

        reasons.append("Aucun blocage")

    logs.append({"Employé": emp, "Blocages identifiés": ", ".join(reasons)})

df_logs = pd.DataFrame(logs)

st.subheader("🛑 Blocages et contraintes")

st.dataframe(df_logs, use_container_width=True)
ST.info - Premium Information Domain for Sale
Discover the exceptional value of ST.info - a premium domain perfect for information services, technology platforms, and professional businesses seeking instant credibility and brand recognition.
 
