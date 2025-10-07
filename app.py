import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ortools.sat.python import cp_model
import matplotlib.pyplot as plt

# -------------------
# CONFIGURATION PAGE
# -------------------
st.set_page_config(layout="wide")
st.title("📅 Générateur de Planning Optimisé avec Équité et Visualisation")

# -------------------
# PARAMÈTRES
# -------------------
st.sidebar.header("⚙️ Paramètres")
nb_employes = st.sidebar.number_input("Nombre d'employés", min_value=5, max_value=50, value=15)
date_debut = st.sidebar.date_input("Date de début de période", value=datetime(2025, 11, 2))
periode_jours = st.sidebar.number_input("Durée de la période (jours)", min_value=7, max_value=84, value=42)
employes = [f"Employé {i+1}" for i in range(nb_employes)]
dates = [date_debut + timedelta(days=i) for i in range(periode_jours)]

# Mapping jour semaine français
french_weekdays = {'Mon':'lun','Tue':'mar','Wed':'mer','Thu':'jeu','Fri':'ven','Sat':'sam','Sun':'dim'}
jours_str = [(d.strftime("%Y-%m-%d") + " (" + french_weekdays[d.strftime("%a")] + ")") for d in dates]

# -------------------
# CONGÉS VALIDÉS
# -------------------
st.subheader("📝 Saisie des congés validés")
conges_dict = {e: [] for e in employes}
for e in employes:
    dates_conges = st.date_input(f"Congés {e} (peut être multiple)",
                                 min_value=date_debut,
                                 max_value=date_debut + timedelta(days=periode_jours - 1),
                                 value=[],
                                 key=e)
    if isinstance(dates_conges, datetime):
        dates_conges = [dates_conges]
    conges_dict[e] = dates_conges

# -------------------
# OPTION: Lever la contrainte 210h
# -------------------
leve_210h = st.checkbox("🔓 Lever la contrainte 210h pour résoudre les blocages", value=False)

# -------------------
# INITIALISATION CP-SAT
# -------------------
model = cp_model.CpModel()
shift_types = ["Repos","Jour","Nuit","Jour_court","Conge"]

# Création des variables IntVar (0 ou 1)
shifts = {}
for e in employes:
    for d in range(periode_jours):
        for s in shift_types:
            shifts[(e,d,s)] = model.NewIntVar(0,1,f"{e}_{d}_{s}")

# -------------------
# CONTRAINTES DE BASE
# -------------------
for e in employes:
    for d in range(periode_jours):
        # Un seul shift par jour
        model.Add(sum(shifts[(e,d,s)] for s in shift_types) == 1)
        # Congé si saisi
        if (date_debut + timedelta(days=d)) in conges_dict[e]:
            model.Add(shifts[(e,d,"Conge")] == 1)
        else:
            model.Add(shifts[(e,d,"Conge")] == 0)

# 1 shift court max par jour
for d in range(periode_jours):
    model.Add(sum(shifts[(e,d,"Jour_court")] for e in employes) <= 1)

# Shift court max 1 par employé sur 6 semaines
for e in employes:
    for block_start in range(0, periode_jours, 42):
        block_end = min(block_start + 42, periode_jours)
        model.Add(sum(shifts[(e,d,"Jour_court")] for d in range(block_start, block_end)) <= 1)

# -------------------
# CONTRAINTES OPÉRATIONNELLES
# -------------------
for d in range(periode_jours):
    weekday = (date_debut + timedelta(days=d)).weekday()
    if weekday < 5: # Lundi → Vendredi
        model.Add(sum(shifts[(e,d,"Jour")] + shifts[(e,d,"Jour_court")] for e in employes) >= 4)
        model.Add(sum(shifts[(e,d,"Jour")] + shifts[(e,d,"Jour_court")] for e in employes) <= 7)
        model.Add(sum(shifts[(e,d,"Nuit")] for e in employes) == 2)
    else: # Week-end
        model.Add(sum(shifts[(e,d,"Jour")] for e in employes) == 2)
        model.Add(sum(shifts[(e,d,"Nuit")] for e in employes) == 2)

# -------------------
# CONTRAINTES REPOS ET BLOCS
# -------------------
for e in employes:
    # Repos après nuit
    for d in range(periode_jours-1):
        model.Add(shifts[(e,d+1,"Repos")] == 1).OnlyEnforceIf(shifts[(e,d,"Nuit")])
    # 2 jours consécutifs de repos/semaine
    for week_start in range(0, periode_jours, 7):
        week_days = range(week_start, min(week_start+7, periode_jours))
        pairs = []
        for i in range(len(week_days)-1):
            pair_var = model.NewBoolVar(f"{e}_repos_pair_{week_days[i]}")
            model.AddBoolAnd([shifts[(e,week_days[i],"Repos")], shifts[(e,week_days[i+1],"Repos")]]).OnlyEnforceIf(pair_var)
            pairs.append(pair_var)
        model.AddBoolOr(pairs)

# -------------------
# ROTATION WEEK-END 1 SUR 3
# -------------------
weekend_days = [(i, i+1) for i in range(periode_jours-1) 
                if (date_debut + timedelta(days=i)).weekday() == 5] # Samedi
