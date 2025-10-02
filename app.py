import streamlit as st
import pandas as pd
import datetime
from ortools.sat.python import cp_model

# ------------------------------
# PARAMÈTRES INTERFACE
# ------------------------------
st.sidebar.title("Paramètres de planification")
nb_employes = st.sidebar.number_input("Nombre d'employés", min_value=1, max_value=50, value=12, step=1)
debut_periode = st.sidebar.date_input("Date de début de période", value=datetime.date(2025,11,2))
nb_semaines = st.sidebar.number_input("Nombre de semaines", min_value=1, max_value=12, value=6, step=1)

# ------------------------------
# TYPES DE SHIFT
# ------------------------------
JOUR_SEMAINE = "Jour semaine"
NUIT_SEMAINE = "Nuit semaine"
WEEKEND_JOUR = "Week-end jour"
WEEKEND_NUIT = "Week-end nuit"
SHIFT_COURT = "Quart court"
REPOS = "Repos"
shift_types = [JOUR_SEMAINE, NUIT_SEMAINE, WEEKEND_JOUR, WEEKEND_NUIT, SHIFT_COURT, REPOS]
shift_index = {s:i for i,s in enumerate(shift_types)}

# ------------------------------
# GENERATION DES JOURS
# ------------------------------
jours = [debut_periode + datetime.timedelta(days=i) for i in range(nb_semaines*7)]
num_days = len(jours) # Get the number of days for easier iteration

# ------------------------------
# SAISIE CONGÉS VALIDÉS
# ------------------------------
st.sidebar.subheader("Saisir congés validés")
conges_input = {}
for i in range(nb_employes):
    emp = f"E{i+1}"
    conges_input[emp] = st.sidebar.date_input(
        label=f"Congés {emp}",
        value=[],
        min_value=debut_periode,
        max_value=debut_periode + datetime.timedelta(days=num_days-1),
        key=f"conges_{i}"
    )

# ------------------------------
# CREATION DU PLANNING VIDE (Not used in OR-Tools model definition, but good for visualization later)
# ------------------------------
# planning = pd.DataFrame(index=[f"E{i+1}" for i in range(nb_employes)], columns=jours)

# ------------------------------
# MODELISATION OR-TOOLS
# ------------------------------
model = cp_model.CpModel()

# Variables: shifts[(employee_index, day_index, shift_type_index)] = boolean variable
planning_vars = {}
for e_idx in range(nb_employes):
    for d_idx in range(num_days):
        for s_idx in range(len(shift_types)):
            planning_vars[(e_idx, d_idx, s_idx)] = model.NewBoolVar(f"shift_e{e_idx}_d{d_idx}_s{s_idx}")

# ------------------------------
# CONTRAINTES PAR EMPLOYÉ
# ------------------------------
for e_idx in range(nb_employes):
    emp = f"E{e_idx+1}" # Get employee name for looking up holidays

    # Each employee works exactly one shift per day
    for d_idx in range(num_days):
        model.AddExactlyOne(planning_vars[(e_idx, d_idx, s_idx)] for s_idx in range(len(shift_types)))

    # Congés validés -> REPOS
    for d_idx in range(num_days):
        current_date = jours[d_idx]
        if current_date in conges_input[emp]:
             model.Add(planning_vars[(e_idx, d_idx, shift_index[REPOS])] == 1) # Must be REPOS if on holiday
             for s in shift_types: # Cannot work any other shift if on holiday
                 if s != REPOS:
                      model.Add(planning_vars[(e_idx, d_idx, shift_index[s])] == 0)


    # Heures cumulées (approx 210h over 6 weeks)
    # Scale factor for hours (multiply by 4 to convert 11.25 and 7.5 to integers)
    scale_factor = 4
    shift_hours_scaled = {
        JOUR_SEMAINE: int(11.25 * scale_factor),
        NUIT_SEMAINE: int(11.25 * scale_factor),
        WEEKEND_JOUR: int(11.25 * scale_factor),
        WEEKEND_NUIT: int(11.25 * scale_factor),
        SHIFT_COURT: int(7.5 * scale_factor),
        REPOS: 0 # Repos hours are 0
    }
    total_hours_scaled = sum(
        shift_hours_scaled[shift_types[s_idx]] * planning_vars[(e_idx, d_idx, s_idx)]
        for d_idx in range(num_days)
        for s_idx in range(len(shift_types))
    )
    # Assuming 210 hours target over 6 weeks (42 days)
    target_hours_scaled = int(210 * scale_factor)
    # Allow a small deviation, e.g., +/- 5 hours scaled
    model.Add(total_hours_scaled >= target_hours_scaled - int(5 * scale_factor))
    model.Add(total_hours_scaled <= target_hours_scaled + int(5 * scale_factor))


