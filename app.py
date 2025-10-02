%%writefile app.py
import streamlit as st
import pandas as pd
import datetime
from ortools.sat.python import cp_model
# from ortools.sat.python.cp_model_helper import ortools_variable_extent # Removed problematic import

# ------------------------------
# TYPES DE SHIFT
# ------------------------------
JOUR_SEMAINE = "Jour semaine"
NUIT_SEMAINE = "Nuit semaine"
WEEKEND_JOUR = "Week-end jour"
WEEKEND_NUIT = "Week-end nuit"
SHIFT_COURT = "Quart court"
REPOS = "Repos"
A_ATTRIBUER = "À attribuer"
shift_types = [JOUR_SEMAINE, NUIT_SEMAINE, WEEKEND_JOUR, WEEKEND_NUIT, SHIFT_COURT, REPOS, A_ATTRIBUER]
shift_index = {s:i for i,s in enumerate(shift_types)}

# ------------------------------
# INTERFACE ET PARAMÈTRES
# ------------------------------
def setup_interface():
    st.sidebar.title("Paramètres de planification")
    nb_employes = st.sidebar.number_input("Nombre d'employés", min_value=1, max_value=50, value=15, step=1)
    debut_periode = st.sidebar.date_input("Date de début de période", value=datetime.date(2025,11,2))
    nb_semaines = st.sidebar.number_input("Nombre de semaines", min_value=1, max_value=12, value=6, step=1)

    jours = [debut_periode + datetime.timedelta(days=i) for i in range(nb_semaines*7)]
    num_days = len(jours)

    st.sidebar.subheader("Saisir congés validés")
    conges_input = {}
    for i in range(nb_employes):
       emp = f"E{i+1}"
       conges_input[emp] = st.sidebar.date_input(
           label=f"Congés {emp} (Ctrl+clic pour plusieurs dates)",
           value=[],
           min_value=debut_periode,
           max_value=debut_periode + datetime.timedelta(days=num_days-1),
           key=f"conges_{i}"
       )
    return nb_employes, debut_periode, nb_semaines, jours, num_days, conges_input

