import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ortools.sat.python import cp_model

st.set_page_config(layout="wide")
st.title("📅 Générateur de Planning — Version Finale Optimisée")

# -------------------
# PARAMÈTRES
# -------------------
st.sidebar.header("⚙️ Paramètres")
nb_employes = st.sidebar.number_input("Nombre d'employés", min_value=5, max_value=50, value=15)
date_debut = st.sidebar.date_input("Date de début", value=datetime(2025, 11, 2))
periode_jours = st.sidebar.number_input("Durée de la période (jours)", min_value=7, max_value=84, value=42)

# Employés et dates
employes = [f"Employé {i+1}" for i in range(nb_employes)]
dates = [date_debut + timedelta(days=i) for i in range(periode_jours)]
jours_str = [d.strftime("%Y-%m-%d") for d in dates]

# -------------------
# CONGÉS
# -------------------
st.subheader("📝 Saisie des congés validés")
conges_dict = {e: [] for e in employes}
for e in employes:
    dates_conges = st.date_input(f"Congés {e} (peut être multiple)", min_value=date_debut,
                                 max_value=date_debut+timedelta(days=periode_jours-1), value=[], key=e)
    if isinstance(dates_conges, datetime):
        dates_conges = [dates_conges]
    conges_dict[e] = dates_conges