# ------------------------------
# CONTRAINTES OPERATIONNELLES
# ------------------------------

for e_idx in range(nb_employes):
    for d_idx in range(num_days):
        # Max 3 shifts consécutifs (Check blocks of 4 days - at least one must be Repos)
        if d_idx <= num_days - 4: # Ensure there are 4 days to check (d_idx, d_idx+1, d_idx+2, d_idx+3)
            model.AddBoolOr([
                planning_vars[(e_idx, d_idx + k, shift_index[REPOS])]
                for k in range(4)
            ])

        # Repos après nuits (If night on day d_idx, then must be repos on day d_idx+1)
        if d_idx < num_days - 1: # Ensure d_idx+1 is within bounds
             model.AddImplication(planning_vars[(e_idx, d_idx, shift_index[NUIT_SEMAINE])], planning_vars[(e_idx, d_idx + 1, shift_index[REPOS])])
             model.AddImplication(planning_vars[(e_idx, d_idx, shift_index[WEEKEND_NUIT])], planning_vars[(e_idx, d_idx + 1, shift_index[REPOS])])

        # Deux jours de repos consécutifs par semaine
        # For each 7-day window, there must be at least one block of 2 consecutive Repos days.
        for week_start_idx in range(0, num_days, 7):
            week_end_idx = min(week_start_idx + 7, num_days)
            # Create a list of Boolean variables representing if a 2-day repos block starts on each day of the week
            two_day_repos_starts = []
            for day_in_week_idx in range(week_start_idx, week_end_idx - 1): # Need at least 2 days remaining
                # This variable is true if day_in_week_idx and day_in_week_idx+1 are Repos
                is_two_day_repos = model.NewBoolVar(f'e{e_idx}_two_day_repos_start_d{day_in_week_idx}')
                model.AddBoolAnd([planning_vars[(e_idx, day_in_week_idx, shift_index[REPOS])], planning_vars[(e_idx, day_in_week_idx + 1, shift_index[REPOS])]]).OnlyEnforceIf(is_two_day_repos)
                model.AddBoolOr([planning_vars[(e_idx, day_in_week_idx, shift_index[REPOS])].Not(), planning_vars[(e_idx, day_in_week_idx + 1, shift_index[REPOS])].Not()]).OnlyEnforceIf(is_two_day_repos.Not())

                two_day_repos_starts.append(is_two_day_repos)

            # At least one two-day repos block must occur in the 7-day window
            if two_day_repos_starts: # Only add constraint if there are at least 2 days in the window
                 model.AddBoolOr(two_day_repos_starts)


        # Week-end blocs
        current_date = jours[d_idx]
        weekday = current_date.weekday() # 0=Lun, ..., 6=Dim

        # If Saturday day, must be Sunday day (if both days are within the period)
        if weekday == 5 and d_idx < num_days - 1: # Saturday and next day exists
            model.AddImplication(planning_vars[(e_idx, d_idx, shift_index[WEEKEND_JOUR])], planning_vars[(e_idx, d_idx + 1, shift_index[WEEKEND_JOUR])])

        # If Saturday night, must be Sunday night (if both days are within the period)
        if weekday == 5 and d_idx < num_days - 1: # Saturday and next day exists
            model.AddImplication(planning_vars[(e_idx, d_idx, shift_index[WEEKEND_NUIT])], planning_vars[(e_idx, d_idx + 1, shift_index[WEEKEND_NUIT])])

        # If Friday night, must also be Saturday and Sunday night (if all days are within the period)
        if weekday == 4 and d_idx < num_days - 2: # Friday and enough days for Sat (d_idx+1) and Sun (d_idx+2)
             model.AddImplication(planning_vars[(e_idx, d_idx, shift_index[WEEKEND_NUIT])], planning_vars[(e_idx, d_idx + 1, shift_index[WEEKEND_NUIT])])
             model.AddImplication(planning_vars[(e_idx, d_idx, shift_index[WEEKEND_NUIT])], planning_vars[(e_idx, d_idx + 2, shift_index[WEEKEND_NUIT])])


        # Interdiction de travailler juste avant/après week-end jour
        if weekday == 5 and d_idx > 0: # Saturday and previous day exists
             model.AddImplication(planning_vars[(e_idx, d_idx, shift_index[WEEKEND_JOUR])], planning_vars[(e_idx, d_idx - 1, shift_index[REPOS])])

        if weekday == 6 and d_idx < num_days - 1: # Sunday and next day exists
             model.AddImplication(planning_vars[(e_idx, d_idx, shift_index[WEEKEND_JOUR])], planning_vars[(e_idx, d_idx + 1, shift_index[REPOS])])


