import pandas as pd
from datetime import datetime, timedelta
from ortools.sat.python import cp_model

class PlanningGenerator:
    def __init__(self, employes, dates, conges_dict, leve_210h=False, log=False):
        self.employes = employes
        self.dates = dates
        self.conges_dict = conges_dict
        self.leve_210h = leve_210h
        self.model = cp_model.CpModel()
        self.log_enabled = log
        self.shift_types = ["Repos","Jour","Nuit","Jour_court","Conge"]
        self.scale_factor = 4
        self.shifts = self._init_vars()
        self.totals = {}

    def _init_vars(self):
        shifts = {}
        for e in self.employes:
            for d in range(len(self.dates)):
                for s in self.shift_types:
                    shifts[(e,d,s)] = self.model.NewIntVar(0,1,f"{e}_{d}_{s}")
        return shifts

    def add_constraints(self):
        self._base_constraints()
        self._operational_constraints()
        self._rest_constraints()
        self._weekend_rotation()
        self._hour_constraints()
        self._equity_objective()

    # -------------------
    # CONTRAINTES
    # -------------------
    def _base_constraints(self):
        for e in self.employes:
            for d, day in enumerate(self.dates):
                self.model.Add(sum(self.shifts[(e,d,s)] for s in self.shift_types)==1)
                if day in self.conges_dict[e]:
                    self.model.Add(self.shifts[(e,d,"Conge")]==1)
                else:
                    self.model.Add(self.shifts[(e,d,"Conge")]==0)
        # Shift court max 1 par jour globalement
        for d in range(len(self.dates)):
            self.model.Add(sum(self.shifts[(e,d,"Jour_court")] for e in self.employes)<=1)
        # Shift court max 1 par employé sur 6 semaines
        for e in self.employes:
            for block_start in range(0,len(self.dates),42):
                block_end = min(block_start+42,len(self.dates))
                self.model.Add(sum(self.shifts[(e,d,"Jour_court")] for d in range(block_start, block_end))<=1)

    def _operational_constraints(self):
        for d, day in enumerate(self.dates):
            weekday = day.weekday()
            if weekday<5:
                self.model.Add(sum(self.shifts[(e,d,"Jour")]+self.shifts[(e,d,"Jour_court")] for e in self.employes)>=4)
                self.model.Add(sum(self.shifts[(e,d,"Jour")]+self.shifts[(e,d,"Jour_court")] for e in self.employes)<=7)
                self.model.Add(sum(self.shifts[(e,d,"Nuit")] for e in self.employes)==2)
            else:
                self.model.Add(sum(self.shifts[(e,d,"Jour")] for e in self.employes)==2)
                self.model.Add(sum(self.shifts[(e,d,"Nuit")] for e in self.employes)==2)

    def _rest_constraints(self):
        for e in self.employes:
            for week_start in range(0,len(self.dates),7):
                week_days = range(week_start,min(week_start+7,len(self.dates)))
                off_days = [self.shifts[(e,d,"Repos")]+self.shifts[(e,d,"Conge")] for d in week_days]
                self.model.Add(sum(off_days)>=2)
            for d in range(len(self.dates)-1):
                self.model.Add(self.shifts[(e,d+1,"Repos")]==1).OnlyEnforceIf(self.shifts[(e,d,"Nuit")])

    def _weekend_rotation(self):
        weekend_days = [(i,i+1) for i, day in enumerate(self.dates) if day.weekday()==5]
        for idx, e in enumerate(self.employes):
            for w_idx, (sat,sun) in enumerate(weekend_days):
                if (w_idx%3)!=(idx%3):
                    self.model.Add(self.shifts[(e,sat,"Jour")]==0)
                    self.model.Add(self.shifts[(e,sun,"Jour")]==0)
        weekend_nuits = [(i,i+1,i+2) for i, day in enumerate(self.dates) if day.weekday()==4]
        for idx,e in enumerate(self.employes):
            for w_idx,(fri,sat,sun) in enumerate(weekend_nuits):
                if (w_idx%3)!=(idx%3):
                    self.model.Add(self.shifts[(e,fri,"Nuit")]==0)
                    self.model.Add(self.shifts[(e,sat,"Nuit")]==0)
                    self.model.Add(self.shifts[(e,sun,"Nuit")]==0)

    def _hour_constraints(self):
        for e in self.employes:
            for block_start in range(0,len(self.dates),42):
                block_end = min(block_start+42,len(self.dates))
                total_scaled = sum(
                    int(11.25*self.scale_factor)*(
                        self.shifts[(e,d,"Jour")]+
                        self.shifts[(e,d,"Nuit")]*(1 if self.dates[d].weekday()<=4 else 0)+
                        self.shifts[(e,d,"Conge")]
                    )+int(7.5*self.scale_factor)*self.shifts[(e,d,"Jour_court")]
                    for d in range(block_start,block_end)
                )
                if not self.leve_210h:
                    self.model.Add(total_scaled==int(210*self.scale_factor))
                else:
                    self.model.Add(total_scaled<=int(210*self.scale_factor))

    def _equity_objective(self):
        self.totals={}
        diff_vars=[]
        for e in self.employes:
            self.totals[e]={}
            self.totals[e]['Jour semaine']=self.model.NewIntVar(0,len(self.dates),f"{e}_JourS")
            self.model.Add(self.totals[e]['Jour semaine']==sum(self.shifts[(e,d,'Jour')]+self.shifts[(e,d,'Jour_court')] for d,day in enumerate(self.dates) if day.weekday()<=4))
            self.totals[e]['Nuit semaine']=self.model.NewIntVar(0,len(self.dates),f"{e}_NuitS")
            self.model.Add(self.totals[e]['Nuit semaine']==sum(self.shifts[(e,d,'Nuit')] for d,day in enumerate(self.dates) if day.weekday()<=4))
            self.totals[e]['Jour week-end']=self.model.NewIntVar(0,len(self.dates),f"{e}_JourWE")
            self.model.Add(self.totals[e]['Jour week-end']==sum(self.shifts[(e,d,'Jour')] for d,day in enumerate(self.dates) if day.weekday()>=5))
            self.totals[e]['Nuit week-end']=self.model.NewIntVar(0,len(self.dates),f"{e}_NuitWE")
            self.model.Add(self.totals[e]['Nuit week-end']==sum(self.shifts[(e,d,'Nuit')] for d,day in enumerate(self.dates) if day.weekday()>=5))
            self.totals[e]['Shift court']=self.model.NewIntVar(0,len(self.dates),f"{e}_Court")
            self.model.Add(self.totals[e]['Shift court']==sum(self.shifts[(e,d,'Jour_court')] for d in range(len(self.dates))))

        for t in ['Jour semaine','Nuit semaine','Jour week-end','Nuit week-end','Shift court']:
            avg=sum(self.totals[e][t] for e in self.employes)//len(self.employes)
            for e in self.employes:
                diff=self.model.NewIntVar(0,len(self.dates),f"diff_{e}_{t}")
                self.model.Add(diff>=self.totals[e][t]-avg)
                self.model.Add(diff>=avg-self.totals[e][t])
                diff_vars.append(diff)
        self.model.Minimize(sum(diff_vars))

    def solve(self,max_time_sec=300):
        solver=cp_model.CpSolver()
        solver.parameters.max_time_in_seconds=max_time_sec
        status=solver.Solve(self.model)
        return solver,status

    # -------------------
    # VALIDATION CONTRAINTES
    # -------------------
    def validate(self, solver):
        violations=[]
        for e in self.employes:
            for week_start in range(0,len(self.dates),7):
                week_days=range(week_start,min(week_start+7,len(self.dates)))
                off=sum(solver.Value(self.shifts[(e,d,"Repos")])+solver.Value(self.shifts[(e,d,"Conge")]) for d in week_days)
                if off<2:
                    violations.append(f"{e} a moins de 2 jours off dans la semaine {week_start//7+1}")
        return violations
