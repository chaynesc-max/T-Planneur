import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ortools.sat.python import cp_model

st.set_page_config(layout="wide")
st.title("📅 Générateur de Planning - Version Week-end Optimisée")

# -------------------
# PARAMÈTRES
# -------------------
st.sidebar.header("⚙️ Paramètres")
nb_employes = st.sidebar.number_input("Nombre d'employés", min_value=5, max_value=50, value=15)
date_debut = st.sidebar.date_input("Date de début de période", value=datetime(2025, 11, 2))
periode_jours = st.sidebar.number_input("Durée de la période (jours)", min_value=7, max_value=84, value=42)
employes = [f"Employé {i+1}" for i in range(nb_employes)]
dates = [date_debut + timedelta(days=i) for i in range(periode_jours)]

# Mapping pour les jours en français
french_weekdays = {'Mon': 'lun', 'Tue': 'mar', 'Wed': 'mer', 'Thu': 'jeu',
                    'Fri': 'ven', 'Sat': 'sam', 'Sun': 'dim'}
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
# VARIABLES ORTOOLS
# -------------------
model = cp_model.CpModel()
shift_types = ["Repos", "Jour", "Nuit", "Jour_court", "Conge"]
shifts = {}
weekend_day = {}  # booléen week-end jour
weekend_night = {}  # booléen week-end nuit

