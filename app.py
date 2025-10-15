# planning_final_with_staffing.py
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ortools.sat.python import cp_model

st.set_page_config(layout="wide")
st.title("📅 Générateur de Planning")

# -------------------
# Paramètres UI
# -------------------
st.sidebar.header("⚙️ Paramètres")
nb_employes = st.sidebar.number_input("Nombre d'employés", min_value=5, max_value=50, value=15)
date_debut = st.sidebar.date_input("Date de début (dimanche)", value=datetime(2025, 11, 2))
periode_jours = st.sidebar.number_input("Durée de la période (jours)", min_value=14, max_value=84, value=42)
solver_timeout = st.sidebar.number_input("Timeout solveur (s)", min_value=30, max_value=1200, value=300)
leve_210h = st.sidebar.checkbox("🔓 Lever la contrainte 210h (debug: passe en <= upper)", value=False)
relax_70h = st.sidebar.checkbox("🔓 Relaxer contrainte 70h (<= au lieu de ==)", value=True)

# Durées (heures)
dur_jour = 11.25
dur_nuit = 11.25
dur_court = 7.5

# Derived
employes = [f"Employé {i+1}" for i in range(nb_employes)]
dates = [date_debut + timedelta(days=i) for i in range(periode_jours)]
french_weekdays = {'Mon':'lun','Tue':'mar','Wed':'mer','Thu':'jeu','Fri':'ven','Sat':'sam','Sun':'dim'}
jours_str = [(d.strftime("%Y-%m-%d") + " (" + french_weekdays[d.strftime('%a')] + ")") for d in dates]

st.markdown("### Saisie des congés (sélection multiple pour chaque employé)")
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
if not st.button("Générer le planning"):
    st.stop()

st.info("Optimisation en cours — ceci peut prendre quelques dizaines de secondes...")

# -------------------
# Modèle OR-Tools
# -------------------
model = cp_model.CpModel()
shift_types = ["Repos", "Jour", "Nuit", "Jour_court", "Conge"]

# Bool vars for shifts
shifts = {}
for ei in range(len(employes)):
    for d in range(periode_jours):
        for s in shift_types:
            shifts[(ei,d,s)] = model.NewBoolVar(f"sh_e{ei}_d{d}_{s}")

# Weekend indices (samedi positions)
weekend_indices = [i for i, dt in enumerate(dates) if dt.weekday() == 5]
nb_weekends = len(weekend_indices)

# Weekend assignment vars
weekend_vars = {}
for ei in range(len(employes)):
    for wj, w in enumerate(weekend_indices):
        b_j = model.NewBoolVar(f"we_e{ei}_w{wj}_jour")
        b_n = model.NewBoolVar(f"we_e{ei}_w{wj}_nuit")
        weekend_vars[(ei,wj)] = (b_j, b_n)

# -------------------
# Contraintes de base
# -------------------
# 1 shift par jour ; congés forcés (Conge)
for ei in range(len(employes)):
    for d in range(periode_jours):
        model.Add(sum(shifts[(ei,d,s)] for s in shift_types) == 1)
        if dates[d] in conges_dict[employes[ei]]:
            model.Add(shifts[(ei,d,"Conge")] == 1)
        else:
            model.Add(shifts[(ei,d,"Conge")] == 0)

# Shift court max 1 par employé sur 42 jours
for ei in range(len(employes)):
    for block_start in range(0, periode_jours, 42):
        block_end = min(block_start + 42, periode_jours)
        model.Add(sum(shifts[(ei,d,"Jour_court")] for d in range(block_start, block_end)) <= 1)

# Shift court global max 1 par jour (lun-vend)
for d in range(periode_jours):
    if dates[d].weekday() < 5:
        model.Add(sum(shifts[(ei,d,"Jour_court")] for ei in range(len(employes))) <= 1)

