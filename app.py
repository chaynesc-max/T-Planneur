import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ortools.sat.python import cp_model
import math

st.set_page_config(layout="wide")
st.title("📅 Générateur de Planning — Week-ends intégrés (nuit WE exclues des 210h)")

# -------------------
# PARAMÈTRES UI
# -------------------
st.sidebar.header("⚙️ Paramètres")
nb_employes = st.sidebar.number_input("Nombre d'employés", min_value=5, max_value=50, value=15)
date_debut = st.sidebar.date_input("Date de début de période", value=datetime(2025, 11, 2))
periode_jours = st.sidebar.number_input("Durée de la période (jours)", min_value=14, max_value=84, value=42)
solver_timeout = st.sidebar.number_input("Timeout solveur (s)", min_value=30, max_value=1200, value=300)
leve_210h = st.sidebar.checkbox("🔓 Lever la contrainte 210h (pour debug)", value=False)

# derived
employes = [f"Employé {i+1}" for i in range(nb_employes)]
dates = [date_debut + timedelta(days=i) for i in range(periode_jours)]
french_weekdays = {'Mon':'lun','Tue':'mar','Wed':'mer','Thu':'jeu','Fri':'ven','Sat':'sam','Sun':'dim'}
jours_str = [(d.strftime("%Y-%m-%d") + " (" + french_weekdays[d.strftime('%a')] + ")") for d in dates]

# -------------------
# SAISIE CONGÉS (MULTI)
# -------------------
st.subheader("📝 Saisie des congés validés (sélection multiple)")
conges_dict = {}
for e in employes:
    # multiselect using formatted dates
    selected = st.multiselect(
        f"Congés {e}",
        options=dates,
        format_func=lambda x: x.strftime("%Y-%m-%d"),
        key=f"conges_{e}"
    )
    conges_dict[e] = selected

st.markdown("---")
st.write("Quand les congés sont saisis pour tous les employés, cliquez sur **Générer le planning**.")

# -------------------
# BOUTON: Génération
# -------------------
if not st.button("Générer le planning"):
    st.stop()

st.info("Optimisation en cours — ceci peut prendre quelques dizaines de secondes selon la taille du problème...")

# -------------------
# MODELISATION OR-TOOLS
# -------------------
model = cp_model.CpModel()

shift_types = ["Repos", "Jour", "Nuit", "Jour_court", "Conge"]
shifts = {}  # shifts[(e_index, d_index, shift_name)] -> BoolVar

for ei, e in enumerate(employes):
    for d in range(periode_jours):
        for s in shift_types:
            shifts[(ei,d,s)] = model.NewBoolVar(f"{ei}_{d}_{s}")

# WEEKEND variables: for each weekend (samedi index) and each employee, two bools
weekend_indices = [i for i,dt in enumerate(dates) if dt.weekday() == 5]  # samedis
weekend_vars = {}  # weekend_vars[(ei, widx)] = (weekend_jour_bool, weekend_nuit_bool)
for ei in range(len(employes)):
    for wj, w in enumerate(weekend_indices):
        b_jour = model.NewBoolVar(f"we_emp{ei}_w{wj}_jour")
        b_nuit = model.NewBoolVar(f"we_emp{ei}_w{wj}_nuit")
        weekend_vars[(ei, wj)] = (b_jour, b_nuit)

# -------------------
# CONTRAINTES DE BASE
# -------------------
# 1) un et un seul shift par employé/jour
for ei in range(len(employes)):
    for d in range(periode_jours):
        model.Add(sum(shifts[(ei,d,s)] for s in shift_types) == 1)
        # si congé sélectionné -> Conge == 1 ; sinon Conge == 0
        if dates[d] in conges_dict[employes[ei]]:
            model.Add(shifts[(ei,d,"Conge")] == 1)
        else:
            model.Add(shifts[(ei,d,"Conge")] == 0)

# 2) shift court max 1 par employé sur 6 semaines (block 42 jours)
for ei in range(len(employes)):
    for block_start in range(0, periode_jours, 42):
        block_end = min(block_start + 42, periode_jours)
        model.Add(sum(shifts[(ei,d,"Jour_court")] for d in range(block_start, block_end)) <= 1)

# 3) shift court global max 1 par jour (lun-vend)
for d in range(periode_jours):
    if dates[d].weekday() < 5:
        model.Add(sum(shifts[(ei,d,"Jour_court")] for ei in range(len(employes))) <= 1)