for e in employes:
    for d in range(periode_jours):
        for s in shift_types:
            shifts[(e,d,s)] = model.NewBoolVar(f"{e}_{d}_{s}")
    # Booléens week-end pour la rotation 1/3
    for w in range(periode_jours // 7 + 1):
        weekend_day[(e,w)] = model.NewBoolVar(f"{e}_weekend_day_{w}")
        weekend_night[(e,w)] = model.NewBoolVar(f"{e}_weekend_night_{w}")

# -------------------
# CONTRAINTES DE BASE
# -------------------
for e in employes:
    for d in range(periode_jours):
        model.Add(sum(shifts[(e,d,s)] for s in shift_types) == 1)
        # Congé uniquement si saisi
        if (date_debut + timedelta(days=d)) in conges_dict[e]:
            model.Add(shifts[(e,d,"Conge")] == 1)
        else:
            model.Add(shifts[(e,d,"Conge")] == 0)

# -------------------
# CONTRAINTES SPECIFIQUES
# -------------------
# Shift court max 1 par employé sur 6 semaines
for e in employes:
    for block_start in range(0, periode_jours, 42):
        block_end = min(block_start + 42, periode_jours)
        model.Add(sum(shifts[(e,d,"Jour_court")] for d in range(block_start, block_end)) <= 1)

# 1 seul shift court par jour
for d in range(periode_jours):
    model.Add(sum(shifts[(e,d,"Jour_court")] for e in employes) <= 1)

# -------------------
# CONTRAINTES OPÉRATIONNELLES
# -------------------
for d in range(periode_jours):
    weekday = (date_debut + timedelta(days=d)).weekday()
    if weekday < 5: # Lundi → Vendredi
        model.Add(sum(shifts[(e,d,"Jour")] + shifts[(e,d,"Jour_court")] for e in employes) >= 4)
        model.Add(sum(shifts[(e,d,"Jour")] + shifts[(e,d,"Jour_court")] for e in employes) <= 7)
        model.Add(sum(shifts[(e,d,"Nuit")] for e in employes) == 2)
    else: # Samedi-Dimanche
        model.Add(sum(shifts[(e,d,"Jour")] for e in employes) == 2)
        model.Add(sum(shifts[(e,d,"Nuit")] for e in employes) == 2)

# -------------------
# CONTRAINTES REPOS
# -------------------
for e in employes:
    # Repos après nuit
    for d in range(periode_jours-1):
        model.Add(shifts[(e,d+1,"Repos")] == 1).OnlyEnforceIf(shifts[(e,d,"Nuit")])
    # Au moins 2 jours off par semaine
    for week_start in range(0, periode_jours, 7):
        week_days = range(week_start, min(week_start+7, periode_jours))
        off_days = [shifts[(e,d,"Repos")] + shifts[(e,d,"Conge")] for d in week_days]
        model.Add(sum(off_days) >= 2)

# -------------------
# LOGIQUE WEEK-END
# -------------------
for e in employes:
    for w, week_start in enumerate(range(0, periode_jours, 7)):
        # index des jours du week-end
        samedi = week_start + 5
        dimanche = week_start + 6
        vendredi = week_start + 4

        # Week-end de jour → samedi & dimanche en jour
        if samedi < periode_jours and dimanche < periode_jours:
            model.Add(shifts[(e,samedi,"Jour")] + shifts[(e,dimanche,"Jour")] == 2).OnlyEnforceIf(weekend_day[(e,w)])
            # pas de nuit pendant ce week-end si jour
            if vendredi < periode_jours:
                model.Add(shifts[(e,vendredi,"Nuit")] == 0).OnlyEnforceIf(weekend_day[(e,w)])
            model.Add(shifts[(e,samedi,"Nuit")] == 0).OnlyEnforceIf(weekend_day[(e,w)])
            model.Add(shifts[(e,dimanche,"Nuit")] == 0).OnlyEnforceIf(weekend_day[(e,w)])

        # Week-end de nuit → vendredi, samedi & dimanche en nuit
        if vendredi < periode_jours and samedi < periode_jours and dimanche < periode_jours:
            model.Add(shifts[(e,vendredi,"Nuit")] + shifts[(e,samedi,"Nuit")] + shifts[(e,dimanche,"Nuit")] == 3).OnlyEnforceIf(weekend_night[(e,w)])
            # pas de jour pendant ce week-end si nuit
            model.Add(shifts[(e,vendredi,"Jour")] == 0).OnlyEnforceIf(weekend_night[(e,w)])
            model.Add(shifts[(e,samedi,"Jour")] == 0).OnlyEnforceIf(weekend_night[(e,w)])
            model.Add(shifts[(e,dimanche,"Jour")] == 0).OnlyEnforceIf(weekend_night[(e,w)])

        # Limiter à 1 week-end actif (jour ou nuit) sur 3 semaines
        if w % 3 == 0:
            model.AddBoolOr([weekend_day[(e,w)], weekend_night[(e,w)]])
        else:
            model.Add(weekend_day[(e,w)] == 0)
            model.Add(weekend_night[(e,w)] == 0)

# -------------------
# HEURES PAR EMPLOYÉ
# -------------------
scale_factor = 4
for e in employes:
    for block_start in range(0, periode_jours, 42):
        block_end = min(block_start + 42, periode_jours)
        total_heures_scaled = sum(
            int(11.25 * scale_factor)*(shifts[(e,d,"Jour")] + shifts[(e,d,"Nuit")] + shifts[(e,d,"Conge")]) +
            int(7.5 * scale_factor)*shifts[(e,d,"Jour_court")]
            for d in range(block_start, block_end)
        )
        if not leve_210h:
            model.Add(total_heures_scaled == int(210 * scale_factor))
        else:
            model.Add(total_heures_scaled <= int(210 * scale_factor))

# -------------------
# SOLVEUR
# -------------------
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 180
status = solver.Solve(model)

planning = pd.DataFrame("", index=employes, columns=jours_str)
compteur = pd.DataFrame(0, index=employes, columns=[
    "Jour semaine", "Nuit semaine", "Jour week-end", "Nuit week-end", "Shift court"
])

# -------------------
# REMPLISSAGE PLANNING ET COMPTEUR
# -------------------
if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
    for e in employes:
        for d in range(periode_jours):
            for s in shift_types:
                if solver.Value(shifts[(e,d,s)]):
                    planning.iloc[employes.index(e), d] = s
                    day = date_debut + timedelta(days=d)
                    if s == "Jour":
                        if day.weekday() <= 4:
                            compteur.loc[e,"Jour semaine"] += 1
                        else:
                            compteur.loc[e,"Jour week-end"] += 1
                    elif s == "Nuit":
                        if day.weekday() <= 3:
                            compteur.loc[e,"Nuit semaine"] += 1
                        else:
                            compteur.loc[e,"Nuit week-end"] += 1
                    elif s == "Jour_court":
                        compteur.loc[e,"Shift court"] += 1
else:
    st.error("Aucune solution trouvée dans le temps imparti. Des shifts restent à attribuer par les responsables.")

# -------------------
# AFFICHAGE
# -------------------
st.subheader("📋 Planning")
def color_shift(val):
    if val == "Jour":
        return 'background-color: #a6cee3'
    elif val == "Nuit":
        return 'background-color: #1f78b4; color: white'
    elif val == "Jour_court":
        return 'background-color: #b2df8a'
    elif val == "Conge":
        return 'background-color: #fb9a99'
    elif val == "Repos":
        return 'background-color: #f0f0f0'
    return ''
st.dataframe(planning.style.applymap(color_shift))

st.subheader("📊 Compteur de shifts par employé")
st.dataframe(compteur)