# -------------------
# STAFFING (selon tes règles)
# - Lun–Ven jour : >=5 (inclut le shift court); max kept at 7 (modifiable)
# - Lun–Jeu nuit : ==2
# - Ven–Dim nuit : >=2 and <=3
# - Sam–Dim jour : >=2 and <=3
# -------------------
for d in range(periode_jours):
    wd = dates[d].weekday()
    if wd <= 4:  # Monday(0) - Friday(4)
        # Day shifts (including day_short) at least 5, keep max 7 to limit
        model.Add(sum(shifts[(ei,d,"Jour")] + shifts[(ei,d,"Jour_court")] for ei in range(len(employes))) >= 5)
        model.Add(sum(shifts[(ei,d,"Jour")] + shifts[(ei,d,"Jour_court")] for ei in range(len(employes))) <= 7)
        # Nights: Monday-Thursday = 2, Friday handled below in Fri-Sun rule
        if wd <= 3:  # Mon-Thu
            model.Add(sum(shifts[(ei,d,"Nuit")] for ei in range(len(employes))) == 2)
    else:
        # Weekend days: Saturday(5) and Sunday(6) days: 2 to 3
        model.Add(sum(shifts[(ei,d,"Jour")] for ei in range(len(employes))) >= 2)
        model.Add(sum(shifts[(ei,d,"Jour")] for ei in range(len(employes))) <= 3)
        # Nights Fri-Sun: for Friday (wd==4) we set in else of weekdays? handle nights for Fri-Sun as 2-3
# Enforce Fri-Sun nights 2-3
for d in range(periode_jours):
    wd = dates[d].weekday()
    if wd >= 4 and wd <= 6:  # Friday(4), Saturday(5), Sunday(6)
        model.Add(sum(shifts[(ei,d,"Nuit")] for ei in range(len(employes))) >= 2)
        model.Add(sum(shifts[(ei,d,"Nuit")] for ei in range(len(employes))) <= 3)

# -------------------
# REPOS: au moins 2 jours off par semaine (Repos ou Conge)
# -------------------
for ei in range(len(employes)):
    for week_start in range(0, periode_jours, 7):
        week_days = range(week_start, min(week_start + 7, periode_jours))
        model.Add(sum(shifts[(ei,d,"Repos")] + shifts[(ei,d,"Conge")] for d in week_days) >= 2)

# -------------------
# REPOS APRÈS NUIT: si nuit -> lendemain Repos ou Conge
# -------------------
for ei in range(len(employes)):
    for d in range(periode_jours - 1):
        model.AddBoolOr([shifts[(ei,d+1,"Repos")], shifts[(ei,d+1,"Conge")]]).OnlyEnforceIf(shifts[(ei,d,"Nuit")])

# -------------------
# MAX 3 SHIFTS CONSECUTIFS (Jour/Nuit/Jour_court)
# -------------------
is_working = {}
for ei in range(len(employes)):
    for d in range(periode_jours):
        wvar = model.NewBoolVar(f"isw_e{ei}_d{d}")
        is_working[(ei,d)] = wvar
        model.Add(shifts[(ei,d,"Jour")] + shifts[(ei,d,"Nuit")] + shifts[(ei,d,"Jour_court")] >= wvar)
        model.Add(shifts[(ei,d,"Jour")] + shifts[(ei,d,"Nuit")] + shifts[(ei,d,"Jour_court")] <= 3 * wvar)
for ei in range(len(employes)):
    for d in range(periode_jours - 3):
        model.Add(sum(is_working[(ei,dd)] for dd in range(d, d+4)) <= 3)

# -------------------
# WEEK-END: contiguity & rotation (flexible)
# - limit per employee: ceil(nb_weekends/3)
# - contiguity enforced when weekend var true
# -------------------
max_weekends_per_emp = (nb_weekends + 2) // 3
for ei in range(len(employes)):
    model.Add(sum(weekend_vars[(ei,wj)][0] + weekend_vars[(ei,wj)][1] for wj in range(nb_weekends)) <= max_weekends_per_emp)
    for wj, w in enumerate(weekend_indices):
        b_j, b_n = weekend_vars[(ei,wj)]
        model.Add(b_j + b_n <= 1)
        # contiguity jour
        model.Add(shifts[(ei,w,"Jour")] == 1).OnlyEnforceIf(b_j)
        if w+1 < periode_jours:
            model.Add(shifts[(ei,w+1,"Jour")] == 1).OnlyEnforceIf(b_j)
        # contiguity nuit: friday(if exists) + saturday + sunday
        model.Add(shifts[(ei,w,"Nuit")] == 1).OnlyEnforceIf(b_n)
        if w+1 < periode_jours:
            model.Add(shifts[(ei,w+1,"Nuit")] == 1).OnlyEnforceIf(b_n)
        if w-1 >= 0:
            model.Add(shifts[(ei,w-1,"Nuit")] == 1).OnlyEnforceIf(b_n)

# -------------------
# HEURES: 210h sur 42 jours, intervalle strict [198.75, 221.25] (scaled)
# - scale_factor = 4: lower=795, upper=885
# - Conge counts as jour; saturday/sunday nights excluded
# - If leve_210h checked -> only enforce upper bound (debug)
# -------------------
scale_factor = 4
lower_scaled = int(198.75 * scale_factor)  # 795
upper_scaled = int(221.25 * scale_factor)  # 885

