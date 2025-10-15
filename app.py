# planning_streamlit_final.py
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ortools.sat.python import cp_model

st.set_page_config(layout="wide")
st.title("📅 Générateur de Planning - Final (contrats : 3 consécutifs, weekends, équité, 70h/2sem)")

# -------------------
# UI - paramètres
# -------------------
st.sidebar.header("⚙️ Paramètres")
nb_employes = st.sidebar.number_input("Nombre d'employés", min_value=5, max_value=50, value=15)
date_debut = st.sidebar.date_input("Date de début de période", value=datetime(2025, 11, 2))
periode_jours = st.sidebar.number_input("Durée de la période (jours)", min_value=14, max_value=84, value=42)
solver_timeout = st.sidebar.number_input("Timeout solveur (s)", min_value=30, max_value=1200, value=300)
leve_210h = st.sidebar.checkbox("🔓 Lever la contrainte 210h (pour debug)", value=False)
relax_70h = st.sidebar.checkbox("🔓 Relaxer contrainte 70h sur 2 semaines (<= au lieu de ==)", value=False)

# derived
employes = [f"Employé {i+1}" for i in range(nb_employes)]
dates = [date_debut + timedelta(days=i) for i in range(periode_jours)]
french_weekdays = {'Mon': 'lun','Tue':'mar','Wed':'mer','Thu':'jeu','Fri':'ven','Sat':'sam','Sun':'dim'}
jours_str = [(d.strftime("%Y-%m-%d") + " (" + french_weekdays[d.strftime('%a')] + ")") for d in dates]

# -------------------
# Saisie congés (multiselect)
# -------------------
st.subheader("📝 Saisie des congés validés (sélection multiple)")
conges_dict = {}
for e in employes:
    selected = st.multiselect(
        f"Congés {e}",
        options=dates,
        format_func=lambda x: x.strftime("%Y-%m-%d"),
        key=f"conges_{e}"
    )
    conges_dict[e] = selected

st.markdown("---")
st.write("Quand les congés sont saisis pour tous les employés, cliquez sur **Générer le planning**.")

if not st.button("Générer le planning"):
    st.stop()

st.info("Optimisation en cours — cela peut prendre un peu de temps selon la taille du problème...")

# -------------------
# Modèle OR-Tools
# -------------------
model = cp_model.CpModel()

shift_types = ["Repos", "Jour", "Nuit", "Jour_court", "Conge"]
# shifts[(ei,d,shift)]
shifts = {}
for ei in range(len(employes)):
    for d in range(periode_jours):
        for s in shift_types:
            shifts[(ei,d,s)] = model.NewBoolVar(f"sh_e{ei}_d{d}_{s}")

# weekend variables (binary) for each saturday index wj
weekend_indices = [i for i, dt in enumerate(dates) if dt.weekday() == 5]  # samedi
nb_weekends = len(weekend_indices)
weekend_vars = {}
for ei in range(len(employes)):
    for wj, w in enumerate(weekend_indices):
        b_j = model.NewBoolVar(f"we_e{ei}_w{wj}_jour")
        b_n = model.NewBoolVar(f"we_e{ei}_w{wj}_nuit")
        weekend_vars[(ei,wj)] = (b_j, b_n)

# -------------------
# CONTRAINTES DE BASE
# -------------------
# 1 shift par jour ; congés forcés
for ei in range(len(employes)):
    for d in range(periode_jours):
        model.Add(sum(shifts[(ei,d,s)] for s in shift_types) == 1)
        if dates[d] in conges_dict[employes[ei]]:
            model.Add(shifts[(ei,d,"Conge")] == 1)
        else:
            model.Add(shifts[(ei,d,"Conge")] == 0)

# shift court max 1 par employé sur 6 semaines
for ei in range(len(employes)):
    for block_start in range(0, periode_jours, 42):
        block_end = min(block_start+42, periode_jours)
        model.Add(sum(shifts[(ei,d,"Jour_court")] for d in range(block_start, block_end)) <= 1)

# shift court max 1 par jour (lun-ven)
for d in range(periode_jours):
    if dates[d].weekday() < 5:
        model.Add(sum(shifts[(ei,d,"Jour_court")] for ei in range(len(employes))) <= 1)

# -------------------
# STAFFING
# -------------------
for d in range(periode_jours):
    wd = dates[d].weekday()
    if wd < 5:  # Lundi-Vendredi
        model.Add(sum(shifts[(ei,d,"Jour")] + shifts[(ei,d,"Jour_court")] for ei in range(len(employes))) >= 4)
        model.Add(sum(shifts[(ei,d,"Jour")] + shifts[(ei,d,"Jour_court")] for ei in range(len(employes))) <= 7)
        model.Add(sum(shifts[(ei,d,"Nuit")] for ei in range(len(employes))) == 2)
    else:  # Samedi-Dimanche, staffing strict
        model.Add(sum(shifts[(ei,d,"Jour")] for ei in range(len(employes))) == 2)
        model.Add(sum(shifts[(ei,d,"Nuit")] for ei in range(len(employes))) == 2)