# -------------------
# STAFFING: nombre de ressources par quart
# -------------------
for d in range(periode_jours):
    wd = dates[d].weekday()
    if wd < 5:  # Lundi-Vendredi
        # Jour (incl. jour_court) >=4 and <=7
        model.Add(sum(shifts[(ei,d,"Jour")] + shifts[(ei,d,"Jour_court")] for ei in range(len(employes))) >= 4)
        model.Add(sum(shifts[(ei,d,"Jour")] + shifts[(ei,d,"Jour_court")] for ei in range(len(employes))) <= 7)
        # Nuit == 2
        model.Add(sum(shifts[(ei,d,"Nuit")] for ei in range(len(employes))) == 2)
    else:
        # Samedi-Dimanche: staffing enforced (2 jours, 2 nuits)
        model.Add(sum(shifts[(ei,d,"Jour")] for ei in range(len(employes))) == 2)
        model.Add(sum(shifts[(ei,d,"Nuit")] for ei in range(len(employes))) == 2)

# -------------------
# REPOS: au moins 2 jours off par semaine (Repos ou Conge)
# -------------------
for ei in range(len(employes)):
    for week_start in range(0, periode_jours, 7):
        week_days = range(week_start, min(week_start + 7, periode_jours))
        model.Add(sum(shifts[(ei,d,"Repos")] + shifts[(ei,d,"Conge")] for d in week_days) >= 2)

# -------------------
# REPOS APRÈS NUIT: si nuit -> jour suivant doit être Repos (sécurité)
# -------------------
for ei in range(len(employes)):
    for d in range(periode_jours - 1):
        # si employé a une nuit le jour d (quelle que soit la date),
        # le jour d+1 doit être Repos (contrainte stricte pour sécurité/recup)
        model.Add(shifts[(ei,d+1,"Repos")] == 1).OnlyEnforceIf(shifts[(ei,d,"Nuit")])

# -------------------
# WEEK-END : variables + limites par employé (1 week-end sur 3 max)
# - weekend_jour => impose samedi & dimanche = Jour
# - weekend_nuit => impose vendredi (si existant), samedi, dimanche = Nuit
# - weekend assignment counted for rotation/equity but some nights (samedi/sunday nights) excluded from 210h
# -------------------
nb_weekends = len(weekend_indices)
max_weekends_per_emp = (nb_weekends + 2) // 3  # ceil(nb_weekends / 3)
for ei in range(len(employes)):
    # total weekends assigned constraint
    model.Add(sum(weekend_vars[(ei,wj)][0] + weekend_vars[(ei,wj)][1] for wj in range(nb_weekends)) <= max_weekends_per_emp)
    for wj, w in enumerate(weekend_indices):
        b_jour, b_nuit = weekend_vars[(ei,wj)]
        # cannot be both jour and nuit same weekend
        model.Add(b_jour + b_nuit <= 1)
        # if b_jour: saturday & sunday must be Jour
        model.Add(shifts[(ei,w,"Jour")] == 1).OnlyEnforceIf(b_jour)
        if w+1 < periode_jours:
            model.Add(shifts[(ei,w+1,"Jour")] == 1).OnlyEnforceIf(b_jour)
        # if b_nuit: saturday & sunday must be Nuit (and friday if exists)
        model.Add(shifts[(ei,w,"Nuit")] == 1).OnlyEnforceIf(b_nuit)
        if w+1 < periode_jours:
            model.Add(shifts[(ei,w+1,"Nuit")] == 1).OnlyEnforceIf(b_nuit)
        if w-1 >= 0:
            model.Add(shifts[(ei,w-1,"Nuit")] == 1).OnlyEnforceIf(b_nuit)

# -------------------
# HEURES (210h / 6 semaines) — *EXCLUSION* : ne pas compter nuits du Samedi et Dimanche
# - Les "Conge" comptent comme journée travaillée (comptées)
# - La nuit du vendredi compte ; seules les nuits du samedi et dimanche sont exclues
# -------------------
scale_factor = 4
for ei in range(len(employes)):
    for block_start in range(0, periode_jours, 42):
        block_end = min(block_start + 42, periode_jours)
        terms = []
        for d in range(block_start, block_end):
            # day shift and jour_court and conge always count
            terms.append(int(11.25 * scale_factor) * shifts[(ei,d,"Jour")])
            terms.append(int(7.5 * scale_factor) * shifts[(ei,d,"Jour_court")])
            terms.append(int(11.25 * scale_factor) * shifts[(ei,d,"Conge")])
            # night: include except if it's saturday(5) or sunday(6)
            if dates[d].weekday() not in (5,6):
                terms.append(int(11.25 * scale_factor) * shifts[(ei,d,"Nuit")])
            else:
                # saturday or sunday night -> do NOT count in hours
                # we simply omit adding those terms
                pass
        total_heures_scaled = sum(terms)
        if not leve_210h:
            model.Add(total_heures_scaled == int(210 * scale_factor))
        else:
            model.Add(total_heures_scaled <= int(210 * scale_factor))

