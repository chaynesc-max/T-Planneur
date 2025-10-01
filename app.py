import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ortools.sat.python import cp_model
# import locale # Removed as it caused an error

st.set_page_config(layout="wide")
st.title("📅 Générateur de Planning 6 Semaines - Version Finale avec Repos Réels")

# -------------------
# PARAMÈTRES
# -------------------
st.sidebar.header("⚙️ Paramètres")
nb_employes = st.sidebar.number_input("Nombre d'employés", min_value=5, max_value=50, value=15)
date_debut = st.sidebar.date_input("Date de début de période", value=datetime(2025, 11, 2))
periode_jours = 42 # 6 semaines

employes = [f"Employé {i+1}" for i in range(nb_employes)]
dates = [date_debut + timedelta(days=i) for i in range(periode_jours)]
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
    dates_conges = st.date_input(
        f"Congés {e} (peut être multiple)",
        min_value=date_debut,
        max_value=date_debut + timedelta(days=periode_jours - 1),
        value=[],
        key=e
    )
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
        # Exactement 1 shift par jour
        model.Add(sum(shifts[(e,d,s)] for s in shift_types) == 1)
        # Congés validés
        if (date_debut + timedelta(days=d)) in conges_dict[e]:
            model.Add(shifts[(e,d,"Conge")] == 1)

# Shift court max 1 par employé sur 6 semaines
for e in employes:
    model.Add(sum(shifts[(e,d,"Jour_court")] for d in range(periode_jours)) <= 1)

# -------------------
# CONTRAINTES OPÉRATIONNELLES
# -------------------
for d in range(periode_jours):
    weekday = (date_debut + timedelta(days=d)).weekday()
    if weekday < 5: # Lundi → Vendredi
        model.Add(sum(shifts[(e,d,"Jour")] + shifts[(e,d,"Jour_court")] for e in employes) >= 4)
        model.Add(sum(shifts[(e,d,"Jour")] + shifts[(e,d,"Jour_court")] for e in employes) <= 6)
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

# -------------------
# HEURES PAR EMPLOYÉ
# -------------------
# Facteur de mise à l'échelle pour les heures (multiplier par 4 pour convertir 11.25 et 7.5 en entiers)
scale_factor = 4

for e in employes:
    total_heures_scaled = sum(
        int(11.25 * scale_factor)*(shifts[(e,d,"Jour")] + shifts[(e,d,"Nuit")] + shifts[(e,d,"Conge")]) +
        int(7.5 * scale_factor)*shifts[(e,d,"Jour_court")]
        for d in range(periode_jours)
    )
    if not leve_210h:
        model.Add(total_heures_scaled == int(210 * scale_factor))
    else:
        model.Add(total_heures_scaled <= int(210 * scale_factor))


# -------------------
# SOLVEUR
# -------------------
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 120
status = solver.Solve(model)

planning = pd.DataFrame("", index=employes, columns=jours_str)
log = []

# -------------------
# REMPLISSAGE PLANNING
# -------------------
if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
    for e in employes:
        for d in range(periode_jours):
            found = False
            for s in shift_types:
                if solver.Value(shifts[(e,d,s)]) == 1:
                    planning.loc[e, jours_str[d]] = s
                    found = True
            if not found:
                planning.loc[e, jours_str[d]] = "A_attribuer"
else:
    planning[:] = "A_attribuer"
    st.error("⚠️ Pas de solution complète trouvée : certains shifts sont à attribuer")

# -------------------
# LOG DES CONTRAINTES BLOQUANTES
# -------------------
if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
    for e in employes:
        # Recalculate total hours based on solver's solution
        total_heures_solved = sum(
            11.25 * (solver.Value(shifts[(e,d,"Jour")]) + solver.Value(shifts[(e,d,"Nuit")]) + solver.Value(shifts[(e,d,"Conge")])) +
            7.5 * solver.Value(shifts[(e,d,"Jour_court")])
            for d in range(periode_jours)
        )
        if not leve_210h and total_heures_solved != 210:
            log.append([e, total_heures_solved, "Total d'heures != 210h"])
        # Add check for <= 210 when leve_210h is True
        if leve_210h and total_heures_solved > 210:
             log.append([e, total_heures_solved, "Total d'heures > 210h malgré l'option levée"])


if log:
    st.subheader("⚠️ Contraintes bloquantes détectées")
    df_log = pd.DataFrame(log, columns=["Employé", "Valeur actuelle", "Problème"])
    st.dataframe(df_log)

# -------------------
# AFFICHAGE CODÉ COULEUR + WEEK-END
# -------------------
st.subheader("📊 Planning généré")
def color_shift(val):
    colors = {
        "Jour":"background-color: #90ee90",
        "Nuit":"background-color: #87cefa",
        "Jour_court":"background-color: #fdfd96",
        "Repos":"background-color: #d3d3d3",
        "Conge":"background-color: #ff7f7f",
        "A_attribuer":"background-color: #ffa500"
    }
    return colors.get(val, "")

def weekend_border(col_name):
    if "(sam)" in col_name.lower() or "(dim)" in col_name.lower():
        return "2px solid black"
    else:
        return ""

styled = planning.style.applymap(color_shift)
for col in planning.columns:
    styled = styled.set_properties(subset=[col], **{'border': weekend_border(col)})

st.dataframe(styled, use_container_width=True)

# -------------------
# HEURES PAR EMPLOYÉ
# -------------------
st.subheader("📈 Heures par employé")
heures_par_employe = {}
for e in employes:
    heures_par_employe[e] = 0
    for d in range(periode_jours):
        val = planning.loc[e, jours_str[d]]
        if val in ["Jour","Nuit","Conge"]: heures_par_employe[e] += 11.25
        if val == "Jour_court": heures_par_employe[e] += 7.5
st.bar_chart(pd.Series(heures_par_employe))

# -------------------
# EXPORT CSV & EXCEL
# -------------------
st.subheader("💾 Exporter le planning")
csv = planning.to_csv(index=True)
st.download_button("Télécharger CSV", csv, "planning_6semaines.csv", "text/csv")
planning.to_excel("planning_6semaines.xlsx", index=True)
with open("planning_6semaines.xlsx", "rb") as f:
    st.download_button("Télécharger Excel", f, "planning_6semaines.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
