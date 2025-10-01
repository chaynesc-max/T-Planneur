 	Avertissement automatisé : Ce courriel provient de l'extérieur de votre organisation. Ne cliquez pas sur les liens et les pièces jointes si vous ne reconnaissez pas l'expéditeur.
 
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ortools.sat.python import cp_model
import locale

st.title("📅 Générateur de Planning - 6 Semaines")

# -------------------
# PARAMÈTRES
# -------------------
st.sidebar.header("⚙️ Paramètres")
nb_employes = st.sidebar.number_input("Nombre d'employés", min_value=5, max_value=50, value=15)
date_debut = st.sidebar.date_input("Date de début de période", value=datetime(2025, 11, 2))
periode_jours = 42 # 6 semaines

employes = [f"Employé {i+1}" for i in range(nb_employes)]
dates = [date_debut + timedelta(days=i) for i in range(periode_jours)]

# Dates + jour de la semaine
locale.setlocale(locale.LC_TIME, 'fr_CA.UTF-8')
jours_str = [(d.strftime("%Y-%m-%d") + " (" + d.strftime("%a") + ")") for d in dates]

# -------------------
# CONGÉS VALIDÉS
# -------------------
st.subheader("📝 Saisie des congés validés")
conges_dict = {e: [] for e in employes}
for e in employes:
dates_conges = st.date_input(
f"Congés {e}",
min_value=date_debut,
max_value=date_debut+timedelta(days=periode_jours-1),
value=[],
key=e
)
if isinstance(dates_conges, datetime):
dates_conges = [dates_conges]
conges_dict[e] = dates_conges

# -------------------
# VARIABLES ORTOOLS
# -------------------
model = cp_model.CpModel()
shift_types = ["Repos", "Jour", "Nuit", "Jour_court", "Conge", "A_attribuer"]
shifts = {}
for e in employes:
for d in range(periode_jours):
for s in shift_types:
shifts[(e, d, s)] = model.NewBoolVar(f"{e}_{d}_{s}")

# -------------------
# CONTRAINTES
# -------------------
for e in employes:
for d in range(periode_jours):
# 1 shift max par jour
model.Add(sum(shifts[(e,d,s)] for s in shift_types) == 1)
# Congés validés
if (date_debut + timedelta(days=d)) in conges_dict[e]:
model.Add(shifts[(e,d,"Conge")] == 1)

# Shift court max 1 par employé sur 6 semaines
for e in employes:
model.Add(sum(shifts[(e,d,"Jour_court")] for d in range(periode_jours)) <= 1)

# Besoins opérationnels
for d in range(periode_jours):
weekday = (date_debut + timedelta(days=d)).weekday()
if weekday < 5: # Lundi → Vendredi
model.Add(sum(shifts[(e,d,"Jour")] + shifts[(e,d,"Jour_court")] for e in employes) >= 4)
model.Add(sum(shifts[(e,d,"Jour")] + shifts[(e,d,"Jour_court")] for e in employes) <= 6)
model.Add(sum(shifts[(e,d,"Nuit")] for e in employes) == 2)
else: # Samedi-Dimanche
model.Add(sum(shifts[(e,d,"Jour")] for e in employes) == 2)
model.Add(sum(shifts[(e,d,"Nuit")] for e in employes) == 2)

# Repos après nuit (au moins 1 jour)
for e in employes:
for d in range(periode_jours-1):
model.AddBoolOr([
shifts[(e,d,"Nuit")].Not(),
shifts[(e,d+1,"Jour")].Not(),
shifts[(e,d+1,"Jour_court")].Not(),
shifts[(e,d+1,"Nuit")].Not()
])

# Heures par employé (~210h / 6 semaines)
for e in employes:
heures = []
for d in range(periode_jours):
heures.append(11.25*shifts[(e,d,"Jour")])
heures.append(11.25*shifts[(e,d,"Nuit")])
heures.append(7.5*shifts[(e,d,"Jour_court")])
total_heures = sum(heures)
model.Add(total_heures >= 210-5)
model.Add(total_heures <= 210+5)

# -------------------
# SOLVEUR
# -------------------
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 120
status = solver.Solve(model)

planning = pd.DataFrame("", index=employes, columns=jours_str)

if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
for e in employes:
for d in range(periode_jours):
found = False
for s in ["Jour","Nuit","Jour_court","Conge"]:
if solver.Value(shifts[(e,d,s)]) == 1:
planning.loc[e, jours_str[d]] = s
found = True
if not found:
planning.loc[e, jours_str[d]] = "A_attribuer"
else:
st.warning("⚠️ Pas de solution complète : certains shifts sont à attribuer manuellement")
planning[:] = "A_attribuer"

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

st.dataframe(styled)

# Heures par employé
st.subheader("📈 Heures par employé")
heures_par_employe = {}
for e in employes:
heures_par_employe[e] = 0
for d in range(periode_jours):
if planning.loc[e, jours_str[d]] == "Jour": heures_par_employe[e] += 11.25
if planning.loc[e, jours_str[d]] == "Nuit": heures_par_employe[e] += 11.25
if planning.loc[e, jours_str[d]] == "Jour_court": heures_par_employe[e] += 7.5
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