# Bouton générer
if st.button("Générer le planning"):

    # -------------------
    # VARIABLES ORTOOLS
    # -------------------
    model = cp_model.CpModel()
    shift_types = ["Repos", "Jour", "Nuit", "Jour_court", "Conge"]
    shifts = {}
    for e in employes:
        for d in range(periode_jours):
            for s in shift_types:
                shifts[(e,d,s)] = model.NewBoolVar(f"{e}_{d}_{s}")

    # -------------------
    # CONTRAINTES DE BASE
    # -------------------
    for e in employes:
        for d in range(periode_jours):
            # Un seul shift par jour
            model.Add(sum(shifts[(e,d,s)] for s in shift_types) == 1)
            # Congés pris en compte
            if dates[d] in conges_dict[e]:
                model.Add(shifts[(e,d,"Conge")] == 1)
            else:
                model.Add(shifts[(e,d,"Conge")] == 0)

    # -------------------
    # SHIFT COURT
    # -------------------
    for e in employes:
        # Max 1 shift court sur 6 semaines
        for block_start in range(0, periode_jours, 42):
            block_end = min(block_start+42, periode_jours)
            model.Add(sum(shifts[(e,d,"Jour_court")] for d in range(block_start, block_end)) <= 1)
    for d in range(periode_jours):
        if dates[d].weekday() < 5:
            # Max 1 shift court par jour
            model.Add(sum(shifts[(e,d,"Jour_court")] for e in employes) <= 1)

    # -------------------
    # STAFFING JOUR ET NUIT
    # -------------------
    for d in range(periode_jours):
        wd = dates[d].weekday()
        if wd < 5:
            # Lundi à vendredi
            model.Add(sum(shifts[(e,d,"Jour")] + shifts[(e,d,"Jour_court")] for e in employes) >= 5)
            model.Add(sum(shifts[(e,d,"Jour")] + shifts[(e,d,"Jour_court")] for e in employes) <= 7)
            model.Add(sum(shifts[(e,d,"Nuit")] for e in employes) == 2 if wd <= 3 else 2)  # Lundi-Jeudi
        else:
            # Samedi-Dimanche
            model.Add(sum(shifts[(e,d,"Jour")] for e in employes) >= 2)
            model.Add(sum(shifts[(e,d,"Jour")] for e in employes) <= 3)
            if wd == 5:  # samedi
                model.Add(sum(shifts[(e,d,"Nuit")] + shifts[(e,d+1 if d+1<periode_jours else d,"Nuit")] for e in employes) >= 2)
                model.Add(sum(shifts[(e,d,"Nuit")] + shifts[(e,d+1 if d+1<periode_jours else d,"Nuit")] for e in employes) <= 3)

    # -------------------
    # REPOS 2 jours minimum par semaine
    # -------------------
    for e in employes:
        for week_start in range(0, periode_jours, 7):
            days = range(week_start, min(week_start+7, periode_jours))
            model.Add(sum(shifts[(e,d,"Repos")] + shifts[(e,d,"Conge")] for d in days) >= 2)

    # -------------------
    # MAX 3 SHIFTS CONSÉCUTIFS
    # -------------------
    for e in employes:
        for d in range(periode_jours-3):
            model.Add(sum(shifts[(e,dd,"Jour")] + shifts[(e,dd,"Nuit")] + shifts[(e,dd,"Jour_court")]
                          for dd in range(d,d+4)) <= 3)

    # -------------------
    # WEEKEND CONTIGU
    # -------------------
    for e in employes:
        for d in range(periode_jours):
            wd = dates[d].weekday()
            # Weekend de jour : samedi & dimanche
            if wd == 5 and d+1<periode_jours:
                model.AddImplication(shifts[(e,d,"Jour")], shifts[(e,d+1,"Jour")])
                model.AddImplication(shifts[(e,d+1,"Jour")], shifts[(e,d,"Jour")])
            # Weekend de nuit : vendredi-samedi-dimanche
            if wd == 4 and d+2<periode_jours:
                model.AddImplication(shifts[(e,d,"Nuit")], shifts[(e,d+1,"Nuit")])
                model.AddImplication(shifts[(e,d,"Nuit")], shifts[(e,d+2,"Nuit")])
            if wd == 5 and d+1<periode_jours:
                model.AddImplication(shifts[(e,d,"Nuit")], shifts[(e,d+1,"Nuit")])
                model.AddImplication(shifts[(e,d+1,"Nuit")], shifts[(e,d,"Nuit")])

    # -------------------
    # HEURES 210 ±10%
    # -------------------
    sf = 4
    min_h = int(198.75*sf)
    max_h = int(221.25*sf)
    for e in employes:
        total = sum(int(11.25*sf)*shifts[(e,d,"Jour")] +
                    int(7.5*sf)*shifts[(e,d,"Jour_court")] +
                    int(11.25*sf)*shifts[(e,d,"Conge")] +
                    (int(11.25*sf)*shifts[(e,d,"Nuit")] if dates[d].weekday()<5 else 0)
                    for d in range(periode_jours))
        model.Add(total >= min_h)
        model.Add(total <= max_h)

    # -------------------
    # SOLVEUR
    # -------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 180
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        # Planning DataFrame
        planning = pd.DataFrame("", index=employes, columns=jours_str)
        compteur = pd.DataFrame(0, index=employes, columns=["Jour semaine","Nuit semaine","Jour weekend","Nuit weekend","Shift court"])
        for e in employes:
            for d in range(periode_jours):
                for s in shift_types:
                    if solver.Value(shifts[(e,d,s)]):
                        planning.loc[e, jours_str[d]] = s
                        day = dates[d]
                        if s=="Jour":
                            if day.weekday()<5: compteur.loc[e,"Jour semaine"] +=1
                            else: compteur.loc[e,"Jour weekend"] +=1
                        elif s=="Nuit":
                            if day.weekday()<5: compteur.loc[e,"Nuit semaine"] +=1
                            else: compteur.loc[e,"Nuit weekend"] +=1
                        elif s=="Jour_court":
                            compteur.loc[e,"Shift court"] +=1
        # -------------------
        # AFFICHAGE
        # -------------------
        def color_shift(val):
            if val=="Jour": return 'background-color: #a6cee3'
            elif val=="Nuit": return 'background-color: #1f78b4; color:white'
            elif val=="Jour_court": return 'background-color: #b2df8a'
            elif val=="Conge": return 'background-color: #fb9a99'
            elif val=="Repos": return 'background-color: #f0f0f0'
            return ''
        st.subheader("📋 Planning")
        st.dataframe(planning.style.applymap(color_shift))
        st.subheader("📊 Compteur de shifts")
        st.dataframe(compteur)
    else:
        st.error("Aucune solution trouvée. Vérifier les contraintes et les congés.")