# ------------------------------
# CONTRAINTES STAFFING MIN/MAX
# ------------------------------
staffing_constraints = {
    JOUR_SEMAINE: (4,6),
    NUIT_SEMAINE: (2,2),
    WEEKEND_JOUR: (2,2),
    WEEKEND_NUIT: (2,2)
}

for d_idx in range(num_days):
    current_date = jours[d_idx]
    weekday = current_date.weekday()

    for shift, (min_staff, max_staff) in staffing_constraints.items():
        shift_assigned = []
        # Determine the correct shift index based on weekday for 'Jour' and 'Nuit'
        if shift == JOUR_SEMAINE:
             if weekday < 5:
                 target_shift_idx = shift_index[JOUR_SEMAINE]
             else: # Weekend, so this constraint doesn't apply to WEEKEND_JOUR, skip
                  continue
        elif shift == NUIT_SEMAINE:
             if weekday < 5:
                  target_shift_idx = shift_index[NUIT_SEMAINE]
             else: # Weekend, so this constraint doesn't apply to WEEKEND_NUIT, skip
                  continue
        elif shift == WEEKEND_JOUR:
             if weekday >= 5:
                  target_shift_idx = shift_index[WEEKEND_JOUR]
             else: # Weekday, skip
                  continue
        elif shift == WEEKEND_NUIT:
             if weekday >= 5:
                  target_shift_idx = shift_index[WEEKEND_NUIT]
             else: # Weekday, skip
                 continue
        else: # Should not happen with defined staffing_constraints, but as a safeguard
             continue

        for e_idx in range(nb_employes):
            shift_assigned.append(planning_vars[(e_idx, d_idx, target_shift_idx)])

        model.Add(sum(shift_assigned) >= min_staff)
        model.Add(sum(shift_assigned) <= max_staff)


# ------------------------------
# SOLVEUR
# ------------------------------
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 60 # Set a time limit
status = solver.Solve(model)

planning_result_df = pd.DataFrame(index=[f"E{i+1}" for i in range(nb_employes)], columns=[f"{d.strftime('%a %d/%m')}" for d in jours])

if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
    st.subheader("Planning 6 semaines")
    for e_idx in range(nb_employes):
        for d_idx in range(num_days):
            for s_idx in range(len(shift_types)):
                if solver.Value(planning_vars[(e_idx, d_idx, s_idx)]) == 1:
                    planning_result_df.iloc[e_idx, d_idx] = shift_types[s_idx]

    def color_shift(val):
        if val == JOUR_SEMAINE: return 'background-color: lightblue'
        elif val == NUIT_SEMAINE: return 'background-color: violet'
        elif val == WEEKEND_JOUR: return 'background-color: lightgreen'
        elif val == WEEKEND_NUIT: return 'background-color: orange'
        elif val == SHIFT_COURT: return 'background-color: pink'
        elif val == REPOS: return 'background-color: lightgrey'
        else: return '' # For any unassigned or other states

    st.dataframe(planning_result_df.style.applymap(color_shift))

    # ------------------------------
    # COMPTEURS PAR EMPLOYÉ
    # ------------------------------
    st.subheader("Compteur d'heures et shifts par employé")
    compteurs = pd.DataFrame(0, index=[f"E{i+1}" for i in range(nb_employes)], columns=shift_types)
    hours_per_employee = {}

    for e_idx in range(nb_employes):
        emp_name = f"E{e_idx+1}"
        hours_per_employee[emp_name] = 0
        for d_idx in range(num_days):
            for s_idx in range(len(shift_types)):
                if solver.Value(planning_vars[(e_idx, d_idx, s_idx)]) == 1:
                    shift_name = shift_types[s_idx]
                    compteurs.loc[emp_name, shift_name] += 1
                    # Add hours - need to use original hours, not scaled
                    if shift_name == JOUR_SEMAINE: hours_per_employee[emp_name] += 11.25
                    elif shift_name == NUIT_SEMAINE: hours_per_employee[emp_name] += 11.25
                    elif shift_name == WEEKEND_JOUR: hours_per_employee[emp_name] += 11.25
                    elif shift_name == WEEKEND_NUIT: hours_per_employee[emp_name] += 11.25
                    elif shift_name == SHIFT_COURT: hours_per_employee[emp_name] += 7.5

    st.dataframe(compteurs)
    st.subheader("Total d'heures par employé")
    st.dataframe(pd.DataFrame.from_dict(hours_per_employee, orient='index', columns=['Heures']))


else:
    st.warning("Impossible de trouver une solution complète avec les contraintes actuelles. Essayez de relâcher certaines contraintes.")
