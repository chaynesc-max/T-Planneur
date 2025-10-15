import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ortools.sat.python import cp_model

st.set_page_config(layout="wide")
st.title("📊 Générateur de Planning — Visualisation améliorée")

# --- Paramètres
st.sidebar.header("⚙️ Paramètres")
nb_employes = st.sidebar.number_input("Nombre d'employés", 5, 50, value=15)
date_debut = st.sidebar.date_input("Date début (dimanche)", value=datetime(2025,11,2))
periode_jours = st.sidebar.number_input("Durée (jours)", 14, 84, value=42)

employes = [f"Employé {i+1}" for i in range(nb_employes)]
dates = [date_debut + timedelta(days=i) for i in range(periode_jours)]

# --- Congés
st.subheader("📝 Saisie des congés")
conges_dict = {}
for e in employes:
    dates_conges = st.multiselect(f"Congés {e}", 
                                  [d.strftime("%Y-%m-%d") for d in dates])
    conges_dict[e] = [datetime.strptime(d,"%Y-%m-%d") for d in dates_conges]

# --- Bouton génération
if st.button("▶️ Générer le planning"):

    model = cp_model.CpModel()
    shift_types = ["Repos","Jour","Nuit","Jour_court","Conge"]
    shifts = {}
    for e in range(nb_employes):
        for d in range(periode_jours):
            for s in shift_types:
                shifts[(e,d,s)] = model.NewBoolVar(f"{e}_{d}_{s}")

    # --- Base: un shift par jour et congés
    for e in range(nb_employes):
        for d in range(periode_jours):
            model.Add(sum(shifts[(e,d,s)] for s in shift_types) == 1)
            if dates[d] in conges_dict[employes[e]]:
                model.Add(shifts[(e,d,"Conge")] == 1)
            else:
                model.Add(shifts[(e,d,"Conge")] == 0)

    # --- Staffing et règles (similaire au script précédent)
    for d in range(periode_jours):
        wd = dates[d].weekday()
        if wd <=4:
            model.Add(sum(shifts[(e,d,"Jour")] + shifts[(e,d,"Jour_court")] for e in range(nb_employes)) >= 5)
            if wd<=3:
                model.Add(sum(shifts[(e,d,"Nuit")] for e in range(nb_employes)) == 2)
        if wd>=5:
            model.Add(sum(shifts[(e,d,"Jour")] for e in range(nb_employes)) >= 2)
            model.Add(sum(shifts[(e,d,"Jour")] for e in range(nb_employes)) <= 3)
            if wd>=4:
                model.Add(sum(shifts[(e,d,"Nuit")] for e in range(nb_employes)) >= 2)
                model.Add(sum(shifts[(e,d,"Nuit")] for e in range(nb_employes)) <= 3)

    # --- Repos 2/j semaine + repos après nuit
    for e in range(nb_employes):
        for week_start in range(0, periode_jours, 7):
            days = range(week_start, min(week_start+7, periode_jours))
            model.Add(sum(shifts[(e,d,"Repos")] + shifts[(e,d,"Conge")] for d in days) >= 2)
        for d in range(periode_jours-1):
            model.Add(shifts[(e,d+1,"Repos")] == 1).OnlyEnforceIf(shifts[(e,d,"Nuit")])

    # --- Max 3 shifts consécutifs
    for e in range(nb_employes):
        for d in range(periode_jours-3):
            model.Add(sum(shifts[(e,dd,"Jour")] + shifts[(e,dd,"Nuit")] + shifts[(e,dd,"Jour_court")] for dd in range(d,d+4)) <=3)

    # --- Week-end contigu
    for e in range(nb_employes):
        for d in range(periode_jours):
            wd = dates[d].weekday()
            if wd==5:
                model.AddImplication(shifts[(e,d,"Jour")], shifts[(e,d+1,"Jour")])
            if wd==4:
                model.AddImplication(shifts[(e,d,"Nuit")], shifts[(e,d+1,"Nuit")])
                model.AddImplication(shifts[(e,d,"Nuit")], shifts[(e,d+2,"Nuit")])

    # --- 210h ±5%
    sf = 4
    min_h = int(198.75*sf)
    max_h = int(221.25*sf)
    for e in range(nb_employes):
        terms = []
        for d in range(periode_jours):
            terms.append(int(11.25*sf)*shifts[(e,d,"Jour")])
            if dates[d].weekday() not in (5,6):
                terms.append(int(11.25*sf)*shifts[(e,d,"Nuit")])
            terms.append(int(7.5*sf)*shifts[(e,d,"Jour_court")])
            terms.append(int(11.25*sf)*shifts[(e,d,"Conge")])
        model.Add(sum(terms) >= min_h)
        model.Add(sum(terms) <= max_h)

    # --- Équité de base (similaire au précédent)
    for s_type in ["Jour","Nuit","Jour_court"]:
        for wd_type in ["semaine","weekend"]:
            indices = [i for i,d in enumerate(dates) if d.weekday()<5] if wd_type=="semaine" else [i for i,d in enumerate(dates) if d.weekday()>=5]
            total = sum(shifts[(e,d,s_type)] for e in range(nb_employes) for d in indices)
            avg = total // nb_employes
            for e in range(nb_employes):
                emp_total = sum(shifts[(e,d,s_type)] for d in indices)
                slack = model.NewIntVar(0, periode_jours, f"slack_{s_type}_{e}_{wd_type}")
                model.Add(emp_total - avg <= slack)
                model.Add(avg - emp_total <= slack)

    # --- Solveur
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 180
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        planning = pd.DataFrame("", index=employes, columns=[d.strftime("%Y-%m-%d") for d in dates])
        for e in range(nb_employes):
            for d in range(periode_jours):
                for s in shift_types:
                    if solver.Value(shifts[(e,d,s)]):
                        planning.iat[e,d] = s

        # --- Coloration avancée pour lisibilité
        def color_shift(val):
            if val=="Jour": return 'background-color:#a6cee3'
            if val=="Nuit": return 'background-color:#1f78b4; color:white'
            if val=="Jour_court": return 'background-color:#b2df8a; font-weight:bold'
            if val=="Conge": return 'background-color:#fb9a99'
            if val=="Repos": return 'background-color:#f0f0f0'
            return ''
        st.subheader("📋 Planning coloré")
        st.dataframe(planning.style.applymap(color_shift))

        # --- Compteurs
        compteur = pd.DataFrame(0, index=employes, columns=["Jour semaine","Nuit semaine","Jour week-end","Nuit week-end","Shift court"])
        for e in range(nb_employes):
            for d in range(periode_jours):
                s = planning.iat[e,d]
                wd = dates[d].weekday()
                if s=="Jour":
                    if wd<5: compteur.loc[employes[e],"Jour semaine"] +=1
                    else: compteur.loc[employes[e],"Jour week-end"] +=1
                elif s=="Nuit":
                    if wd<5: compteur.loc[employes[e],"Nuit semaine"] +=1
                    else: compteur.loc[employes[e],"Nuit week-end"] +=1
                elif s=="Jour_court":
                    compteur.loc[employes[e],"Shift court"] +=1
        st.subheader("📊 Compteur de shifts par employé")
        st.dataframe(compteur)
    else:
        st.error("Aucune solution trouvée.")

