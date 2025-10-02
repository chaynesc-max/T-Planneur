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
       for d in all_days:
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
   for d in all_days:
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
       for i, d in enumerate(all_days[:-1]):
           next_d = all_days[i+1]
           # Pas de jour après nuit sans repos
           model.Add(shifts[e, d, "night_week"] + shifts[e, d, "night_weekend"] + shifts[e, next_d, "day_week"] <= 1)
           model.Add(shifts[e, d, "night_week"] + shifts[e, d, "night_weekend"] + shifts[e, next_d, "short_day"] <= 1)
           # Max 3 shifts consécutifs
           if i < len(all_days)-3:
               model.Add(sum(shifts[e, all_days[i+k], s]
                             for k in range(4)
                             for s in ["day_week","short_day","day_weekend","night_week","night_weekend"]) <= 3)
   # Week-end blocs
   for e in employees:
       for i, d in enumerate(all_days):
           if d.weekday() == 5:  # samedi jour
               model.Add(shifts[e, d, "day_weekend"] == shifts[e, d+datetime.timedelta(days=1), "day_weekend"])
           if d.weekday() == 4:  # vendredi nuit
               model.Add(shifts[e, d, "night_weekend"] <= shifts[e, d+datetime.timedelta(days=1), "night_weekend"])
               model.Add(shifts[e, d, "night_weekend"] <= shifts[e, d+datetime.timedelta(days=2), "night_weekend"])
   # 210h strictes par employé
   for e in employees:
       total_hours = sum(shifts[e,d,s]*SHIFT_TYPES[s]["hours"] for d in all_days for s in SHIFT_TYPES)
       if strict_210:
           model.Add(total_hours == 210)
       else:
           model.Add(total_hours <= 210)
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
