import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ortools.sat.python import cp_model

st.set_page_config(layout="wide")
st.title("📅 Générateur de Planning - Version Fonctionnelle")

# -------------------
# PARAMÈTRES
# -------------------
st.sidebar.header("⚙️ Paramètres")
nb_employes = st.sidebar.number_input("Nombre d'employés", 5, 50, 15)
date_debut = st.sidebar.date_input("Date de début de période", value=datetime(2025,11,2))
periode_jours = st.sidebar.number_input("Durée de la période (jours)", 7, 84, 42)

employes = [f"Employé {i+1}" for i in range(nb_employes)]
dates = [date_debut + timedelta(days=i) for i in range(periode_jours)]
jours_str = [d.strftime("%Y-%m-%d") for d in dates]

# -------------------
# Saisie des congés
# -------------------
st.subheader("📝 Saisie des congés validés")
conges_dict = {}
for e in employes:
    selected = st.multiselect(f"Congés {e}", options=dates, format_func=lambda x: x.strftime("%Y-%m-%d"), key=f"conges_{e}")
    conges_dict[e] = selected

# -------------------
# Bouton pour générer le planning
# -------------------
if st.button("Générer le planning"):
    st.info("Optimisation en cours…")
    
    model = cp_model.CpModel()
    shift_types = ["Repos","Jour","Nuit","Jour_court","Conge"]
    shifts = {}
    for e in employes:
        for d in range(periode_jours):
            for s in shift_types:
                shifts[(e,d,s)] = model.NewBoolVar(f"{e}_{d}_{s}")
    
    # Chaque jour un seul shift
    for e in employes:
        for d in range(periode_jours):
            model.Add(sum(shifts[(e,d,s)] for s in shift_types) == 1)
            # Congés comme journée travaillée
            if dates[d] in conges_dict[e]:
                model.Add(shifts[(e,d,"Conge")] == 1)
            else:
                model.Add(shifts[(e,d,"Conge")] == 0)
    
    # Exemple simplifié : au moins 2 jours off par semaine
    for e in employes:
        for week_start in range(0, periode_jours, 7):
            week_days = [d for d in range(week_start, min(week_start+7, periode_jours))]
            model.Add(sum(shifts[(e,d,"Repos")] for d in week_days) >= 2)
    
    # Heures par employé (210h / 6 semaines), congés comptent
    scale_factor = 4
    for e in employes:
        for block_start in range(0, periode_jours, 42):
            block_end = min(block_start+42, periode_jours)
            total_heures_scaled = sum(
                int(11.25*scale_factor)*(shifts[(e,d,"Jour")] + shifts[(e,d,"Nuit")] + shifts[(e,d,"Conge")]) +
                int(7.5*scale_factor)*shifts[(e,d,"Jour_court")]
                for d in range(block_start, block_end)
            )
            model.Add(total_heures_scaled == int(210*scale_factor))
    
    # Solveur
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 180
    status = solver.Solve(model)
    
    planning = pd.DataFrame("", index=employes, columns=jours_str)
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        for e in employes:
            for d in range(periode_jours):
                for s in shift_types:
                    if solver.Value(shifts[(e,d,s)]):
                        planning.iloc[employes.index(e), d] = s
        
        st.subheader("📋 Planning")
        def color_shift(val):
            if val=="Jour": return 'background-color: #a6cee3'
            elif val=="Nuit": return 'background-color: #1f78b4; color:white'
            elif val=="Jour_court": return 'background-color: #b2df8a'
            elif val=="Conge": return 'background-color: #fb9a99'
            elif val=="Repos": return 'background-color: #f0f0f0'
            return ''
        st.dataframe(planning.style.applymap(color_shift))
    else:
        st.error("Aucune solution trouvée")
