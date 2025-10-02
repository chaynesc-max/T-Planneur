@@ -2,7 +2,7 @@
import pandas as pd
from datetime import datetime, timedelta
from ortools.sat.python import cp_model
import locale
# import locale # Removed as it caused an error

st.set_page_config(layout="wide")
st.title("📅 Générateur de Planning - Version Finale Optimisée")
@@ -16,23 +16,29 @@
periode_jours = st.sidebar.number_input("Durée de la période (jours)", min_value=7, max_value=84, value=42)
employes = [f"Employé {i+1}" for i in range(nb_employes)]
dates = [date_debut + timedelta(days=i) for i in range(periode_jours)]
locale.setlocale(locale.LC_TIME, 'fr_CA.UTF-8')
jours_str = [(d.strftime("%Y-%m-%d") + " (" + d.strftime("%a") + ")") for d in dates]
# locale.setlocale(locale.LC_TIME, 'fr_CA.UTF-8') # Removed as it caused an error
# Mapping for English weekday abbreviations to French
french_weekdays = {
    'Mon': 'lun', 'Tue': 'mar', 'Wed': 'mer', 'Thu': 'jeu',
    'Fri': 'ven', 'Sat': 'sam', 'Sun': 'dim'
}
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
@@ -46,137 +52,141 @@
shift_types = ["Repos", "Jour", "Nuit", "Jour_court", "Conge"]
shifts = {}
for e in employes:
for d in range(periode_jours):
for s in shift_types:
shifts[(e,d,s)] = model.NewBoolVar(f"{e}_{d}_{s}")
    for d in range(periode_jours):
        for s in shift_types:
            shifts[(e,d,s)] = model.NewBoolVar(f"{e}_{d}_{s}")

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
    for d in range(periode_jours):
        model.Add(sum(shifts[(e,d,s)] for s in shift_types) == 1)
        # Congé uniquement si saisi
        if (date_debut + timedelta(days=d)) in conges_dict[e]:
            model.Add(shifts[(e,d,"Conge")] == 1)
        else:
            model.Add(shifts[(e,d,"Conge")] == 0)

# Shift court max 1 par employé sur 6 semaines
for e in employes:
for block_start in range(0, periode_jours, 42):
block_end = min(block_start + 42, periode_jours)
model.Add(sum(shifts[(e,d,"Jour_court")] for d in range(block_start, block_end)) <= 1)
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
else: # Samedi-Dimanche
model.Add(sum(shifts[(e,d,"Jour")] for e in employes) == 2)
model.Add(sum(shifts[(e,d,"Nuit")] for e in employes) == 2)
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
for d in range(periode_jours-1):
# Repos après nuit
model.Add(shifts[(e,d+1,"Repos")] == 1).OnlyEnforceIf(shifts[(e,d,"Nuit")])
# 2 jours consécutifs de repos par semaine
for week_start in range(0, periode_jours, 7):
week_days = range(week_start, min(week_start+7, periode_jours))
pairs = []
for i in range(len(week_days)-1):
pair_var = model.NewBoolVar(f"{e}_repos_pair_{week_days[i]}")
model.AddBoolAnd([shifts[(e,week_days[i],"Repos")], shifts[(e,week_days[i+1],"Repos")]]).OnlyEnforceIf(pair_var)
pairs.append(pair_var)
model.AddBoolOr(pairs)
    for d in range(periode_jours-1):
        # Repos après nuit
        model.Add(shifts[(e,d+1,"Repos")] == 1).OnlyEnforceIf(shifts[(e,d,"Nuit")])
    # 2 jours consécutifs de repos par semaine
    for week_start in range(0, periode_jours, 7):
        week_days = range(week_start, min(week_start+7, periode_jours))
        pairs = []
        for i in range(len(week_days)-1):
            pair_var = model.NewBoolVar(f"{e}_repos_pair_{week_days[i]}")
            model.AddBoolAnd([shifts[(e,week_days[i],"Repos")], shifts[(e,week_days[i+1],"Repos")]]).OnlyEnforceIf(pair_var)
            pairs.append(pair_var)
        model.AddBoolOr(pairs)

# -------------------
# BLOCS DE JOURS TRAVAILLÉS
# -------------------
for e in employes:
for d in range(periode_jours-2):
weekday = (date_debut + timedelta(days=d)).weekday()
if weekday <= 4: # Lundi → Vendredi
model.AddBoolOr([
shifts[(e,d,"Repos")],
shifts[(e,d+1,"Repos")],
shifts[(e,d+2,"Repos")]
])
for d in range(periode_jours-1):
weekday = (date_debut + timedelta(days=d)).weekday()
if weekday >= 5: # Week-end
# Jour consécutifs 2 jours
model.AddBoolOr([
shifts[(e,d,"Repos")],
shifts[(e,d+1,"Repos")],
shifts[(e,d,"Conge")],
shifts[(e,d+1,"Conge")]
]).OnlyEnforceIf([shifts[(e,d,"Jour")], shifts[(e,d+1,"Jour")]])
model.AddBoolOr([
shifts[(e,d,"Repos")],
shifts[(e,d+1,"Repos")],
shifts[(e,d,"Conge")],
shifts[(e,d+1,"Conge")]
]).OnlyEnforceIf([shifts[(e,d,"Nuit")], shifts[(e,d+1,"Nuit")]])
    for d in range(periode_jours-2):
        weekday = (date_debut + timedelta(days=d)).weekday()
        if weekday <= 4: # Lundi → Vendredi
            model.AddBoolOr([
                shifts[(e,d,"Repos")],
                shifts[(e,d+1,"Repos")],
                shifts[(e,d+2,"Repos")]
            ])
    for d in range(periode_jours-1):
        weekday = (date_debut + timedelta(days=d)).weekday()
        if weekday >= 5: # Week-end
            # Jour consécutifs 2 jours
            model.AddBoolOr([
                shifts[(e,d,"Repos")],
                shifts[(e,d+1,"Repos")],
                shifts[(e,d,"Conge")],
                shifts[(e,d+1,"Conge")]
            ]).OnlyEnforceIf([shifts[(e,d,"Jour")], shifts[(e,d+1,"Jour")]])
            model.AddBoolOr([
                shifts[(e,d,"Repos")],
                shifts[(e,d+1,"Repos")],
                shifts[(e,d,"Conge")],
                shifts[(e,d+1,"Conge")]
            ]).OnlyEnforceIf([shifts[(e,d,"Nuit")], shifts[(e,d+1,"Nuit")]])