# -------------------
# REPOS: au moins 2 jours off par semaine (Repos ou Conge)
# -------------------
for ei in range(len(employes)):
    for week_start in range(0, periode_jours, 7):
        days = range(week_start, min(week_start+7, periode_jours))
        model.Add(sum(shifts[(ei,d,"Repos")] + shifts[(ei,d,"Conge")] for d in days) >= 2)

# -------------------
# REPOS APRÈS NUIT: si nuit -> lendemain Repos (OnlyEnforceIf)
# -------------------
for ei in range(len(employes)):
    for d in range(periode_jours-1):
        model.Add(shifts[(ei,d+1,"Repos")] == 1).OnlyEnforceIf(shifts[(ei,d,"Nuit")])

# -------------------
# MAX 3 SHIFTS CONSECUTIFS (quel que soit le type jour/nuit/jour_court)
# - on crée is_working[ei,d] boolean
# - sum_{d..d+3} is_working <= 3
# -------------------
is_working = {}
for ei in range(len(employes)):
    for d in range(periode_jours):
        wvar = model.NewBoolVar(f"iswork_e{ei}_d{d}")
        is_working[(ei,d)] = wvar
        # sum_shifts_work = Jour + Nuit + Jour_court
        model.Add(shifts[(ei,d,"Jour")] + shifts[(ei,d,"Nuit")] + shifts[(ei,d,"Jour_court")] >= wvar)
        model.Add(shifts[(ei,d,"Jour")] + shifts[(ei,d,"Nuit")] + shifts[(ei,d,"Jour_court")] <= 3 * wvar)
        # If Conge or Repos then wvar must be 0 implied by the inequalities
for ei in range(len(employes)):
    for d in range(periode_jours - 3):
        model.Add(sum(is_working[(ei,dd)] for dd in range(d, d+4)) <= 3)

# -------------------
# WEEK-ENDS : assignation flexible + contiguity (impose les shifts lorsque weekend_jour/nuit = 1)
# - limiter nb weekends par employé à ceil(nb_weekends/3)
# -------------------
max_weekends_per_emp = (nb_weekends + 2) // 3  # ceil
for ei in range(len(employes)):
    model.Add(sum(weekend_vars[(ei,wj)][0] + weekend_vars[(ei,wj)][1] for wj in range(nb_weekends)) <= max_weekends_per_emp)
    for wj, w in enumerate(weekend_indices):
        b_j, b_n = weekend_vars[(ei,wj)]
        model.Add(b_j + b_n <= 1)
        # contiguity for jour
        model.Add(shifts[(ei,w,"Jour")] == 1).OnlyEnforceIf(b_j)
        if w+1 < periode_jours:
            model.Add(shifts[(ei,w+1,"Jour")] == 1).OnlyEnforceIf(b_j)
        # contiguity for nuit
        model.Add(shifts[(ei,w,"Nuit")] == 1).OnlyEnforceIf(b_n)
        if w+1 < periode_jours:
            model.Add(shifts[(ei,w+1,"Nuit")] == 1).OnlyEnforceIf(b_n)
        if w-1 >= 0:
            model.Add(shifts[(ei,w-1,"Nuit")] == 1).OnlyEnforceIf(b_n)

# -------------------
# HEURES 210h / 6 semaines (scale_factor = 4)
# - NOTE: nuits du samedi et du dimanche (weekday 5 et 6) NE SONT PAS comptées
# - Les "Conge" comptent comme journée travaillée
# -------------------
scale_factor = 4
for ei in range(len(employes)):
    for block_start in range(0, periode_jours, 42):
        block_end = min(block_start+42, periode_jours)
        terms = []
        for d in range(block_start, block_end):
            # Jour
            terms.append(int(11.25 * scale_factor) * shifts[(ei,d,"Jour")])
            # Jour_court
            terms.append(int(7.5 * scale_factor) * shifts[(ei,d,"Jour_court")])
            # Conge counts as worked day
            terms.append(int(11.25 * scale_factor) * shifts[(ei,d,"Conge")])
            # Nuits: include only if not saturday(5) or sunday(6)
            if dates[d].weekday() not in (5,6):
                terms.append(int(11.25 * scale_factor) * shifts[(ei,d,"Nuit")])
            # else: skip saturday/sunday night
        total_block = sum(terms)
        if not leve_210h:
            model.Add(total_block == int(210 * scale_factor))
        else:
            model.Add(total_block <= int(210 * scale_factor))

# -------------------
# CONTRAINTE SUPPLÉMENTAIRE: Moyenne 70h sur fenêtres glissantes de 14 jours (dimanche->samedi)
# - On impose pour chaque fenêtre commençant un dimanche: total_hours_window == 70*scale_factor
# - Si 'relax_70h' est coché on impose <= 70*scale_factor (relaxation)
# -------------------
hours_2w_scaled = 70 * scale_factor
for start in range(periode_jours):
    if dates[start].weekday() == 6 and start + 13 < periode_jours:  # sunday start, 14-day window exists
        for ei in range(len(employes)):
            terms = []
            for d in range(start, start+14):
                # add same logic as above for counting hours (exclude sat/sun nights)
                terms.append(int(11.25 * scale_factor) * shifts[(ei,d,"Jour")])
                terms.append(int(7.5 * scale_factor) * shifts[(ei,d,"Jour_court")])
                terms.append(int(11.25 * scale_factor) * shifts[(ei,d,"Conge")])
                if dates[d].weekday() not in (5,6):
                    terms.append(int(11.25 * scale_factor) * shifts[(ei,d,"Nuit")])
            total_win = sum(terms)
            if relax_70h:
                model.Add(total_win <= hours_2w_scaled)
            else:
                model.Add(total_win == hours_2w_scaled)