# ------------------------------
# MODELISATION OR-TOOLS (Function)
# ------------------------------
def build_or_tools_model(nb_employes, num_days, shift_types, shift_index, jours, conges_input):
    model = cp_model.CpModel()

    # Variables: planning_vars[(employee_index, day_index)] = integer variable representing shift type index
    planning_vars = {}
    for e_idx in range(nb_employes):
        for d_idx in range(num_days):
           planning_vars[(e_idx, d_idx)] = model.NewIntVar(0, len(shift_types)-1, f"shift_e{e_idx}_d{d_idx}")

    # ------------------------------
    # CONTRAINTES PAR EMPLOYÉ
    # ------------------------------
    for e_idx in range(nb_employes):
       emp = f"E{e_idx+1}" # Get employee name for looking up holidays
       total_hours_scaled = [] # Use scaled hours for integer arithmetic in OR-Tools

       # Scale factor for hours (multiply by 4 for 11.25 and 7.5)
       scale_factor = 4
       shift_hours_scaled = {
           JOUR_SEMAINE: int(11.25 * scale_factor),
           NUIT_SEMAINE: int(11.25 * scale_factor),
           WEEKEND_JOUR: int(11.25 * scale_factor),
           WEEKEND_NUIT: int(11.25 * scale_factor),
           SHIFT_COURT: int(7.5 * scale_factor),
           REPOS: 0,
           A_ATTRIBUER: int(11.25 * scale_factor) # Assuming 'À attribuer' counts as a full shift for hours
       }

       for d_idx in range(num_days):
           var = planning_vars[(e_idx, d_idx)]
           current_date = jours[d_idx]

           # Congés validés -> REPOS
           if current_date in conges_input[emp]:
               model.Add(var == shift_index[REPOS])

           # Heures cumulées - calculate scaled hours based on assigned shift
           heures_jour_scaled = model.NewIntVar(0, int(12 * scale_factor), f"heures_scaled_e{e_idx}_d{d_idx}")

           # Create boolean variables for each shift type on this day for this employee
           shift_is = {}
           for s in shift_types:
               shift_is[s] = model.NewBoolVar(f"e{e_idx}_d{d_idx}_is_{s}")
               model.Add(var == shift_index[s]).OnlyEnforceIf(shift_is[s])
               model.Add(var != shift_index[s]).OnlyEnforceIf(shift_is[s].Not())

           # Add constraints to link shift type to scaled hours
           for s in shift_types:
                model.Add(heures_jour_scaled == shift_hours_scaled[s]).OnlyEnforceIf(shift_is[s])

           total_hours_scaled.append(heures_jour_scaled)

       # Total hours constraint (approx 210h over 6 weeks)
       target_hours_scaled = int(210 * scale_factor)
       # Allow a small deviation, e.g., +/- 5 hours scaled
       model.Add(sum(total_hours_scaled) >= target_hours_scaled - int(5 * scale_factor))
       model.Add(sum(total_hours_scaled) <= target_hours_scaled + int(5 * scale_factor))


    # ------------------------------
    # CONTRAINTES OPERATIONNELLES
    # ------------------------------
    for e_idx in range(nb_employes):
       for d_idx in range(num_days):
           var = planning_vars[(e_idx, d_idx)]
           current_date = jours[d_idx]
           weekday = current_date.weekday()  # 0=Lun, ..., 6=Dim

           # Create boolean variables for each shift type on this day for this employee (if not already created)
           shift_is = {}
           for s in shift_types:
               shift_is[s] = model.NewBoolVar(f"e{e_idx}_d{d_idx}_is_{s}")
               model.Add(var == shift_index[s]).OnlyEnforceIf(shift_is[s])
               model.Add(var != shift_index[s]).OnlyEnforceIf(shift_is[s].Not())


           # Max 3 shifts consécutifs (Check blocks of 4 days - at least one must be Repos)
           if d_idx <= num_days - 4: # Ensure there are 4 days to check (d_idx, d_idx+1, d_idx+2, d_idx+3)
               # Create boolean variables for each day in the block being Repos
               is_repos_in_block = []
               for k in range(4):
                    is_repos = model.NewBoolVar(f'e{e_idx}_d{d_idx+k}_is_repos_in_block')
                    model.Add(planning_vars[(e_idx, d_idx + k)] == shift_index[REPOS]).OnlyEnforceIf(is_repos)
                    model.Add(planning_vars[(e_idx, d_idx + k)] != shift_index[REPOS]).OnlyEnforceIf(is_repos.Not())
                    is_repos_in_block.append(is_repos)

               # At least one day in the 4-day block must be Repos
               model.AddBoolOr(is_repos_in_block)


           # Repos après nuits (If night on day d_idx, then must be repos on day d_idx+1)
           if d_idx < num_days - 1: # Ensure d_idx+1 is within bounds
                is_next_day_repos = model.NewBoolVar(f'e{e_idx}_d{d_idx+1}_is_repos')
                model.Add(planning_vars[(e_idx, d_idx + 1)] == shift_index[REPOS]).OnlyEnforceIf(is_next_day_repos)
                model.Add(planning_vars[(e_idx, d_idx + 1)] != shift_index[REPOS]).OnlyEnforceIf(is_next_day_repos.Not())
                model.AddImplication(shift_is[NUIT_SEMAINE], is_next_day_repos)
                model.AddImplication(shift_is[WEEKEND_NUIT], is_next_day_repos)


           # Deux jours de repos consécutifs par semaine
           # For each 7-day window, there must be at least one block of 2 consecutive Repos days.
           for week_start_idx in range(0, num_days, 7):
               week_end_idx = min(week_start_idx + 7, num_days)
               # Create a list of Boolean variables representing if a 2-day repos block starts on each day of the week
               two_day_repos_starts = []
               for day_in_week_idx in range(week_start_idx, week_end_idx - 1): # Need at least 2 days remaining
                   # This variable is true if day_in_week_idx and day_in_week_idx+1 are Repos
                   is_two_day_repos = model.NewBoolVar(f'e{e_idx}_two_day_repos_start_d{day_in_week_idx}')

                   # Create boolean variables for the conditions within the AddBoolAnd and AddBoolOr
                   is_day1_repos = model.NewBoolVar(f'e{e_idx}_d{day_in_week_idx}_is_repos_for_pair')
                   is_day2_repos = model.NewBoolVar(f'e{e_idx}_d{day_in_week_idx+1}_is_repos_for_pair')

                   model.Add(planning_vars[(e_idx, day_in_week_idx)] == shift_index[REPOS]).OnlyEnforceIf(is_day1_repos)
                   model.Add(planning_vars[(e_idx, day_in_week_idx)] != shift_index[REPOS]).OnlyEnforceIf(is_day1_repos.Not())
                   model.Add(planning_vars[(e_idx, day_in_week_idx+1)] == shift_index[REPOS]).OnlyEnforceIf(is_day2_repos)
                   model.Add(planning_vars[(e_idx, day_in_week_idx+1)] != shift_index[REPOS]).OnlyEnforceIf(is_day2_repos.Not())

                   model.AddBoolAnd([is_day1_repos, is_day2_repos]).OnlyEnforceIf(is_two_day_repos)
                   model.AddBoolOr([is_day1_repos.Not(), is_day2_repos.Not()]).OnlyEnforceIf(is_two_day_repos.Not())


                   two_day_repos_starts.append(is_two_day_repos)

               # At least one two-day repos block must occur in the 7-day window
               if two_day_repos_starts: # Only add constraint if there are at least 2 days in the window
                    model.AddBoolOr(two_day_repos_starts)


           # Week-end blocs
           # If Saturday day, must be Sunday day (if both days are within the period)
           if weekday == 5 and d_idx < num_days - 1: # Saturday and next day exists
               is_next_day_weekend_jour = model.NewBoolVar(f'e{e_idx}_d{d_idx+1}_is_weekend_jour')
               model.Add(planning_vars[(e_idx, d_idx + 1)] == shift_index[WEEKEND_JOUR]).OnlyEnforceIf(is_next_day_weekend_jour)
               model.AddImplication(shift_is[WEEKEND_JOUR], is_next_day_weekend_jour)

           # If Saturday night, must be Sunday night (if both days are within the period)
           if weekday == 5 and d_idx < num_days - 1: # Saturday and next day exists
               is_next_day_weekend_nuit = model.NewBoolVar(f'e{e_idx}_d{d_idx+1}_is_weekend_nuit')
               model.Add(planning_vars[(e_idx, d_idx + 1)] == shift_index[WEEKEND_NUIT]).OnlyEnforceIf(is_next_day_weekend_nuit)
               model.AddImplication(shift_is[WEEKEND_NUIT], is_next_day_weekend_nuit)

           # If Friday night, must also be Saturday and Sunday night (if all days are within the period)
           if weekday == 4 and d_idx < num_days - 2: # Friday and enough days for Sat (d_idx+1) and Sun (d_idx+2)
                is_next_day_weekend_nuit = model.NewBoolVar(f'e{e_idx}_d{d_idx+1}_is_weekend_nuit')
                is_day_after_next_weekend_nuit = model.NewBoolVar(f'e{e_idx}_d{d_idx+2}_is_weekend_nuit')
                model.Add(planning_vars[(e_idx, d_idx + 1)] == shift_index[WEEKEND_NUIT]).OnlyEnforceIf(is_next_day_weekend_nuit)
                model.Add(planning_vars[(e_idx, d_idx + 2)] == shift_index[WEEKEND_NUIT]).OnlyEnforceIf(is_day_after_next_weekend_nuit)
                model.AddImplication(shift_is[WEEKEND_NUIT], is_next_day_weekend_nuit)
                model.AddImplication(shift_is[WEEKEND_NUIT], is_day_after_next_weekend_nuit)


           # Interdiction de travailler juste avant/après week-end jour
           if weekday == 5 and d_idx > 0: # Saturday and previous day exists
                is_prev_day_repos = model.NewBoolVar(f'e{e_idx}_d{d_idx-1}_is_repos')
                model.Add(planning_vars[(e_idx, d_idx - 1)] == shift_index[REPOS]).OnlyEnforceIf(is_prev_day_repos)
                model.AddImplication(shift_is[WEEKEND_JOUR], is_prev_day_repos)


           if weekday == 6 and d_idx < num_days - 1: # Sunday and next day exists
                is_next_day_repos = model.NewBoolVar(f'e{e_idx}_d{d_idx+1}_is_repos')
                model.Add(planning_vars[(e_idx, d_idx + 1)] == shift_index[REPOS]).OnlyEnforceIf(is_next_day_repos)
                model.AddImplication(shift_is[WEEKEND_JOUR], is_next_day_repos)


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
               # Create boolean variable for this employee being assigned this specific shift on this day
               is_assigned_shift = model.NewBoolVar(f"e{e_idx}_d{d_idx}_is_{shift}")
               model.Add(planning_vars[(e_idx, d_idx)] == target_shift_idx).OnlyEnforceIf(is_assigned_shift)
               model.Add(planning_vars[(e_idx, d_idx)] != target_shift_idx).OnlyEnforceIf(is_assigned_shift.Not())

               shift_assigned.append(is_assigned_shift)

           model.Add(sum(shift_assigned) >= min_staff)
           model.Add(sum(shift_assigned) <= max_staff)

    return model, planning_vars

