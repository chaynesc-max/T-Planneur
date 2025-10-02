import streamlit as st
import pandas as pd
import datetime
from ortools.sat.python import cp_model
# ---------------------------
# DÉFINITION DES TYPES DE SHIFTS
# ---------------------------
SHIFT_TYPES = {
   "day_week": {"label": "Jour semaine", "hours": 11.25, "color": "#a8dadc"},
   "short_day": {"label": "Jour court", "hours": 7.5, "color": "#457b9d"},
   "day_weekend": {"label": "Jour week-end", "hours": 11.25, "color": "#1d3557"},
   "night_week": {"label": "Nuit semaine", "hours": 11.25, "color": "#f4a261"},
   "night_weekend": {"label": "Nuit week-end", "hours": 11.25, "color": "#e76f51"},
   "rest": {"label": "Repos", "hours": 0, "color": "#f1faee"},
   "leave": {"label": "Congés validés", "hours": 11.25, "color": "#e63946"},
   "to_assign": {"label": "À attribuer", "hours": 11.25, "color": "#ffbe0b"}
}
# ---------------------------
# SIDEBAR PARAMÈTRES
# ---------------------------
st.sidebar.title("Paramètres du planning")
num_employees = st.sidebar.number_input("Nombre d'employés", min_value=1, value=15)
start_date = st.sidebar.date_input("Date de début", datetime.date(2025, 11, 2))
num_weeks = st.sidebar.number_input("Durée de la période (semaines)", 2, 12, 6)
strict_210 = st.sidebar.checkbox("Appliquer strictement 210h par employé", value=True)
st.sidebar.subheader("Saisie employés")
employees = []
for i in range(num_employees):
   employees.append(st.sidebar.text_input(f"Employé {i+1}", f"Employé {i+1}"))
# ---------------------------
# CONGÉS VALIDÉS
# ---------------------------
st.subheader("🛫 Congés validés")
leave_input = st.text_area("Saisir congés (format : Employé, YYYY-MM-DD, YYYY-MM-DD)")
leave_periods = []
for line in leave_input.splitlines():
   parts = [p.strip() for p in line.split(",")]
   if len(parts) == 3 and parts[0] in employees:
       emp, d1, d2 = parts
       leave_periods.append((emp, datetime.date.fromisoformat(d1), datetime.date.fromisoformat(d2)))
