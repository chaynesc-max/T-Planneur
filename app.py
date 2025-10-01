import streamlit as st

import pandas as pd

import datetime

from ortools.sat.python import cp_model

# ---------------------------

# PARAMÈTRES DE BASE

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

# INTERFACE STREAMLIT

# ---------------------------

st.title("📅 Planification automatique des horaires cliniques")

employees = st.text_area("Liste des employés (1 par ligne)").splitlines()

employees = [e.strip() for e in employees if e.strip()]

start_date = st.date_input("Date de début", datetime.date(2025, 11, 2))

num_weeks = st.number_input("Durée de la période (en semaines)", 2, 12, 6)

num_days = num_weeks * 7

strict_210 = st.checkbox("🔒 Appliquer strictement les 210h par employé", value=True)

st.subheader("🛫 Congés validés")

leave_input = st.text_area("Saisir (format: Employé, YYYY-MM-DD, YYYY-MM-DD)")

leave_periods = []

for line in leave_input.splitlines():

    parts = [p.strip() for p in line.split(",")]

    if len(parts) == 3 and parts[0] in employees:

        emp, d1, d2 = parts

        d1 = datetime.date.fromisoformat(d1)

        d2 = datetime.date.fromisoformat(d2)

        leave_periods.append((emp, d1, d2))

# ---------------------------

# BOUTON DE CALCUL

# ---------------------------

if st.button("🚀 Générer le planning"):

    model = cp_model.CpModel()

    all_days = [start_date + datetime.timedelta(days=i) for i in range(num_days)]

    shifts = {}

    # Variables

    for e in employees:

        for d in all_days:

            for s in SHIFT_TYPES.keys():

                shifts[e, d, s] = model.NewBoolVar(f"{e}_{d}_{s}")

    # Chaque employé = 1 shift par jour

    for e in employees:

        for d in all_days:

            model.Add(sum(shifts[e, d, s] for s in SHIFT_TYPES.keys()) == 1)

    # Congés validés forcés

    for emp, d1, d2 in leave_periods:

        for d in all_days:

            if d1 <= d <= d2:

                for s in SHIFT_TYPES:

                    if s != "leave":

                        model.Add(shifts[emp, d, s] == 0)

                model.Add(shifts[emp, d, "leave"] == 1)

    # Couverture journalière

    for d in all_days:

        weekday = d.weekday()

        if weekday < 5:  # semaine

            model.Add(sum(shifts[e, d, "day_week"] + shifts[e, d, "short_day"] for e in employees) >= 4)

            model.Add(sum(shifts[e, d, "day_week"] + shifts[e, d, "short_day"] for e in employees) <= 7)

            model.Add(sum(shifts[e, d, "night_week"] for e in employees) == 2)

        else:  # week-end

            model.Add(sum(shifts[e, d, "day_weekend"] for e in employees) == 2)

            model.Add(sum(shifts[e, d, "night_weekend"] for e in employees) == 2)

    # Règles de repos et enchaînements

    for e in employees:

        for i, d in enumerate(all_days[:-1]):

            next_d = all_days[i+1]

            # Pas de jour après nuit

            model.Add(shifts[e, d, "night_week"] + shifts[e, d, "night_weekend"] + shifts[e, next_d, "day_week"] <= 1)

            # Pas plus de 3 shifts d'affilée

            if i < len(all_days)-3:

                model.Add(sum(shifts[e, all_days[i+k], s] 

                              for k in range(4) for s in ["day_week","short_day","day_weekend","night_week","night_weekend"]) <= 3)

    # Week-end blocs (2 jours jour, 3 nuits nuit)

    for e in employees:

        for i, d in enumerate(all_days):

            if d.weekday() == 5:  # samedi

                # si jour samedi alors jour dimanche

                model.Add(shifts[e, d, "day_weekend"] == shifts[e, d+datetime.timedelta(days=1), "day_weekend"])

            if d.weekday() == 4:  # vendredi

                # si nuit vendredi → nuit samedi + nuit dimanche

                model.Add(shifts[e, d, "night_weekend"] <= shifts[e, d+datetime.timedelta(days=1), "night_weekend"])

                model.Add(shifts[e, d, "night_weekend"] <= shifts[e, d+datetime.timedelta(days=2), "night_weekend"])

    # 210h strictes

    for e in employees:

        total_hours = sum(shifts[e, d, s] * SHIFT_TYPES[s]["hours"] for d in all_days for s in SHIFT_TYPES)

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

        hours_summary = {e: 0 for e in employees}

        shifts_summary = {e: {s:0 for s in SHIFT_TYPES} for e in employees}

        for e in employees:

            for d in all_days:

                for s in SHIFT_TYPES:

                    if solver.Value(shifts[e, d, s]) == 1:

                        df.loc[e, f"{d.strftime('%a %d/%m')}"] = SHIFT_TYPES[s]["label"]

                        hours_summary[e] += SHIFT_TYPES[s]["hours"]

                        shifts_summary[e][s] += 1

        # Affichage planning

        st.subheader("📅 Planning")

        st.dataframe(df)

        # Heures par employé

        st.subheader("⏱️ Heures totales")

        st.table(pd.DataFrame.from_dict(hours_summary, orient="index", columns=["Heures"]))

        # Répartition shifts

        st.subheader("⚖️ Répartition des shifts")

        st.dataframe(pd.DataFrame(shifts_summary).T)

    else:

        st.error("⚠️ Aucune solution trouvée. Consultez vos contraintes ou levez 210h strictes.")
 