# ------------------------------
# SOLVEUR (Function)
# ------------------------------
def solve_model(model, planning_vars):
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    return solver, status

# ------------------------------
# AFFICHAGE PLANNING (Function)
# ------------------------------
def display_results(solver, status, planning_vars, nb_employes, num_days, shift_types, shift_index, jours):
    st.header("Planning Généré")
    planning_result_df = pd.DataFrame(index=[f"Employé {i+1}" for i in range(nb_employes)], columns=[f"{d.strftime('%a %d/%m')}" for d in jours])

    for e_idx in range(nb_employes):
       for d_idx in range(num_days):
           try:
               shift_id = solver.Value(planning_vars[(e_idx, d_idx)])
               planning_result_df.iloc[e_idx, d_idx] = shift_types[shift_id]
           except:
               planning_result_df.iloc[e_idx, d_idx] = A_ATTRIBUER

    def color_shift(val):
       if val == JOUR_SEMAINE: return 'background-color: lightblue'
       elif val == NUIT_SEMAINE: return 'background-color: violet'
       elif val == WEEKEND_JOUR: return 'background-color: lightgreen'
       elif val == WEEKEND_NUIT: return 'background-color: orange'
       elif val == SHIFT_COURT: return 'background-color: pink'
       elif val == REPOS: return 'background-color: lightgrey'
       elif val == A_ATTRIBUER: return 'background-color: red; color:white'
       else: return ''

    planning_display = planning_result_df.copy()
    # Adjusting column width for better readability
    st.dataframe(planning_display.style.applymap(color_shift), column_config={col: st.column_config.Column(width="small") for col in planning_display.columns})

    # ------------------------------
    # COMPTEURS PAR EMPLOYÉ
    # ------------------------------
    st.header("Récapitulatif par Employé")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Compteurs de shifts par employé")
        compteurs = pd.DataFrame(0, index=[f"Employé {i+1}" for i in range(nb_employes)], columns=shift_types)

        shift_hours = {
            JOUR_SEMAINE: 11.25,
            NUIT_SEMAINE: 11.25,
            WEEKEND_JOUR: 11.25,
            WEEKEND_NUIT: 11.25,
            SHIFT_COURT: 7.5,
            REPOS: 0,
            A_ATTRIBUER: 0 # Do not count hours for unassigned shifts
        }

        for e_idx in range(nb_employes):
            emp_name = f"Employé {e_idx+1}"
            for d_idx in range(num_days):
                shift_name = planning_result_df.iloc[e_idx, d_idx]
                if shift_name in shift_types:
                    compteurs.loc[emp_name, shift_name] += 1

        st.dataframe(compteurs)

    with col2:
        st.subheader("Total d'heures par employé")
        hours_per_employee = {}
        for e_idx in range(nb_employes):
            emp_name = f"Employé {e_idx+1}"
            hours_per_employee[emp_name] = 0
            for d_idx in range(num_days):
                shift_name = planning_result_df.iloc[e_idx, d_idx]
                hours_per_employee[emp_name] += shift_hours.get(shift_name, 0)

        st.dataframe(pd.DataFrame.from_dict(hours_per_employee, orient='index', columns=['Heures']))


    # ------------------------------
    # LOGS CONFLITS
    # ------------------------------
    st.header("Statut de la Résolution")
    if status == cp_model.OPTIMAL:
       st.success("Planning généré avec succès ! Toutes les contraintes ont été satisfaites.")
    elif status == cp_model.FEASIBLE:
       st.info("Planning généré. Certaines contraintes pourraient ne pas avoir été parfaitement optimisées, but a feasible solution was found.")
    else:
       st.warning("Impossible de générer un planning satisfaisant toutes les contraintes. Certains shifts sont marqués 'À attribuer'. Veuillez ajuster les paramètres ou les contraintes.")
       # Optionally, add details about unsatisfied constraints if available from the solver


# ------------------------------
# MAIN EXECUTION
# ------------------------------
nb_employes, debut_periode, nb_semaines, jours, num_days, conges_input = setup_interface()

if st.sidebar.button("Générer Planning"):
    # Add a spinner or progress indicator while solving
    with st.spinner("Génération du planning en cours..."):
        model, planning_vars = build_or_tools_model(nb_employes, num_days, shift_types, shift_index, jours, conges_input)
        solver, status = solve_model(model, planning_vars)
    display_results(solver, status, planning_vars, nb_employes, num_days, shift_types, shift_index, jours)
