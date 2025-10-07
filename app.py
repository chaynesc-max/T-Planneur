# -------------------
# GRAPHIQUE ROTATION WEEK-END
# -------------------
st.subheader("📊 Rotation week-ends (jour vs nuit)")

# Préparer les données
weekend_summary = pd.DataFrame(0, index=employes, columns=['Jour WE','Nuit WE'])
for e in employes:
    for w_idx, (sat,sun) in enumerate(weekend_days):
        if solver.Value(shifts[(e,sat,"Jour")]) and solver.Value(shifts[(e,sun,"Jour")]):
            weekend_summary.loc[e,'Jour WE'] += 1
    for w_idx, (fri,sat) in enumerate([(i,i+1) for i in range(periode_jours-2) 
                                       if (date_debut + timedelta(days=i)).weekday()==4]):
        if solver.Value(shifts[(e,fri,"Nuit")]) and solver.Value(shifts[(e,sat,"Nuit")]) and solver.Value(shifts[(e,sat+1,"Nuit")]):
            weekend_summary.loc[e,'Nuit WE'] += 1

# Graphique empilé pour visualiser rotation
fig2, ax2 = plt.subplots(figsize=(12,6))
weekend_summary.plot(kind='bar', stacked=True, ax=ax2, colormap='Paired')
ax2.set_ylabel("Nombre de week-ends assignés")
ax2.set_xlabel("Employés")
ax2.set_title("Rotation des week-ends : jour vs nuit")
st.pyplot(fig2)

st.write("✅ Chaque employé devrait idéalement avoir 1 week-end sur 3 de jour et 1 sur 3 de nuit.")
