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
nb_employes = st.sidebar.number_input("Nombre d'employés", min_value=5, max_value=50, value=15)
date_debut = st.sidebar.date_input("Date de début de période", value=datetime(2025, 11, 2))
periode_jours = st.sidebar.number_input("Durée de la période (jours)", min_value=7, max_value=84, value=42)
employes = [f"Employé {i+1}" for i in range(nb_employes)]
dates = [date_debut + timedelta(days=i) for i in range(periode_jours)]
french_weekdays = {'Mon':'lun','Tue':'mar','Wed':'mer','Thu':'jeu','Fri':'ven','Sat':'sam','Sun':'dim'}
jours_str = [(d.strftime("%Y-%m-%d") + " (" + french_weekdays[d.strftime('%a')] + ")") for d in dates]

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
        model.Add(sum(shifts[(e,d,s)] for s in shift_types) == 1)
        if dates[d] in conges_dict[e]:
            model.Add(shifts[(e,d,"Conge")] == 1)
        else:
            model.Add(shifts[(e,d,"Conge")] == 0)

# -------------------
# SHIFT COURT MAX 1 PAR EMPLOYÉ SUR 6 SEMAINES
# -------------------
for e in employes:
    model.Add(sum(shifts[(e,d,"Jour_court")] for d in range(periode_jours)) <= 1)

# -------------------
# SHIFT COURT MAX 1 PAR JOUR (LUN-VEN)
# -------------------
for d in range(periode_jours):
    if dates[d].weekday() < 5:
        model.Add(sum(shifts[(e,d,"Jour_court")] for e in employes) <= 1)

# -------------------
# STAFFING
# -------------------
for d in range(periode_jours):
    weekday = dates[d].weekday()
    if weekday < 5:  # Lundi-Vendredi
        model.Add(sum(shifts[(e,d,"Jour")] + shifts[(e,d,"Jour_court")] for e in employes) >= 4)
        model.Add(sum(shifts[(e,d,"Jour")] + shifts[(e,d,"Jour_court")] for e in employes) <= 7)
        model.Add(sum(shifts[(e,d,"Nuit")] for e in employes) == 2)
    else:  # Week-end
        model.Add(sum(shifts[(e,d,"Jour")] for e in employes) == 2)
        model.Add(sum(shifts[(e,d,"Nuit")] for e in employes) == 2)

# -------------------
# REPOS (au moins 2 jours off par semaine)
# -------------------
for e in employes:
    for week_start in range(0, periode_jours, 7):
        week_days = [d for d in range(week_start, min(week_start+7, periode_jours))]
        model.Add(sum(shifts[(e,d,"Repos")] for d in week_days) >= 2)

# -------------------
# HEURES PAR EMPLOYÉ (210h / 6 semaines)
# -------------------
scale_factor = 4
for e in employes:
    for block_start in range(0, periode_jours, 42):
        block_end = min(block_start+42, periode_jours)
        total_heures_scaled = sum(
            int(11.25*scale_factor)*(shifts[(e,d,"Jour")] + shifts[(e,d,"Nuit")] + shifts[(e,d,"Conge")]) +
            int(7.5*scale_factor)*shifts[(e,d,"Jour_court")]
            for d in range(block_start, block_end) if dates[d].weekday()<5 or dates[d].weekday()==5
        )
        if not leve_210h:
            model.Add(total_heures_scaled == int(210*scale_factor))
        else:
            model.Add(total_heures_scaled <= int(210*scale_factor))

# -------------------
# WEEK-END ROTATION FLEXIBLE
# -------------------
weekend_indices = [i for i,d in enumerate(dates) if d.weekday() == 5]  # samedi
for e in employes:
    for w in weekend_indices:
        weekend_jour = model.NewBoolVar(f"{e}_weekend_{w}_jour")
        weekend_nuit = model.NewBoolVar(f"{e}_weekend_{w}_nuit")
        # max 1 week-end sur 3
        model.Add(weekend_jour + weekend_nuit <= 1)
        # si weekend de jour => samedi et dimanche jour
        model.Add(shifts[(e,w,"Jour")] == 1).OnlyEnforceIf(weekend_jour)
        if w+1 < periode_jours:
            model.Add(shifts[(e,w+1,"Jour")] == 1).OnlyEnforceIf(weekend_jour)
        # si weekend de nuit => vendredi, samedi, dimanche nuit
        if w-1 >= 0:
            model.Add(shifts[(e,w-1,"Nuit")] == 1).OnlyEnforceIf(weekend_nuit)
        model.Add(shifts[(e,w,"Nuit")] == 1).OnlyEnforceIf(weekend_nuit)
        if w+1 < periode_jours:
            model.Add(shifts[(e,w+1,"Nuit")] == 1).OnlyEnforceIf(weekend_nuit)

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
                    day = dates[d]
                    if s=="Jour":
                        if day.weekday()<=4:
                            compteur.loc[e,"Jour semaine"] +=1
                        else:
                            compteur.loc[e,"Jour week-end"] +=1
                    elif s=="Nuit":
                        if day.weekday()<=3:
                            compteur.loc[e,"Nuit semaine"] +=1
                        else:
                            compteur.loc[e,"Nuit week-end"] +=1
                    elif s=="Jour_court":
                        compteur.loc[e,"Shift court"] +=1
else:
    st.error("Aucune solution trouvée dans le temps imparti.")

# -------------------
# AFFICHAGE
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

st.subheader("📊 Compteur de shifts par employé")
st.dataframe(compteur)