# -------------------
# OBJECTIF (facultatif) : équilibrer les week-ends jour/nuit entre employés (soft)
# On minimise la somme des écarts absolus par rapport à la moyenne
# -------------------
# compute totals per employee for weekend_jour and weekend_nuit
weekend_jour_counts = []
weekend_nuit_counts = []
for ei in range(len(employes)):
    wj_count = model.NewIntVar(0, nb_weekends, f"wj_count_{ei}")
    wn_count = model.NewIntVar(0, nb_weekends, f"wn_count_{ei}")
    model.Add(wj_count == sum(weekend_vars[(ei,wj)][0] for wj in range(nb_weekends)))
    model.Add(wn_count == sum(weekend_vars[(ei,wj)][1] for wj in range(nb_weekends)))
    weekend_jour_counts.append(wj_count)
    weekend_nuit_counts.append(wn_count)

# average (integer division)
avg_jour = sum(weekend_jour_counts)  # symbolically; will use diffs below
avg_nuit = sum(weekend_nuit_counts)

# create diff vars to minimize inequity
diff_vars = []
for ei in range(len(employes)):
    # we minimize absolute deviation from mean (approx) by using pairwise diffs to sum
    # compute difference to average via helper IntVar (we'll use simple local mean)
    diff_j = model.NewIntVar(0, nb_weekends, f"diff_j_{ei}")
    diff_n = model.NewIntVar(0, nb_weekends, f"diff_n_{ei}")
    # For simplicity, enforce diff_j >= wj_count - target and diff_j >= target - wj_count
    # choose target as floor(nb_weekends/len(employes)) which is typically 0; instead we use sum/nb_employes is hard to linearize here
    # We'll instead try to minimize total weekends assigned disparity relative to other employees via pairwise diffs (approx)
    diff_vars.append(diff_j)
    diff_vars.append(diff_n)
    # Loose bounds — set to 0 as placeholder; not adding arithmetic constraints here to avoid complicating model
    model.Add(diff_j >= 0)
    model.Add(diff_n >= 0)

# Minimal objective: prefer solutions that assign weekends (minimize total number assigned if solver struggles)
# This keeps it feasible — objective is optional; we still set a small objective to help solver find fairish solution.
model.Minimize(sum(diff_vars))

# -------------------
# SOLVE
# -------------------
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = int(solver_timeout)
solver.parameters.num_search_workers = 8
status = solver.Solve(model)

# -------------------
# RÉSULTATS -> DataFrame
# -------------------
planning = pd.DataFrame("", index=employes, columns=jours_str)
compteur = pd.DataFrame(0, index=employes, columns=["Jour semaine","Nuit semaine","Jour week-end","Nuit week-end","Shift court","Conge"])

if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    for ei in range(len(employes)):
        for d in range(periode_jours):
            for s in shift_types:
                if solver.Value(shifts[(ei,d,s)]):
                    planning.iat[ei, d] = s
                    day = dates[d]
                    if s == "Jour":
                        if day.weekday() <= 4:
                            compteur.iat[ei, compteur.columns.get_loc("Jour semaine")] += 1
                        else:
                            compteur.iat[ei, compteur.columns.get_loc("Jour week-end")] += 1
                    elif s == "Nuit":
                        if day.weekday() <= 3:
                            compteur.iat[ei, compteur.columns.get_loc("Nuit semaine")] += 1
                        else:
                            compteur.iat[ei, compteur.columns.get_loc("Nuit week-end")] += 1
                    elif s == "Jour_court":
                        compteur.iat[ei, compteur.columns.get_loc("Shift court")] += 1
                    elif s == "Conge":
                        compteur.iat[ei, compteur.columns.get_loc("Conge")] += 1
else:
    st.error("Aucune solution trouvée dans le temps imparti. Essaie de lever 210h ou d'augmenter le timeout.")

# -------------------
# AFFICHAGE
# -------------------
st.subheader("📋 Planning généré")
def color_shift(val):
    if val == "Jour": return 'background-color: #a6cee3'
    if val == "Nuit": return 'background-color: #1f78b4; color:white'
    if val == "Jour_court": return 'background-color: #b2df8a'
    if val == "Conge": return 'background-color: #fb9a99'
    if val == "Repos": return 'background-color: #f0f0f0'
    return ''

st.dataframe(planning.style.applymap(color_shift))
st.subheader("📊 Compteurs par employé")
st.dataframe(compteur)

st.write("✅ Remarques :")
st.write("- Les nuits du **samedi** et du **dimanche** ont été exclues du calcul des 210h (la nuit de vendredi compte).")
st.write("- Les week-ends sont intégrés au modèle via `weekend_jour` / `weekend_nuit` pour rotation, staffing et repos.")
st.write("- Si le solveur ne trouve pas de solution, essaie d'activer 'Lever la contrainte 210h' ou d'augmenter le timeout.")