# -------------------
# ÉQUITÉ: minimiser l'écart max-min par catégorie
# - Catégories: Jour semaine, Nuit semaine, Jour week-end, Nuit week-end, Jour_court (global)
# - Pour chaque cat: créer total_ei (IntVar), max_cat, min_cat ; contrainte puis minimize sum(max-min)
# -------------------
cats = {
    "Jour_semaine": lambda ei,d: (dates[d].weekday() <= 4, "Jour"),
    "Nuit_semaine": lambda ei,d: (dates[d].weekday() <= 4, "Nuit"),
    "Jour_weekend": lambda ei,d: (dates[d].weekday() >= 5, "Jour"),
    "Nuit_weekend": lambda ei,d: (dates[d].weekday() >= 5, "Nuit"),
    "Jour_court": lambda ei,d: (True, "Jour_court")
}
totals = {cat: [] for cat in cats}
for cat, condfun in cats.items():
    for ei in range(len(employes)):
        tot_var = model.NewIntVar(0, periode_jours, f"tot_{cat}_e{ei}")
        # build sum expression
        expr = []
        for d in range(periode_jours):
            cond, sh_name = condfun(ei,d)
            if cond:
                expr.append(shifts[(ei,d,sh_name)])
        model.Add(tot_var == sum(expr))
        totals[cat].append(tot_var)
# create max/min and diff per category
diff_cat_vars = []
for cat in cats:
    max_var = model.NewIntVar(0, periode_jours, f"max_{cat}")
    min_var = model.NewIntVar(0, periode_jours, f"min_{cat}")
    for ei in range(len(employes)):
        model.Add(max_var >= totals[cat][ei])
        model.Add(min_var <= totals[cat][ei])
    diff = model.NewIntVar(0, periode_jours, f"diff_{cat}")
    model.Add(diff == max_var - min_var)
    diff_cat_vars.append(diff)

# -------------------
# OBJECTIF: minimiser la somme des différences (équité)
# -------------------
model.Minimize(sum(diff_cat_vars))

# -------------------
# Solve
# -------------------
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = int(solver_timeout)
solver.parameters.num_search_workers = 8
status = solver.Solve(model)

# -------------------
# Extraction résultats
# -------------------
planning = pd.DataFrame("", index=employes, columns=jours_str)
compteur = pd.DataFrame(0, index=employes, columns=["Jour semaine","Nuit semaine","Jour week-end","Nuit week-end","Shift court","Conge"])

if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    for ei in range(len(employes)):
        for d in range(periode_jours):
            for s in shift_types:
                if solver.Value(shifts[(ei,d,s)]):
                    planning.iat[ei,d] = s
                    day = dates[d]
                    if s == "Jour":
                        if day.weekday() <= 4:
                            compteur.at[employes[ei],"Jour semaine"] += 1
                        else:
                            compteur.at[employes[ei],"Jour week-end"] += 1
                    elif s == "Nuit":
                        if day.weekday() <= 3:
                            compteur.at[employes[ei],"Nuit semaine"] += 1
                        else:
                            compteur.at[employes[ei],"Nuit week-end"] += 1
                    elif s == "Jour_court":
                        compteur.at[employes[ei],"Shift court"] += 1
                    elif s == "Conge":
                        compteur.at[employes[ei],"Conge"] += 1
else:
    st.error("Aucune solution trouvée. Essaie d'augmenter le timeout ou de décocher 'Lever la contrainte 210h' / 'Relaxer 70h'.")

# -------------------
# Affichage
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

st.subheader("📊 Compteurs et vérifications")
st.dataframe(compteur)

# affichage supplémentaire : totaux weekend jugés par employé
we_summary = []
for ei in range(len(employes)):
    wj = sum(int(solver.Value(weekend_vars[(ei,wj)][0])) for wj in range(nb_weekends))
    wn = sum(int(solver.Value(weekend_vars[(ei,wj)][1])) for wj in range(nb_weekends))
    we_summary.append({"employe": employes[ei], "weekend_jour": wj, "weekend_nuit": wn})
st.write(pd.DataFrame(we_summary))

st.write("✅ Remarques :")
st.write("- Les nuits du samedi et du dimanche ont été exclues du calcul des 210h (la nuit de vendredi compte).")
st.write("- Les week-ends sont pris en compte dans la rotation et la planification (contiguïté imposée).")
st.write("- Max 3 jours travaillés consécutifs (tous types confondus) est appliqué.")
st.write("- Les fenêtres de 14 jours débutent les dimanches ; si 'Relaxer 70h' est décochée, la contrainte ==70h est imposée, sinon <=70h.")