# ---------------------------
# GENERATION DU PLANNING
# ---------------------------
if st.button("🚀 Générer le planning"):
   model = cp_model.CpModel()
   num_days = num_weeks * 7
   all_days = [start_date + datetime.timedelta(days=i) for i in range(num_days)]
   shifts = {}
   # Variables binaires
   for e in employees:
       for i in range(num_days): # Iterate using day index
           d = all_days[i]
           for s in SHIFT_TYPES.keys():
               shifts[e, d, s] = model.NewBoolVar(f"{e}_{d}_{s}")
   # Chaque employé = 1 shift par jour
   for e in employees:
       for d in all_days:
           model.Add(sum(shifts[e, d, s] for s in SHIFT_TYPES.keys()) == 1)
   # Congés validés
   for emp, d1, d2 in leave_periods:
       for d in all_days:
           if d1 <= d <= d2:
               for s in SHIFT_TYPES:
                   if s != "leave":
                       model.Add(shifts[emp, d, s] == 0)
               model.Add(shifts[emp, d, "leave"] == 1)
   # Couverture journalière
   for i in range(num_days): # Iterate using day index
       d = all_days[i]
       wd = d.weekday()
       if wd < 5:  # semaine
           model.Add(sum(shifts[e, d, "day_week"] + shifts[e, d, "short_day"] for e in employees) >= 4)
           model.Add(sum(shifts[e, d, "day_week"] + shifts[e, d, "short_day"] for e in employees) <= 7)
           model.Add(sum(shifts[e, d, "night_week"] for e in employees) == 2)
       else:  # week-end
           model.Add(sum(shifts[e, d, "day_weekend"] for e in employees) == 2)
           model.Add(sum(shifts[e, d, "night_weekend"] for e in employees) == 2)
   # Repos et blocs consécutifs
   for e in employees:
       for i in range(num_days - 1): # Iterate using day index up to the second to last day
           d = all_days[i]
           next_d = all_days[i+1]
           # Pas de jour après nuit sans repos (If night on day i, then must be rest on day i+1)
           model.AddImplication(shifts[e, d, "night_week"], shifts[e, next_d, "rest"])
           model.AddImplication(shifts[e, d, "night_weekend"], shifts[e, next_d, "rest"])

           # Max 3 working shifts consécutifs (Check blocks of 4 days)
           if i <= num_days - 4: # Ensure there are 4 days to check (i, i+1, i+2, i+3)
               model.Add(sum(shifts[e, all_days[i+k], s]
                             for k in range(4)
                             for s in ["day_week","short_day","day_weekend","night_week","night_weekend"]) <= 3)
   # Week-end blocs (Ensure if working Saturday day, also work Sunday day, and similarly for night)
   for e in employees:
       for i in range(num_days): # Iterate using day index
           d = all_days[i]

           # If Saturday day, must be Sunday day (if both days are within the period)
           if d.weekday() == 5 and i + 1 < num_days:
               next_d = all_days[i+1]
               model.AddImplication(shifts[e, d, "day_weekend"], shifts[e, next_d, "day_weekend"])

           # If Saturday night, must be Sunday night (if both days are within the period)
           if d.weekday() == 5 and i + 1 < num_days:
                next_d = all_days[i+1]
                model.AddImplication(shifts[e, d, "night_weekend"], shifts[e, next_d, "night_weekend"])

           # New constraint: If Friday night, must also be Saturday and Sunday night (if all days are within the period)
           if d.weekday() == 4 and i + 2 < num_days: # Friday and enough days for Sat (i+1) and Sun (i+2)
                next_d = all_days[i+1]
                day_after_next_d = all_days[i+2]
                model.AddImplication(shifts[e, d, "night_weekend"], shifts[e, next_d, "night_weekend"])
                model.AddImplication(shifts[e, d, "night_weekend"], shifts[e, day_after_next_d, "night_weekend"])


   # 210h strictes par employé
   # Scale factor for hours (multiply by 4 to convert 11.25 and 7.5 to integers)
   scale_factor = 4
   for e in employees:
       total_hours_scaled = sum(
           int(SHIFT_TYPES[s]["hours"] * scale_factor) * shifts[e, all_days[i], s]
           for i in range(num_days)
           for s in SHIFT_TYPES
           if SHIFT_TYPES[s]["hours"] > 0 # Only include shifts with hours
       )
       if strict_210:
           model.Add(total_hours_scaled == int(210 * scale_factor))
       else:
           model.Add(total_hours_scaled <= int(210 * scale_factor))


   # Solve
   solver = cp_model.CpSolver()
   solver.parameters.max_time_in_seconds = 60
   status = solver.Solve(model)
   if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
       df = pd.DataFrame(index=employees, columns=[f"{d.strftime('%a %d/%m')}" for d in all_days])
       hours_summary = {e:0 for e in employees}
       shifts_summary = {e:{s:0 for s in SHIFT_TYPES} for e in employees}
       for e in employees:
           for d in all_days:
               for s in SHIFT_TYPES:
                   if solver.Value(shifts[e,d,s]) == 1:
                       df.loc[e, f"{d.strftime('%a %d/%m')}"] = SHIFT_TYPES[s]["label"]
                       hours_summary[e] += SHIFT_TYPES[s]["hours"]
                       shifts_summary[e][s] += 1
       st.subheader("📅 Planning")
       st.dataframe(df)
       st.subheader("⏱️ Heures totales par employé")
       st.table(pd.DataFrame.from_dict(hours_summary, orient="index", columns=["Heures"]))
       st.subheader("⚖️ Répartition des shifts par employé")
       st.dataframe(pd.DataFrame(shifts_summary).T)
   else:
       st.error("⚠️ Aucune solution trouvée. Consultez vos contraintes ou levez 210h strictes.")