for ei in range(len(employes)):
    for block_start in range(0, periode_jours, 42):
        block_end = min(block_start + 42, periode_jours)
        terms = []
        for d in range(block_start, block_end):
            terms.append(int(dur_jour * scale_factor) * shifts[(ei,d,"Jour")])
            terms.append(int(dur_court * scale_factor) * shifts[(ei,d,"Jour_court")])
            terms.append(int(dur_jour * scale_factor) * shifts[(ei,d,"Conge")])
            # count night hours only when not Sat/Sun
            if dates[d].weekday() not in (5,6):
                terms.append(int(dur_nuit * scale_factor) * shifts[(ei,d,"Nuit")])
        total_block = sum(terms)
        if not leve_210h:
            model.Add(total_block >= lower_scaled)
            model.Add(total_block <= upper_scaled)
        else:
            model.Add(total_block <= upper_scaled)

# -------------------
# Fenêtres glissantes 14j (dimanche->samedi): cible 70h (souple)
# -------------------
hours_14_scaled = int(70 * scale_factor)
tol_14_scaled = int(4 * scale_factor)  # small flexibility ~4h
window_slacks = []
for start in range(periode_jours):
    if dates[start].weekday() == 6 and start + 13 < periode_jours:
        for ei in range(len(employes)):
            terms = []
            for d in range(start, start+14):
                terms.append(int(dur_jour * scale_factor) * shifts[(ei,d,"Jour")])
                terms.append(int(dur_court * scale_factor) * shifts[(ei,d,"Jour_court")])
                terms.append(int(dur_jour * scale_factor) * shifts[(ei,d,"Conge")])
                if dates[d].weekday() not in (5,6):
                    terms.append(int(dur_nuit * scale_factor) * shifts[(ei,d,"Nuit")])
            sum_win = sum(terms)
            if relax_70h:
                model.Add(sum_win <= hours_14_scaled + tol_14_scaled)
            else:
                slack_hi = model.NewIntVar(0, 1000000, f"wsl_hi_e{ei}_s{start}")
                slack_lo = model.NewIntVar(0, 1000000, f"wsl_lo_e{ei}_s{start}")
                model.Add(sum_win + slack_lo >= hours_14_scaled - tol_14_scaled)
                model.Add(sum_win - slack_hi <= hours_14_scaled + tol_14_scaled)
                window_slacks.append(slack_hi)
                window_slacks.append(slack_lo)

# -------------------
# Équité : totals per category and diffs
# Categories: Jour_semaine, Nuit_semaine, Jour_weekend, Nuit_weekend, Jour_court
# -------------------
cats = {
    "Jour_semaine": lambda d: dates[d].weekday() <= 4 and "Jour",
    "Nuit_semaine": lambda d: dates[d].weekday() <= 4 and "Nuit",
    "Jour_weekend": lambda d: dates[d].weekday() >= 5 and "Jour",
    "Nuit_weekend": lambda d: dates[d].weekday() >= 5 and "Nuit",
    "Jour_court": lambda d: True and "Jour_court"
}
totals = {cat: [] for cat in cats}
for cat, condfun in cats.items():
    for ei in range(len(employes)):
        tot_var = model.NewIntVar(0, periode_jours, f"tot_{cat}_e{ei}")
        expr = []
        for d in range(periode_jours):
            cond_sh = condfun(d)
            if cond_sh:
                sh_name = cond_sh
                expr.append(shifts[(ei,d,sh_name)])
        model.Add(tot_var == sum(expr))
        totals[cat].append(tot_var)

diff_cat_vars = []
for cat in totals:
    max_var = model.NewIntVar(0, periode_jours, f"max_{cat}")
    min_var = model.NewIntVar(0, periode_jours, f"min_{cat}")
    for ei in range(len(employes)):
        model.Add(max_var >= totals[cat][ei])
        model.Add(min_var <= totals[cat][ei])
    diff = model.NewIntVar(0, periode_jours, f"diff_{cat}")
    model.Add(diff == max_var - min_var)
    diff_cat_vars.append(diff)

# -------------------
# OBJECTIF: minimise sum(diff_cat_vars) with slight penalty on window_slacks
# -------------------
W_WINDOW = 100  # penalize window slacks if used
W_EQUITY = 1
obj_terms = []
for d in diff_cat_vars:
    obj_terms.append(W_EQUITY * d)