# -------------------
# BLOCS DE NUITS
# -------------------
for e in employes:
for d in range(periode_jours-1):
weekday = (date_debut + timedelta(days=d)).weekday()
if weekday <= 3: # Lundi → Jeudi
model.AddBoolOr([
shifts[(e,d,"Repos")],
shifts[(e,d+1,"Repos")],
shifts[(e,d,"Jour")],
shifts[(e,d+1,"Jour")],
shifts[(e,d,"Jour_court")],
shifts[(e,d+1,"Jour_court")],
shifts[(e,d,"Conge")],
shifts[(e,d+1,"Conge")]
]).OnlyEnforceIf([shifts[(e,d,"Nuit")], shifts[(e,d+1,"Nuit")]])
for d in range(periode_jours-2):
weekday = (date_debut + timedelta(days=d)).weekday()
if weekday == 4: # Vendredi
model.AddBoolOr([
shifts[(e,d,"Repos")],
shifts[(e,d+1,"Repos")],
shifts[(e,d+2,"Repos")],
shifts[(e,d,"Jour")],
shifts[(e,d+1,"Jour")],
shifts[(e,d+2,"Jour")],
shifts[(e,d,"Jour_court")],
shifts[(e,d+1,"Jour_court")],
shifts[(e,d+2,"Jour_court")],
shifts[(e,d,"Conge")],
shifts[(e,d+1,"Conge")],
shifts[(e,d+2,"Conge")]
]).OnlyEnforceIf([shifts[(e,d,"Nuit")], shifts[(e,d+1,"Nuit")], shifts[(e,d+2,"Nuit")]])
    for d in range(periode_jours-1):
        weekday = (date_debut + timedelta(days=d)).weekday()
        if weekday <= 3: # Lundi → Jeudi
            model.AddBoolOr([
                shifts[(e,d,"Repos")],
                shifts[(e,d+1,"Repos")],
                shifts[(e,d,"Jour")],
                shifts[(e,d+1,"Jour")],
                shifts[(e,d,"Jour_court")],
                shifts[(e,d+1,"Jour_court")],
                shifts[(e,d,"Conge")],
                shifts[(e,d+1,"Conge")]
            ]).OnlyEnforceIf([shifts[(e,d,"Nuit")], shifts[(e,d+1,"Nuit")]])
    for d in range(periode_jours-2):
        weekday = (date_debut + timedelta(days=d)).weekday()
        if weekday == 4: # Vendredi
            model.AddBoolOr([
                shifts[(e,d,"Repos")],
                shifts[(e,d+1,"Repos")],
                shifts[(e,d+2,"Repos")],
                shifts[(e,d,"Jour")],
                shifts[(e,d+1,"Jour")],
                shifts[(e,d+2,"Jour")],
                shifts[(e,d,"Jour_court")],
                shifts[(e,d+1,"Jour_court")],
                shifts[(e,d+2,"Jour_court")],
                shifts[(e,d,"Conge")],
                shifts[(e,d+1,"Conge")],
                shifts[(e,d+2,"Conge")]
            ]).OnlyEnforceIf([shifts[(e,d,"Nuit")], shifts[(e,d+1,"Nuit")], shifts[(e,d+2,"Nuit")]])

# -------------------
# HEURES PAR EMPLOYÉ
# -------------------
# Facteur de mise à l'échelle pour les heures (multiplier par 4 pour convertir 11.25 et 7.5 en entiers)
scale_factor = 4

for e in employes:
for block_start in range(0, periode_jours, 42):
block_end = min(block_start + 42, periode_jours)
total_heures = sum(
11.25*(shifts[(e,d,"Jour")] + shifts[(e,d,"Nuit")] + shifts[(e,d,"Conge")]) +
7.5*shifts[(e,d,"Jour_court")]
for d in range(block_start, block_end)
)
if not leve_210h:
model.Add(total_heures == 210)
else:
model.Add(total_heures <= 210)
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
@@ -192,46 +202,46 @@
# REMPLISSAGE PLANNING ET COMPTEUR
# -------------------
compteur = pd.DataFrame(0, index=employes, columns=[
"Jour semaine", "Nuit semaine", "Jour week-end", "Nuit week-end", "Shift court"
    "Jour semaine", "Nuit semaine", "Jour week-end", "Nuit week-end", "Shift court"
])
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