for idx, e in enumerate(employes):
    # Jour week-end: assigner 1 sur 3
    for w_idx, (sat,sun) in enumerate(weekend_days):
        if (w_idx % 3) != (idx % 3):
            model.Add(shifts[(e,sat,"Jour")] == 0)
            model.Add(shifts[(e,sun,"Jour")] == 0)
    # Nuit week-end: assigner 1 sur 3
    for w_idx, (fri,sat) in enumerate([(i,i+1) for i in range(periode_jours-2) 
                                       if (date_debut + timedelta(days=i)).weekday()==4]): # Vendredi
        if (w_idx % 3) != (idx % 3):
            model.Add(shifts[(e,fri,"Nuit")] == 0)
            model.Add(shifts[(e,sat,"Nuit")] == 0)
            model.Add(shifts[(e,sat+1,"Nuit")] == 0)

# -------------------
# HEURES PAR EMPLOYÉ
# -------------------
scale_factor = 4
for e in employes:
    for block_start in range(0, periode_jours, 42):
        block_end = min(block_start+42, periode_jours)
        total_heures_scaled = sum(
            int(11.25*scale_factor)*(shifts[(e,d,"Jour")] + shifts[(e,d,"Nuit")] + shifts[(e,d,"Conge")]) +
            int(7.5*scale_factor)*shifts[(e,d,"Jour_court")]
            for d in range(block_start, block_end)
        )
        if not leve_210h:
            model.Add(total_heures_scaled == int(210*scale_factor))
        else:
            model.Add(total_heures_scaled <= int(210*scale_factor))

# -------------------
# OBJECTIF D'ÉQUITÉ
# -------------------
totals = {}
for e in employes:
    totals[e] = {}
    for t in ['Jour semaine','Nuit semaine','Jour week-end','Nuit week-end','Shift court']:
        totals[e][t] = model.NewIntVar(0, periode_jours, f"{e}_{t}")

# Calcul des totaux par employé
for e in employes:
    model.Add(totals[e]['Jour semaine'] == sum(shifts[(e,d,'Jour')] + shifts[(e,d,'Jour_court')] for d in range(periode_jours) if (date_debut + timedelta(days=d)).weekday()<=4))
    model.Add(totals[e]['Nuit semaine'] == sum(shifts[(e,d,'Nuit')] for d in range(periode_jours) if (date_debut + timedelta(days=d)).weekday()<=4))
    model.Add(totals[e]['Jour week-end'] == sum(shifts[(e,d,'Jour')] for d in range(periode_jours) if (date_debut + timedelta(days=d)).weekday()>=5))
    model.Add(totals[e]['Nuit week-end'] == sum(shifts[(e,d,'Nuit')] for d in range(periode_jours) if (date_debut + timedelta(days=d)).weekday()>=5))
    model.Add(totals[e]['Shift court'] == sum(shifts[(e,d,'Jour_court')] for d in range(periode_jours)))

# Moyenne et écarts
diff_vars = []
for t in ['Jour semaine','Nuit semaine','Jour week-end','Nuit week-end','Shift court']:
    avg = sum(totals[e][t] for e in employes) // nb_employes
    for e in employes:
        diff = model.NewIntVar(0, periode_jours, f"diff_{e}_{t}")
        model.Add(diff >= totals[e][t] - avg)
        model.Add(diff >= avg - totals[e][t])
        diff_vars.append(diff)

model.Minimize(sum(diff_vars))

# -------------------
# SOLVEUR
# -------------------
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 300
status = solver.Solve(model)

planning = pd.DataFrame("", index=employes, columns=jours_str)
compteur = pd.DataFrame(0, index=employes, columns=["Jour semaine","Nuit semaine","Jour week-end","Nuit week-end","Shift court"])

if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
    for e in employes:
        for d in range(periode_jours):
            for s in shift_types:
                if solver.Value(shifts[(e,d,s)]):
                    planning.iloc[employes.index(e), d] = s
                    day = date_debut + timedelta(days=d)
                    if s=="Jour":
                        if day.weekday()<=4: compteur.loc[e,"Jour semaine"]+=1
                        else: compteur.loc[e,"Jour week-end"]+=1
                    elif s=="Nuit":
                        if day.weekday()<=4: compteur.loc[e,"Nuit semaine"]+=1
                        else: compteur.loc[e,"Nuit week-end"]+=1
                    elif s=="Jour_court": compteur.loc[e,"Shift court"]+=1
else:
    st.error("Aucune solution trouvée dans le temps imparti.")

# -------------------
# AFFICHAGE PLANNING
# -------------------
st.subheader("📋 Planning")
def color_shift(val):
    if val=="Jour": return 'background-color: #a6cee3'
    elif val=="Nuit": return 'background-color: #1f78b4; color:white'
    elif val=="Jour_court": return 'background-color: #b2df8a'
    elif val=="Conge": return 'background-color: #fb9a99'
    elif val=="Repos": return 'background-color: #f0f0f0'
    return ''
st.dataframe(planning.style.applymap(color_shift))

# -------------------
# AFFICHAGE COMPTEURS ET GRAPHIQUE
# -------------------
st.subheader("📊 Compteur de shifts par employé")
st.dataframe(compteur)

# Graphique répartition
st.subheader("📈 Répartition des shifts par type")
fig, ax = plt.subplots(figsize=(12,6))
compteur.plot(kind='bar', stacked=True, ax=ax, colormap='tab20')
ax.set_ylabel("Nombre de shifts")
ax.set_xlabel("Employés")
ax.set_title("Répartition des shifts par type d'employé")
st.pyplot(fig)