for s in window_slacks:
    obj_terms.append(W_WINDOW * s)
model.Minimize(sum(obj_terms))

# -------------------
# Solve
# -------------------
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = int(solver_timeout)
solver.parameters.num_search_workers = 8
solver.parameters.linearization_level = 2
solver.parameters.cp_model_presolve = True

status = solver.Solve(model)

planning = pd.DataFrame("", index=employes, columns=jours_str)
compteur = pd.DataFrame(0, index=employes, columns=["Jour semaine","Nuit semaine","Jour week-end","Nuit week-end","Jour_court","Conge","Repos"])

if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    st.success(f"Solution trouvée : {solver.StatusName(status)} (obj={solver.ObjectiveValue():.1f})")
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
                        compteur.at[employes[ei],"Jour_court"] += 1
                    elif s == "Conge":
                        compteur.at[employes[ei],"Conge"] += 1
                    elif s == "Repos":
                        compteur.at[employes[ei],"Repos"] += 1
else:
    st.error(f"Aucune solution trouvée (status={solver.StatusName(status)}). Essaie d'augmenter le timeout ou de cocher 'Lever la contrainte 210h' / 'Relaxer 70h'.")
    st.stop()

# -------------------
# Affichage
# -------------------
st.subheader("📋 Planning")
def color_shift(val):
    if val == "Jour": return 'background-color: #a6cee3'
    if val == "Nuit": return 'background-color: #1f78b4; color:white'
    if val == "Jour_court": return 'background-color: #b2df8a'
    if val == "Conge": return 'background-color: #fb9a99'
    if val == "Repos": return 'background-color: #f0f0f0'
    return ''
st.dataframe(planning.style.applymap(color_shift), height=600)

st.subheader("📊 Compteurs par employé")
st.dataframe(compteur)

# -------------------
# Vérifications horaires (42j) et fenêtres 14j
# -------------------
scale_factor = 4
def compute_scaled_hours_for_ei(ei):
    total = 0
    for d in range(periode_jours):
        s = planning.iat[ei,d]
        if s == "Jour":
            total += int(dur_jour * scale_factor)
        elif s == "Jour_court":
            total += int(dur_court * scale_factor)
        elif s == "Conge":
            total += int(dur_jour * scale_factor)
        elif s == "Nuit":
            if dates[d].weekday() not in (5,6):
                total += int(dur_nuit * scale_factor)
    return total

st.subheader("🔎 Vérifications hours & windows")
hours_summary = []
for ei in range(len(employes)):
    h_scaled = compute_scaled_hours_for_ei(ei)
    hours = h_scaled / scale_factor
    hours_summary.append({"employe": employes[ei], "hours_42d": hours})
st.dataframe(pd.DataFrame(hours_summary))

# windows 14d
win_summary = []
for start in range(periode_jours):
    if dates[start].weekday() == 6 and start + 13 < periode_jours:
        row = {"window_start": dates[start].strftime("%Y-%m-%d")}
        for ei in range(len(employes)):
            total = 0.0
            for d in range(start, start+14):
                s = planning.iat[ei,d]
                if s == "Jour":
                    total += dur_jour
                elif s == "Jour_court":
                    total += dur_court
                elif s == "Conge":
                    total += dur_jour
                elif s == "Nuit":
                    if dates[d].weekday() not in (5,6):
                        total += dur_nuit
            row[employes[ei]] = total
        win_summary.append(row)
if win_summary:
    st.write("Fenêtres 14j (heures) — lignes: fenêtres débutant dimanche")
    st.dataframe(pd.DataFrame(win_summary).set_index("window_start"))

# weekend summary
we_summary = []
for ei in range(len(employes)):
    wj = sum(int(solver.Value(weekend_vars[(ei,wj)][0])) for wj in range(nb_weekends))
    wn = sum(int(solver.Value(weekend_vars[(ei,wj)][1])) for wj in range(nb_weekends))
    we_summary.append({"employe": employes[ei], "weekend_jour": wj, "weekend_nuit": wn})
st.subheader("📈 Récapitulatif week-ends")
st.dataframe(pd.DataFrame(we_summary))

st.write("✅ Remarques :")
st.write("- La contrainte 210 h est appliquée strictement dans [198.75, 221.25] (sauf si 'Lever la contrainte 210h' est coché).")
st.write("- Les nuits du samedi et dimanche sont exclues du calcul des 210 h (la nuit du vendredi compte).")
st.write("- Si la résolution échoue, augmente le timeout ou active le debug 'Lever la contrainte 210h' / 'Relaxer 70h'.")
